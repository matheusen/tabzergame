"""
Study Agent — TypeScript Patcher
Reads and patches studyExercises.ts to append new exercise definitions.
Uses conservative regex — does NOT parse or rewrite the full AST.
"""
from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXERCISES_TS = _REPO_ROOT / "frontend" / "src" / "app" / "study" / "studyExercises.ts"

# ── TypeScript value formatter ─────────────────────────────────────────────────

def _ts_value(v: Any, indent: int = 6) -> str:
    """Recursively format a Python value as a TypeScript literal."""
    pad = " " * indent
    inner_pad = " " * (indent + 2)
    if v is None:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # escape backticks and use double quotes
        escaped = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(v, list):
        if not v:
            return "[]"
        items = [f"{inner_pad}{_ts_value(item, indent + 2)}" for item in v]
        return "[\n" + ",\n".join(items) + f",\n{pad}]"
    if isinstance(v, tuple) and len(v) == 2:
        return f"[{_ts_value(v[0])}, {_ts_value(v[1])}]"
    return str(v)


def format_exercise_as_ts(exercise: dict[str, Any], base_indent: int = 4) -> str:
    """
    Converts an ExerciseDefinition dict to a TypeScript object literal string.
    base_indent: number of spaces for the opening brace level.
    """
    pad = " " * base_indent
    field_pad = " " * (base_indent + 2)
    lines = [f"{pad}{{"]

    # Field ordering matches the TypeScript interface
    field_order = [
        "id", "title", "type", "difficulty", "estimatedMinutes",
        "targetSkills", "objective", "instructions",
        "bpmStart", "bpmGoal", "patternTab", "fretRange",
        "evaluationHints", "premiumOnly",
    ]
    seen = set()
    for key in field_order:
        if key in exercise:
            seen.add(key)
            val = exercise[key]
            # Skip undefined-equivalent values
            if val is None:
                continue
            ts_val = _ts_value(val, base_indent + 2)
            lines.append(f"{field_pad}{key}: {ts_val},")
    # Append any extra keys not in the ordered list
    for key, val in exercise.items():
        if key not in seen and val is not None:
            ts_val = _ts_value(val, base_indent + 2)
            lines.append(f"{field_pad}{key}: {ts_val},")

    lines.append(f"{pad}}}")
    return "\n".join(lines)


# ── Reader ─────────────────────────────────────────────────────────────────────

def list_topics(path: Path = _EXERCISES_TS) -> list[str]:
    """Return all topic IDs present in EXERCISES_BY_TOPIC."""
    text = path.read_text(encoding="utf-8")
    return re.findall(r'"([^"]+)":\s*\[', text)


def topic_exercise_count(topic_id: str, path: Path = _EXERCISES_TS) -> int:
    """Count how many exercises currently exist for a topic."""
    text = path.read_text(encoding="utf-8")
    # Find the topic block
    pattern = re.compile(
        r'"' + re.escape(topic_id) + r'":\s*\[(.*?)(?=\n  "[^"]+":|\n\};)',
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return 0
    block = m.group(1)
    # Count top-level opening braces (each exercise starts with {)
    return len(re.findall(r"^\s+\{", block, re.MULTILINE))


# ── Writer ─────────────────────────────────────────────────────────────────────

def append_exercises(
    exercises: list[dict[str, Any]],
    topic_id: str,
    path: Path = _EXERCISES_TS,
    create_topic_if_missing: bool = True,
) -> None:
    """
    Append new exercise objects to the EXERCISES_BY_TOPIC[topic_id] array.
    If the topic doesn't exist and create_topic_if_missing=True, creates it.
    Preserves all existing content — only inserts before the closing ] of the array.
    """
    text = path.read_text(encoding="utf-8")
    formatted = [format_exercise_as_ts(ex) for ex in exercises]
    block_ts = ",\n".join(formatted)

    # Pattern: find the array for this topic and insert before its closing ]
    # Matches: "topic-id": [  ...content...  ]
    array_pattern = re.compile(
        r'("' + re.escape(topic_id) + r'":\s*\[)(.*?)(\n  \])',
        re.DOTALL,
    )
    m = array_pattern.search(text)
    if m:
        opener = m.group(1)
        content = m.group(2)
        closer = m.group(3)
        # Ensure trailing comma on last existing item
        content_stripped = content.rstrip()
        if content_stripped and not content_stripped.endswith(","):
            content_stripped += ","
        new_content = content_stripped + "\n" + block_ts + ","
        new_text = text[: m.start()] + opener + new_content + closer + text[m.end() :]
        path.write_text(new_text, encoding="utf-8")
        return

    if not create_topic_if_missing:
        raise ValueError(f"Topic '{topic_id}' not found in {path} and create_topic_if_missing=False")

    # Insert new topic before the closing }; of EXERCISES_BY_TOPIC
    export_end = re.search(r"\n\};\s*$", text)
    if not export_end:
        raise RuntimeError(f"Could not locate closing '}}' of EXERCISES_BY_TOPIC in {path}")

    new_topic_block = f'\n  "{topic_id}": [\n{block_ts},\n  ],'
    insert_pos = export_end.start()
    new_text = text[:insert_pos] + new_topic_block + text[insert_pos:]
    path.write_text(new_text, encoding="utf-8")


# ── CLI helper ─────────────────────────────────────────────────────────────────

def preview(exercises: list[dict[str, Any]]) -> str:
    """Return a preview string of exercises as they would appear in the .ts file."""
    parts = [format_exercise_as_ts(ex) for ex in exercises]
    return ",\n".join(parts)
