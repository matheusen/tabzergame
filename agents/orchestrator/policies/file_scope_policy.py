"""File scope policy — enforce allowed/blocked path rules."""
from __future__ import annotations

import fnmatch
from pathlib import Path


_GLOBAL_BLOCKED: list[str] = [
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "**/secrets/**",
    "**/*secret*",
    "**/*credential*",
    "**/id_rsa",
    "**/id_ed25519",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "**/docker-compose.prod.*",
    "**/infra/prod/**",
    "**/*.pem",
    "**/*.key",
]

# These require human approval but are not auto-blocked
_REQUIRES_APPROVAL: list[str] = [
    "package.json",
    "**/package.json",
    "**/requirements.txt",
    "**/pyproject.toml",
    "**/Makefile",
    "**/docker-compose*.yml",
    "**/Dockerfile*",
    "*.lock",
    "**/migrations/**",
    "**/alembic/**",
]


def is_path_blocked(path: str, extra_blocked: list[str] | None = None) -> tuple[bool, str]:
    """Return (blocked, reason)."""
    all_blocked = _GLOBAL_BLOCKED + (extra_blocked or [])
    for pattern in all_blocked:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern):
            return True, f"matches blocked pattern: {pattern!r}"
    return False, ""


def requires_human_approval(path: str) -> bool:
    for pattern in _REQUIRES_APPROVAL:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern):
            return True
    return False


def filter_allowed_files(
    files: list[str],
    allowed_paths: list[str] | None = None,
    extra_blocked: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Returns (allowed_files, blocked_files).
    If allowed_paths is given, only files matching those patterns pass.
    """
    allowed = []
    blocked = []

    for f in files:
        is_blocked, reason = is_path_blocked(f, extra_blocked)
        if is_blocked:
            blocked.append(f)
            continue

        if allowed_paths:
            if any(fnmatch.fnmatch(f, pat) for pat in allowed_paths):
                allowed.append(f)
            else:
                blocked.append(f)
        else:
            allowed.append(f)

    return allowed, blocked


def check_patch_files(
    files_changed: list[str],
    allowed_paths: list[str] | None = None,
    extra_blocked: list[str] | None = None,
) -> list[str]:
    """Return list of violations for files changed by a patch."""
    violations = []
    for f in files_changed:
        blocked, reason = is_path_blocked(f, extra_blocked)
        if blocked:
            violations.append(f"Blocked file in patch: {f} — {reason}")
        if allowed_paths and not any(fnmatch.fnmatch(f, p) for p in allowed_paths):
            violations.append(f"File outside allowed scope: {f}")
    return violations
