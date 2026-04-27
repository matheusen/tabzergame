"""Bugfix Workflow — reproduce → plan → patch → validate → review → report."""
from __future__ import annotations

from pathlib import Path

from ..agents import intake_agent, patch_agent, planner_agent, reviewer_agent
from ..agents.repo_mapper_agent import map_files
from ..adapters.backend_bug_adapter import BackendBugAdapter
from ..adapters.frontend_bug_adapter import FrontendBugAdapter
from ..adapters.tab_debug_adapter import TabDebugAdapter
from ..config import OrchestratorConfig
from ..schemas import (
    FinalReport,
    PatchAttempt,
    TaskIntent,
    ValidationResult,
)
from ..state import TaskState
from ..tools.git_worktree import create_worktree, worktree_available
from ..tools.patch_applier import apply_patch, extract_changed_files, rollback_patch
from ..tools.test_runner import (
    all_passed,
    run_backend_validations,
    run_frontend_validations,
    run_generic_validations,
)


def run(
    task: TaskIntent,
    state: TaskState,
    repo_root: Path,
    cfg: OrchestratorConfig,
) -> FinalReport:
    print(f"[BugfixWorkflow] Starting: {task.task_id}")

    # ── worktree ──────────────────────────────────────────────────────────────
    workspace = repo_root  # fallback: work in-place
    if worktree_available() and task.autonomy_level >= 3:
        try:
            worktrees_dir = repo_root / cfg.worktrees_dir
            workspace = create_worktree(repo_root, worktrees_dir, task.task_id)
            state.set_workspace(workspace)
            state.transition("worktree_created")
            print(f"[BugfixWorkflow] Worktree: {workspace}")
        except Exception as e:
            print(f"[BugfixWorkflow] Worktree creation failed ({e})")
            return _build_report(
                state,
                task,
                "needs_human",
                [str(e)],
                "Could not create isolated worktree. No patch was applied.",
            )
    elif task.autonomy_level >= 3:
        return _build_report(
            state,
            task,
            "needs_human",
            ["git is not available"],
            "Could not create isolated worktree because git is unavailable. No patch was applied.",
        )

    # ── baseline ──────────────────────────────────────────────────────────────
    state.transition("baseline_running")
    baseline = _run_baseline(task, workspace, cfg)
    state.set_baseline(baseline)

    baseline_ok = all_passed(baseline)
    state.transition("baseline_passed" if baseline_ok else "baseline_failed")

    baseline_errors = [v for v in baseline if not v.passed]
    print(f"[BugfixWorkflow] Baseline: {len(baseline_ok and []  or baseline_errors)} issues")

    # ── run specialized agents (read-only) ────────────────────────────────────
    _run_diagnostic_agents(task, workspace, state)

    # ── plan ──────────────────────────────────────────────────────────────────
    state.transition("planning")
    plan = planner_agent.create_plan(task, workspace, cfg)
    state.set_plan(plan)
    print(f"[BugfixWorkflow] Plan: {len(plan.probable_files)} files, {len(plan.steps)} steps")

    # ── patch loop ────────────────────────────────────────────────────────────
    if task.autonomy_level < 3:
        # Diagnosis only — no patching
        return _build_report(state, task, "needs_human", [], "Diagnosis complete. Autonomy < 3: no patch applied.")

    previous_failures: list[str] = []
    successful_attempt: PatchAttempt | None = None

    for attempt_no in range(1, cfg.max_attempts + 1):
        print(f"[BugfixWorkflow] Attempt {attempt_no}/{cfg.max_attempts}")
        state.transition("patching")

        # Generate patch
        patch_content = patch_agent.generate_patch(
            task, plan, workspace, attempt_no, previous_failures, cfg
        )

        if not patch_content:
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                status="failed",
            )
            attempt.validation_results = []
            state.add_attempt(attempt)
            previous_failures.append("Patch agent could not generate a diff")
            if cfg.llm_provider == "none":
                break
            continue

        files_changed = extract_changed_files(patch_content)

        # Dry-run safety check
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

        # Apply patch
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
            previous_failures.append(f"Patch apply failed: {apply_result.stderr[:200]}")
            continue

        # Validate
        state.transition("validating")
        validations = _run_validations(task, workspace, cfg)

        # Review
        state.transition("reviewing")
        attempt = PatchAttempt(
            attempt_no=attempt_no,
            plan_summary=plan.hypothesis,
            patch_content=patch_content,
            files_changed=files_changed,
            validation_results=validations,
        )
        review = reviewer_agent.review(task, attempt, validations, cfg)
        attempt.review = review

        if review.approved and all_passed(validations):
            attempt.status = "passed"
            state.add_attempt(attempt)
            successful_attempt = attempt
            print(f"[BugfixWorkflow] Attempt {attempt_no} PASSED")
            break
        else:
            # Rollback and try again
            rollback_patch(workspace)
            attempt.status = "rolled_back"
            attempt.rollback_performed = True
            state.add_attempt(attempt)

            failure_summary = review.blocking_issues or [
                v.name for v in validations if not v.passed
            ]
            previous_failures.extend(failure_summary[:3])
            print(f"[BugfixWorkflow] Attempt {attempt_no} failed: {failure_summary[:2]}")

    # ── final report ──────────────────────────────────────────────────────────
    no_patch_generated = not any(a.patch_content for a in state.attempts)
    if successful_attempt:
        status = "completed"
        summary = f"Fixed: {task.title}. {len(successful_attempt.files_changed)} file(s) changed."
        if successful_attempt.review and successful_attempt.review.requires_human_approval:
            state.transition("waiting_human_approval")
            summary += " Waiting for human approval before commit."
    elif no_patch_generated:
        status = "needs_human"
        summary = (
            f"Diagnosis and planning completed for: {task.title}. "
            "No safe automatic patch was generated by the selected provider."
        )
    else:
        status = "failed"
        summary = f"Could not fix: {task.title} after {cfg.max_attempts} attempts."

    return _build_report(state, task, status, previous_failures, summary)


# ── helpers ────────────────────────────────────────────────────────────────────

def _run_baseline(task: TaskIntent, workspace: Path, cfg: OrchestratorConfig) -> list[ValidationResult]:
    results = []
    area = task.target_area

    if area in ("frontend", "tabzer", "fullstack") and cfg.frontend_validation.enabled:
        results.extend(run_frontend_validations(workspace, cfg.frontend_validation.commands))

    if area in ("backend", "fullstack") and cfg.backend_validation.enabled:
        results.extend(run_backend_validations(workspace, cfg.backend_validation.commands))

    return results


def _run_validations(task: TaskIntent, workspace: Path, cfg: OrchestratorConfig) -> list[ValidationResult]:
    return _run_baseline(task, workspace, cfg)


def _run_diagnostic_agents(task: TaskIntent, workspace: Path, state: TaskState) -> None:
    area = task.target_area

    if area in ("frontend", "tabzer", "fullstack"):
        result = FrontendBugAdapter().run(task, workspace)
        state.add_agent_result(result)
        print(f"[BugfixWorkflow] {result.agent_name}: {result.status}")

    if area in ("backend", "fullstack"):
        result = BackendBugAdapter().run(task, workspace)
        state.add_agent_result(result)
        print(f"[BugfixWorkflow] {result.agent_name}: {result.status}")

    if area == "tabzer":
        result = TabDebugAdapter().run(task, workspace, timeout_sec=120)
        state.add_agent_result(result)
        print(f"[BugfixWorkflow] {result.agent_name}: {result.status}")


def _build_report(
    state: TaskState,
    task: TaskIntent,
    status: str,
    failures: list[str],
    summary: str,
) -> FinalReport:
    files_changed = []
    for a in state.attempts:
        if a.status == "passed":
            files_changed.extend(a.files_changed)

    all_validations = state.baseline_results + [
        v for a in state.attempts for v in a.validation_results
    ]

    recs = list(failures[:3])
    if not files_changed and status == "failed":
        recs.append("Consider running the agent with --autonomy 1 for diagnosis only")
    if state.baseline_results and not all(v.passed for v in state.baseline_results):
        recs.append("Fix baseline errors before re-running the agent")

    report = FinalReport(
        task_id=task.task_id,
        status=status,
        summary=summary,
        files_changed=list(dict.fromkeys(files_changed)),
        validations=all_validations,
        attempts=state.attempts,
        agent_results=state.agent_results,
        recommendations=recs,
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
