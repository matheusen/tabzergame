"""Planner Agent — generates execution Plan from TaskIntent + repo context."""
from __future__ import annotations

from pathlib import Path

from ..config import OrchestratorConfig
from ..schemas import Plan, TaskIntent
from ..tools.llm_client import LLMError, extract_json, get_client
from .repo_mapper_agent import build_context_for_llm, map_files


_SYSTEM = """You are a senior game engineer acting as the Planner Agent for the Tabzer Game Agent Orchestrator.

Current project stack:
- Godot 4 project with project.godot
- GDScript gameplay scripts under scripts/
- Godot scenes under scenes/
- Pixel-art sprites and generated frames under art/
- Audio and music resources under audio/ and resources/

Given the task and relevant source files, generate a technical plan.

Return ONLY valid JSON (no markdown, no explanation):
{
  "hypothesis": "Root cause hypothesis or feature design intent (2-3 sentences)",
  "steps": ["Step 1: ...", "Step 2: ..."],
  "probable_files": ["path/to/file.ts"],
  "validations_to_run": ["npm run typecheck", "npm run lint"],
  "risk_assessment": "Brief risk description",
  "estimated_complexity": "low"|"medium"|"high",
  "feature_spec": null
}

Rules:
- probable_files: max 8, only files that MUST be changed
- For bugfixes: first step must be "Reproduce the bug"
- For features: include "Write acceptance criteria test" before implementation
- For game tasks: include a headless/smoke validation or visual/manual verification step
- Small focused steps only"""


def create_plan(task: TaskIntent, repo_root: Path, cfg: OrchestratorConfig | None = None) -> Plan:
    probable_files = map_files(task, repo_root)

    p = cfg.llm_provider if cfg else "auto"
    m = cfg.llm_model if cfg else None
    mf = cfg.llm_model_fast if cfg else None
    client = get_client(p, m, mf)

    if client.available:
        try:
            context = build_context_for_llm(task, repo_root, probable_files, max_chars_per_file=2000)
            raw = client.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": context},
                ],
                json_mode=True,
                max_tokens=1024,
            )
            data = extract_json(raw) or {}

            complexity = data.get("estimated_complexity", "medium")
            if complexity not in ("low", "medium", "high"):
                complexity = "medium"

            return Plan(
                task_id=task.task_id,
                task_type=task.task_type,
                probable_files=data.get("probable_files", probable_files[:6]),
                hypothesis=str(data.get("hypothesis", "")),
                steps=data.get("steps", []),
                validations_to_run=data.get("validations_to_run", []),
                risk_assessment=str(data.get("risk_assessment", "")),
                estimated_complexity=complexity,
                feature_spec=data.get("feature_spec"),
            )
        except LLMError as e:
            print(f"[PlannerAgent] LLM failed ({e}) — fallback plan")
        except Exception as e:
            print(f"[PlannerAgent] Unexpected error ({e}) — fallback plan")

    return _fallback(task, probable_files)


def _fallback(task: TaskIntent, probable_files: list[str]) -> Plan:
    if task.task_type in ("bugfix", "tabzer_specialized"):
        steps = [
            "Reproduce the issue and document symptoms",
            "Identify root cause in relevant files",
            "Apply minimal fix",
            "Run validations",
            "Verify fix resolves the original symptom",
        ]
        validations = ["npm run typecheck", "npm run lint"]
    elif task.task_type in ("game_specialized", "level_design", "enemy_ai", "asset_pipeline", "render_pass", "mechanic"):
        steps = [
            "Reproduce or describe the in-game behavior",
            "Map affected Godot scripts, scenes, and assets",
            "Apply a small gameplay or asset pipeline change",
            "Run Godot/project smoke validations where available",
            "Verify the result in the main scene",
        ]
        validations = ["godot headless smoke", "asset transparency/bounds audit"]
    elif task.task_type == "feature":
        steps = [
            "Define acceptance criteria",
            "Map affected components and files",
            "Implement minimal vertical slice",
            "Add basic tests",
            "Run validations",
        ]
        validations = ["npm run typecheck", "npm run lint"]
    else:
        steps = ["Analyze current state", "Apply changes", "Validate"]
        validations = ["npm run typecheck"]

    return Plan(
        task_id=task.task_id,
        task_type=task.task_type,
        probable_files=probable_files[:6],
        hypothesis=f"[Fallback] Addressing: {task.user_request[:100]}",
        steps=steps,
        validations_to_run=validations,
        risk_assessment=f"Risk level: {task.risk}",
        estimated_complexity="medium",
    )
