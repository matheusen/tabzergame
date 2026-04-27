"""Game Workflow - Godot-focused feature, bugfix, level, AI, asset, and render tasks."""
from __future__ import annotations

from pathlib import Path

from ..agents import level_designer_agent, patch_agent, planner_agent, reviewer_agent
from ..config import OrchestratorConfig
from ..schemas import AgentResult, FinalReport, PatchAttempt, TaskIntent
from ..state import TaskState
from ..tools.git_worktree import create_worktree, worktree_available
from ..tools.patch_applier import apply_patch, extract_changed_files, rollback_patch
from ..tools.test_runner import all_passed, run_game_validations


_GAME_ALLOWED_PATHS = [
    "project.godot",
    "scripts/**",
    "scenes/**",
    "resources/**",
    "tools/**",
    "art/**",
    "audio/**",
]


def run(
    task: TaskIntent,
    state: TaskState,
    repo_root: Path,
    cfg: OrchestratorConfig,
) -> FinalReport:
    print(f"[GameWorkflow] Starting: {task.task_id}")

    workspace = repo_root
    if worktree_available() and task.autonomy_level >= 3:
        try:
            workspace = create_worktree(repo_root, repo_root / cfg.worktrees_dir, task.task_id)
            state.set_workspace(workspace)
            state.transition("worktree_created")
            print(f"[GameWorkflow] Worktree: {workspace}")
        except Exception as e:
            return _build_report(
                state,
                task,
                "needs_human",
                f"Could not create isolated worktree. No patch was applied. Error: {e}",
            )
    elif task.autonomy_level >= 3:
        return _build_report(
            state,
            task,
            "needs_human",
            "Could not create isolated worktree because git is unavailable. No patch was applied.",
        )

    state.transition("baseline_running")
    baseline = run_game_validations(workspace, cfg.game_validation.commands)
    state.set_baseline(baseline)
    state.transition("baseline_passed" if all_passed(baseline) else "baseline_failed")
    baseline_issues = sum(1 for v in baseline if v.status not in ("passed", "skipped"))
    print(f"[GameWorkflow] Baseline: {baseline_issues} issue(s)")

    _add_game_diagnostics(task, workspace, state)

    state.transition("planning")
    enriched_task = _with_game_scope(task)
    plan = planner_agent.create_plan(enriched_task, workspace, cfg)

    if task.task_type == "level_design" or task.target_area == "level":
        scene_brief = level_designer_agent.create_scene_brief(task, cfg)
        state.run_dir.joinpath("scene_brief.json").write_text(
            _json_dumps(scene_brief.model_dump()),
            encoding="utf-8",
        )
        state.add_agent_result(level_designer_agent.to_agent_result(scene_brief))
        plan.feature_spec = scene_brief.model_dump()
        plan.steps = _scene_steps(scene_brief) + plan.steps
        plan.validations_to_run = list(dict.fromkeys([
            "scene brief acceptance criteria",
            "godot project structure",
            "main scene traversal smoke",
            *plan.validations_to_run,
        ]))

    state.set_plan(plan)
    print(f"[GameWorkflow] Plan: {len(plan.probable_files)} file(s), {len(plan.steps)} step(s)")

    if task.autonomy_level < 3:
        return _build_report(
            state,
            task,
            "needs_human",
            "Diagnosis and Godot plan are ready. Autonomy < 3, so no patch was applied.",
        )

    previous_failures = [
        f"{v.name}: {v.stderr or v.stdout}"
        for v in baseline
        if not v.passed
    ]
    successful_attempt: PatchAttempt | None = None

    for attempt_no in range(1, cfg.max_attempts + 1):
        print(f"[GameWorkflow] Attempt {attempt_no}/{cfg.max_attempts}")
        state.transition("patching")

        patch_content = patch_agent.generate_patch(
            enriched_task, plan, workspace, attempt_no, previous_failures, cfg
        )

        if not patch_content:
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                status="failed",
            )
            state.add_attempt(attempt)
            previous_failures.append("Patch agent did not generate a diff")
            if cfg.llm_provider == "none":
                break
            continue

        files_changed = extract_changed_files(patch_content)
        dry = apply_patch(workspace, patch_content, dry_run=True)
        if not dry.ok:
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                patch_content=patch_content,
                files_changed=files_changed,
                status="failed",
            )
            state.add_attempt(attempt)
            previous_failures.append(f"Patch dry-run failed: {dry.stderr[:200]}")
            continue

        applied = apply_patch(workspace, patch_content)
        if not applied.ok:
            rollback_patch(workspace)
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                patch_content=patch_content,
                files_changed=files_changed,
                rollback_performed=True,
                status="rolled_back",
            )
            state.add_attempt(attempt)
            previous_failures.append(f"Patch apply failed: {applied.stderr[:200]}")
            continue

        state.transition("validating")
        validations = run_game_validations(workspace, cfg.game_validation.commands)

        state.transition("reviewing")
        attempt = PatchAttempt(
            attempt_no=attempt_no,
            plan_summary=plan.hypothesis,
            patch_content=patch_content,
            files_changed=files_changed,
            validation_results=validations,
        )
        attempt.review = reviewer_agent.review(enriched_task, attempt, validations, cfg)

        if attempt.review.approved and all_passed(validations):
            attempt.status = "passed"
            state.add_attempt(attempt)
            successful_attempt = attempt
            break

        rollback_patch(workspace)
        attempt.status = "rolled_back"
        attempt.rollback_performed = True
        state.add_attempt(attempt)
        previous_failures.extend(attempt.review.blocking_issues[:3])

    no_patch_generated = not any(a.patch_content for a in state.attempts)
    if successful_attempt:
        return _build_report(
            state,
            task,
            "completed",
            f"Game task completed: {task.title}. {len(successful_attempt.files_changed)} file(s) changed.",
        )
    if no_patch_generated:
        return _build_report(
            state,
            task,
            "needs_human",
            "Godot diagnostics and plan completed. No safe automatic patch was generated by the selected provider.",
        )
    return _build_report(
        state,
        task,
        "failed",
        f"Could not complete game task after {cfg.max_attempts} attempt(s).",
    )


