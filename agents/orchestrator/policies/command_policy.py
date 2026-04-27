"""Command allowlist/denylist policy."""
from __future__ import annotations


_ALLOWED_PREFIXES: list[tuple[str, ...]] = [
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "show"),
    ("git", "worktree"),
    ("git", "branch"),
    ("git", "checkout"),
    ("git", "apply"),
    ("npm", "run"),
    ("npx",),
    ("python", "-m", "pytest"),
    ("python", "-m", "ruff"),
    ("python", "-m", "mypy"),
    ("python", "agents/"),
    ("python", "backend/agents/"),
    ("node",),
    ("tsc",),
]

_FORBIDDEN_SUBSTRINGS: list[str] = [
    "rm -rf",
    "del /s",
    "format ",
    "shutdown",
    "reboot",
    "git reset --hard",
    "git clean -fdx",
    "docker system prune",
    "docker volume rm",
    "npm publish",
    "pip upload",
    "pip install",
    "--no-verify",
    "git push",
    "git merge",
]


def is_command_allowed(command: list[str]) -> tuple[bool, str]:
    """Return (allowed, reason). Reason is empty when allowed."""
    if not command:
        return False, "empty command"

    joined = " ".join(command)
    for fragment in _FORBIDDEN_SUBSTRINGS:
        if fragment in joined:
            return False, f"forbidden fragment: {fragment!r}"

    for prefix in _ALLOWED_PREFIXES:
        if tuple(command[: len(prefix)]) == prefix:
            return True, ""

    return False, f"command not in allowlist: {command[0]!r}"


def assert_command_allowed(command: list[str]) -> None:
    allowed, reason = is_command_allowed(command)
    if not allowed:
        raise PermissionError(f"Command blocked by policy: {reason} — {command}")
