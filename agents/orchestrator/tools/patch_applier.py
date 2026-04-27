"""Apply and roll back unified diffs to a workspace."""
from __future__ import annotations

import re
from pathlib import Path

from .safe_shell import ShellResult, safe_run


class PatchError(Exception):
    pass


def apply_patch(workspace: Path, patch_content: str, dry_run: bool = False) -> ShellResult:
    """Write the patch to a temp file and apply it with git apply."""
    if not patch_content.strip():
        raise PatchError("Empty patch content")

    patch_file = workspace / ".agent_patch.diff"
    patch_file.write_text(patch_content, encoding="utf-8")

    cmd = ["git", "apply", "--reject", str(patch_file)]
    if dry_run:
        cmd.insert(2, "--check")

    result = safe_run(cmd, cwd=workspace, timeout_sec=30)
    patch_file.unlink(missing_ok=True)
    return result


def rollback_patch(workspace: Path) -> ShellResult:
    """Rollback uncommitted changes in the worktree."""
    return safe_run(
        ["git", "checkout", "--", "."],
        cwd=workspace,
        timeout_sec=30,
    )


def extract_changed_files(patch_content: str) -> list[str]:
    """Parse unified diff to extract changed file paths."""
    files = []
    for line in patch_content.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
    return list(dict.fromkeys(files))  # deduplicate, preserve order


def validate_patch_safety(
    patch_content: str,
    blocked_paths: list[str],
) -> list[str]:
    """Return list of blocking violations in the patch."""
    import fnmatch

    changed = extract_changed_files(patch_content)
    violations = []

    for changed_file in changed:
        for blocked in blocked_paths:
            if fnmatch.fnmatch(changed_file, blocked):
                violations.append(f"Patch touches blocked path: {changed_file} (pattern: {blocked})")

    lines = patch_content.splitlines()
    test_removals = [
        l for l in lines
        if l.startswith("-") and ("test(" in l or "it(" in l or "describe(" in l or "def test_" in l)
    ]
    if len(test_removals) > 5:
        violations.append(f"Patch removes {len(test_removals)} test lines — suspicious")

    # Detect suppressed errors (any as escape hatch)
    any_casts = [l for l in lines if l.startswith("+") and "as any" in l]
    if len(any_casts) > 3:
        violations.append(f"Patch adds {len(any_casts)} 'as any' TypeScript suppressions")

    return violations
