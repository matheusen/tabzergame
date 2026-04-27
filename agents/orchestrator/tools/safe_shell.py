"""Safe subprocess runner — never uses shell=True."""
from __future__ import annotations

import subprocess
import time
import shutil
from dataclasses import dataclass
from pathlib import Path


_FORBIDDEN_FRAGMENTS = {
    "rm -rf",
    "del /s",
    "format ",
    "shutdown",
    "git reset --hard",
    "git clean -fdx",
    "docker system prune",
    "docker volume rm",
    "npm publish",
    "pip upload",
    "--no-verify",
}

_SHELL_OPERATORS = {"&&", "||", ";", "|", ">", "<", "`"}


@dataclass
class ShellResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SafeShellError(Exception):
    pass


def safe_run(
    command: list[str],
    cwd: Path,
    timeout_sec: int = 120,
    env: dict | None = None,
) -> ShellResult:
    if not command:
        raise SafeShellError("Empty command is not allowed")

    joined = " ".join(command)
    for fragment in _FORBIDDEN_FRAGMENTS:
        if fragment in joined:
            raise SafeShellError(f"Forbidden command fragment detected: {fragment!r}")

    for part in command:
        for op in _SHELL_OPERATORS:
            if op in part and op not in ("--", "->"):
                raise SafeShellError(f"Shell operator {op!r} detected in argument: {part!r}")

    if not cwd.exists():
        raise SafeShellError(f"Working directory does not exist: {cwd}")

    resolved_command = list(command)
    executable = shutil.which(resolved_command[0])
    if executable:
        resolved_command[0] = executable

    import os
    run_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if env:
        run_env.update(env)

    t0 = time.monotonic()
    try:
        # Use binary mode + manual decode to avoid Windows cp1252 reader thread issues
        proc = subprocess.run(
            resolved_command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            shell=False,
            env=run_env,
        )
    except subprocess.TimeoutExpired:
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout_sec}s",
            duration_sec=timeout_sec,
        )
    except FileNotFoundError as e:
        return ShellResult(
            command=command,
            exit_code=-2,
            stdout="",
            stderr=f"Command not found: {e}",
            duration_sec=time.monotonic() - t0,
        )

    return ShellResult(
        command=command,
        exit_code=proc.returncode,
        stdout=proc.stdout.decode("utf-8", errors="replace"),
        stderr=proc.stderr.decode("utf-8", errors="replace"),
        duration_sec=time.monotonic() - t0,
    )
