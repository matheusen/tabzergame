"""Level Designer Agent - turns a natural-language scene request into a SceneBrief."""
from __future__ import annotations

from ..config import OrchestratorConfig
from ..schemas import AgentResult, SceneBrief, TaskIntent
from ..tools.llm_client import LLMError, extract_json, get_client


_SYSTEM = """You are a level designer for a Godot 2D side-scrolling action game.

Convert the user's scene description into a practical scene brief for implementation.
Return ONLY valid JSON:
{
  "scene_name": "short snake_case name",
  "theme": "visual theme",
  "mood": "mood",
  "objective": "what the player must do",
  "player_start": "where the player starts",
  "layout": ["macro layout beats"],
  "traversal": ["movement challenges"],
  "platforms": ["platform/collision elements"],
  "hazards": ["hazards"],
  "enemies": ["enemy placements and behavior"],
  "props": ["foreground/background props"],
  "background_layers": ["parallax/background layers"],
  "lighting": ["lighting/render notes"],
  "audio": ["music/sfx notes"],
  "mechanics": ["mechanics used or needed"],
  "camera": ["camera framing and limits"],
  "acceptance_criteria": ["testable criteria"],
  "non_goals": ["out of scope"]
}

Rules:
- Be implementable with existing project folders: scenes, scripts, art, audio.
- Mention collision, spawn points, camera limits, enemy pacing, and verification.
- Keep it focused enough for a first playable pass."""


def create_scene_brief(task: TaskIntent, cfg: OrchestratorConfig | None = None) -> SceneBrief:
    client = get_client(
        cfg.llm_provider if cfg else "auto",
        cfg.llm_model if cfg else None,
        cfg.llm_model_fast if cfg else None,
    )

    if client.available:
        try:
            raw = client.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": task.user_request},
                ],
                json_mode=True,
                max_tokens=900,
                fast=True,
            )
            data = extract_json(raw) or {}
            return _from_data(task, data)
        except LLMError as e:
            print(f"[LevelDesignerAgent] LLM failed ({e}) - using deterministic brief")
        except Exception as e:
            print(f"[LevelDesignerAgent] Unexpected error ({e}) - using deterministic brief")

    return _fallback_brief(task)


def to_agent_result(brief: SceneBrief) -> AgentResult:
    findings = [
        f"Scene: {brief.scene_name}",
        f"Theme: {brief.theme}",
        f"Objective: {brief.objective}",
        f"Enemies: {len(brief.enemies)}",
        f"Platforms: {len(brief.platforms)}",
    ]
    return AgentResult(
        agent_name="level_designer_agent",
        status="passed",
        summary="Created structured scene brief from the user's description",
        findings=findings,
        artifacts=["scene_brief.json"],
    )


def _from_data(task: TaskIntent, data: dict) -> SceneBrief:
    return SceneBrief(
        task_id=task.task_id,
        scene_name=str(data.get("scene_name") or _scene_name(task)),
        theme=str(data.get("theme", "")),
        mood=str(data.get("mood", "")),
        objective=str(data.get("objective", task.user_request)),
        player_start=str(data.get("player_start", "left side of the scene")),
        layout=_list(data.get("layout")),
        traversal=_list(data.get("traversal")),
        platforms=_list(data.get("platforms")),
        hazards=_list(data.get("hazards")),
        enemies=_list(data.get("enemies")),
        props=_list(data.get("props")),
        background_layers=_list(data.get("background_layers")),
        lighting=_list(data.get("lighting")),
        audio=_list(data.get("audio")),
        mechanics=_list(data.get("mechanics")),
        camera=_list(data.get("camera")),
        acceptance_criteria=_list(data.get("acceptance_criteria")) or task.acceptance_criteria,
        non_goals=_list(data.get("non_goals")),
    )


def _fallback_brief(task: TaskIntent) -> SceneBrief:
    low = task.user_request.lower()
    theme = "industrial data-center corridor"
    if "noite" in low or "night" in low:
        theme = "night industrial exterior"
    elif "laboratorio" in low or "laboratório" in low or "lab" in low:
        theme = "damaged cyberpunk laboratory"
    elif "cidade" in low or "rua" in low:
        theme = "urban street combat lane"

    enemies = ["2 patrol agents spaced across the main lane"]
    if "boss" in low:
        enemies.append("1 stronger boss enemy near the exit")
    if "tiro" in low or "atirador" in low or "shoot" in low:
        enemies.append("1 ranged enemy on a raised platform")

    hazards = []
    if "laser" in low:
        hazards.append("timed laser barrier with safe gap")
    if "buraco" in low or "pit" in low:
        hazards.append("small pit that requires a jump")

    return SceneBrief(
        task_id=task.task_id,
        scene_name=_scene_name(task),
        theme=theme,
        mood="tense, readable, high-contrast",
        objective="Move from the left spawn to the right exit while clearing enemies.",
        player_start="left edge on the main floor",
        layout=[
            "main horizontal combat lane",
            "mid-scene raised platform for vertical variation",
            "right-side exit zone after the final encounter",
        ],
        traversal=[
            "walkable floor with clear collision",
            "one optional raised platform",
            "camera follows player without exposing outside the level bounds",
        ],
        platforms=[
            "solid ground across the scene",
            "one mid-height platform reachable by jump",
        ],
        hazards=hazards,
        enemies=enemies,
        props=[
            "server racks and cables in the background",
            "foreground catwalk lip for depth",
        ],
        background_layers=[
            "dark base backdrop",
            "large background image segment",
            "subtle color wash overlay",
        ],
        lighting=[
            "cool blue ambient wash",
            "small warning accents near combat areas",
        ],
        audio=[
            "reuse current music director track",
            "enemy attack and player hit SFX stay unchanged",
        ],
        mechanics=[
            "player movement, jump, crouch and melee combat",
            "enemy patrol/chase/melee/ranged behavior",
        ],
        camera=[
            "Camera2D follows Hero",
            "limits match level width and 720p vertical framing",
        ],
        acceptance_criteria=task.acceptance_criteria or [
            "Player can traverse from start to exit without getting stuck",
            "Enemy spawns are reachable and do not overlap solid collision",
            "Camera keeps the playable route framed",
            "Scene loads without missing resources",
        ],
        non_goals=[
            "final art polish",
            "new enemy classes unless explicitly requested",
        ],
    )


def _scene_name(task: TaskIntent) -> str:
    words = [
        "".join(ch for ch in word.lower() if ch.isalnum())
        for word in task.title.split()
    ]
    words = [w for w in words if w][:5]
    return "_".join(words) or "generated_scene"


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []
