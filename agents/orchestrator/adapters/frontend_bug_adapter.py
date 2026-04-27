"""Adapter for the existing frontend_bug_agent."""
from __future__ import annotations

import sys
from pathlib import Path

from ..schemas import AgentResult, TaskIntent
from ..tools.safe_shell import safe_run


class FrontendBugAdapter:
    name = "frontend_bug_agent"

    def run(self, task: TaskIntent, workspace: Path) -> AgentResult:
        agent_script = workspace / "backend" / "agents" / "frontend_bug_agent" / "run_agent.py"

        if not agent_script.exists():
            return AgentResult(
                agent_name=self.name,
                status="skipped",
                summary="frontend_bug_agent not found in workspace",
            )

        result = safe_run(
            [sys.executable, str(agent_script)],
            cwd=workspace,
            timeout_sec=180,
        )

        findings = []
        if result.stdout:
            # Try to parse JSON output from the agent
            import json
            try:
                data = json.loads(result.stdout)
                errors = data.get("errors", 0)
                warnings = data.get("warnings", 0)
                findings.append(f"TypeScript errors: {errors}, warnings: {warnings}")
            except (json.JSONDecodeError, AttributeError):
                # Fallback: extract key lines
                for line in result.stdout.splitlines()[:10]:
                    if line.strip():
                        findings.append(line.strip())

        status = "passed" if result.ok else "failed"
        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=f"Frontend validation {'passed' if result.ok else 'failed'} (exit {result.exit_code})",
            findings=findings,
            metrics={"exit_code": result.exit_code, "duration_sec": result.duration_sec},
            error=result.stderr[:500] if not result.ok else None,
        )
