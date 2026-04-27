"""Git worktree management — creates isolated branches per task."""
from __future__ import annotations

import shutil
from pathlib import Path

from .safe_shell import ShellResult, safe_run


class WorktreeError(Exception):
    pass


def create_worktree(repo_root: Path, worktrees_dir: Path, task_id: str) -> Path:
    """Create a new git worktree for the task and return its path."""
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    worktree_path = worktrees_dir / task_id
    branch_name = f"agent/{task_id}"

    if worktree_path.exists():
        return worktree_path

    result = safe_run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
        cwd=repo_root,
        timeout_sec=30,
    )

    if not result.ok:
        # Branch may already exist — try without -b
        result2 = safe_run(
            ["git", "worktree", "add", str(worktree_path), "HEAD"],
            cwd=repo_root,
            timeout_sec=30,
        )
        if not result2.ok:
            raise WorktreeError(
                f"Failed to create worktree: {result.stderr} / {result2.stderr}"
            )

    return worktree_path


def remove_worktree(repo_root: Path, worktree_path: Path) -> ShellResult:
    """Remove a git worktree and prune the reference."""
    result = safe_run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_root,
        timeout_sec=30,
    )
    if not result.ok and worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
        safe_run(["git", "worktree", "prune"], cwd=repo_root, timeout_sec=15)
    return result


def list_worktrees(repo_root: Path) -> list[str]:
    result = safe_run(["git", "worktree", "list", "--porcelain"], cwd=repo_root)
    return [
        line.split()[-1]
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def worktree_available() -> bool:
    """Check whether git is available."""
    import subprocess
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, timeout=5, shell=False)
        return r.returncode == 0
    except Exception:
        return False
