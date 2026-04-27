"""Configuration loading for the Orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None


@dataclass
class ValidationConfig:
    enabled: bool = True
    commands: list[list[str]] = field(default_factory=list)
    cwd_relative: str = "."


@dataclass
class OrchestratorConfig:
    project_name: str = "tabzer"
    project_root: str = "."
    default_autonomy_level: int = 3
    runs_dir: str = ".agent-runs"
    worktrees_dir: str = ".agent-worktrees"
    artifacts_dir: str = ".agent-artifacts"
    max_attempts: int = 3
    require_human_approval_for: list[str] = field(default_factory=list)
    frontend_validation: ValidationConfig = field(default_factory=ValidationConfig)
    backend_validation: ValidationConfig = field(default_factory=ValidationConfig)
    tabzer_validation: ValidationConfig = field(default_factory=ValidationConfig)
    game_validation: ValidationConfig = field(default_factory=ValidationConfig)
    target_url: str = "http://localhost:3000"
    llm_provider: str = "auto"
    llm_model: str | None = None
    llm_model_fast: str | None = None

    @classmethod
    def load(cls, config_path: Path | None = None) -> "OrchestratorConfig":
        search_paths = [
            Path("agents/orchestrator/orchestrator_config.yaml"),
            Path("backend/agents/orchestrator/orchestrator_config.yaml"),
            Path("orchestrator_config.yaml"),
        ]
        if config_path:
            search_paths.insert(0, config_path)

        for p in search_paths:
            if p.exists():
                raw = _load_config_file(p)
                return cls._from_dict(raw)

        return cls._defaults()

    @classmethod
    def _defaults(cls) -> "OrchestratorConfig":
        cfg = cls()
        cfg.require_human_approval_for = [
            "commit",
            "pull_request",
            "lockfile_change",
            "package_install",
            "migration",
            "delete_file",
            "auth_change",
            "infra_change",
        ]
        cfg.frontend_validation = ValidationConfig(
            enabled=True,
            cwd_relative="frontend",
            commands=[
                ["npm", "run", "typecheck"],
                ["npm", "run", "lint"],
            ],
        )
        cfg.backend_validation = ValidationConfig(
            enabled=True,
            cwd_relative="backend",
            commands=[
                ["python", "-m", "ruff", "check", "."],
            ],
        )
        cfg.tabzer_validation = ValidationConfig(
            enabled=False,
            cwd_relative=".",
            commands=[
                ["python", "backend/agents/tab_debug_agent/run_agent.py", "--codex-stdout-only"],
            ],
        )
        cfg.game_validation = ValidationConfig(
            enabled=True,
            cwd_relative=".",
            commands=[],
        )
        return cfg

    @classmethod
    def _from_dict(cls, data: dict) -> "OrchestratorConfig":
        cfg = cls()
        project = data.get("project", {})
        cfg.project_name = project.get("name", "tabzer")
        cfg.project_root = project.get("root", ".")
        cfg.default_autonomy_level = project.get("default_autonomy_level", 3)

        paths = data.get("paths", {})
        cfg.runs_dir = paths.get("runs_dir", ".agent-runs")
        cfg.worktrees_dir = paths.get("worktrees_dir", ".agent-worktrees")
        cfg.artifacts_dir = paths.get("artifacts_dir", ".agent-artifacts")

        policies = data.get("policies", {})
        cfg.max_attempts = policies.get("max_attempts", 3)
        cfg.require_human_approval_for = policies.get("require_human_approval_for", [])

        val = data.get("validation", {})
        fe = val.get("frontend", {})
        cfg.frontend_validation = ValidationConfig(
            enabled=fe.get("enabled", True),
            cwd_relative=fe.get("cwd_relative", "frontend"),
            commands=fe.get("commands", []),
        )
        be = val.get("backend", {})
        cfg.backend_validation = ValidationConfig(
            enabled=be.get("enabled", True),
            cwd_relative=be.get("cwd_relative", "backend"),
            commands=be.get("commands", []),
        )
        tabzer = data.get("tabzer", {})
        cfg.tabzer_validation = ValidationConfig(
            enabled=tabzer.get("enabled", False),
            cwd_relative=tabzer.get("cwd_relative", "."),
            commands=tabzer.get("commands", []),
        )
        cfg.target_url = tabzer.get("target_url", "http://localhost:3000")

        game = data.get("game", {})
        cfg.game_validation = ValidationConfig(
            enabled=game.get("enabled", True),
            cwd_relative=game.get("cwd_relative", "."),
            commands=game.get("commands", []),
        )

        llm = data.get("llm", {})
        cfg.llm_provider = llm.get("provider", "auto")
        cfg.llm_model = llm.get("model") or None
        cfg.llm_model_fast = llm.get("model_fast") or None
        return cfg


def _load_config_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text) or {}

    try:
        import json

        return json.loads(text)
    except Exception:
        return OrchestratorConfig._defaults()._as_plain_dict()


def _validation_to_dict(cfg: ValidationConfig) -> dict:
    return {
        "enabled": cfg.enabled,
        "cwd_relative": cfg.cwd_relative,
        "commands": cfg.commands,
    }


def _as_plain_dict(self: OrchestratorConfig) -> dict:
    return {
        "project": {
            "name": self.project_name,
            "root": self.project_root,
            "default_autonomy_level": self.default_autonomy_level,
        },
        "paths": {
            "runs_dir": self.runs_dir,
            "worktrees_dir": self.worktrees_dir,
            "artifacts_dir": self.artifacts_dir,
        },
        "policies": {
            "max_attempts": self.max_attempts,
            "require_human_approval_for": self.require_human_approval_for,
        },
        "validation": {
            "frontend": _validation_to_dict(self.frontend_validation),
            "backend": _validation_to_dict(self.backend_validation),
        },
        "tabzer": _validation_to_dict(self.tabzer_validation)
        | {"target_url": self.target_url},
        "game": _validation_to_dict(self.game_validation),
        "llm": {
            "provider": self.llm_provider,
            "model": self.llm_model,
            "model_fast": self.llm_model_fast,
        },
    }


OrchestratorConfig._as_plain_dict = _as_plain_dict
