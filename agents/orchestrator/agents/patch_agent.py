"""Patch Agent — generates unified diffs using an LLM given a plan and file context."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import OrchestratorConfig
from ..schemas import Plan, TaskIntent
from ..tools.llm_client import LLMError, get_client
from .repo_mapper_agent import build_context_for_llm


_SYSTEM = """You are a senior software/game engineer acting as the Patch Agent for the Tabzer Agent Orchestrator.

Your job: generate a minimal, correct unified diff (git diff format) that fixes the issue or implements the feature.

CRITICAL RULES:
1. Output ONLY the unified diff. No explanation, no markdown fences.
2. Use standard unified diff format: --- a/path, +++ b/path, @@ -L,S +L,S @@
3. Make the smallest possible change. Do NOT refactor unrelated code.
4. Do NOT touch .env, secrets, lock files.
5. Do NOT add "as any" TypeScript casts without justification.
6. Do NOT remove existing tests.
7. New files: use --- /dev/null, +++ b/new_file.ext
8. For Godot tasks, preserve existing node names, scene structure, collision layers, and resource paths unless the task requires changing them.
9. If you cannot produce a confident, safe fix, output exactly: PATCH_IMPOSSIBLE"""

_FEATURE_NOTE = """
For features: implement the minimal vertical slice only.
Add TODO comments for anything deferred to a future iteration."""


def generate_patch(
    task: TaskIntent,
    plan: Plan,
    repo_root: Path,
    attempt_no: int = 1,
    previous_failures: list[str] | None = None,
    cfg: OrchestratorConfig | None = None,
) -> str | None:
    p = cfg.llm_provider if cfg else "auto"
    m = cfg.llm_model if cfg else None
    mf = cfg.llm_model_fast if cfg else None
    client = get_client(p, m, mf)

    if not client.available:
        print("[PatchAgent] No LLM provider — cannot generate patch automatically")
        return None

    try:
        context = build_context_for_llm(task, repo_root, plan.probable_files, max_chars_per_file=3000)
        user_content = _build_prompt(task, plan, context, attempt_no, previous_failures)

        raw = client.complete(
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_content},
            ],
            json_mode=False,
            max_tokens=3000,
        )

        if not raw or raw.strip() == "PATCH_IMPOSSIBLE":
            print("[PatchAgent] LLM declared patch impossible")
            return None

        patch = _extract_diff(raw)
        if not patch:
            print("[PatchAgent] Could not extract valid diff from response")
            return None

        return patch

    except LLMError as e:
        print(f"[PatchAgent] LLM failed: {e}")
        return None
    except Exception as e:
        print(f"[PatchAgent] Unexpected error: {e}")
        return None


def _build_prompt(
    task: TaskIntent,
    plan: Plan,
    context: str,
    attempt_no: int,
    previous_failures: list[str] | None,
) -> str:
    parts = [
        f"# Task (Attempt {attempt_no})",
        f"**Type**: {task.task_type}",
        f"**Request**: {task.user_request}",
        f"**Acceptance criteria**: {json.dumps(task.acceptance_criteria, ensure_ascii=False)}",
        "",
        "# Plan",
        f"**Hypothesis**: {plan.hypothesis}",
        "**Steps**:",
    ]
    for step in plan.steps:
        parts.append(f"  - {step}")

    if previous_failures:
        parts += ["", "# Previous Failures (do NOT repeat):"]
        for f in previous_failures:
            parts.append(f"  - {f}")

    if task.task_type == "feature":
        parts.append(_FEATURE_NOTE)

    parts += ["", "# Codebase Context", context]
    return "\n".join(parts)


def _extract_diff(raw: str) -> str | None:
    """Extract a unified diff block from the LLM response."""
    raw = re.sub(r"```diff\s*", "", raw)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()
    if "--- " in raw and "+++ " in raw and "@@ " in raw:
        return raw
    return None
