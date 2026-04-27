"""Reviewer Agent — deterministic rules + optional LLM review."""
from __future__ import annotations

import json

from ..config import OrchestratorConfig
from ..schemas import PatchAttempt, ReviewResult, RiskLevel, TaskIntent, ValidationResult
from ..tools.llm_client import LLMError, extract_json, get_client
from ..policies.file_scope_policy import check_patch_files, requires_human_approval
from ..tools.patch_applier import extract_changed_files, validate_patch_safety


_SYSTEM = """You are a senior software engineer reviewing a code patch for the Tabzer guitar app.

Evaluate strictly. Return ONLY valid JSON (no markdown, no explanation):
{
  "approved": true|false,
  "risk": "low"|"medium"|"high"|"critical",
  "summary": "1-2 sentence review",
  "blocking_issues": [],
  "non_blocking_suggestions": [],
  "requires_human_approval": false
}

Blocking (approved=false):
- Patch doesn't address the stated task
- Removes tests to pass validation
- Touches secrets/env files
- Adds large unrelated refactors
- Introduces obvious security vulnerability
- TypeScript 'as any' without justification

Requires human approval (approved=true but flag=true):
- Changes to authentication logic
- Database schema changes
- Infrastructure files
- File deletions"""


def review(
    task: TaskIntent,
    attempt: PatchAttempt,
    validation_results: list[ValidationResult],
    cfg: OrchestratorConfig | None = None,
) -> ReviewResult:
    patch = attempt.patch_content
    files_changed = extract_changed_files(patch)
    blocking: list[str] = []
    suggestions: list[str] = []
    requires_human = False

    # ── deterministic checks ──────────────────────────────────────────────────
    blocking.extend(validate_patch_safety(patch, task.blocked_paths or []))
    blocking.extend(check_patch_files(files_changed, task.allowed_paths or None))

    added = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
    if added > 200:
        suggestions.append(f"Large patch ({added} added lines) — consider splitting")

    failed_validations = [v for v in validation_results if not v.passed]
    for v in failed_validations:
        blocking.append(f"Validation failed: {v.name} (exit {v.exit_code})")

    for f in files_changed:
        if requires_human_approval(f):
            requires_human = True
            suggestions.append(f"{f} requires human approval")

    if blocking:
        risk: RiskLevel = "high" if len(blocking) > 2 else "medium"
        return ReviewResult(
            approved=False,
            risk=risk,
            summary=f"Blocked: {blocking[0]}",
            blocking_issues=blocking,
            non_blocking_suggestions=suggestions,
            requires_human_approval=requires_human,
        )

    # ── LLM review ────────────────────────────────────────────────────────────
    p = cfg.llm_provider if cfg else "auto"
    m = cfg.llm_model_fast if cfg else None
    client = get_client(p, None, m)

    if client.available and patch:
        try:
            result = _llm_review(task, attempt, validation_results, client)
            result.non_blocking_suggestions.extend(suggestions)
            result.requires_human_approval = result.requires_human_approval or requires_human
            return result
        except (LLMError, Exception) as e:
            print(f"[ReviewerAgent] LLM review failed ({e}) — deterministic approval")

    # ── deterministic approval ────────────────────────────────────────────────
    risk_level: RiskLevel = "low" if added < 50 else "medium"
    return ReviewResult(
        approved=True,
        risk=risk_level,
        summary=f"Deterministic review passed. {added} lines added, {removed} removed.",
        blocking_issues=[],
        non_blocking_suggestions=suggestions,
        requires_human_approval=requires_human,
    )


def _llm_review(
    task: TaskIntent,
    attempt: PatchAttempt,
    validation_results: list[ValidationResult],
    client,
) -> ReviewResult:
    val_summary = "\n".join(
        f"- {v.name}: {'PASSED' if v.passed else 'FAILED'} (exit {v.exit_code})"
        for v in validation_results
    )
    user_content = f"""Task type: {task.task_type}
Request: {task.user_request}
Acceptance criteria: {json.dumps(task.acceptance_criteria, ensure_ascii=False)}

Validation results:
{val_summary}

Patch (attempt {attempt.attempt_no}):
{attempt.patch_content[:4000]}"""

    raw = client.complete(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_content},
        ],
        json_mode=True,
        max_tokens=512,
        fast=True,
    )
    data = extract_json(raw) or {}

    risk = data.get("risk", "medium")
    if risk not in ("low", "medium", "high", "critical"):
        risk = "medium"

    return ReviewResult(
        approved=bool(data.get("approved", False)),
        risk=risk,
        summary=str(data.get("summary", "LLM review completed")),
        blocking_issues=data.get("blocking_issues", []),
        non_blocking_suggestions=data.get("non_blocking_suggestions", []),
        requires_human_approval=bool(data.get("requires_human_approval", False)),
    )
