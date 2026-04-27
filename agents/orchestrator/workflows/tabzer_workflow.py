"""Tabzer Workflow — specialized for cursor, AlphaTab, player, and tab-sync issues."""
from __future__ import annotations

from pathlib import Path

from ..adapters.tab_debug_adapter import TabDebugAdapter
from ..adapters.frontend_bug_adapter import FrontendBugAdapter
from ..agents import patch_agent, planner_agent, reviewer_agent
from ..config import OrchestratorConfig
from ..schemas import FinalReport, PatchAttempt, TaskIntent
from ..state import TaskState
from ..tools.git_worktree import create_worktree, worktree_available
from ..tools.patch_applier import apply_patch, extract_changed_files, rollback_patch
from ..tools.test_runner import all_passed, run_frontend_validations


_TABZER_CRITICAL_AREAS = {
    "cursor": ["frontend/src/app/play", "frontend/src/hooks", "frontend/src/components"],
    "alphatab": ["frontend/src/app/play", "frontend/src/lib/alphaTab"],
    "player": ["frontend/src/app/play", "frontend/src/hooks"],
    "study": ["frontend/src/app/study", "backend/agents/study_agent"],
    "sync": ["frontend/src/app/play", "frontend/src/hooks"],
    "youtube": ["frontend/src/app/play"],
}


