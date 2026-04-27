"""Feature Workflow — spec → plan → implement minimal vertical slice → validate → report."""
from __future__ import annotations

import json
from pathlib import Path

from ..agents import patch_agent, planner_agent, reviewer_agent
from ..adapters.frontend_bug_adapter import FrontendBugAdapter
from ..config import OrchestratorConfig
from ..schemas import FinalReport, PatchAttempt, TaskIntent
from ..state import TaskState
from ..tools.git_worktree import create_worktree, worktree_available
from ..tools.patch_applier import apply_patch, extract_changed_files, rollback_patch
from ..tools.test_runner import all_passed, run_frontend_validations


def run(
    task: TaskIntent,
    state: TaskState,
    repo_root: Path,
    cfg: OrchestratorConfig,
) -> FinalReport:
    print(f"[FeatureWorkflow] Starting: {task.task_id}")

    # ── worktree ──────────────────────────────────────────────────────────────
    workspace = repo_root
    if worktree_available() and task.autonomy_level >= 3:
        try:
            workspace = create_worktree(repo_root, repo_root / cfg.worktrees_dir, task.task_id)
            state.set_workspace(workspace)
            state.transition("worktree_created")
        except Exception as e:
            print(f"[FeatureWorkflow] Worktree failed ({e})")
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

    # ── feature spec ──────────────────────────────────────────────────────────
    spec = _generate_spec(task, cfg)
    print(f"[FeatureWorkflow] Spec generated: {spec.get('feature_name', task.title)}")

    # ── plan ──────────────────────────────────────────────────────────────────
    state.transition("planning")
    plan = planner_agent.create_plan(task, workspace, cfg)
    plan.feature_spec = spec
    state.set_plan(plan)

    if task.autonomy_level < 3:
        return _build_report(
            state, task, "needs_human", "Autonomy < 3: spec and plan ready. Implementation requires approval."
        )

    # ── diagnostic baseline ───────────────────────────────────────────────────
    state.transition("baseline_running")
    baseline = run_frontend_validations(workspace, cfg.frontend_validation.commands)
    state.set_baseline(baseline)
    state.transition("baseline_passed" if all_passed(baseline) else "baseline_failed")

    # ── implementation loop ───────────────────────────────────────────────────
    previous_failures: list[str] = []
    successful_attempt: PatchAttempt | None = None

    for attempt_no in range(1, cfg.max_attempts + 1):
        print(f"[FeatureWorkflow] Attempt {attempt_no}/{cfg.max_attempts}")
        state.transition("patching")

        patch_content = patch_agent.generate_patch(
            task, plan, workspace, attempt_no, previous_failures, cfg
        )

        if not patch_content:
            attempt = PatchAttempt(
                attempt_no=attempt_no,
                plan_summary=plan.hypothesis,
                status="failed",
            )
            state.add_attempt(attempt)
            previous_failures.append("Patch agent could not generate implementation")
            if cfg.llm_provider == "none":
                break
            continue

        files_changed = extract_changed_files(patch_content)

        # Dry-run
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

        # Apply
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

        # Validate
        state.transition("validating")
        validations = run_frontend_validations(workspace, cfg.frontend_validation.commands)

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
            break
        else:
            rollback_patch(workspace)
            attempt.status = "rolled_back"
            attempt.rollback_performed = True
            state.add_attempt(attempt)
            previous_failures.extend(review.blocking_issues[:2])

    no_patch_generated = not any(a.patch_content for a in state.attempts)
    if successful_attempt:
        status = "completed"
        summary = (
            f"Feature implemented: {task.title}. "
            f"{len(successful_attempt.files_changed)} file(s) changed."
        )
    elif no_patch_generated:
        status = "needs_human"
        summary = (
            f"Spec and plan completed for: {task.title}. "
            "No safe automatic implementation was generated by the selected provider."
        )
    else:
        status = "failed"
        summary = f"Could not implement: {task.title} after {cfg.max_attempts} attempts."

    return _build_report(state, task, status, summary)


def _generate_spec(task: TaskIntent, cfg: OrchestratorConfig) -> dict:
    """Generate a feature spec — LLM if available, template otherwise."""
    from ..tools.llm_client import extract_json, get_client, LLMError

    client = get_client(cfg.llm_provider, cfg.llm_model, cfg.llm_model_fast)
    if not client.available:
        return _template_spec(task)

    try:
        prompt = f"""Generate a concise feature specification for this Tabzer app request.
Return ONLY valid JSON:
{{
  "feature_name": "...",
  "problem": "...",
  "goal": "...",
  "user_flow": ["step1"],
  "acceptance_criteria": ["criterion1"],
  "non_goals": ["..."],
  "minimal_vertical_slice": "description of MVP"
}}

Request: {task.user_request}"""

        raw = client.complete(
            messages=[{"role": "user", "content": prompt}],
            json_mode=True,
            max_tokens=600,
            fast=True,
        )
        return extract_json(raw) or _template_spec(task)
    except (LLMError, Exception) as e:
        print(f"[FeatureWorkflow] Spec generation failed ({e}) — using template")
        return _template_spec(task)


def _template_spec(task: TaskIntent) -> dict:
    return {
        "feature_name": task.title,
        "problem": task.user_request,
        "goal": f"Implement: {task.title}",
        "user_flow": ["User triggers feature", "Feature responds correctly"],
        "acceptance_criteria": task.acceptance_criteria or [f"Feature works as described: {task.title}"],
        "non_goals": ["Full production-grade implementation in first iteration"],
        "minimal_vertical_slice": "Basic implementation that satisfies acceptance criteria",
    }


def _build_report(state: TaskState, task: TaskIntent, status: str, summary: str) -> FinalReport:
    files_changed = []
    for a in state.attempts:
        if a.status == "passed":
            files_changed.extend(a.files_changed)

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
            "Review the generated spec before running at higher autonomy",
            "Add Playwright tests for the new feature flow",
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