def _with_game_scope(task: TaskIntent) -> TaskIntent:
    allowed = list(dict.fromkeys(task.allowed_paths + _GAME_ALLOWED_PATHS))
    return task.model_copy(update={"allowed_paths": allowed})


def _scene_steps(scene_brief) -> list[str]:
    return [
        f"Create or adapt scene pass for `{scene_brief.scene_name}`",
        "Block out floor, platforms, spawn points, camera limits, and exit route",
        "Place enemies according to the scene brief pacing",
        "Wire props/background/audio using existing assets first",
        "Validate every acceptance criterion from scene_brief.json",
    ]


def _add_game_diagnostics(task: TaskIntent, workspace: Path, state: TaskState) -> None:
    findings = []
    for path in ["project.godot", "scenes/main.tscn", "scripts/player_controller.gd", "scripts/enemy_agent.gd"]:
        if (workspace / path).exists():
            findings.append(f"Found {path}")
    if (workspace / "art/Player").exists():
        findings.append("Player art folder available")
    if (workspace / "art/Enemies").exists():
        findings.append("Enemy art folder available")

    state.add_agent_result(
        AgentResult(
            agent_name="godot_repo_diagnostics",
            status="passed",
            summary=f"Mapped Godot project context for {task.target_area}",
            findings=findings,
        )
    )


def _json_dumps(data: dict) -> str:
    import json

    return json.dumps(data, indent=2, ensure_ascii=False)


def _build_report(state: TaskState, task: TaskIntent, status: str, summary: str) -> FinalReport:
    files_changed = [
        f
        for attempt in state.attempts
        if attempt.status == "passed"
        for f in attempt.files_changed
    ]
    report = FinalReport(
        task_id=task.task_id,
        status=status,
        summary=summary,
        files_changed=list(dict.fromkeys(files_changed)),
        validations=state.baseline_results + [
            v for attempt in state.attempts for v in attempt.validation_results
        ],
        attempts=state.attempts,
        agent_results=state.agent_results,
        recommendations=[
            "Run the main scene in Godot and verify player, enemy, camera, and collisions",
            "Set GODOT_BIN to enable headless project validation from the orchestrator",
            "For asset tasks, inspect transparency and sprite bounds before committing",
        ],
        duration_sec=state.elapsed_sec(),
    )
    state.set_final_report(report)
    if status == "completed":
        state.transition("completed")
    elif status == "needs_human":
        state.transition("needs_human")
    else:
        state.transition("failed")
    return report
