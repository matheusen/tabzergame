"""TaskState: the mutable, persisted state machine for a single orchestrator run."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import (
    AgentResult,
    FinalReport,
    PatchAttempt,
    Plan,
    TaskIntent,
    TaskStatus,
    ValidationResult,
)


class TaskState:
    def __init__(self, task: TaskIntent, runs_dir: Path) -> None:
        self.task = task
        self.runs_dir = runs_dir
        self.run_dir = runs_dir / task.task_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._status: TaskStatus = "created"
        self.workspace: Path | None = None
        self.baseline_results: list[ValidationResult] = []
        self.plan: Plan | None = None
        self.attempts: list[PatchAttempt] = []
        self.agent_results: list[AgentResult] = []
        self.final_report: FinalReport | None = None
        self.started_at = datetime.now()

        self._save_json("intent.json", self.task.model_dump())
        self._persist()

    # ── status ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> TaskStatus:
        return self._status

    def transition(self, new_status: TaskStatus) -> None:
        self._status = new_status
        self._persist()

    # ── mutations ─────────────────────────────────────────────────────────────

    def set_workspace(self, path: Path) -> None:
        self.workspace = path
        self._persist()

    def set_baseline(self, results: list[ValidationResult]) -> None:
        self.baseline_results = results
        baseline_dir = self.run_dir / "baseline"
        baseline_dir.mkdir(exist_ok=True)
        self._save_json("baseline/results.json", [r.model_dump() for r in results])
        self._persist()

    def set_plan(self, plan: Plan) -> None:
        self.plan = plan
        self._save_json("plan.json", plan.model_dump())
        self._persist()

    def add_agent_result(self, result: AgentResult) -> None:
        self.agent_results.append(result)
        self._persist()

    def add_attempt(self, attempt: PatchAttempt) -> None:
        self.attempts.append(attempt)
        attempt_dir = self.run_dir / "attempts" / f"attempt-{attempt.attempt_no:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        self._save_json(
            f"attempts/attempt-{attempt.attempt_no:03d}/attempt.json",
            attempt.model_dump(),
        )
        if attempt.patch_content:
            (attempt_dir / "patch.diff").write_text(
                attempt.patch_content, encoding="utf-8"
            )
        self._persist()

    def set_final_report(self, report: FinalReport) -> None:
        self.final_report = report
        self._save_json("final_report.json", report.model_dump())
        # Write human-readable markdown
        md = self._render_markdown(report)
        (self.run_dir / "final-report.md").write_text(md, encoding="utf-8")

    # ── helpers ───────────────────────────────────────────────────────────────

    def elapsed_sec(self) -> float:
        return (datetime.now() - self.started_at).total_seconds()

    def attempt_dir(self, attempt_no: int) -> Path:
        d = self.run_dir / "attempts" / f"attempt-{attempt_no:03d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist(self) -> None:
        data: dict[str, Any] = {
            "task_id": self.task.task_id,
            "status": self._status,
            "workspace": str(self.workspace) if self.workspace else None,
            "baseline_results": [r.model_dump() for r in self.baseline_results],
            "plan": self.plan.model_dump() if self.plan else None,
            "attempts_count": len(self.attempts),
            "agent_results": [r.model_dump() for r in self.agent_results],
            "updated_at": datetime.now().isoformat(),
        }
        self._save_json("state.json", data)

    def _save_json(self, relative: str, data: Any) -> None:
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _render_markdown(report: FinalReport) -> str:
        lines = [
            f"# Agent Run Report: {report.task_id}",
            "",
            f"## Status",
            f"`{report.status.upper()}`",
            "",
            f"## Summary",
            report.summary,
            "",
        ]

        if report.files_changed:
            lines += ["## Files Changed", ""]
            for f in report.files_changed:
                lines.append(f"- `{f}`")
            lines.append("")

        if report.validations:
            lines += ["## Validations", "", "| Validation | Status |", "|---|---|"]
            for v in report.validations:
                if v.status == "skipped":
                    icon = "SKIP"
                else:
                    icon = "PASS" if v.passed else "FAIL"
                lines.append(f"| {v.name} | {icon} {v.status} |")
            lines.append("")

        if report.attempts:
            lines += ["## Attempts", ""]
            for a in report.attempts:
                lines.append(f"- Attempt {a.attempt_no}: **{a.status}** - {a.plan_summary}")
            lines.append("")

        if report.agent_results:
            lines += ["## Agent Results", ""]
            for ar in report.agent_results:
                icon = "PASS" if ar.status == "passed" else "WARN"
                lines.append(f"- {icon} `{ar.agent_name}`: {ar.summary}")
            lines.append("")

        if report.recommendations:
            lines += ["## Recommendations", ""]
            for r in report.recommendations:
                lines.append(f"- {r}")
            lines.append("")

        if report.duration_sec:
            lines.append(f"_Completed in {report.duration_sec:.1f}s_")

        return "\n".join(lines)