def run(
    task: TaskIntent,
    state: TaskState,
    repo_root: Path,
    cfg: OrchestratorConfig,
) -> FinalReport:
    print(f"[TabzerWorkflow] Starting: {task.task_id}")

    # ── identify critical area ─────────────────────────────────────────────────
    low = task.user_request.lower()
    focused_area = next(
        (area for area in _TABZER_CRITICAL_AREAS if area in low),
        "player",
    )
    print(f"[TabzerWorkflow] Focused area: {focused_area}")

    # ── worktree ──────────────────────────────────────────────────────────────
    workspace = repo_root
    if worktree_available() and task.autonomy_level >= 3:
        try:
            workspace = create_worktree(repo_root, repo_root / cfg.worktrees_dir, task.task_id)
            state.set_workspace(workspace)
            state.transition("worktree_created")
        except Exception as e:
            print(f"[TabzerWorkflow] Worktree failed ({e})")
            return _build_report(
                state,
                task,
                "needs_human",
                "Could not create isolated worktree. No patch was applied.",
            )
    elif task.autonomy_level >= 3:
        return _build_report(
            state,
            task,
            "needs_human",
            "Could not create isolated worktree because git is unavailable. No patch was applied.",
        )

    # ── run tab_debug_agent baseline ──────────────────────────────────────────
    state.transition("baseline_running")
    tab_adapter = TabDebugAdapter()
    baseline_result = tab_adapter.run(task, workspace, timeout_sec=180)
    state.add_agent_result(baseline_result)

    fe_result = FrontendBugAdapter().run(task, workspace)
    state.add_agent_result(fe_result)

    fe_baseline = run_frontend_validations(workspace, cfg.frontend_validation.commands)
    state.set_baseline(fe_baseline)
    state.transition("baseline_passed" if all_passed(fe_baseline) else "baseline_failed")

    print(f"[TabzerWorkflow] Tab debug: {baseline_result.status}")
    print(f"[TabzerWorkflow] Frontend: {fe_result.status}")

    # ── plan ──────────────────────────────────────────────────────────────────
    state.transition("planning")

    # Inject tab-specific context into the task for better planning
    enriched_task = task.model_copy(update={
        "allowed_paths": [
            "frontend/src/app/play/**",
            "frontend/src/hooks/**",
            "frontend/src/components/**",
            "frontend/src/lib/**",
        ]
    })

    plan = planner_agent.create_plan(enriched_task, workspace, cfg)
    state.set_plan(plan)
    print(f"[TabzerWorkflow] Plan: {len(plan.probable_files)} files")

    if task.autonomy_level < 3:
        return _build_report(
            state, task, "needs_human",
            f"Diagnosis complete. Tab debug: {baseline_result.status}. "
            f"Findings: {'; '.join(baseline_result.findings[:3])}. Autonomy < 3.",
        )

    # ── try fix_loop first for cursor/smoothness issues ───────────────────────
    if focused_area in ("cursor", "player", "sync") and "cursor" in low:
        print("[TabzerWorkflow] Attempting automated cursor fix loop")
        fix_result = tab_adapter.run_fix_loop(task, workspace, timeout_sec=600)
        state.add_agent_result(fix_result)
        if fix_result.status == "passed":
            # Validate after fix loop
            validations = run_frontend_validations(workspace, cfg.frontend_validation.commands)
            state.set_baseline(validations)
            if all_passed(validations):
                report = _build_report(
                    state, task, "completed",
                    f"Cursor fix loop resolved the issue. Findings: {'; '.join(fix_result.findings[:3])}",
                )
                return report
        print("[TabzerWorkflow] Fix loop did not fully resolve — trying LLM patch")

    # ── LLM patch loop ────────────────────────────────────────────────────────
    previous_failures = [f for f in baseline_result.findings if "fail" in f.lower() or "error" in f.lower()]
    successful_attempt: PatchAttempt | None = None

    for attempt_no in range(1, cfg.max_attempts + 1):
        print(f"[TabzerWorkflow] Attempt {attempt_no}/{cfg.max_attempts}")
        state.transition("patching")

        patch_content = patch_agent.generate_patch(
            enriched_task, plan, workspace, attempt_no, previous_failures, cfg
        )

        if not patch_content:
            attempt = PatchAttempt(
                attempt_no=attempt_no, plan_summary=plan.hypothesis, status="failed"
            )
            state.add_attempt(attempt)
            previous_failures.append("Patch agent could not generate a diff")
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
            previous_failures.append(f"Dry-run failed: {dry.stderr[:150]}")
            continue

        apply_result = apply_patch(workspace, patch_content)
        if not apply_result.ok:
            rollback_patch(workspace)
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                patch_content=patch_content,
                files_changed=files_changed,
                status="rolled_back",
                rollback_performed=True,
            )
            state.add_attempt(attempt)
            previous_failures.append(f"Apply failed: {apply_result.stderr[:150]}")
            continue

        # Validate with both typecheck AND tab_debug_agent
        state.transition("validating")
        fe_validations = run_frontend_validations(workspace, cfg.frontend_validation.commands)

        # Re-run tab debug to confirm improvement
        post_patch_tab = tab_adapter.run(task, workspace, timeout_sec=180)
        state.add_agent_result(post_patch_tab)

        all_validations = fe_validations

        # Review
        state.transition("reviewing")
        attempt = PatchAttempt(
            attempt_no=attempt_no,
            plan_summary=plan.hypothesis,
            patch_content=patch_content,
            files_changed=files_changed,
            validation_results=all_validations,
        )
        review = reviewer_agent.review(enriched_task, attempt, all_validations, cfg)
        attempt.review = review

        if review.approved and all_passed(fe_validations):
            attempt.status = "passed"
            state.add_attempt(attempt)
            successful_attempt = attempt
            print(f"[TabzerWorkflow] Attempt {attempt_no} PASSED")
            break
        else:
            rollback_patch(workspace)
            attempt.status = "rolled_back"
            attempt.rollback_performed = True
            state.add_attempt(attempt)
            previous_failures.extend(review.blocking_issues[:2])
            print(f"[TabzerWorkflow] Attempt {attempt_no} failed")

    no_patch_generated = not any(a.patch_content for a in state.attempts)
    if successful_attempt:
        return _build_report(
            state, task, "completed",
            f"Fixed Tabzer issue ({focused_area}): {task.title}. "
            f"{len(successful_attempt.files_changed)} file(s) changed.",
        )
    elif no_patch_generated:
        return _build_report(
            state, task, "needs_human",
            f"Diagnosis and planning completed for: {task.title}. "
            "No safe automatic patch was generated by the selected provider.",
        )
    else:
        return _build_report(
            state, task, "failed",
            f"Could not fix: {task.title} after {cfg.max_attempts} attempts. "
            f"Tab debug findings: {'; '.join(baseline_result.findings[:2])}",
        )


def _build_report(state: TaskState, task: TaskIntent, status: str, summary: str) -> FinalReport:
    files_changed = [f for a in state.attempts if a.status == "passed" for f in a.files_changed]
    report = FinalReport(
        task_id=task.task_id,
        status=status,
        summary=summary,
        files_changed=list(dict.fromkeys(files_changed)),
        validations=state.baseline_results + [
            v for a in state.attempts for v in a.validation_results
        ],
        attempts=state.attempts,
        agent_results=state.agent_results,
        recommendations=[
            "Run Playwright visual regression tests after applying changes",
            "Check cursor smoothness with tab_debug_agent --debug-cursor flag",
            "Verify AlphaTab memory consumption after patch (target < 700MB)",
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
