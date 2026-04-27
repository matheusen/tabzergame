"""Adapter for the existing tab_debug_agent — the most specialized Tabzer agent."""
from __future__ import annotations

import json
import sys
import importlib.util
from pathlib import Path

from ..schemas import AgentResult, TaskIntent
from ..tools.safe_shell import safe_run


class TabDebugAdapter:
    name = "tab_debug_agent"

    def run(
        self,
        task: TaskIntent,
        workspace: Path,
        mode: str = "codex",
        timeout_sec: int = 300,
    ) -> AgentResult:
        agent_script = workspace / "backend" / "agents" / "tab_debug_agent" / "run_agent.py"

        if not agent_script.exists():
            return AgentResult(
                agent_name=self.name,
                status="skipped",
                summary="tab_debug_agent not found in workspace",
            )
        if importlib.util.find_spec("playwright") is None:
            return AgentResult(
                agent_name=self.name,
                status="skipped",
                summary="tab_debug_agent skipped: Python package 'playwright' is not installed",
                findings=["Install backend/agents/tab_debug_agent/requirements.txt to enable browser diagnostics"],
            )

        cmd = [sys.executable, str(agent_script), "--codex-stdout-only", "--no-openai"]
        if task.target_url:
            cmd += ["--url", task.target_url]

        result = safe_run(cmd, cwd=workspace, timeout_sec=timeout_sec)

        findings: list[str] = []
        metrics: dict = {"exit_code": result.exit_code, "duration_sec": result.duration_sec}

        if result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    if "score" in data:
                        metrics["score"] = data["score"]
                        findings.append(f"Cursor score: {data['score']}")
                    if "verdict" in data:
                        findings.append(f"Verdict: {data['verdict']}")
                    for key in ("freezes", "pauses", "kicks", "jitter"):
                        if key in data:
                            findings.append(f"{key}: {data[key]}")
            except (json.JSONDecodeError, AttributeError):
                for line in result.stdout.splitlines()[:15]:
                    if line.strip():
                        findings.append(line.strip())

        if result.stderr and not result.ok:
            findings.append(f"stderr: {result.stderr[:200]}")

        status = "passed" if result.ok else "failed"
        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=f"Tab debug {'passed' if result.ok else 'failed'} (exit {result.exit_code})",
            findings=findings,
            metrics=metrics,
            error=result.stderr[:500] if not result.ok else None,
        )

    def run_fix_loop(self, task: TaskIntent, workspace: Path, timeout_sec: int = 600) -> AgentResult:
        """Run the automated cursor fix loop."""
        script = workspace / "backend" / "agents" / "tab_debug_agent" / "run_fix_loop.py"

        if not script.exists():
            return AgentResult(
                agent_name=f"{self.name}/fix_loop",
                status="skipped",
                summary="run_fix_loop.py not found",
            )
        if importlib.util.find_spec("playwright") is None:
            return AgentResult(
                agent_name=f"{self.name}/fix_loop",
                status="skipped",
                summary="Fix loop skipped: Python package 'playwright' is not installed",
            )

        result = safe_run([sys.executable, str(script)], cwd=workspace, timeout_sec=timeout_sec)

        findings = []
        if result.stdout:
            for line in result.stdout.splitlines()[:20]:
                if line.strip():
                    findings.append(line.strip())

        return AgentResult(
            agent_name=f"{self.name}/fix_loop",
            status="passed" if result.ok else "failed",
            summary=f"Fix loop {'completed' if result.ok else 'failed'}",
            findings=findings,
            metrics={"exit_code": result.exit_code, "duration_sec": result.duration_sec},
        )
