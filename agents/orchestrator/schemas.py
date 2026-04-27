"""Core Pydantic schemas for the Tabzer Agent Orchestrator."""
from __future__ import annotations

import uuid
import copy
from datetime import datetime
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field
except ModuleNotFoundError:
    class _FieldInfo:
        def __init__(self, default: Any = None, default_factory: Any = None, **_: Any) -> None:
            self.default = default
            self.default_factory = default_factory

        def value(self) -> Any:
            if self.default_factory is not None:
                return self.default_factory()
            return copy.deepcopy(self.default)

    def Field(default: Any = None, default_factory: Any = None, **kwargs: Any) -> _FieldInfo:
        return _FieldInfo(default=default, default_factory=default_factory, **kwargs)

    class BaseModel:
        def __init__(self, **data: Any) -> None:
            annotations = self._collect_annotations()
            for name in annotations:
                if name in data:
                    value = data.pop(name)
                else:
                    value = self._default_for(name)
                setattr(self, name, value)
            for name, value in data.items():
                setattr(self, name, value)

        @classmethod
        def _collect_annotations(cls) -> dict[str, Any]:
            annotations: dict[str, Any] = {}
            for base in reversed(cls.__mro__):
                annotations.update(getattr(base, "__annotations__", {}))
            return annotations

        @classmethod
        def _default_for(cls, name: str) -> Any:
            if hasattr(cls, name):
                default = getattr(cls, name)
                if isinstance(default, _FieldInfo):
                    return default.value()
                return copy.deepcopy(default)
            return None

        def model_dump(self) -> dict[str, Any]:
            def dump(value: Any) -> Any:
                if isinstance(value, BaseModel):
                    return value.model_dump()
                if isinstance(value, list):
                    return [dump(item) for item in value]
                if isinstance(value, dict):
                    return {k: dump(v) for k, v in value.items()}
                return value

            return {
                name: dump(getattr(self, name))
                for name in self._collect_annotations()
                if hasattr(self, name)
            }

        def model_copy(self, update: dict[str, Any] | None = None) -> "BaseModel":
            data = self.model_dump()
            if update:
                data.update(update)
            return self.__class__(**data)

TaskType = Literal[
    "bugfix",
    "feature",
    "refactor",
    "visual_regression",
    "performance",
    "test_generation",
    "documentation",
    "tabzer_specialized",
    "game_specialized",
    "level_design",
    "enemy_ai",
    "asset_pipeline",
    "render_pass",
    "mechanic",
    "infra",
    "security",
]

TaskArea = Literal[
    "frontend",
    "backend",
    "fullstack",
    "tabzer",
    "game",
    "player",
    "enemy_ai",
    "level",
    "asset_pipeline",
    "render",
    "audio",
    "ui",
    "infra",
    "unknown",
]
RiskLevel = Literal["low", "medium", "high", "critical"]

TaskStatus = Literal[
    "created",
    "intake_parsed",
    "worktree_created",
    "baseline_running",
    "baseline_failed",
    "baseline_passed",
    "planning",
    "repo_mapping",
    "patching",
    "validating",
    "reviewing",
    "waiting_human_approval",
    "completed",
    "failed",
    "cancelled",
    "needs_human",
    "out_of_scope",
    "unsafe",
]


def _task_id() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"task-{ts}-{short}"


class TaskIntent(BaseModel):
    task_id: str = Field(default_factory=_task_id)
    task_type: TaskType
    title: str
    user_request: str
    target_area: TaskArea = "unknown"
    risk: RiskLevel = "medium"
    autonomy_level: int = Field(default=3, ge=0, le=5)
    acceptance_criteria: list[str] = []
    target_url: str | None = None
    allowed_paths: list[str] = []
    blocked_paths: list[str] = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ValidationResult(BaseModel):
    name: str
    command: list[str]
    status: Literal["passed", "failed", "timeout", "skipped", "error"]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_sec: float | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


class ReviewResult(BaseModel):
    approved: bool
    risk: RiskLevel
    summary: str
    blocking_issues: list[str] = []
    non_blocking_suggestions: list[str] = []
    requires_human_approval: bool = False


class PatchAttempt(BaseModel):
    attempt_no: int
    plan_summary: str
    files_changed: list[str] = []
    patch_content: str = ""
    validation_results: list[ValidationResult] = []
    review: ReviewResult | None = None
    rollback_performed: bool = False
    status: Literal["pending", "passed", "failed", "rolled_back"] = "pending"


class AgentResult(BaseModel):
    agent_name: str
    status: Literal["passed", "failed", "skipped", "needs_human"]
    summary: str
    findings: list[str] = []
    artifacts: list[str] = []
    metrics: dict[str, Any] = {}
    error: str | None = None


class Plan(BaseModel):
    task_id: str
    task_type: TaskType
    probable_files: list[str] = []
    hypothesis: str = ""
    steps: list[str] = []
    validations_to_run: list[str] = []
    risk_assessment: str = ""
    estimated_complexity: Literal["low", "medium", "high"] = "medium"
    feature_spec: dict[str, Any] | None = None


class SceneBrief(BaseModel):
    task_id: str
    scene_name: str
    theme: str = ""
    mood: str = ""
    objective: str = ""
    player_start: str = "left side of the scene"
    layout: list[str] = []
    traversal: list[str] = []
    platforms: list[str] = []
    hazards: list[str] = []
    enemies: list[str] = []
    props: list[str] = []
    background_layers: list[str] = []
    lighting: list[str] = []
    audio: list[str] = []
    mechanics: list[str] = []
    camera: list[str] = []
    acceptance_criteria: list[str] = []
    non_goals: list[str] = []


class FinalReport(BaseModel):
    task_id: str
    status: Literal["completed", "failed", "needs_human", "cancelled"]
    summary: str
    files_changed: list[str] = []
    validations: list[ValidationResult] = []
    attempts: list[PatchAttempt] = []
    agent_results: list[AgentResult] = []
    recommendations: list[str] = []
    pr_url: str | None = None
    duration_sec: float | None = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
