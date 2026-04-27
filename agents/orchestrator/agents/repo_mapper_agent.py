"""Repo Mapper Agent — maps a TaskIntent to relevant files in the codebase."""
from __future__ import annotations

from pathlib import Path

from ..schemas import TaskIntent
from ..tools.repo_scanner import build_repo_context, find_files, grep


# ── area-specific file patterns ──────────────────────────────────────────────

_AREA_PATTERNS: dict[str, list[str]] = {
    "game": [
        "scripts/**/*.gd",
        "scenes/**/*.tscn",
        "resources/**/*.tres",
        "tools/**/*.gd",
        "project.godot",
    ],
    "player": [
        "scripts/player*.gd",
        "art/Player/**/*",
        "tools/**/*.gd",
        "scenes/**/*.tscn",
    ],
    "enemy_ai": [
        "scripts/enemy*.gd",
        "art/Enemies/**/*",
        "scenes/**/*.tscn",
    ],
    "level": [
        "scenes/**/*.tscn",
        "art/Environment/**/*",
        "resources/**/*.tres",
        "*.png",
    ],
    "asset_pipeline": [
        "art/**/*",
        "tools/**/*.gd",
        "*.png",
        "*.png.import",
    ],
    "render": [
        "scenes/**/*.tscn",
        "scripts/follow_camera.gd",
        "project.godot",
        "art/Environment/**/*",
    ],
    "audio": [
        "scripts/music*.gd",
        "audio/**/*",
        "resources/music/**/*.tres",
    ],
    "frontend": [
        "frontend/src/**/*.tsx",
        "frontend/src/**/*.ts",
        "frontend/src/**/*.css",
    ],
    "backend": [
        "backend/**/*.py",
    ],
    "tabzer": [
        "frontend/src/app/play/**",
        "frontend/src/app/study/**",
        "frontend/src/components/**/*.tsx",
        "frontend/src/hooks/**/*.ts",
        "frontend/src/lib/**/*.ts",
        "backend/agents/tab_debug_agent/**/*.py",
    ],
    "fullstack": [
        "frontend/src/**/*.tsx",
        "frontend/src/**/*.ts",
        "backend/**/*.py",
        "scripts/**/*.gd",
        "scenes/**/*.tscn",
    ],
}

_TABZER_CRITICAL_PATTERNS = [
    r"cursor|Cursor",
    r"AlphaTab|alphaTab",
    r"playback|Playback",
    r"player|Player",
    r"usePlayback|usePlayer",
    r"syncroniz|syncroni",
]

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "bugfix": [],
    "feature": ["export function", "export const", "export default"],
    "performance": ["useEffect", "useMemo", "useCallback", "requestAnimationFrame"],
    "visual_regression": ["className", "style=", "css"],
    "tabzer_specialized": ["AlphaTab", "cursor", "playback", "player"],
    "game_specialized": ["CharacterBody2D", "AnimatedSprite2D", "CollisionShape2D", "player", "enemy"],
    "level_design": ["StaticBody2D", "CollisionShape2D", "Camera2D", "spawn", "position"],
    "enemy_ai": ["State", "take_damage", "melee", "shoot", "patrol", "chase"],
    "asset_pipeline": ["SpriteFrames", "Image", "png", "frame", "transparent"],
    "render_pass": ["Camera2D", "z_index", "texture_filter", "Light", "Canvas"],
    "mechanic": ["velocity", "Input", "damage", "hitbox", "cooldown"],
}


_CODE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".py", ".css", ".gd", ".tscn", ".tres", ".godot", ".import"}
_SKIP_PATTERNS = [
    "node_modules", ".next", "__pycache__", ".git",
    "dist/", "build/", ".agent-", "runs/", ".playwright-cli/",
    ".claude/", "claude/", "work_audio_to_tab/", "synthtab_data",
    "settings.local", ".env",
]
_SKIP_EXTENSIONS = {".md", ".txt", ".yml", ".yaml", ".bat", ".sh", ".json5", ".lock", ".json"}

