"""Persistent run store — index of all past orchestrator runs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..schemas import FinalReport, TaskIntent


_INDEX_FILE = "runs_index.json"


class RunStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = runs_dir / _INDEX_FILE

    def record_start(self, task: TaskIntent) -> None:
        index = self._load_index()
        index[task.task_id] = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "title": task.title,
            "target_area": task.target_area,
            "status": "running",
            "started_at": task.created_at,
            "finished_at": None,
        }
        self._save_index(index)

    def record_finish(self, report: FinalReport) -> None:
        index = self._load_index()
        if report.task_id in index:
            index[report.task_id]["status"] = report.status
            index[report.task_id]["finished_at"] = datetime.now().isoformat()
            index[report.task_id]["files_changed"] = len(report.files_changed)
            index[report.task_id]["attempts"] = len(report.attempts)
        self._save_index(index)

    def list_runs(self, task_type: str | None = None, limit: int = 20) -> list[dict]:
        index = self._load_index()
        runs = list(index.values())
        runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        if task_type:
            runs = [r for r in runs if r.get("task_type") == task_type]
        return runs[:limit]

    def get_run(self, task_id: str) -> dict | None:
        index = self._load_index()
        return index.get(task_id)

    def get_final_report(self, task_id: str) -> dict | None:
        path = self.runs_dir / task_id / "final_report.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def find_similar(self, keywords: list[str]) -> list[dict]:
        """Find past runs that share keywords with the current task."""
        index = self._load_index()
        matches = []
        for run in index.values():
            title = run.get("title", "").lower()
            if any(kw.lower() in title for kw in keywords):
                matches.append(run)
        return matches[:5]

    def _load_index(self) -> dict:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_index(self, index: dict) -> None:
        self._index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )
