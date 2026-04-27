"""
Commander — Copilot Adapter
Wraps the `gh copilot` CLI for suggest and explain actions.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_copilot_installed() -> bool:
    if not _gh_available():
        return False
    result = subprocess.run(
        ["gh", "copilot", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0


def suggest(prompt: str, shell: str = "powershell") -> str:
    """
    Run `gh copilot suggest '<prompt>'`.
    shell: "powershell" | "bash" | "zsh" (default: powershell on Windows)
    """
    if not _gh_available():
        return "[copilot] gh CLI not found. Install from https://cli.github.com/"
    if not _gh_copilot_installed():
        return "[copilot] gh copilot extension not installed. Run: gh extension install github/gh-copilot"

    try:
        result = subprocess.run(
            ["gh", "copilot", "suggest", "--shell-out", shell, prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (result.stdout + result.stderr).strip()
        return out if out else "[copilot] No response."
    except subprocess.TimeoutExpired:
        return "[copilot] Request timed out."
    except Exception as exc:
        return f"[copilot] Error: {exc}"


def explain(command: str) -> str:
    """Run `gh copilot explain '<command>'`."""
    if not _gh_available():
        return "[copilot] gh CLI not found. Install from https://cli.github.com/"
    if not _gh_copilot_installed():
        return "[copilot] gh copilot extension not installed. Run: gh extension install github/gh-copilot"

    try:
        result = subprocess.run(
            ["gh", "copilot", "explain", command],
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (result.stdout + result.stderr).strip()
        return out if out else "[copilot] No explanation."
    except subprocess.TimeoutExpired:
        return "[copilot] Request timed out."
    except Exception as exc:
        return f"[copilot] Error: {exc}"


def status() -> dict[str, Any]:
    """Return installation status of gh and gh copilot."""
    gh_ok = _gh_available()
    copilot_ok = _gh_copilot_installed() if gh_ok else False
    return {
        "gh_available": gh_ok,
        "copilot_available": copilot_ok,
        "gh_path": shutil.which("gh") or None,
    }
