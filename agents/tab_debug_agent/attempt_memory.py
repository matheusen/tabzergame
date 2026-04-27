from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AttemptMemory:
    path: Path
    records: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "AttemptMemory":
        resolved = Path(path)
        if resolved.exists():
            try:
                raw = json.loads(resolved.read_text(encoding="utf-8"))
            except Exception:
                raw = []
            if isinstance(raw, list):
                return cls(path=resolved, records=raw)
        return cls(path=resolved, records=[])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")

    def append(self, record: dict[str, Any]) -> None:
        self.records.append(record)
        self.save()

    def has_rejected_signature(self, *, strategy: str, signature: str) -> bool:
        for item in reversed(self.records):
            if str(item.get("strategy") or "") != str(strategy):
                continue
            if str(item.get("signature") or "") != str(signature):
                continue
            if not bool(item.get("accepted")):
                return True
        return False

    def latest_for_task(self, task_id: str) -> dict[str, Any] | None:
        for item in reversed(self.records):
            if str(item.get("taskId") or "") == str(task_id):
                return item
        return None
