"""
Commander — Command Parser
Extracts intent from natural language commands (text or voice transcript).
Returns a CommandIntent with agent, action, and params.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandIntent:
    agent: str                         # "study" | "bug" | "copilot" | "tab_debug" | "unknown"
    action: str                        # e.g. "exercises", "theory", "fix", "suggest", "run"
    params: dict[str, Any] = field(default_factory=dict)
    raw: str = ""


# ── keyword maps ──────────────────────────────────────────────────────────────

_STUDY_KEYWORDS = re.compile(
    r"\b(gera|gerar|cria|criar|adiciona|adicionar|exercicio|exercicios|teoria|"
    r"study|estuda|estudar|escala|escalas|acorde|acordes|arpejo|arpejos|"
    r"campo harmonico|cadencia|cadencias|caged|circulo)\b",
    re.IGNORECASE,
)

_BUG_KEYWORDS = re.compile(
    r"\b(fix|bug|bugs|erro|erros|corrige|corrigir|correcao|"
    r"tsc|typescript|eslint|lint|ruff|check|verifica|verificar|"
    r"frontend|backend|problema|problemas|falha|falhas)\b",
    re.IGNORECASE,
)

_COPILOT_KEYWORDS = re.compile(
    r"\b(copilot|explica|explicar|explain|suggest|sugere|sugerir|"
    r"como fazer|o que e|what is|help with|ajuda com)\b",
    re.IGNORECASE,
)

_TAB_DEBUG_KEYWORDS = re.compile(
    r"\b(cursor|probe|tab|play|playback|sintetico|synthetic|"
    r"jitter|freeze|quicada|smooth|debug|trace)\b",
    re.IGNORECASE,
)

# Theory-mode triggers
_THEORY_KEYWORDS = re.compile(
    r"\b(teoria|theory|visual|ouvido|ear|auditivo)\b",
    re.IGNORECASE,
)

# Specific topic extraction helpers
_TOPIC_HINTS: dict[str, list[str]] = {
    "postura-anatomia-tecnica-basica": ["postura", "cromatico", "cromatismo", "tecnica basica", "anatomia"],
    "escalas-e-modos": ["escala", "escalas", "modo", "modos", "maior", "menor", "dorico", "frigio"],
    "acordes-triades-e-intervalos": ["acorde", "acordes", "triade", "triades", "intervalo"],
    "campo-harmonico": ["campo harmonico", "grau", "graus", "diatonico"],
    "cadencias": ["cadencia", "cadencias", "v-i", "ii-v-i", "resolucao"],
    "arpejos": ["arpejo", "arpejos", "tetrade"],
    "caged": ["caged", "shape", "shapes", "regiao"],
    "circulo-de-quintas": ["circulo de quintas", "circulo das quintas", "armadura"],
}


def _extract_topic(text: str) -> str | None:
    text_lower = text.lower()
    for topic_id, hints in _TOPIC_HINTS.items():
        if any(h in text_lower for h in hints):
            return topic_id
    return None


def _extract_count(text: str) -> int:
    m = re.search(r"\b(\d+)\s*(exercicios?|exercises?|teoria|theory)?\b", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return n
    return 2


def parse(text: str) -> CommandIntent:
    """Parse a natural language command into a CommandIntent."""
    text = text.strip()

    # Internal commands
    lower = text.lower()
    if lower in ("help", "ajuda", "?"):
        return CommandIntent(agent="internal", action="help", raw=text)
    if lower in ("quit", "exit", "sair", "q"):
        return CommandIntent(agent="internal", action="quit", raw=text)
    if lower in ("status", "estado"):
        return CommandIntent(agent="internal", action="status", raw=text)

    # Score by keyword density
    study_score = len(_STUDY_KEYWORDS.findall(text))
    bug_score = len(_BUG_KEYWORDS.findall(text))
    copilot_score = len(_COPILOT_KEYWORDS.findall(text))
    tab_score = len(_TAB_DEBUG_KEYWORDS.findall(text))

    scores = {
        "study": study_score,
        "bug": bug_score,
        "copilot": copilot_score,
        "tab_debug": tab_score,
    }
    top_agent = max(scores, key=lambda k: scores[k])

    if scores[top_agent] == 0:
        # No strong signal — send to copilot as a general question
        return CommandIntent(
            agent="copilot",
            action="suggest",
            params={"prompt": text},
            raw=text,
        )

    if top_agent == "study":
        action = "theory" if _THEORY_KEYWORDS.search(text) else "exercises"
        topic = _extract_topic(text)
        count = _extract_count(text)
        return CommandIntent(
            agent="study",
            action=action,
            params={"topic": topic, "count": count, "dry_run": False},
            raw=text,
        )

    if top_agent == "bug":
        run_fe = bool(re.search(r"\bfrontend\b", text, re.IGNORECASE))
        run_be = bool(re.search(r"\bbackend\b", text, re.IGNORECASE))
        if not run_fe and not run_be:
            run_fe = run_be = True  # default: both
        return CommandIntent(
            agent="bug",
            action="fix",
            params={"frontend": run_fe, "backend": run_be},
            raw=text,
        )

    if top_agent == "copilot":
        action = "explain" if re.search(r"\b(explica|explain|o que e|what is)\b", text, re.IGNORECASE) else "suggest"
        return CommandIntent(
            agent="copilot",
            action=action,
            params={"prompt": text},
            raw=text,
        )

    if top_agent == "tab_debug":
        return CommandIntent(
            agent="tab_debug",
            action="run",
            params={"task": "cursor-glide-quality"},
            raw=text,
        )

    return CommandIntent(agent="unknown", action="unknown", raw=text)
