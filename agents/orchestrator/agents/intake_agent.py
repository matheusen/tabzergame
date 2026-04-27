"""Intake Agent — parses natural language requests into TaskIntent."""
from __future__ import annotations

from ..config import OrchestratorConfig
from ..schemas import RiskLevel, TaskArea, TaskIntent, TaskType
from ..tools.llm_client import LLMError, extract_json, get_client


# ── deterministic keyword fallback ────────────────────────────────────────────

_TABZER_KW = {"cursor", "player", "alphatab", "tab", "playback", "sincronização",
              "compasso", "ligado", "slide", "bend", "flicker", "pauta", "soundfont"}
_BUG_KW    = {"bug", "erro", "error", "fix", "corrigir", "quebrou", "crash",
              "travando", "freezing", "não funciona", "problema", "problem"}
_FEAT_KW   = {"feature", "criar", "create", "adicionar", "add", "implementar",
              "implement", "nova", "new", "quero um", "make a", "build"}
_PERF_KW   = {"lento", "slow", "performance", "memória", "memory", "ram", "fps", "jitter"}
_VISUAL_KW = {"visual", "screenshot", "aparência", "cor", "color", "layout", "ui"}
_FRONT_KW  = {"frontend", "react", "next", "tsx", "typescript", "css", "component"}
_BACK_KW   = {"backend", "api", "endpoint", "fastapi", "python", "database"}
_GAME_KW   = {"godot", "game", "jogo", "player", "inimigo", "inimigos", "enemy",
              "boss", "fase", "level", "cenario", "cenário", "mapa", "sprite",
              "animacao", "animação", "colisao", "colisão", "camera", "câmera",
              "render", "fps", "mecanica", "mecânica", "combate", "ataque"}
_LEVEL_KW  = {"fase", "level", "cenario", "cenário", "mapa", "plataforma", "spawn"}
_ENEMY_KW  = {"inimigo", "inimigos", "enemy", "ia", "ai", "patrulha", "boss"}
_ASSET_KW  = {"sprite", "spritesheet", "asset", "png", "transparente", "frame", "animacao", "animação"}
_RENDER_KW = {"render", "fps", "camera", "câmera", "parallax", "luz", "iluminacao", "iluminação"}


def _classify(request: str) -> tuple[TaskType, TaskArea, RiskLevel]:
    low = request.lower()
    task_type: TaskType = "bugfix"
    if any(kw in low for kw in _FEAT_KW) and not any(kw in low for kw in _BUG_KW):
        task_type = "feature"
    elif any(kw in low for kw in _PERF_KW):
        task_type = "performance"
    elif any(kw in low for kw in _VISUAL_KW):
        task_type = "visual_regression"

    if any(kw in low for kw in _GAME_KW):
        area = "game"
        task_type = "game_specialized"
        if any(kw in low for kw in _LEVEL_KW):
            task_type = "level_design"
            area = "level"
        elif any(kw in low for kw in _ENEMY_KW):
            task_type = "enemy_ai"
            area = "enemy_ai"
        elif any(kw in low for kw in _ASSET_KW):
            task_type = "asset_pipeline"
            area = "asset_pipeline"
        elif any(kw in low for kw in _RENDER_KW):
            task_type = "render_pass"
            area = "render"
        elif any(kw in low for kw in {"mecanica", "mecânica", "combate", "ataque", "defesa"}):
            task_type = "mechanic"
            area = "game"
    elif any(kw in low for kw in _TABZER_KW):
        area: TaskArea = "tabzer"
        if task_type not in ("feature", "performance"):
            task_type = "tabzer_specialized"
    elif any(kw in low for kw in _FRONT_KW):
        area = "frontend"
    elif any(kw in low for kw in _BACK_KW):
        area = "backend"
    else:
        area = "fullstack"

    risk: RiskLevel = "medium"
    if any(kw in low for kw in {"auth", "secret", "senha", "password", "migration"}):
        risk = "high"
    elif task_type == "bugfix":
        risk = "low"

    return task_type, area, risk


_SYSTEM = """You are the intake agent for the Tabzer Game Agent Orchestrator.

This repository is a Godot 4 side-scrolling action game.
Key areas include player controller, enemy AI, combat mechanics, level/scenario design,
sprite animation, asset pipeline, audio, camera, rendering, and performance.

Parse the user's development request into a structured JSON object.

Return ONLY valid JSON (no markdown, no extra text):
{
  "task_type": "bugfix"|"feature"|"refactor"|"visual_regression"|"performance"|"test_generation"|"documentation"|"tabzer_specialized"|"game_specialized"|"level_design"|"enemy_ai"|"asset_pipeline"|"render_pass"|"mechanic"|"infra"|"security",
  "title": "short title (max 80 chars)",
  "target_area": "frontend"|"backend"|"fullstack"|"tabzer"|"game"|"player"|"enemy_ai"|"level"|"asset_pipeline"|"render"|"audio"|"ui"|"infra"|"unknown",
  "risk": "low"|"medium"|"high"|"critical",
  "acceptance_criteria": ["criterion1", "criterion2"],
  "keywords": ["keyword1", "keyword2"]
}

Rules:
- "game_specialized" = broad Godot gameplay work
- "level_design" = scenarios, maps, platforms, spawn points, pacing
- "enemy_ai" = enemy behavior, state machines, perception, attacks
- "asset_pipeline" = spritesheets, transparency, frames, import settings
- "render_pass" = camera, z-index, lighting, parallax, FPS, visual composition
- "mechanic" = movement, combat, defense, hitboxes, health, interactions
- acceptance_criteria: 2-4 specific, testable criteria
- keywords: 3-6 relevant code keywords for grep search"""


def parse_request(
    request: str,
    autonomy_level: int = 3,
    cfg: OrchestratorConfig | None = None,
    target_url: str | None = None,
    provider: str | None = None,
) -> TaskIntent:
    p = provider or (cfg.llm_provider if cfg else "auto")
    m = cfg.llm_model if cfg else None
    mf = cfg.llm_model_fast if cfg else None

    client = get_client(p, m, mf)

    if client.available:
        try:
            raw = client.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": f"Request: {request}"},
                ],
                json_mode=True,
                max_tokens=512,
                fast=True,
            )
            data = extract_json(raw) or {}

            task_type = data.get("task_type", "bugfix")
            valid_types = {"bugfix","feature","refactor","visual_regression","performance",
                           "test_generation","documentation","tabzer_specialized","game_specialized",
                           "level_design","enemy_ai","asset_pipeline","render_pass","mechanic",
                           "infra","security"}
            if task_type not in valid_types:
                task_type = "bugfix"

            area = data.get("target_area", "unknown")
            if area not in {"frontend","backend","fullstack","tabzer","game","player","enemy_ai",
                            "level","asset_pipeline","render","audio","ui","infra","unknown"}:
                area = "unknown"

            risk = data.get("risk", "medium")
            if risk not in {"low","medium","high","critical"}:
                risk = "medium"

            return TaskIntent(
                task_type=task_type,
                title=str(data.get("title", request[:80])),
                user_request=request,
                target_area=area,
                risk=risk,
                autonomy_level=autonomy_level,
                acceptance_criteria=data.get("acceptance_criteria", []),
                target_url=target_url,
            )
        except LLMError as e:
            print(f"[IntakeAgent] LLM failed ({e}) — deterministic fallback")
        except Exception as e:
            print(f"[IntakeAgent] Unexpected error ({e}) — deterministic fallback")

    print("[IntakeAgent] Using deterministic classification")
    task_type, area, risk = _classify(request)
    return TaskIntent(
        task_type=task_type,
        title=request[:80],
        user_request=request,
        target_area=area,
        risk=risk,
        autonomy_level=autonomy_level,
        acceptance_criteria=[f"Resolve: {request}"],
        target_url=target_url,
    )
