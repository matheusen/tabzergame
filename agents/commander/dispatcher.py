"""
Commander — Dispatcher
Receives a CommandIntent and invokes the appropriate agent via subprocess.
Returns the agent output as a string.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PYTHON = sys.executable


def _run_subprocess(cmd: list[str], cwd: Path = _REPO_ROOT, timeout: int = 180) -> str:
    """Run a subprocess and return combined stdout+stderr as a string."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(result.stderr.strip())
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return "[dispatcher] Timed out waiting for agent."
    except Exception as exc:
        return f"[dispatcher] Error: {exc}"


def dispatch(intent: "Any") -> str:  # intent: CommandIntent from command_parser
    agent = intent.agent
    action = intent.action
    params = intent.params

    # ── Internal commands ──────────────────────────────────────────────────────
    if agent == "internal":
        if action == "help":
            return _HELP_TEXT
        if action == "quit":
            return "__quit__"
        if action == "status":
            return _status_text()
        return "Unknown internal command."

    # ── Study Agent ────────────────────────────────────────────────────────────
    if agent == "study":
        topic = params.get("topic")
        count = params.get("count", 2)
        dry_run = params.get("dry_run", False)
        script = _REPO_ROOT / "backend" / "agents" / "study_agent" / "run_agent.py"

        if not topic:
            topics_output = _run_subprocess(
                [_PYTHON, str(script), "--list-topics"], cwd=_REPO_ROOT
            )
            return (
                "[commander] Topic not identified. Available topics:\n"
                + topics_output
                + "\n\nTry: 'gera 2 exercicios para escalas'"
            )

        cmd = [_PYTHON, str(script), "--topic", topic, "--action", action, "--count", str(count)]
        if dry_run:
            cmd.append("--dry-run")
        return _run_subprocess(cmd, timeout=120)

    # ── Bug Team ───────────────────────────────────────────────────────────────
    if agent == "bug":
        run_fe = params.get("frontend", True)
        run_be = params.get("backend", True)
        script = _REPO_ROOT / "backend" / "agents" / "bug_team" / "run_orchestrator.py"
        cmd = [_PYTHON, str(script)]
        if run_fe and run_be:
            cmd.append("--all")
        elif run_fe:
            cmd.append("--frontend")
        elif run_be:
            cmd.append("--backend")
        return _run_subprocess(cmd, timeout=300)

    # ── Copilot ────────────────────────────────────────────────────────────────
    if agent == "copilot":
        from copilot_adapter import suggest, explain  # type: ignore[import]
        prompt = params.get("prompt", intent.raw)
        if action == "explain":
            return explain(prompt)
        return suggest(prompt)

    # ── Tab Debug Agent ────────────────────────────────────────────────────────
    if agent == "tab_debug":
        task = params.get("task", "cursor-glide-quality")
        url = params.get("url", "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugCursor=1")
        script = _REPO_ROOT / "backend" / "agents" / "tab_debug_agent" / "run_agent.py"
        cmd = [
            _PYTHON, str(script),
            "--task", task,
            "--url", url,
            "--no-openai", "--codex-stdout-only", "--headless", "0",
            "--wait-ms", "15000", "--tab-shots", "0",
        ]
        return _run_subprocess(cmd, timeout=120)

    return f"[dispatcher] Unknown agent: '{agent}'"


# ── helpers ───────────────────────────────────────────────────────────────────

def _status_text() -> str:
    try:
        from copilot_adapter import status as copilot_status  # type: ignore[import]
        cop = copilot_status()
    except Exception:
        cop = {"gh_available": False, "copilot_available": False}

    lines = [
        "── Commander Status ──",
        f"  gh CLI:      {'✓' if cop['gh_available'] else '✗ (install from https://cli.github.com/)'}",
        f"  gh copilot:  {'✓' if cop['copilot_available'] else '✗ (gh extension install github/gh-copilot)'}",
        f"  Python:      {_PYTHON}",
        f"  Repo root:   {_REPO_ROOT}",
    ]
    return "\n".join(lines)


_HELP_TEXT = """
── Commander Help ──────────────────────────────────────────────────

STUDY AGENT — Generate exercises for the /study page
  gera 2 exercicios para escalas
  cria teoria para campo harmonico
  gera 3 exercicios tecnicos de postura
  [usa OpenAI se OPENAI_API_KEY estiver configurada]

BUG TEAM — Find TypeScript / lint / API errors
  fix bugs                    (roda frontend + backend)
  verifica erros de frontend  (tsc + eslint)
  verifica backend            (ruff + healthcheck)

COPILOT — Ask gh copilot
  explica git rebase -i
  sugere como otimizar esta query SQL
  [requer gh CLI + gh copilot extension]

TAB DEBUG — Run cursor probe
  debug cursor                (cursor-glide-quality task)
  probe tab playback

INTERNAL
  status    — show tool availability
  help / ?  — this message
  quit      — exit

────────────────────────────────────────────────────────────────────
"""