_AREA_PREFIXES = {
    "game": ("scripts/", "scenes/", "resources/", "tools/", "art/", "audio/", "project.godot"),
    "player": ("scripts/", "scenes/", "art/Player/", "tools/"),
    "enemy_ai": ("scripts/", "scenes/", "art/Enemies/"),
    "level": ("scenes/", "art/Environment/", "resources/", "scripts/"),
    "asset_pipeline": ("art/", "tools/", "scripts/"),
    "render": ("scenes/", "scripts/", "art/Environment/", "project.godot"),
    "audio": ("scripts/", "audio/", "resources/music/"),
    "tabzer": ("frontend/src/", "backend/agents/"),
    "frontend": ("frontend/src/",),
    "backend": ("backend/",),
    "fullstack": ("frontend/src/", "backend/"),
    "infra": ("backend/",),
}


def map_files(task: TaskIntent, repo_root: Path, max_files: int = 20) -> list[str]:
    """Return a list of relevant file paths (relative to repo root)."""
    area = task.target_area if task.target_area != "unknown" else "fullstack"
    patterns = _AREA_PATTERNS.get(area, _AREA_PATTERNS["fullstack"])

    found = find_files(repo_root, patterns, max_results=max_files * 2)

    # Grep only within relevant globs to avoid doc files
    area_globs = {
        "game": "*.{gd,tscn,tres,godot,import}",
        "player": "*.{gd,tscn,tres,import}",
        "enemy_ai": "*.{gd,tscn,tres,import}",
        "level": "*.{gd,tscn,tres,import}",
        "asset_pipeline": "*.{gd,tscn,tres,import}",
        "render": "*.{gd,tscn,tres,godot,import}",
        "audio": "*.{gd,tres,import}",
        "tabzer": "*.{ts,tsx,py}",
        "frontend": "*.{ts,tsx}",
        "backend": "*.py",
        "fullstack": "*.{ts,tsx,py}",
    }
    grep_glob = area_globs.get(area, "*.{ts,tsx,py}")

    keywords = _extract_keywords(task)
    grep_hits: set[str] = set()
    repo_str = str(repo_root).replace("\\", "/")

    for kw in keywords[:4]:
        matches = grep(kw, repo_root, glob=grep_glob, case_insensitive=True, max_results=10)
        for m in matches:
            rel = m["file"].replace("\\", "/")
            if rel.startswith(repo_str):
                rel = rel[len(repo_str):].lstrip("/")
            grep_hits.add(rel)

    # Merge: grep hits take priority, then pattern matches
    all_files = list(grep_hits) + [f for f in found if f not in grep_hits]

    # Determine allowed path prefixes for this area
    allowed_prefixes = _AREA_PREFIXES.get(area, ("frontend/", "backend/"))

    # Filter noise
    filtered = []
    for f in all_files:
        # Must start with an allowed prefix
        if not any(f.startswith(prefix) for prefix in allowed_prefixes):
            continue
        if any(skip in f for skip in _SKIP_PATTERNS):
            continue
        ext = Path(f).suffix.lower()
        if ext in _SKIP_EXTENSIONS:
            continue
        if ext not in _CODE_EXTENSIONS and ext:
            continue
        filtered.append(f)

    return filtered[:max_files]


def _extract_keywords(task: TaskIntent) -> list[str]:
    """Extract search keywords from the task intent."""
    words = task.user_request.lower().split()
    # Remove common stop words
    stops = {"o", "a", "de", "do", "da", "no", "na", "com", "que", "para",
              "the", "is", "in", "at", "on", "and", "or", "to", "of", "fix"}
    keywords = [w for w in words if w not in stops and len(w) > 3]

    # Add type-specific keywords
    extra = _TYPE_KEYWORDS.get(task.task_type, [])
    keywords = extra + keywords

    return keywords[:10]


def build_context_for_llm(
    task: TaskIntent,
    repo_root: Path,
    probable_files: list[str],
    max_chars_per_file: int = 3000,
) -> str:
    """Build a text block with file contents for the LLM patch agent."""
    lines = [
        f"# Task: {task.title}",
        f"Request: {task.user_request}",
        f"Type: {task.task_type} | Area: {task.target_area}",
        "",
        "# Relevant Files",
    ]

    for rel_path in probable_files[:10]:
        abs_path = repo_root / rel_path
        if not abs_path.exists():
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n... (truncated)"

        lines += [
            f"\n## {rel_path}",
            "```",
            content,
            "```",
        ]

    return "\n".join(lines)
