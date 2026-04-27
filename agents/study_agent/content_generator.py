"""
Study Agent — Content Generator
Generates ExerciseDefinition objects (and optional theory text) for a given study topic.
Uses OpenAI when OPENAI_API_KEY is available; falls back to an offline template otherwise.
"""
from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

# ── paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
_STUDY_DIR = _REPO_ROOT / "frontend" / "src" / "app" / "study"
_EXERCISES_TS = _STUDY_DIR / "studyExercises.ts"
_ROADMAP_TS = _STUDY_DIR / "studyRoadmap.ts"
_ENV_FILE = _REPO_ROOT / "backend" / ".env"


# ── env loading ────────────────────────────────────────────────────────────────
def _load_env() -> None:
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env()


# ── topic metadata extraction ──────────────────────────────────────────────────
def _extract_topic_meta(topic_id: str) -> dict[str, Any]:
    """
    Extracts metadata for a topic from studyRoadmap.ts using regex.
    Returns a dict with title, whatIs, whyItMatters, howToUse, contentItems.
    """
    text = _ROADMAP_TS.read_text(encoding="utf-8")

    # Find the topic block by id
    id_pattern = re.compile(
        r'id:\s*["\']' + re.escape(topic_id) + r'["\'](.+?)(?=\{\s*id:|$)',
        re.DOTALL,
    )
    m = id_pattern.search(text)
    if not m:
        return {"id": topic_id, "title": topic_id}

    block = m.group(0)

    def _field(name: str) -> str:
        fm = re.search(
            name + r':\s*["\'](.+?)["\']',
            block,
            re.DOTALL,
        )
        if fm:
            return fm.group(1).strip()
        # multi-line string concatenation
        fm2 = re.search(name + r':\s*"(.*?)"', block, re.DOTALL)
        return fm2.group(1).strip() if fm2 else ""

    content_items: list[str] = re.findall(r'"([^"]+)",\s*//?\s*', block)
    # simpler fallback — grab quoted items in contentItems array
    ci_match = re.search(r"contentItems:\s*\[(.*?)\]", block, re.DOTALL)
    if ci_match:
        content_items = re.findall(r'"([^"]+)"', ci_match.group(1))

    return {
        "id": topic_id,
        "title": _field("title"),
        "whatIs": _field("whatIs"),
        "whyItMatters": _field("whyItMatters"),
        "howToUse": _field("howToUse"),
        "contentItems": content_items,
    }


# ── interface schema extraction ────────────────────────────────────────────────
def _exercise_interface_schema() -> str:
    text = _EXERCISES_TS.read_text(encoding="utf-8")
    m = re.search(r"export interface ExerciseDefinition \{(.+?)\}", text, re.DOTALL)
    return m.group(0) if m else ""


# ── offline fallback template ──────────────────────────────────────────────────
_OFFLINE_TEMPLATE = {
    "id": "{topic_id}-gen-{n:02d}",
    "title": "Exercicio gerado (offline) #{n}",
    "type": "technical",
    "difficulty": "beginner",
    "estimatedMinutes": 5,
    "targetSkills": ["tecnica", "musicalidade"],
    "objective": "Exercicio placeholder gerado sem conexao com OpenAI.",
    "instructions": [
        "Leia a descricao do topico acima.",
        "Pratique lentamente, focando na qualidade do som.",
        "Aumente o BPM so quando o padrao estiver limpo.",
    ],
    "bpmStart": 60,
    "bpmGoal": 100,
    "evaluationHints": [
        "O som esta limpo e uniforme?",
        "Ha tensao desnecessaria nas maos?",
    ],
}


def _offline_exercises(topic_id: str, count: int) -> list[dict[str, Any]]:
    result = []
    for n in range(1, count + 1):
        ex = dict(_OFFLINE_TEMPLATE)
        ex["id"] = f"{topic_id}-gen-{n:02d}"
        ex["title"] = f"Exercicio gerado (offline) #{n}"
        result.append(ex)
    return result


# ── OpenAI generation ──────────────────────────────────────────────────────────
def _openai_generate(topic_meta: dict[str, Any], count: int, action: str) -> list[dict[str, Any]]:
    try:
        import openai
    except ImportError:
        print("[study_agent] openai package not installed — using offline fallback.", file=sys.stderr)
        return _offline_exercises(topic_meta["id"], count)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("[study_agent] OPENAI_API_KEY not set — using offline fallback.", file=sys.stderr)
        return _offline_exercises(topic_meta["id"], count)

    client = openai.OpenAI(api_key=api_key)
    schema = _exercise_interface_schema()

    system_prompt = textwrap.dedent("""
        You are an expert music education content designer specializing in guitar pedagogy.
        You generate structured exercise definitions for a Brazilian Portuguese guitar learning app.
        All text content (titles, instructions, objectives, hints) must be in Brazilian Portuguese.
        Respond ONLY with a valid JSON array. No markdown, no explanation text.
    """).strip()

    if action == "theory":
        user_prompt = textwrap.dedent(f"""
            Topic: {topic_meta.get('title', topic_meta['id'])}
            What it is: {topic_meta.get('whatIs', '')}
            Why it matters: {topic_meta.get('whyItMatters', '')}
            Content items: {', '.join(topic_meta.get('contentItems', []))}

            Generate {count} theory-focused exercises (type: "visual" or "ear") following this TypeScript interface:
            {schema}

            Rules:
            - Each exercise must have a unique id starting with "{topic_meta['id']}-theory-"
            - Include patternTab (guitar tab ASCII) when relevant
            - instructions must be an array of strings, each a clear actionable step
            - difficulty must be "beginner", "intermediate", or "advanced"
            - type must be one of: "technical", "visual", "ear", "application", "constraint"
            - Return a JSON array only.
        """).strip()
    else:
        user_prompt = textwrap.dedent(f"""
            Topic: {topic_meta.get('title', topic_meta['id'])}
            What it is: {topic_meta.get('whatIs', '')}
            Why it matters: {topic_meta.get('whyItMatters', '')}
            How to use: {topic_meta.get('howToUse', '')}
            Content items: {', '.join(topic_meta.get('contentItems', []))}

            Generate {count} practical guitar exercises following this TypeScript interface:
            {schema}

            Rules:
            - Each exercise must have a unique id starting with "{topic_meta['id']}-gen-"
            - Include patternTab (guitar tab ASCII art, 6 lines e/B/G/D/A/E) when the exercise has a specific pattern
            - instructions must be an array of 3-5 clear actionable steps in Portuguese
            - bpmStart and bpmGoal are optional but include them for technical exercises
            - difficulty must match the topic complexity realistically
            - evaluationHints should contain 2-3 self-assessment questions in Portuguese
            - Return a JSON array only.
        """).strip()

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "[]"
        # model may return {"exercises": [...]} or [...]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        # unwrap first list value
        for v in parsed.values():
            if isinstance(v, list):
                return v
        return _offline_exercises(topic_meta["id"], count)
    except Exception as exc:
        print(f"[study_agent] OpenAI error: {exc} — using offline fallback.", file=sys.stderr)
        return _offline_exercises(topic_meta["id"], count)


# ── public API ─────────────────────────────────────────────────────────────────
def generate(topic_id: str, count: int = 2, action: str = "exercises") -> list[dict[str, Any]]:
    """
    Generate exercise definitions for a topic.
    action: "exercises" | "theory" | "both"
    Returns a list of dicts matching ExerciseDefinition.
    """
    topic_meta = _extract_topic_meta(topic_id)
    if action == "both":
        tech = _openai_generate(topic_meta, count, "exercises")
        theory = _openai_generate(topic_meta, max(1, count // 2), "theory")
        return tech + theory
    return _openai_generate(topic_meta, count, action)
