from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import sys
from urllib.parse import parse_qs, urlparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None  # type: ignore[assignment]
from playwright.sync_api import sync_playwright

DEFAULT_TAB_URL = "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugSystemLines=1&debugSave=1"


@dataclass
class AgentConfig:
    url: str
    model: str
    wait_ms: int
    include_non_tab: bool
    recent_limit: int
    headless: bool
    keep_open: bool
    output_dir: Path
    screenshot: bool
    tab_shots: bool
    tab_shots_max: int
    tab_shot_wait_ms: int
    no_openai: bool
    emit_codex_stdout: bool
    codex_stdout_only: bool
    task: str | None
    task_dir: Path
    task_iterations: int


@dataclass
class TaskSpec:
    id: str
    name: str
    app_url: str
    reference_url: str
    goal: str
    instructions: str
    wait_ms: int
    tab_shots_max: int
    playback_mode: str | None
    probe_duration_ms: int
    probe_sample_ms: int
    freeze_min_duration_ms: int
    required_systems: int
    max_frame_gap_ms: int
    max_long_task_ms: int
    max_audio_stall_ms: int
    max_stationary_pair_rate_pct: float
    stationary_pair_dx_px: float
    max_velocity_jitter_p90_pct: float
    velocity_jitter_spike_threshold_pct: float
    max_velocity_jitter_spike_count: int
    max_display_hold_event_count: int
    max_target_jump_event_count: int
    task_iterations: int
    require_all_iterations_pass: bool


def is_click_task_spec(task: TaskSpec | None) -> bool:
    if not task:
        return False
    haystack = " ".join(
        [
            task.id or "",
            task.name or "",
            task.goal or "",
            task.instructions or "",
        ]
    ).lower()
    return any(token in haystack for token in ("cursor", "click"))


def is_playback_task_spec(task: TaskSpec | None) -> bool:
    """Return True when the task specifically tests playback cursor motion/sync."""
    if not task:
        return False
    haystack = " ".join(
        [
            task.id or "",
            task.name or "",
            task.goal or "",
            task.instructions or "",
        ]
    ).lower()
    return "playback" in haystack and ("cursor" in haystack or "smooth" in haystack or "sync" in haystack)


def parse_args() -> AgentConfig:
    parser = argparse.ArgumentParser(
        description="Open browser, collect __tabzerSystemDebug and ask OpenAI for diagnosis."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_TAB_URL,
        help="Target page URL.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5.2",
        help="OpenAI model name.",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=3500,
        help="Milliseconds to wait after page load.",
    )
    parser.add_argument(
        "--include-non-tab",
        type=int,
        default=1,
        choices=[0, 1],
        help="Forward includeNonTab to scanNow().",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=400,
        help="How many recent debug entries to keep in prompt payload.",
    )
    parser.add_argument(
        "--headless",
        type=int,
        default=0,
        choices=[0, 1],
        help="1=headless, 0=opens visible browser window.",
    )
    parser.add_argument(
        "--keep-open",
        action="store_true",
        help="Keep browser open at the end.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (defaults to backend/agents/tab_debug_agent/runs).",
    )
    parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Save screenshot of final page state.",
    )
    parser.add_argument(
        "--tab-shots",
        type=int,
        default=1,
        choices=[0, 1],
        help="Capture tab screenshots (including scroll) and send to OpenAI.",
    )
    parser.add_argument(
        "--tab-shots-max",
        type=int,
        default=8,
        help="Maximum number of tab screenshots to capture.",
    )
    parser.add_argument(
        "--tab-shot-wait-ms",
        type=int,
        default=160,
        help="Wait between scroll steps when capturing tab screenshots.",
    )
    parser.add_argument(
        "--no-openai",
        action="store_true",
        help="Skip OpenAI call and generate local heuristic diagnosis only.",
    )
    parser.add_argument(
        "--emit-codex-stdout",
        action="store_true",
        help="Print latest-codex payload JSON to stdout at the end.",
    )
    parser.add_argument(
        "--codex-stdout-only",
        action="store_true",
        help="Print only latest-codex payload JSON (single line) to stdout.",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Task id or markdown task file path (backend/agents/tab_debug_agent/tasks/*.md).",
    )
    parser.add_argument(
        "--task-dir",
        default=None,
        help="Directory containing markdown task files.",
    )
    parser.add_argument(
        "--task-iterations",
        type=int,
        default=1,
        help="How many task analysis rounds to run in a single execution.",
    )
    args = parser.parse_args()

    default_output = Path(__file__).resolve().parent / "runs"
    default_task_dir = Path(__file__).resolve().parent / "tasks"
    return AgentConfig(
        url=args.url,
        model=args.model,
        wait_ms=max(0, int(args.wait_ms)),
        include_non_tab=bool(args.include_non_tab),
        recent_limit=max(10, min(2000, int(args.recent_limit))),
        headless=bool(args.headless),
        keep_open=bool(args.keep_open),
        output_dir=Path(args.output_dir) if args.output_dir else default_output,
        screenshot=bool(args.screenshot),
        tab_shots=bool(args.tab_shots),
        tab_shots_max=max(1, min(20, int(args.tab_shots_max))),
        tab_shot_wait_ms=max(0, min(3000, int(args.tab_shot_wait_ms))),
        no_openai=bool(args.no_openai),
        emit_codex_stdout=bool(args.emit_codex_stdout),
        codex_stdout_only=bool(args.codex_stdout_only),
        task=(str(args.task).strip() if args.task else None),
        task_dir=Path(args.task_dir) if args.task_dir else default_task_dir,
        task_iterations=max(1, min(20, int(args.task_iterations))),
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_target_url(raw_url: str | None) -> str:
    candidate = (raw_url or "").strip()
    if not candidate:
        return DEFAULT_TAB_URL
    lowered = candidate.lower()
    if (
        "localhost:3000/play" in lowered
        or "127.0.0.1:3000/play" in lowered
        or "localhost:3001/play" in lowered
        or "127.0.0.1:3001/play" in lowered
    ):
        return candidate
    return DEFAULT_TAB_URL


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        repaired = text.encode(enc, errors="replace").decode(enc, errors="replace")
        print(repaired)


def load_backend_env() -> Path:
    backend_dir = Path(__file__).resolve().parents[2]
    env_path = backend_dir / ".env"
    load_dotenv(env_path)
    return env_path


def require_openai_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip().strip("'").strip('"')
    if not key:
        raise RuntimeError("OPENAI_API_KEY not found in environment/.env.")
    return key


def _strip_quotes(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 2 and ((raw[0] == raw[-1] == '"') or (raw[0] == raw[-1] == "'")):
        return raw[1:-1]
    return raw


def _parse_boolish(value: str | None, default: bool = False) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _parse_simple_frontmatter(md_text: str) -> dict[str, str]:
    lines = md_text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}
    data: dict[str, str] = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        if ":" in line:
            key, val = line.split(":", 1)
            data[key.strip().lower()] = _strip_quotes(val.strip())
        i += 1
    return data


def load_task_spec(task_ref: str | None, task_dir: Path) -> TaskSpec | None:
    if not task_ref:
        return None

    task_dir = task_dir.resolve()
    task_path: Path
    as_path = Path(task_ref)
    if as_path.exists():
        task_path = as_path.resolve()
    else:
        by_name = task_dir / f"{task_ref}.md"
        if not by_name.exists():
            raise RuntimeError(f"Task not found: {task_ref} (expected file: {by_name})")
        task_path = by_name.resolve()

    raw = task_path.read_text(encoding="utf-8")
    meta = _parse_simple_frontmatter(raw)

    task_id = meta.get("id") or task_path.stem
    name = meta.get("name") or task_id
    app_url = meta.get("app_url") or DEFAULT_TAB_URL
    reference_url = meta.get("reference_url") or ""
    goal = meta.get("goal") or "Compare app tablature lines against reference images."
    instructions = meta.get("instructions") or ""
    wait_ms = int(meta.get("wait_ms") or "3500")
    tab_shots_max = int(meta.get("tab_shots_max") or "8")
    playback_mode = (meta.get("playback_mode") or "").strip().lower() or None
    probe_duration_ms = int(meta.get("probe_duration_ms") or "5200")
    probe_sample_ms = int(meta.get("probe_sample_ms") or "16")
    freeze_min_duration_ms = int(meta.get("freeze_min_duration_ms") or "180")
    required_systems = int(meta.get("required_systems") or "1")
    max_frame_gap_ms = int(meta.get("max_frame_gap_ms") or "80")
    max_long_task_ms = int(meta.get("max_long_task_ms") or "80")
    max_audio_stall_ms = int(meta.get("max_audio_stall_ms") or "180")
    max_stationary_pair_rate_pct = float(meta.get("max_stationary_pair_rate_pct") or "12")
    stationary_pair_dx_px = float(meta.get("stationary_pair_dx_px") or "0.1")
    max_velocity_jitter_p90_pct = float(meta.get("max_velocity_jitter_p90_pct") or "0")
    velocity_jitter_spike_threshold_pct = float(meta.get("velocity_jitter_spike_threshold_pct") or "0")
    max_velocity_jitter_spike_count = int(meta.get("max_velocity_jitter_spike_count") or "0")
    max_display_hold_event_count = int(meta.get("max_display_hold_event_count") or "999999")
    max_target_jump_event_count = int(meta.get("max_target_jump_event_count") or "999999")
    task_iterations = int(meta.get("task_iterations") or "1")
    require_all_iterations_pass = _parse_boolish(meta.get("require_all_iterations_pass"), default=False)

    if not reference_url:
        raise RuntimeError(f"Task '{task_id}' missing required field: reference_url")

    return TaskSpec(
        id=task_id,
        name=name,
        app_url=app_url,
        reference_url=reference_url,
        goal=goal,
        instructions=instructions,
        wait_ms=max(500, min(15000, wait_ms)),
        tab_shots_max=max(1, min(20, tab_shots_max)),
        playback_mode=playback_mode,
        probe_duration_ms=max(2000, min(30000, probe_duration_ms)),
        probe_sample_ms=max(8, min(40, probe_sample_ms)),
        freeze_min_duration_ms=max(60, min(2000, freeze_min_duration_ms)),
        required_systems=max(1, min(8, required_systems)),
        max_frame_gap_ms=max(24, min(1000, max_frame_gap_ms)),
        max_long_task_ms=max(24, min(1000, max_long_task_ms)),
        max_audio_stall_ms=max(60, min(2000, max_audio_stall_ms)),
        max_stationary_pair_rate_pct=max(0.0, min(100.0, max_stationary_pair_rate_pct)),
        stationary_pair_dx_px=max(0.0, min(5.0, stationary_pair_dx_px)),
        max_velocity_jitter_p90_pct=max(0.0, min(1000.0, max_velocity_jitter_p90_pct)),
        velocity_jitter_spike_threshold_pct=max(0.0, min(1000.0, velocity_jitter_spike_threshold_pct)),
        max_velocity_jitter_spike_count=max(0, min(50000, max_velocity_jitter_spike_count)),
        max_display_hold_event_count=max(0, min(50000, max_display_hold_event_count)),
        max_target_jump_event_count=max(0, min(50000, max_target_jump_event_count)),
        task_iterations=max(1, min(20, task_iterations)),
        require_all_iterations_pass=require_all_iterations_pass,
    )


def collect_debug_snapshot(page: Any, include_non_tab: bool, recent_limit: int) -> dict[str, Any]:
    script = """
({ includeNonTab, recentLimit }) => {
  const api = window.__tabzerSystemDebug;

  const hasSystemDebug = !!api;
  if (hasSystemDebug) {
    try { api.clear?.(); } catch {}
  }

  let scan = null;
  let summary = null;
  let failures = [];
  let suspects = [];
  let recent = [];
  let byTagged = [];
  let svgLayout = [];
  let debugLogSummary = null;
  let debugLogRecent = [];
  let debugLogSmart = null;
  let errors = [];

  if (hasSystemDebug) {
    try { scan = api.scanNow?.({ push: true, includeNonTab }) ?? null; } catch (e) { errors.push(String(e)); }
    try { summary = api.summary?.() ?? null; } catch (e) { errors.push(String(e)); }
    try { failures = api.failures?.(200) ?? []; } catch (e) { errors.push(String(e)); }
    try { suspects = api.suspects?.(300) ?? []; } catch (e) { errors.push(String(e)); }
    try { recent = api.recent?.(recentLimit) ?? []; } catch (e) { errors.push(String(e)); }
  }

  try {
    svgLayout = Array.from(document.querySelectorAll("svg"))
      .map((svg, i) => {
        const rect = svg.getBoundingClientRect();
        const style = window.getComputedStyle(svg);
        return {
          svg: i,
          tagged: svg.querySelectorAll(".tab-string-line").length,
          forced: svg.querySelectorAll("[data-tabzer-forced-line='1']").length,
          marginTopInline: svg.style.marginTop || "",
          marginTopComputed: style.marginTop || "",
          stackShiftAttr: svg.getAttribute("data-tabzer-stack-shift"),
          stackShiftProp: (svg).__tabzerStackShift ?? null,
          topCrop: (svg).__tabzerTopCrop ?? null,
          bottomCrop: (svg).__tabzerBottomCrop ?? null,
          h: Number.isFinite(rect.height) ? rect.height : null,
          top: Number.isFinite(rect.top) ? rect.top : null,
        };
      })
      .slice(0, 240);
  } catch (e) {
    errors.push(String(e));
  }

  if (hasSystemDebug) {
    try {
      const rows = Array.from(document.querySelectorAll("svg"))
        .map((svg, i) => ({
          svg: i,
          tagged: svg.querySelectorAll(".tab-string-line").length,
          forced: svg.querySelectorAll("[data-tabzer-forced-line='1']").length,
          status: svg.getAttribute("data-tabzer-system-line-status"),
          cause: svg.getAttribute("data-tabzer-system-line-cause")
        }))
        .filter(row => row.tagged > 0);
      byTagged = rows;
    } catch (e) {
      errors.push(String(e));
    }
  }

  try {
    const logApi = window.__tabzerDebugLog;
    if (logApi) {
      debugLogSummary = logApi.summary?.() ?? null;
      debugLogRecent = logApi.recent?.(Math.max(60, Math.min(1200, recentLimit * 4))) ?? [];
      debugLogSmart = logApi.smartExtract?.({
        count: 4200,
        pairSampleLimit: 220,
        eventSampleLimit: 180
      }) ?? null;
    }
  } catch (e) {
    errors.push(String(e));
  }

  return {
    ok: hasSystemDebug || !!debugLogSummary || !!debugLogSmart,
    reason: hasSystemDebug ? null : "__tabzerSystemDebug is not available on window",
    systemDebugPresent: hasSystemDebug,
    href: window.location.href,
    ts: new Date().toISOString(),
    scan,
    summary,
    failures,
    suspects,
    recent,
    byTagged,
    svgLayout,
    debugLogSummary,
    debugLogRecent,
    debugLogSmart,
    errors
  };
}
"""
    return page.evaluate(
        script,
        {"includeNonTab": include_non_tab, "recentLimit": recent_limit},
    )


def compact_for_llm(snapshot: dict[str, Any], recent_limit: int) -> dict[str, Any]:
    recent = snapshot.get("recent") or []
    failures = snapshot.get("failures") or []
    suspects = snapshot.get("suspects") or []
    debug_log_recent = snapshot.get("debugLogRecent") or []
    debug_log_smart = snapshot.get("debugLogSmart") or {}
    debug_log_smart_summary = debug_log_smart.get("summary") if isinstance(debug_log_smart, dict) else None
    debug_log_smart_samples = debug_log_smart.get("samples") if isinstance(debug_log_smart, dict) else None

    def cut_pairs(items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        return items[-max_items:] if len(items) > max_items else items

    def cut(items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
        return items[-max_items:] if len(items) > max_items else items

    return {
        "href": snapshot.get("href"),
        "ts": snapshot.get("ts"),
        "scan": snapshot.get("scan"),
        "summary": snapshot.get("summary"),
        "byTagged": cut(snapshot.get("byTagged") or [], 120),
        "failures": cut(failures, 120),
        "suspects": cut(suspects, 120),
        "recent": cut(recent, min(250, recent_limit)),
        "debugLogSummary": snapshot.get("debugLogSummary"),
        "debugLogRecent": cut(debug_log_recent, min(300, recent_limit * 2)),
        "debugSmartSummary": debug_log_smart_summary,
        "debugSmartPairsRecent": cut_pairs(
            (debug_log_smart_samples or {}).get("stackPairsRecent") if isinstance(debug_log_smart_samples, dict) else [],
            120,
        ),
        "debugSmartPairsLargestFinalGap": cut_pairs(
            (debug_log_smart_samples or {}).get("stackPairsLargestFinalGap") if isinstance(debug_log_smart_samples, dict) else [],
            120,
        ),
        "errors": snapshot.get("errors") or [],
    }


def capture_tab_screenshots(
    page: Any,
    output_dir: Path,
    max_shots: int,
    wait_ms: int,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    selector_info = page.evaluate(
        """
() => {
  const debugPresent = !!window.__tabzerSystemDebug;
  const href = window.location.href || "";
  const looksLikePlayPage = /\\/play(\\?|$)/.test(href);
  if (!debugPresent && !looksLikePlayPage) {
    return { selector: null, reason: "not-tab-context", href, debugPresent };
  }

  const selectors = [
    ".sheet-wrap .at-main",
    ".sheet-wrap .at-viewport",
    ".sheet-wrap",
    ".at-main",
    ".at-viewport",
    ".alphaTab",
    "#alphaTab",
    "[data-tabzer-sheet]",
    "[data-testid='tab']"
  ];

  let best = null;
  for (const selector of selectors) {
    const nodes = Array.from(document.querySelectorAll(selector));
    for (const el of nodes) {
      if (!(el instanceof HTMLElement)) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 200 || rect.height < 120) continue;
      const svgCount = el.querySelectorAll("svg").length;
      const okSvgCount = el.querySelectorAll("svg[data-tabzer-system-line-status='ok']").length;
      const taggedLines = el.querySelectorAll(".tab-string-line").length;
      const score = okSvgCount * 100 + taggedLines * 2 + svgCount;
      if (score <= 0) continue;
      if (!best || score > best.score) {
        const scrollHeight = Number(el.scrollHeight || 0);
        const clientHeight = Number(el.clientHeight || 0);
        best = {
          selector,
          scrollHeight,
          clientHeight,
          scrollable: scrollHeight > clientHeight + 6,
          score,
          svgCount,
          okSvgCount,
          taggedLines
        };
      }
    }
  }

  if (!best) {
    return { selector: null, reason: "tab-container-not-found", href, debugPresent };
  }
  return { ...best, reason: "ok", href, debugPresent };
}
"""
    )

    shots: list[str] = []
    if not selector_info or not selector_info.get("selector"):
        reason = selector_info.get("reason") if isinstance(selector_info, dict) else "unknown"
        safe_print(f"[tab-debug-agent] tab screenshots skipped: {reason}")
        return []

    selector = selector_info["selector"]
    locator = page.locator(selector).first
    scroll_height = int(selector_info.get("scrollHeight") or 0)
    client_height = int(selector_info.get("clientHeight") or 0)
    scrollable = bool(selector_info.get("scrollable"))
    page_scroll_info = page.evaluate(
        """
() => {
  const doc = document.documentElement;
  const body = document.body;
  const scrollHeight = Math.max(
    doc?.scrollHeight || 0,
    body?.scrollHeight || 0
  );
  const clientHeight = window.innerHeight || doc?.clientHeight || 0;
  const scrollY = window.scrollY || window.pageYOffset || 0;
  return { scrollHeight, clientHeight, scrollY };
}
"""
    )
    page_scroll_height = int((page_scroll_info or {}).get("scrollHeight") or 0)
    page_client_height = int((page_scroll_info or {}).get("clientHeight") or 0)
    page_scroll_start = int((page_scroll_info or {}).get("scrollY") or 0)
    page_scrollable = page_scroll_height > page_client_height + 8 and page_client_height > 0
    tab_doc_bounds = page.evaluate(
        """
(selector) => {
  const root = document.querySelector(selector);
  if (!root) return null;
  const svgs = Array.from(root.querySelectorAll("svg"));
  if (!svgs.length) return null;
  const tabLineSvgs = svgs.filter((svg) => svg.querySelectorAll(".tab-string-line").length >= 6);
  const tabOkSvgs = svgs.filter((svg) => (svg.getAttribute("data-tabzer-system-line-status") || "").toLowerCase() === "ok");
  const target = tabLineSvgs.length ? tabLineSvgs : (tabOkSvgs.length ? tabOkSvgs : svgs);
  if (!target.length) return null;
  let top = Number.POSITIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  const scrollY = window.scrollY || window.pageYOffset || 0;
  for (const svg of target) {
    const r = svg.getBoundingClientRect();
    top = Math.min(top, r.top + scrollY);
    bottom = Math.max(bottom, r.bottom + scrollY);
  }
  if (!Number.isFinite(top) || !Number.isFinite(bottom) || bottom <= top) return null;
  return { top, bottom };
}
""",
        selector,
    )

    # Hide visual noise not part of the tab area (fixed overlays, non-tab svgs).
    page.evaluate(
        """
(selector) => {
  const root = document.querySelector(selector);
  if (!root) return;
  const markHidden = (el, why) => {
    if (!(el instanceof Element)) return;
    if (!("style" in el)) return;
    if (el.hasAttribute("data-tabzer-shot-hidden")) return;
    el.setAttribute("data-tabzer-shot-hidden", "1");
    el.setAttribute("data-tabzer-shot-hidden-why", why);
    el.setAttribute("data-tabzer-shot-prev-visibility", el.style.visibility || "");
    el.style.visibility = "hidden";
  };

  document.querySelectorAll("svg[data-tabzer-system-line-status='non-tab']").forEach((svg) => {
    markHidden(svg, "non-tab-svg");
  });

  document.querySelectorAll("g[data-tabzer-debug-system-lines='1'], g[data-tabzer-debug-vibrato='1'], .tabzer-debug-compress").forEach((node) => {
    markHidden(node, "debug-overlay");
  });
  document.querySelectorAll("[data-tabzer-debug-tabline-skip], [data-tabzer-debug-compress-el='1']").forEach((node) => {
    markHidden(node, "debug-overlay-el");
  });

  const tabSvgs = Array.from(root.querySelectorAll("svg"));
  const tabLineSvgs = tabSvgs.filter((svg) => svg.querySelectorAll(".tab-string-line").length >= 6);
  const tabOkSvgs = tabSvgs.filter((svg) => (svg.getAttribute("data-tabzer-system-line-status") || "").toLowerCase() === "ok");
  const tabTargets = tabLineSvgs.length ? tabLineSvgs : (tabOkSvgs.length ? tabOkSvgs : tabSvgs);
  const ownsTabSvg = (el) => tabTargets.some((svg) => el === svg || el.contains(svg));
  const targetBounds = (() => {
    if (!tabTargets.length) return null;
    let left = Number.POSITIVE_INFINITY;
    let top = Number.POSITIVE_INFINITY;
    let right = Number.NEGATIVE_INFINITY;
    let bottom = Number.NEGATIVE_INFINITY;
    for (const svg of tabTargets) {
      const r = svg.getBoundingClientRect();
      left = Math.min(left, r.left);
      top = Math.min(top, r.top);
      right = Math.max(right, r.right);
      bottom = Math.max(bottom, r.bottom);
    }
    if (!Number.isFinite(left) || !Number.isFinite(top) || !Number.isFinite(right) || !Number.isFinite(bottom)) return null;
    return { left, top, right, bottom };
  })();
  const intersectsTarget = (rect) => {
    if (!targetBounds) return false;
    return !(
      rect.right < targetBounds.left ||
      rect.left > targetBounds.right ||
      rect.bottom < targetBounds.top ||
      rect.top > targetBounds.bottom
    );
  };

  document.querySelectorAll("body *").forEach((el) => {
    if (!(el instanceof HTMLElement)) return;
    if (el === root) return;
    const cs = window.getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return;
    if (ownsTabSvg(el)) return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    if (!intersectsTarget(rect)) return;
    markHidden(el, "overlay-intersecting-tab");
  });
}
""",
        selector,
    )

    def restore_hidden_and_scroll() -> None:
        try:
            page.evaluate(
                """
(payload) => {
  const { selector, pageScrollTop } = payload || {};
  const el = document.querySelector(selector);
  if (el) el.scrollTop = 0;
  if (typeof pageScrollTop === "number" && Number.isFinite(pageScrollTop)) {
    window.scrollTo(0, pageScrollTop);
  }
  document.querySelectorAll("[data-tabzer-shot-hidden='1']").forEach((node) => {
    if (!(node instanceof Element)) return;
    if (!("style" in node)) return;
    const prev = node.getAttribute("data-tabzer-shot-prev-visibility") || "";
    if (prev) node.style.visibility = prev;
    else node.style.removeProperty("visibility");
    node.removeAttribute("data-tabzer-shot-prev-visibility");
    node.removeAttribute("data-tabzer-shot-hidden-why");
    node.removeAttribute("data-tabzer-shot-hidden");
  });
}
""",
                {"selector": selector, "pageScrollTop": page_scroll_start},
            )
        except Exception:
            pass

    # Deterministic captures: always start from the top of the tab container.
    try:
        page.evaluate(
            """
(selector) => {
  const el = document.querySelector(selector);
  if (!el) return false;
  el.scrollTop = 0;
  return true;
}
""",
            selector,
        )
    except Exception:
        pass

    def capture_visible_tab_area(path: Path) -> bool:
        clip = page.evaluate(
            """
(selector) => {
  const root = document.querySelector(selector);
  if (!root) return null;

  const isVisible = (r) =>
    r.width > 2 &&
    r.height > 2 &&
    r.bottom > 0 &&
    r.right > 0 &&
    r.top < window.innerHeight &&
    r.left < window.innerWidth;

  const svgs = Array.from(root.querySelectorAll("svg"));
  const lineVisible = svgs
    .filter((svg) => svg.querySelectorAll(".tab-string-line").length >= 6)
    .filter((svg) => isVisible(svg.getBoundingClientRect()));
  const okVisible = svgs
    .filter((svg) => (svg.getAttribute("data-tabzer-system-line-status") || "").toLowerCase() === "ok")
    .filter((svg) => isVisible(svg.getBoundingClientRect()));
  const anyVisible = svgs.filter((svg) => isVisible(svg.getBoundingClientRect()));
  const target = lineVisible.length ? lineVisible : (okVisible.length ? okVisible : anyVisible);
  if (!target.length) return null;

  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const svg of target) {
    const r = svg.getBoundingClientRect();
    left = Math.min(left, r.left);
    top = Math.min(top, r.top);
    right = Math.max(right, r.right);
    bottom = Math.max(bottom, r.bottom);
  }

  if (!Number.isFinite(left) || !Number.isFinite(top) || !Number.isFinite(right) || !Number.isFinite(bottom)) return null;

  // Exclude fixed/sticky overlays (transport/player bars) that cover the tab area.
  const blockers = Array.from(document.querySelectorAll("body *"))
    .filter((el) => el instanceof HTMLElement)
    .filter((el) => {
      const cs = window.getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") return false;
      const pos = cs.position;
      if (pos !== "fixed" && pos !== "sticky") return false;
      const z = Number.parseInt(cs.zIndex || "0", 10);
      if (Number.isFinite(z) && z < 8) return false;
      if (target.some((svg) => el === svg || el.contains(svg))) return false;
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 20) return false;
      const intersects = !(r.right < left || r.left > right || r.bottom < top || r.top > bottom);
      return intersects;
    })
    .map((el) => el.getBoundingClientRect());

  // If a blocker sits near the lower part of the capture, cut the clip above it.
  const lowerBlockerTop = blockers
    .map((r) => r.top)
    .filter((v) => Number.isFinite(v) && v > top + 40 && v < bottom)
    .sort((a, b) => a - b)[0];
  if (Number.isFinite(lowerBlockerTop)) {
    bottom = Math.min(bottom, lowerBlockerTop - 4);
  }

  left = Math.max(0, left);
  top = Math.max(0, top);
  right = Math.min(window.innerWidth, right);
  bottom = Math.min(window.innerHeight, bottom);
  // Guard band to avoid transport/player overlays usually pinned to the bottom.
  const footerGuard = Math.max(56, Math.min(120, Math.round(window.innerHeight * 0.12)));
  bottom = Math.min(bottom, window.innerHeight - footerGuard);
  const width = Math.max(2, right - left);
  const height = Math.max(2, bottom - top);
  if (width < 180 || height < 120) return null;
  return { x: left, y: top, width, height };
}
""",
            selector,
        )
        if not clip:
            return False
        page.screenshot(path=str(path), clip=clip, type="png")
        return True

    if not scrollable or client_height <= 0 or scroll_height <= client_height:
        if page_scrollable:
            max_doc_scroll = max(0, page_scroll_height - page_client_height)
            bounds_top = int((tab_doc_bounds or {}).get("top") or 0)
            bounds_bottom = int((tab_doc_bounds or {}).get("bottom") or 0)
            if bounds_bottom > bounds_top:
                min_scroll_top = max(0, bounds_top - 24)
                max_scroll_top = min(max_doc_scroll, max(min_scroll_top, bounds_bottom - page_client_height + 24))
            else:
                min_scroll_top = 0
                max_scroll_top = max_doc_scroll
            span = max(0, max_scroll_top - min_scroll_top)
            step = max(1, int(page_client_height * 0.85))
            total_positions = max(1, math.ceil(span / step) + 1)
            use_positions = min(max_shots, total_positions)
            if use_positions <= 1:
                positions = [min_scroll_top]
            else:
                positions = [
                    int(round(min_scroll_top + (i * span) / (use_positions - 1)))
                    for i in range(use_positions)
                ]
            for idx, top in enumerate(positions):
                page.evaluate("top => window.scrollTo(0, top)", top)
                if wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
                shot_file = output_dir / f"tab-{stamp}-{idx:02d}.png"
                if not capture_visible_tab_area(shot_file):
                    locator.screenshot(path=str(shot_file), type="png")
                shots.append(str(shot_file))
            restore_hidden_and_scroll()
            return shots
        single = output_dir / f"tab-{stamp}-0.png"
        if not capture_visible_tab_area(single):
            locator.screenshot(path=str(single), type="png")
        restore_hidden_and_scroll()
        return [str(single)]

    step = max(1, int(client_height * 0.85))
    total_positions = max(1, math.ceil((scroll_height - client_height) / step) + 1)
    use_positions = min(max_shots, total_positions)
    if use_positions <= 1:
        positions = [0]
    else:
        max_scroll_top = max(0, scroll_height - client_height)
        positions = [
            int(round((i * max_scroll_top) / (use_positions - 1)))
            for i in range(use_positions)
        ]

    for idx, top in enumerate(positions):
        page.evaluate(
            """
({selector, top}) => {
  const el = document.querySelector(selector);
  if (!el) return false;
  el.scrollTop = top;
  return true;
}
""",
            {"selector": selector, "top": top},
        )
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
        shot_file = output_dir / f"tab-{stamp}-{idx:02d}.png"
        if not capture_visible_tab_area(shot_file):
            locator.screenshot(path=str(shot_file), type="png")
        shots.append(str(shot_file))

    restore_hidden_and_scroll()

    return shots


def capture_reference_screenshots(
    page: Any,
    output_dir: Path,
    max_shots: int,
    wait_ms: int,
) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shots: list[str] = []

    def take_shot(path: Path) -> None:
        # Reference page can have overlays/popups. We keep viewport-only snapshots and
        # rely on multiple scroll positions for context.
        page.screenshot(path=str(path), type="png")

    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)

    first = output_dir / f"ref-{stamp}-00.png"
    take_shot(first)
    shots.append(str(first))
    if max_shots <= 1:
        return shots

    scroll_info = page.evaluate(
        """
() => {
  const doc = document.documentElement;
  const body = document.body;
  const scrollHeight = Math.max(
    doc?.scrollHeight || 0,
    body?.scrollHeight || 0
  );
  const clientHeight = window.innerHeight || doc?.clientHeight || 0;
  return { scrollHeight, clientHeight };
}
"""
    )
    total_height = int(scroll_info.get("scrollHeight") or 0)
    view_height = int(scroll_info.get("clientHeight") or 0)
    if total_height <= view_height + 8 or view_height <= 0:
        return shots

    step = max(1, int(view_height * 0.85))
    max_scroll_top = max(0, total_height - view_height)
    total_positions = max(1, math.ceil(max_scroll_top / step) + 1)
    use_positions = min(max_shots, total_positions)
    if use_positions <= 1:
        positions = [0]
    else:
        positions = [int(round((i * max_scroll_top) / (use_positions - 1))) for i in range(use_positions)]

    for idx, top in enumerate(positions[1:], start=1):
        page.evaluate("top => window.scrollTo(0, top)", top)
        if wait_ms > 0:
            page.wait_for_timeout(min(wait_ms, 900))
        shot = output_dir / f"ref-{stamp}-{idx:02d}.png"
        take_shot(shot)
        shots.append(str(shot))
    return shots


def _gather_visible_systems(page: Any) -> list[dict[str, Any]]:
    """Gather tab staff bands (systems), splitting multiple systems inside the same SVG."""
    system_info = page.evaluate(
        """
() => {
  const viewport = document.querySelector(".sheet-wrap .viewport, .sheet-wrap .at-main, .sheet-wrap");
  if (!viewport) return { systems: [], error: "no-viewport" };

  const svgs = Array.from(viewport.querySelectorAll("svg"));
  const tabSvgs = svgs.filter(svg => {
    const lines = svg.querySelectorAll(".tab-string-line");
    if (lines.length >= 4) return true;
    const status = (svg.getAttribute("data-tabzer-system-line-status") || "").toLowerCase();
    return status === "ok";
  });

  if (!tabSvgs.length) return { systems: [], error: "no-tab-svgs" };

  const systems = [];
  const numTextRegex = /^\\(?\\d{1,2}\\)?$/;

  const median = (arr) => {
    if (!arr.length) return null;
    const s = [...arr].sort((a, b) => a - b);
    const m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };

  const mergeYs = (ys, tol) => {
    const out = [];
    for (const y of ys) {
      const prev = out[out.length - 1];
      if (prev === undefined || Math.abs(y - prev) > tol) out.push(y);
      else out[out.length - 1] = (prev + y) / 2;
    }
    return out;
  };

  for (const svg of tabSvgs) {
    const svgIndex = svgs.indexOf(svg);
    const lineRects = Array.from(svg.querySelectorAll(".tab-string-line"))
      .map((el) => {
        try {
          const r = el.getBoundingClientRect();
          return {
            left: r.left,
            right: r.right,
            top: r.top,
            bottom: r.bottom,
            width: r.width,
            height: r.height,
            cy: r.top + r.height / 2,
          };
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .filter((r) =>
        Number.isFinite(r.width) &&
        Number.isFinite(r.height) &&
        Number.isFinite(r.cy) &&
        r.width > 60 &&
        r.height >= 0 &&
        r.height <= 6
      )
      .sort((a, b) => a.cy - b.cy);

    if (!lineRects.length) continue;

    const diffs = [];
    for (let i = 1; i < lineRects.length; i++) {
      const d = lineRects[i].cy - lineRects[i - 1].cy;
      if (d > 0.4 && d < 40) diffs.push(d);
    }
    const baseSpacing = median(diffs) ?? 12;
    const breakGap = Math.max(20, baseSpacing * 2.25);
    const mergeTol = Math.max(1.2, baseSpacing * 0.28);

    const groups = [];
    let current = [lineRects[0]];
    for (let i = 1; i < lineRects.length; i++) {
      const prev = lineRects[i - 1];
      const next = lineRects[i];
      if (next.cy - prev.cy > breakGap) {
        groups.push(current);
        current = [next];
      } else {
        current.push(next);
      }
    }
    if (current.length) groups.push(current);

    groups.forEach((grp, clusterIndex) => {
      const ys = grp.map((r) => r.cy).sort((a, b) => a - b);
      const uniqueYs = mergeYs(ys, mergeTol);
      if (uniqueYs.length < 4) return;

      const topLine = uniqueYs[0];
      const bottomLine = uniqueYs[uniqueYs.length - 1];
      const left = Math.min(...grp.map((r) => r.left));
      const right = Math.max(...grp.map((r) => r.right));
      const top = Math.min(...grp.map((r) => r.top), topLine - 4);
      const bottom = Math.max(...grp.map((r) => r.bottom), bottomLine + 4);
      const rect = {
        top,
        bottom,
        left,
        right,
        width: Math.max(1, right - left),
        height: Math.max(1, bottom - top),
      };

      const notePoints = Array.from(svg.querySelectorAll("text"))
        .map((t) => {
          const text = (t.textContent || "").trim();
          if (!numTextRegex.test(text)) return null;
          try {
            const r = t.getBoundingClientRect();
            if (!Number.isFinite(r.left) || !Number.isFinite(r.top) || !Number.isFinite(r.width) || !Number.isFinite(r.height)) {
              return null;
            }
            const x = r.left + r.width / 2;
            const y = r.top + r.height / 2;
            if (y < topLine - 18 || y > bottomLine + 18) return null;
            if (x < left - 24 || x > right + 24) return null;
            return { x, y, text };
          } catch {
            return null;
          }
        })
        .filter(Boolean)
        .sort((a, b) => a.x - b.x)
        .slice(0, 80);

      systems.push({
        index: -1,
        uid: `${svgIndex}:${clusterIndex}:${Math.round(topLine)}`,
        svgIndex,
        clusterIndex,
        docTop: topLine + window.scrollY,
        docBottom: bottomLine + window.scrollY,
        rect,
        lineCount: grp.length,
        uniqueLineCount: uniqueYs.length,
        uniqueYs,
        topLine,
        bottomLine,
        midY: (topLine + bottomLine) / 2,
        notePoints,
        visible: rect.bottom > 0 && rect.top < window.innerHeight && rect.width > 50
      });
    });
  }

  systems.sort((a, b) => a.docTop - b.docTop);
  systems.forEach((sys, idx) => { sys.index = idx; });

  return { systems, totalSvgs: svgs.length, error: null };
}
"""
    )
    return system_info.get("systems") or []


def perform_click_tests(
    page: Any,
    output_dir: Path,
    max_clicks: int = 24,
    wait_ms: int = 600,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Click at various positions across visible tab systems and capture screenshots.

    Returns (screenshot_paths, click_results, click_summary) where click_summary has
    pass-rate and failure reasons for cursor placement accuracy.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shots: list[str] = []
    results: list[dict[str, Any]] = []
    skipped_systems: list[dict[str, Any]] = []

    systems_all = _gather_visible_systems(page)
    if not systems_all:
        safe_print("[tab-debug-agent] click tests skipped: no tab systems found")
        return [], [], {"total": 0, "passed": 0, "failed": 0, "passRate": 0.0, "byKind": {}, "bySystem": {}, "failures": []}

    total_systems = len(systems_all)

    def _allow_click_through_loading_overlays() -> None:
        try:
            page.evaluate(
                """
() => {
  const selectors = [
    ".play-loader-overlay",
    "[class*='TabSkeleton-module'][class*='skeletonContainer']",
    "[class*='TabSkeleton'][class*='skeletonContainer']",
    "[class*='skeletonContainer']",
  ];
  const touched = [];
  for (const sel of selectors) {
    for (const node of Array.from(document.querySelectorAll(sel))) {
      if (!(node instanceof HTMLElement)) continue;
      const style = window.getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") <= 0.01) continue;
      if (rect.width < 12 || rect.height < 12) continue;
      node.style.pointerEvents = "none";
      touched.push({
        selector: sel,
        width: rect.width,
        height: rect.height,
        top: rect.top,
        left: rect.left,
      });
    }
  }
  return { touchedCount: touched.length, touched };
}
"""
            )
        except Exception:
            return

    def _scroll_to_doc_top(doc_top: float) -> None:
        page.evaluate(
            """
(docTop) => {
  const target = Math.max(0, docTop - window.innerHeight * 0.28);
  window.scrollTo(0, target);
}
""",
            float(doc_top),
        )

    def _read_cursor_state(click_x: float | None = None, click_y: float | None = None) -> dict[str, Any]:
        return page.evaluate(
            """
(__args) => {
  const clickX = __args?.clickX ?? null;
  const clickY = __args?.clickY ?? null;
  const debugLast = window.__tabzerCursorDebugLast ?? null;
  const logApi = window.__tabzerDebugLog ?? null;
  let clickEvents = [];
  if (logApi?.recent) {
    try {
      const recent = logApi.recent(80) || [];
      clickEvents = recent
        .filter((entry) => String(entry?.stage || "").startsWith("click."))
        .slice(-18);
    } catch {}
  }
  const selectors = [
    "#songsterr-cursor",
    ".custom-play-cursor",
    ".tabzer-cursor",
    ".at-cursor-beat",
    ".at-cursor-bar",
    "[data-tabzer-cursor]",
    "[class*='cursor']",
    "[id*='cursor']",
  ];
  const uniq = new Set();
  const candidates = [];
  for (const sel of selectors) {
    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (!(el instanceof HTMLElement)) continue;
      if (uniq.has(el)) continue;
      uniq.add(el);
      const r = el.getBoundingClientRect();
      const cs = window.getComputedStyle(el);
      const visible =
        r.width > 1 &&
        r.height > 1 &&
        r.bottom > 0 &&
        r.top < window.innerHeight &&
        cs.display !== "none" &&
        cs.visibility !== "hidden" &&
        cs.visibility !== "collapse" &&
        Number(cs.opacity || "1") > 0.05;
      if (!visible) continue;
      const id = String(el.id || "");
      const className = String(el.className || "");
      const merged = `${id} ${className}`.toLowerCase();
      const isPreferred =
        id === "songsterr-cursor" ||
        merged.includes("custom-play-cursor") ||
        merged.includes("tabzer-cursor");
      const isAlphaCursor = merged.includes("at-cursor");
      const isCursorLikeShape =
        r.width <= 80 &&
        r.height <= Math.max(140, window.innerHeight * 1.05);
      const tooLarge =
        r.height > window.innerHeight * 2.2 ||
        r.width > window.innerWidth * 0.98 ||
        (r.width * r.height) > (window.innerWidth * window.innerHeight * 1.15);
      if (!isPreferred && tooLarge) continue;
      candidates.push({
        tag: el.tagName,
        id: id.slice(0, 120),
        className: className.slice(0, 140),
        isPreferred,
        isAlphaCursor,
        isCursorLikeShape,
        rect: { top: r.top, left: r.left, width: r.width, height: r.height },
      });
    }
  }

  let chosen = null;
  if (candidates.length) {
    let pool = candidates;
    const preferredPool = pool.filter((c) => c.isPreferred);
    if (preferredPool.length) {
      pool = preferredPool;
    } else {
      const alphaPool = pool.filter((c) => c.isAlphaCursor);
      if (alphaPool.length) pool = alphaPool;
      const compactPool = pool.filter((c) => c.isCursorLikeShape);
      if (compactPool.length) pool = compactPool;
    }
    if (Number.isFinite(clickX) && Number.isFinite(clickY)) {
      chosen = pool
        .map((c) => {
          const cx = c.rect.left + c.rect.width / 2;
          const cy = c.rect.top + c.rect.height / 2;
          const dist = Math.hypot(cx - Number(clickX), cy - Number(clickY));
          const penalty = c.isCursorLikeShape ? 0 : 120;
          return { c, score: dist + penalty };
        })
        .sort((a, b) => a.score - b.score)[0]?.c ?? pool[0];
    } else {
      chosen = pool
        .slice()
        .sort((a, b) => {
          const pa = (a.isPreferred ? -4 : 0) + (a.isAlphaCursor ? -2 : 0) + (a.isCursorLikeShape ? -1 : 1) + (a.rect.width * a.rect.height) / 5000;
          const pb = (b.isPreferred ? -4 : 0) + (b.isAlphaCursor ? -2 : 0) + (b.isCursorLikeShape ? -1 : 1) + (b.rect.width * b.rect.height) / 5000;
          return pa - pb;
        })[0] ?? pool[0];
    }
  }
  const cursorRect = chosen ? chosen.rect : null;

  return {
    cursorInfo: debugLast ? {
      phase: debugLast.phase ?? null,
      note: debugLast.note ?? null,
      beat: debugLast.beat ?? null,
      system: debugLast.system ?? null,
      anchor: debugLast.anchor ?? null,
      clickedSvgIdx: debugLast.svg?.clickedSvgIdx ?? null,
      clickLocalX: debugLast.click?.localX ?? null,
      clickLocalY: debugLast.click?.localY ?? null,
      band: debugLast.band ?? null,
      reason: debugLast.reason ?? null
    } : null,
    cursorRect,
    lastClick: debugLast,
    clickEvents,
    href: window.location.href
  };
}
"""
        )

    def _state_has_beat(state: dict[str, Any] | None) -> bool:
        if not isinstance(state, dict):
            return False
        info = state.get("cursorInfo") or {}
        phase = str(info.get("phase") or "").lower()
        beat = info.get("beat") or {}
        return phase in {"done", "final"} and beat.get("bar") is not None and beat.get("beat") is not None

    def _match_system(ref_sys: dict[str, Any], refreshed: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not refreshed:
            return None
        ref_top = float(ref_sys.get("docTop") or 0)
        best = min(refreshed, key=lambda s: abs(float(s.get("docTop") or 0) - ref_top))
        return best

    def _sample_system_indices(count: int) -> list[int]:
        idxs = [0]
        if count > 1:
            idxs.append(count - 1)
        if count > 2:
            idxs.append(count // 2)
        if count > 3:
            idxs.append(count // 3)
        if count > 4:
            idxs.append((2 * count) // 3)
        return sorted(set(i for i in idxs if 0 <= i < count))

    clickable_systems: list[dict[str, Any]] = []
    seen_uids: set[str] = set()
    probe_wait = max(220, min(wait_ms, 450))
    _allow_click_through_loading_overlays()
    for ref_sys in systems_all:
        _scroll_to_doc_top(float(ref_sys.get("docTop") or 0))
        page.wait_for_timeout(420)
        _allow_click_through_loading_overlays()
        refreshed = _gather_visible_systems(page)
        current = _match_system(ref_sys, refreshed)
        if not current:
            continue
        uid = str(current.get("uid") or f"{current.get('svgIndex')}:{current.get('index')}")
        if uid in seen_uids:
            continue
        seen_uids.add(uid)

        rect = current["rect"]
        top_line = float(current.get("topLine", rect["top"]))
        bottom_line = float(current.get("bottomLine", rect["bottom"]))
        mid_y = float(current.get("midY", (top_line + bottom_line) / 2))
        line_span = max(8.0, bottom_line - top_line)
        x_center = float(rect["left"]) + float(rect["width"]) * 0.5
        note_points = current.get("notePoints") or []
        note_points_on_row = [
            n for n in note_points
            if isinstance(n, dict) and isinstance(n.get("y"), (int, float)) and abs(float(n.get("y") or 0) - mid_y) <= max(16.0, line_span * 0.55)
        ]
        note_pool = note_points_on_row if note_points_on_row else note_points
        anchor_note = min(note_pool, key=lambda n: abs(float(n.get("x") or 0) - x_center)) if note_pool else None
        probe_x = float(anchor_note.get("x")) if anchor_note and isinstance(anchor_note.get("x"), (int, float)) else x_center

        page.mouse.click(probe_x, mid_y)
        page.wait_for_timeout(probe_wait)
        probe_state = _read_cursor_state()
        if _state_has_beat(probe_state):
            clickable_systems.append(current)
            continue
        skipped_systems.append(
            {
                "systemIndex": current["index"],
                "svgIndex": current["svgIndex"],
                "reason": "no-beat-on-probe",
                "probeX": round(probe_x, 1),
                "probeY": round(mid_y, 1),
                "phase": (probe_state.get("cursorInfo") or {}).get("phase") if isinstance(probe_state, dict) else None,
            }
        )

    sample_indices = _sample_system_indices(len(clickable_systems))
    tested_systems: list[dict[str, Any]] = [clickable_systems[i] for i in sample_indices]
    click_points: list[dict[str, Any]] = []
    for current in tested_systems:
        rect = current["rect"]
        top_line = float(current.get("topLine", rect["top"]))
        bottom_line = float(current.get("bottomLine", rect["bottom"]))
        mid_y = float(current.get("midY", (top_line + bottom_line) / 2))
        line_span = max(8.0, bottom_line - top_line)
        spacing = line_span / max(5.0, float(max(2, int(current.get("uniqueLineCount") or 6)) - 1))
        margin = max(5.0, min(10.0, spacing * 0.65))
        x_center = float(rect["left"]) + float(rect["width"]) * 0.5
        note_points = current.get("notePoints") or []
        note_points_on_row = [
            n for n in note_points
            if isinstance(n, dict) and isinstance(n.get("y"), (int, float)) and abs(float(n.get("y") or 0) - mid_y) <= max(16.0, line_span * 0.55)
        ]
        note_pool = note_points_on_row if note_points_on_row else note_points
        anchor_note = min(note_pool, key=lambda n: abs(float(n.get("x") or 0) - x_center)) if note_pool else None
        x_primary = float(anchor_note.get("x")) if anchor_note and isinstance(anchor_note.get("x"), (int, float)) else x_center
        x_label_primary = "note-column" if anchor_note else "center"

        for y_label, y in [
            ("top-margin", top_line - margin),
            ("mid", mid_y),
            ("bottom-margin", bottom_line + margin),
        ]:
            click_points.append(
                {
                    "kind": "system",
                    "systemIndex": current["index"],
                    "svgIndex": current["svgIndex"],
                    "expectedSvgIndices": [current["svgIndex"]],
                    "targetTopLine": top_line,
                    "targetBottomLine": bottom_line,
                    "targetDocTop": current.get("docTop"),
                    "x": round(x_primary, 1),
                    "y": round(y, 1),
                    "xLabel": x_label_primary,
                    "yLabel": y_label,
                }
            )

        if note_pool:
            note = anchor_note or min(note_pool, key=lambda n: abs(float(n.get("x") or 0) - x_center))
            click_points.append(
                {
                    "kind": "note",
                    "systemIndex": current["index"],
                    "svgIndex": current["svgIndex"],
                    "expectedSvgIndices": [current["svgIndex"]],
                    "targetTopLine": top_line,
                    "targetBottomLine": bottom_line,
                    "targetDocTop": current.get("docTop"),
                    "x": round(float(note.get("x") or x_center), 1),
                    "y": round(float(note.get("y") or mid_y), 1),
                    "xLabel": "note",
                    "yLabel": "note-near",
                    "noteText": note.get("text"),
                }
            )

    tested_systems = sorted(tested_systems, key=lambda s: float(s.get("docTop") or 0))
    for i in range(len(tested_systems) - 1):
        a = tested_systems[i]
        b = tested_systems[i + 1]
        gap = float(b.get("topLine") or 0) - float(a.get("bottomLine") or 0)
        if gap < 14:
            continue
        a_rect = a.get("rect") or {}
        b_rect = b.get("rect") or {}
        a_left = float(a_rect.get("left") or 0)
        a_right = float(a_rect.get("right") or 0)
        b_left = float(b_rect.get("left") or 0)
        b_right = float(b_rect.get("right") or 0)
        overlap_left = max(a_left, b_left)
        overlap_right = min(a_right, b_right)
        if overlap_right > overlap_left:
            x = (overlap_left + overlap_right) / 2
        else:
            x = (a_left + a_right + b_left + b_right) / 4
        y = (float(a.get("bottomLine") or 0) + float(b.get("topLine") or 0)) / 2
        click_points.append(
            {
                "kind": "gap",
                "systemIndex": a["index"],
                "svgIndex": a["svgIndex"],
                "expectedSvgIndices": sorted({int(a["svgIndex"]), int(b["svgIndex"])}),
                "targetTopLine": float(a.get("bottomLine") or y),
                "targetBottomLine": float(b.get("topLine") or y),
                "targetDocTop": float(a.get("docTop") or 0),
                "x": round(x, 1),
                "y": round(y, 1),
                "xLabel": "gap",
                "yLabel": "between-systems",
                "gapBetween": [a["index"], b["index"]],
            }
        )

    if len(click_points) > max_clicks:
        click_points = click_points[:max_clicks]

    if not click_points:
        summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "passRate": 0.0,
            "byKind": {},
            "bySystem": {},
            "failures": [],
            "skippedSystems": skipped_systems,
            "allSystemCount": total_systems,
            "clickableSystemCount": len(clickable_systems),
        }
        safe_print("[tab-debug-agent] click tests skipped: no clickable systems")
        return [], [], summary

    safe_print(
        f"[tab-debug-agent] performing {len(click_points)} click tests across {len(tested_systems)} sampled systems "
        f"(clickable {len(clickable_systems)}/{total_systems})"
    )

    last_doc_top: float | None = None
    for idx, pt in enumerate(click_points):
        target_doc_top = pt.get("targetDocTop")
        if isinstance(target_doc_top, (int, float)) and (
            last_doc_top is None or abs(float(target_doc_top) - float(last_doc_top)) > 40
        ):
            _scroll_to_doc_top(float(target_doc_top))
            page.wait_for_timeout(420)
            _allow_click_through_loading_overlays()
            last_doc_top = float(target_doc_top)

        x = float(pt.get("x") or 0)
        y = float(pt.get("y") or 0)
        try:
            before_state = _read_cursor_state()
            page.mouse.click(x, y)
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)
            cursor_state = _read_cursor_state()

            info = (cursor_state.get("cursorInfo") or {}) if isinstance(cursor_state, dict) else {}
            phase = str(info.get("phase") or "").lower()
            beat = info.get("beat") or {}
            has_beat = beat.get("bar") is not None and beat.get("beat") is not None
            observed_svg = info.get("clickedSvgIdx")
            expected_svg_list = [int(v) for v in (pt.get("expectedSvgIndices") or []) if isinstance(v, (int, float))]
            same_svg = observed_svg in expected_svg_list if expected_svg_list and observed_svg is not None else False
            near_svg = False
            if (
                not same_svg
                and observed_svg is not None
                and expected_svg_list
            ):
                near_svg = min(abs(int(observed_svg) - int(v)) for v in expected_svg_list) <= 1

            anchor = info.get("anchor") or {}
            click_local_x = info.get("clickLocalX")
            anchor_x = anchor.get("x")
            x_error = None
            if isinstance(click_local_x, (int, float)) and isinstance(anchor_x, (int, float)):
                x_error = abs(float(anchor_x) - float(click_local_x))

            passed = False
            reasons: list[str] = []
            kind = str(pt.get("kind") or "system")
            if kind == "gap":
                if phase not in {"done", "abort"}:
                    reasons.append("gap-phase-invalid")
                if has_beat:
                    if observed_svg is None:
                        reasons.append("gap-missing-svg")
                    elif expected_svg_list and observed_svg not in expected_svg_list:
                        if min(abs(int(observed_svg) - int(v)) for v in expected_svg_list) > 1:
                            reasons.append("gap-wrong-system-jump")
                passed = len(reasons) == 0
            else:
                if phase not in {"done", "final"}:
                    reasons.append("phase-not-done")
                if not has_beat:
                    reasons.append("missing-beat")
                if not same_svg and not near_svg:
                    reasons.append("wrong-system")

                # Cursor debug snappedY and clickLocalY share the same local coordinate space.
                snapped_y = (info.get("band") or {}).get("snappedY")
                click_local_y = info.get("clickLocalY")
                if isinstance(snapped_y, (int, float)) and isinstance(click_local_y, (int, float)):
                    y_delta = abs(float(snapped_y) - float(click_local_y))
                    y_limit = 128.0 if kind == "system" else 92.0
                    if y_delta > y_limit:
                        reasons.append("y-outside-target")

                if kind == "note":
                    if x_error is not None and x_error > 80:
                        reasons.append("note-x-misaligned")
                passed = len(reasons) == 0

            result = {
                "clickIndex": idx,
                "kind": kind,
                "systemIndex": pt.get("systemIndex"),
                "svgIndex": pt.get("svgIndex"),
                "expectedSvgIndices": pt.get("expectedSvgIndices"),
                "clickX": x,
                "clickY": y,
                "xLabel": pt.get("xLabel"),
                "yLabel": pt.get("yLabel"),
                "targetTopLine": pt.get("targetTopLine"),
                "targetBottomLine": pt.get("targetBottomLine"),
                "cursorState": cursor_state.get("cursorInfo"),
                "cursorRect": cursor_state.get("cursorRect"),
                "cursorElement": cursor_state.get("cursorElement"),
                "lastClick": cursor_state.get("lastClick"),
                "clickEvents": cursor_state.get("clickEvents"),
                "beforeCursorState": before_state.get("cursorInfo") if isinstance(before_state, dict) else None,
                "assessment": {
                    "passed": passed,
                    "reasons": reasons,
                    "phase": phase,
                    "hasBeat": has_beat,
                    "observedSvgIndex": observed_svg,
                    "expectedSvgIndices": expected_svg_list,
                    "xError": x_error,
                },
            }
            results.append(result)

            shot_path = output_dir / f"click-{stamp}-{idx:02d}.png"
            page.screenshot(path=str(shot_path), type="png")
            shots.append(str(shot_path))
        except Exception as exc:
            results.append(
                {
                    "clickIndex": idx,
                    "kind": pt.get("kind"),
                    "clickX": x,
                    "clickY": y,
                    "error": str(exc),
                    "assessment": {
                        "passed": False,
                        "reasons": ["exception"],
                    },
                }
            )

    summary = summarize_click_results(results)
    summary["skippedSystems"] = skipped_systems
    summary["testedSystemCount"] = len({r.get("systemIndex") for r in results if r.get("systemIndex") is not None})
    summary["targetSystemCount"] = len(sample_indices)
    summary["allSystemCount"] = total_systems
    summary["clickableSystemCount"] = len(clickable_systems)
    safe_print(
        f"[tab-debug-agent] click accuracy: {summary.get('passed', 0)}/{summary.get('total', 0)} ({summary.get('passRate', 0.0):.1f}%)"
    )
    return shots, results, summary


def summarize_click_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = 0
    by_kind: dict[str, dict[str, Any]] = {}
    by_system: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    for item in results:
        kind = str(item.get("kind") or "unknown")
        system_key = str(item.get("systemIndex") if item.get("systemIndex") is not None else "n/a")
        assess = item.get("assessment") or {}
        is_pass = bool(assess.get("passed")) and not item.get("error")
        if is_pass:
            passed += 1

        kind_bucket = by_kind.setdefault(kind, {"total": 0, "passed": 0, "failed": 0})
        kind_bucket["total"] += 1
        if is_pass:
            kind_bucket["passed"] += 1
        else:
            kind_bucket["failed"] += 1

        sys_bucket = by_system.setdefault(system_key, {"total": 0, "passed": 0, "failed": 0})
        sys_bucket["total"] += 1
        if is_pass:
            sys_bucket["passed"] += 1
        else:
            sys_bucket["failed"] += 1
            failures.append(
                {
                    "clickIndex": item.get("clickIndex"),
                    "kind": kind,
                    "systemIndex": item.get("systemIndex"),
                    "svgIndex": item.get("svgIndex"),
                    "reasons": assess.get("reasons") or ([item.get("error")] if item.get("error") else []),
                    "expectedSvgIndices": assess.get("expectedSvgIndices"),
                    "observedSvgIndex": assess.get("observedSvgIndex"),
                }
            )

    pass_rate = (passed / total * 100.0) if total > 0 else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": round(pass_rate, 2),
        "byKind": by_kind,
        "bySystem": by_system,
        "failures": failures[:80],
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    idx = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return ordered[lo]
    weight = idx - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _build_velocity_jitter_metrics_from_samples(
    samples: list[dict[str, Any]],
    *,
    time_key: str,
    position_key: str,
    stationary_pair_dx_px: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    moving_velocity_samples: list[dict[str, Any]] = []
    velocity_jitter_events: list[dict[str, Any]] = []

    for i in range(1, len(samples)):
        prev = samples[i - 1]
        curr = samples[i]
        prev_pos = prev.get(position_key)
        curr_pos = curr.get(position_key)
        if not isinstance(prev_pos, (int, float)) or not isinstance(curr_pos, (int, float)):
            continue

        prev_time = float(prev.get(time_key) or 0.0)
        curr_time = float(curr.get(time_key) or prev_time)
        dt = max(0.0, curr_time - prev_time)
        if dt < 5.0:
            continue

        prev_system = prev.get("systemIndex")
        curr_system = curr.get("systemIndex")
        same_system = (
            prev_system == curr_system
            or not isinstance(prev_system, (int, float))
            or not isinstance(curr_system, (int, float))
        )
        if not same_system:
            continue

        delta_x = float(curr_pos) - float(prev_pos)
        if delta_x <= stationary_pair_dx_px:
            continue

        velocity = delta_x / dt
        moving_velocity_samples.append(
            {
                "sampleIndex": i,
                "systemIndex": curr_system,
                "dt": dt,
                "deltaX": delta_x,
                "velocity": velocity,
            }
        )

        prev_velocity_sample = moving_velocity_samples[-2] if len(moving_velocity_samples) >= 2 else None
        if (
            prev_velocity_sample
            and prev_velocity_sample.get("systemIndex") == curr_system
            and int(prev_velocity_sample.get("sampleIndex") or -1) == i - 1
        ):
            prev_velocity_candidates = [
                sample
                for sample in moving_velocity_samples[-4:-1]
                if sample.get("systemIndex") == curr_system
            ]
            if prev_velocity_candidates:
                smoothed_prev_velocity = sum(
                    float(sample.get("velocity") or 0.0) for sample in prev_velocity_candidates
                ) / len(prev_velocity_candidates)
            else:
                smoothed_prev_velocity = float(prev_velocity_sample.get("velocity") or 0.0)
            prev_velocity = float(prev_velocity_sample.get("velocity") or 0.0)
            jitter_ratio = abs(velocity - smoothed_prev_velocity) / max(
                abs(velocity), smoothed_prev_velocity, 0.01
            )
            velocity_jitter_events.append(
                {
                    "samplePair": [i - 1, i],
                    "systemIndex": curr_system,
                    "dt": round(dt, 2),
                    "deltaX": round(delta_x, 3),
                    "velocityPxPerMs": round(velocity, 6),
                    "previousVelocityPxPerMs": round(prev_velocity, 6),
                    "smoothedPreviousVelocityPxPerMs": round(smoothed_prev_velocity, 6),
                    "jitterRatioPct": round(jitter_ratio * 100.0, 2),
                }
            )

    return moving_velocity_samples, velocity_jitter_events


def _count_stationary_pairs_from_samples(
    samples: list[dict[str, Any]],
    *,
    position_key: str,
    stationary_pair_dx_px: float,
) -> tuple[int, int]:
    same_system_pair_count = 0
    stationary_pair_count = 0

    for i in range(1, len(samples)):
        prev = samples[i - 1]
        curr = samples[i]
        prev_pos = prev.get(position_key)
        curr_pos = curr.get(position_key)
        if not isinstance(prev_pos, (int, float)) or not isinstance(curr_pos, (int, float)):
            continue

        prev_system = prev.get("systemIndex")
        curr_system = curr.get("systemIndex")
        same_system = (
            prev_system == curr_system
            or not isinstance(prev_system, (int, float))
            or not isinstance(curr_system, (int, float))
        )
        if not same_system:
            continue

        same_system_pair_count += 1
        if abs(float(curr_pos) - float(prev_pos)) <= stationary_pair_dx_px:
            stationary_pair_count += 1

    return same_system_pair_count, stationary_pair_count


def perform_playback_cursor_tests(
    page: Any,
    output_dir: Path,
    mode: str = "synthetic",
    sample_interval_ms: int = 500,
    total_duration_ms: int = 5000,
    probe_sample_ms: int = 16,
    freeze_min_duration_ms: int = 180,
    required_systems: int = 1,
    max_frame_gap_ms: int = 80,
    max_long_task_ms: int = 80,
    max_audio_stall_ms: int = 180,
    max_stationary_pair_rate_pct: float = 12.0,
    stationary_pair_dx_px: float = 0.1,
    max_velocity_jitter_p90_pct: float = 0.0,
    velocity_jitter_spike_threshold_pct: float = 0.0,
    max_velocity_jitter_spike_count: int = 0,
    max_display_hold_event_count: int = 999999,
    max_target_jump_event_count: int = 999999,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Start playback, sample cursor position at frame cadence, and detect freezes/stalls."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shots: list[str] = []
    samples: list[dict[str, Any]] = []
    target_mode = "original" if str(mode or "").strip().lower().startswith("orig") else "synthetic"

    start_result = page.evaluate(
        """
(__mode) => {
  const results = { actions: [], errors: [] };
  try {
    const modeButtons = Array.from(document.querySelectorAll('button, [role="button"], [data-audio-mode]'));
    const targetBtn = modeButtons.find((b) => {
      const t = ((b.textContent || '') + ' ' + (b.getAttribute('data-audio-mode') || '') + ' '
        + (b.getAttribute('aria-label') || '') + ' ' + (b.className || '')).toLowerCase();
      if (__mode === 'original') {
        return t.includes('original') || t.includes('youtube') || t.includes('audio original') || t.includes('source');
      }
      return t.includes('sintetico') || t.includes('synthetic') || t.includes('midi') || t.includes('synth');
    });
    if (targetBtn) {
      const active = targetBtn.getAttribute('aria-pressed') === 'true'
        || targetBtn.classList.contains('active')
        || targetBtn.classList.contains('selected');
      if (!active) {
        targetBtn.click();
        results.actions.push('clicked-mode:' + __mode);
      } else {
        results.actions.push('mode-already-active:' + __mode);
      }
    } else {
      results.actions.push('mode-button-not-found:' + __mode);
    }
  } catch (e) {
    results.errors.push('mode-switch: ' + String(e));
  }
  return results;
}
""",
        target_mode,
    )
    safe_print(f"[playback-test] mode setup: {start_result}")
    page.wait_for_timeout(1200)

    play_result = page.evaluate(
        """
() => {
  const results = { actions: [], errors: [], playButtonFound: false };
  try {
    const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
    const playBtn = candidates.find((b) => {
      const t = ((b.textContent || '') + ' ' + (b.getAttribute('aria-label') || '') + ' '
        + (b.className || '') + ' ' + (b.getAttribute('title') || '')).toLowerCase();
      return t.includes('play') || t.includes('reproduz') || t.includes('tocar');
    });
    if (playBtn) {
      playBtn.click();
      results.playButtonFound = true;
      results.actions.push('clicked-play');
    } else {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
      results.actions.push('space-fallback');
    }
  } catch (e) {
    results.errors.push('play: ' + String(e));
  }
  return results;
}
"""
    )
    safe_print(f"[playback-test] play trigger: {play_result}")
    page.wait_for_timeout(1500)
    try:
        page.wait_for_function(
            """
() => {
  const dbg = window.__tabzerPlaybackDebug?.read?.() ?? null;
  const cursor = dbg?.cursor ?? null;
  return Boolean(
    dbg?.isPlaying &&
    cursor &&
    cursor.display !== 'none' &&
    cursor.opacity !== '0'
  );
}
""",
            timeout=12000,
        )
    except Exception:
        pass

    probe_result = page.evaluate(
        """
(__args) => {
  const sampleMs = Math.max(8, Math.min(40, Number(__args?.sampleMs) || 16));
  const maxSamples = Math.max(240, Math.min(6000, Number(__args?.maxSamples) || 900));
  const readCursor = () => {
    const cursor = document.getElementById('songsterr-cursor')
      || document.querySelector('.custom-play-cursor')
      || document.querySelector('.tabzer-cursor')
      || document.querySelector('.at-cursor-beat')
      || document.querySelector('.at-cursor-bar');
    if (!(cursor instanceof HTMLElement)) {
      return {
        found: false,
        x: null,
        y: null,
        width: null,
        height: null,
        opacity: null,
        display: null,
        transform: null,
        visible: false,
        systemIndex: -1,
      };
    }
    const style = window.getComputedStyle(cursor);
    const rect = cursor.getBoundingClientRect();
    const transform = cursor.style.transform || style.transform || '';
    let x = Number.isFinite(rect.left) ? rect.left : null;
    let y = Number.isFinite(rect.top) ? rect.top : null;
    const match = transform.match(/translate(?:3d)?\\(([\\d.\\-]+)px,\\s*([\\d.\\-]+)px/);
    if (match) {
      x = parseFloat(match[1]);
      y = parseFloat(match[2]);
    }
    const visible = style.display !== 'none' && parseFloat(style.opacity || '1') > 0.01;
    let systemIndex = -1;
    if (x !== null && y !== null) {
      const svgs = Array.from(document.querySelectorAll('.alphaTab svg, svg'));
      for (let i = 0; i < svgs.length; i += 1) {
        const r = svgs[i].getBoundingClientRect();
        if (y >= r.top - 16 && y <= r.bottom + 16) {
          systemIndex = i;
          break;
        }
      }
    }
    return {
      found: true,
      x,
      y,
      width: Number.isFinite(rect.width) ? rect.width : null,
      height: Number.isFinite(rect.height) ? rect.height : null,
      opacity: style.opacity || null,
      display: style.display || null,
      transform,
      visible,
      systemIndex,
    };
  };

  try {
    if (window.__tabzerPlaybackProbe?.stop) {
      window.__tabzerPlaybackProbe.stop();
    }
  } catch {}

  const startedAt = performance.now();
  const samples = [];
  const longTasks = [];
  let intervalId = 0;
  let rafId = 0;
  let rafCount = 0;
  let observer = null;

  const rafTick = () => {
    rafCount += 1;
    rafId = window.requestAnimationFrame(rafTick);
  };

  intervalId = window.setInterval(() => {
    const playbackDebug = window.__tabzerPlaybackDebug?.read?.() ?? null;
    samples.push({
      ...readCursor(),
      playbackDebug,
      t: performance.now() - startedAt,
      ts: Date.now(),
    });
    if (samples.length > maxSamples) {
      samples.shift();
    }
  }, sampleMs);

  rafId = window.requestAnimationFrame(rafTick);

  if ('PerformanceObserver' in window) {
    try {
      observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          longTasks.push({
            start: entry.startTime,
            duration: entry.duration,
            name: entry.name || 'longtask',
          });
        }
      });
      observer.observe({ entryTypes: ['longtask'] });
    } catch {}
  }

  window.__tabzerPlaybackProbe = {
    stop: () => {
      try { window.clearInterval(intervalId); } catch {}
      try { window.cancelAnimationFrame(rafId); } catch {}
      try { observer?.disconnect?.(); } catch {}
      const elapsedMs = performance.now() - startedAt;
      const result = {
        startedAt,
        elapsedMs,
        sampleMs,
        rafCount,
        samples: samples.slice(),
        longTasks: longTasks.slice(),
      };
      delete window.__tabzerPlaybackProbe;
      return result;
    },
  };

  return { started: true, sampleMs, maxSamples };
}
""",
        {"sampleMs": probe_sample_ms, "maxSamples": max(300, int(total_duration_ms / max(8, probe_sample_ms)) + 180)},
    )
    safe_print(f"[playback-test] probe setup: {probe_result}")

    waited_ms = 0
    screenshot_offsets = [
        max(900, min(total_duration_ms - 600, sample_interval_ms)),
        max(1500, total_duration_ms - 500),
    ]
    for idx, target_wait in enumerate(screenshot_offsets):
        step_wait = max(0, int(target_wait) - waited_ms)
        if step_wait > 0:
            page.wait_for_timeout(step_wait)
            waited_ms += step_wait
        shot_path = str(output_dir / f"playback-cursor-{stamp}-{idx:02d}.png")
        try:
            page.screenshot(path=shot_path, full_page=False)
            shots.append(shot_path)
        except Exception as exc:
            safe_print(f"[playback-test] screenshot failed: {exc}")

    if waited_ms < total_duration_ms:
        page.wait_for_timeout(total_duration_ms - waited_ms)

    probe_dump = page.evaluate("() => window.__tabzerPlaybackProbe?.stop?.() ?? null")
    smoothness_dump = page.evaluate("() => window.__tabzerPlaybackDebug?.smoothness?.() ?? null")
    if isinstance(probe_dump, dict):
        samples = list(probe_dump.get("samples") or [])

    try:
        page.evaluate(
            """
() => {
  const candidates = Array.from(document.querySelectorAll('button, [role="button"]'));
  const stopBtn = candidates.find((b) => {
    const t = ((b.textContent || '') + ' ' + (b.getAttribute('aria-label') || '')).toLowerCase();
    return t.includes('pause') || t.includes('stop') || t.includes('parar');
  });
  if (stopBtn) {
    stopBtn.click();
  } else {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
  }
}
"""
        )
    except Exception:
        pass

    found_samples = [s for s in samples if s.get("found")]
    visible_samples = [s for s in found_samples if s.get("visible")]
    hidden_count = sum(1 for s in found_samples if not s.get("visible"))
    systems_seen: set[int] = set()
    freeze_runs: list[dict[str, Any]] = []
    backward_jumps: list[dict[str, Any]] = []
    long_tasks = list((probe_dump or {}).get("longTasks") or [])
    freeze_min_duration_ms = float(freeze_min_duration_ms)
    max_frame_gap_ms = float(max_frame_gap_ms)
    max_long_task_ms = float(max_long_task_ms)
    max_audio_stall_ms = float(max_audio_stall_ms)
    stationary_pair_dx_px = float(max(0.0, stationary_pair_dx_px))
    max_velocity_jitter_p90_pct = float(max(0.0, max_velocity_jitter_p90_pct))
    velocity_jitter_spike_threshold_pct = float(max(0.0, velocity_jitter_spike_threshold_pct))
    max_velocity_jitter_spike_count = int(max(0, max_velocity_jitter_spike_count))
    max_display_hold_event_count = int(max(0, max_display_hold_event_count))
    max_target_jump_event_count = int(max(0, max_target_jump_event_count))
    current_freeze: dict[str, Any] | None = None
    current_freeze_duration = 0.0
    frame_gap_spikes: list[dict[str, Any]] = []
    audio_stalls: list[dict[str, Any]] = []
    current_audio_stall: dict[str, Any] | None = None
    current_audio_stall_duration = 0.0
    same_system_pair_count = 0
    stationary_pair_count = 0
    moving_velocity_samples: list[dict[str, Any]] = []
    velocity_jitter_events: list[dict[str, Any]] = []

    for sample in visible_samples:
        sys_idx = sample.get("systemIndex")
        if isinstance(sys_idx, (int, float)):
            systems_seen.add(int(sys_idx))

    for i in range(1, len(visible_samples)):
        prev = visible_samples[i - 1]
        curr = visible_samples[i]
        same_system = prev.get("systemIndex") == curr.get("systemIndex")
        prev_x = prev.get("x")
        curr_x = curr.get("x")
        prev_t = float(prev.get("t") or 0.0)
        curr_t = float(curr.get("t") or prev_t)
        dt = max(0.0, curr_t - prev_t)
        if dt >= max_frame_gap_ms:
            frame_gap_spikes.append(
                {
                    "samplePair": [i - 1, i],
                    "systemIndex": curr.get("systemIndex"),
                    "dt": round(dt, 2),
                    "tStart": round(prev_t, 2),
                    "tEnd": round(curr_t, 2),
                }
            )

        if not same_system or not isinstance(prev_x, (int, float)) or not isinstance(curr_x, (int, float)):
            if current_freeze and current_freeze_duration >= freeze_min_duration_ms:
                freeze_runs.append(dict(current_freeze, durationMs=round(current_freeze_duration, 2)))
            current_freeze = None
            current_freeze_duration = 0.0
        else:
            same_system_pair_count += 1
            delta_x = float(curr_x) - float(prev_x)
            if abs(delta_x) <= stationary_pair_dx_px:
                stationary_pair_count += 1
                if current_freeze is None:
                    current_freeze = {
                        "sampleStart": i - 1,
                        "sampleEnd": i,
                        "systemIndex": curr.get("systemIndex"),
                        "x": round(float(curr_x), 3),
                        "tStart": round(prev_t, 2),
                        "tEnd": round(curr_t, 2),
                    }
                    current_freeze_duration = dt
                else:
                    current_freeze["sampleEnd"] = i
                    current_freeze["tEnd"] = round(curr_t, 2)
                    current_freeze_duration += dt
            else:
                if current_freeze and current_freeze_duration >= freeze_min_duration_ms:
                    freeze_runs.append(dict(current_freeze, durationMs=round(current_freeze_duration, 2)))
                current_freeze = None
                current_freeze_duration = 0.0

            if delta_x < -2.0:
                backward_jumps.append(
                    {
                        "samplePair": [i - 1, i],
                        "systemIndex": curr.get("systemIndex"),
                        "fromX": round(float(prev_x), 3),
                        "toX": round(float(curr_x), 3),
                        "deltaX": round(delta_x, 3),
                        "dt": round(dt, 2),
                    }
                )
            elif dt > 0.0 and dt < max_frame_gap_ms and delta_x > stationary_pair_dx_px:
                velocity = delta_x / dt
                # Skip samples where the probe timer fired unusually early (dt < 5ms).
                # setInterval(8ms) cannot realistically fire faster than ~4ms by the HTML spec;
                # any sample with dt < 5ms is a scheduler artifact.  Such samples produce an
                # artificially high velocity (normal deltaX / very short dt) and contaminate the
                # rolling-average reference for subsequent pairs, generating false jitter spikes.
                # We still register stationary/backward checks above, but exclude these samples
                # from velocity analysis entirely.
                min_jitter_dt_ms = 5.0
                if dt < min_jitter_dt_ms:
                    continue
                moving_velocity_samples.append(
                    {
                        "sampleIndex": i,
                        "systemIndex": curr.get("systemIndex"),
                        "dt": dt,
                        "deltaX": delta_x,
                        "velocity": velocity,
                    }
                )
                prev_velocity_sample = moving_velocity_samples[-2] if len(moving_velocity_samples) >= 2 else None
                if (
                    prev_velocity_sample
                    and prev_velocity_sample.get("systemIndex") == curr.get("systemIndex")
                    and int(prev_velocity_sample.get("sampleIndex") or -1) == i - 1
                ):
                    # Use a 3-sample rolling-average of the previous velocities to smooth out
                    # stroboscopic aliasing caused by the probe's ~8 ms timer firing at slightly
                    # irregular intervals relative to the cursor's ~8 ms update interval.  A single
                    # consecutive-pair comparison is too noisy; the rolling average retains
                    # sensitivity to genuine glitches (freezes, backward jumps, sudden kicks)
                    # while suppressing high-frequency timer-jitter artefacts.
                    prev_velocity_candidates = [
                        s for s in moving_velocity_samples[-4:-1]
                        if s.get("systemIndex") == curr.get("systemIndex")
                    ]
                    if prev_velocity_candidates:
                        smoothed_prev_velocity = sum(
                            float(s.get("velocity") or 0.0) for s in prev_velocity_candidates
                        ) / len(prev_velocity_candidates)
                    else:
                        smoothed_prev_velocity = float(prev_velocity_sample.get("velocity") or 0.0)
                    prev_velocity = float(prev_velocity_sample.get("velocity") or 0.0)
                    jitter_ratio = abs(velocity - smoothed_prev_velocity) / max(abs(velocity), smoothed_prev_velocity, 0.01)
                    velocity_jitter_events.append(
                        {
                            "samplePair": [i - 1, i],
                            "systemIndex": curr.get("systemIndex"),
                            "dt": round(dt, 2),
                            "deltaX": round(delta_x, 3),
                            "velocityPxPerMs": round(velocity, 6),
                            "previousVelocityPxPerMs": round(prev_velocity, 6),
                            "smoothedPreviousVelocityPxPerMs": round(smoothed_prev_velocity, 6),
                            "jitterRatioPct": round(jitter_ratio * 100.0, 2),
                        }
                    )

        prev_dbg = prev.get("playbackDebug") or {}
        curr_dbg = curr.get("playbackDebug") or {}
        prev_playing = bool(prev_dbg.get("isPlaying"))
        curr_playing = bool(curr_dbg.get("isPlaying"))
        if prev_playing and curr_playing:
            prev_progress = None
            curr_progress = None
            if target_mode == "synthetic":
                prev_progress = ((prev_dbg.get("synthClock") or {}).get("ms"))
                curr_progress = ((curr_dbg.get("synthClock") or {}).get("ms"))
            else:
                prev_progress = prev_dbg.get("gpMsFromOriginal")
                curr_progress = curr_dbg.get("gpMsFromOriginal")

            if isinstance(prev_progress, (int, float)) and isinstance(curr_progress, (int, float)):
                delta_progress = float(curr_progress) - float(prev_progress)
                min_expected_progress = max(2.0, dt * 0.18)
                if dt >= 12.0 and delta_progress <= min_expected_progress:
                    if current_audio_stall is None:
                        current_audio_stall = {
                            "sampleStart": i - 1,
                            "sampleEnd": i,
                            "systemIndex": curr.get("systemIndex"),
                            "fromProgressMs": round(float(prev_progress), 2),
                            "toProgressMs": round(float(curr_progress), 2),
                            "tStart": round(prev_t, 2),
                            "tEnd": round(curr_t, 2),
                            "deltaProgressMs": round(delta_progress, 2),
                        }
                        current_audio_stall_duration = dt
                    else:
                        current_audio_stall["sampleEnd"] = i
                        current_audio_stall["tEnd"] = round(curr_t, 2)
                        current_audio_stall["toProgressMs"] = round(float(curr_progress), 2)
                        current_audio_stall["deltaProgressMs"] = round(
                            float(curr_progress) - float(current_audio_stall.get("fromProgressMs") or prev_progress),
                            2,
                        )
                        current_audio_stall_duration += dt
                else:
                    if current_audio_stall and current_audio_stall_duration >= max_audio_stall_ms:
                        audio_stalls.append(dict(current_audio_stall, durationMs=round(current_audio_stall_duration, 2)))
                    current_audio_stall = None
                    current_audio_stall_duration = 0.0
            else:
                if current_audio_stall and current_audio_stall_duration >= max_audio_stall_ms:
                    audio_stalls.append(dict(current_audio_stall, durationMs=round(current_audio_stall_duration, 2)))
                current_audio_stall = None
                current_audio_stall_duration = 0.0
        else:
            if current_audio_stall and current_audio_stall_duration >= max_audio_stall_ms:
                audio_stalls.append(dict(current_audio_stall, durationMs=round(current_audio_stall_duration, 2)))
            current_audio_stall = None
            current_audio_stall_duration = 0.0

    if current_freeze and current_freeze_duration >= freeze_min_duration_ms:
        freeze_runs.append(dict(current_freeze, durationMs=round(current_freeze_duration, 2)))
    if current_audio_stall and current_audio_stall_duration >= max_audio_stall_ms:
        audio_stalls.append(dict(current_audio_stall, durationMs=round(current_audio_stall_duration, 2)))

    freeze_count = len(freeze_runs)
    frame_gap_count = len(frame_gap_spikes)
    audio_stall_count = len(audio_stalls)
    long_task_count = len([entry for entry in long_tasks if float(entry.get("duration") or 0.0) >= max_long_task_ms])
    worst_long_task_ms = max((float(entry.get("duration") or 0.0) for entry in long_tasks), default=0.0)
    worst_frame_gap_ms = max((float(entry.get("dt") or 0.0) for entry in frame_gap_spikes), default=0.0)
    stationary_pair_rate = (
        (float(stationary_pair_count) / float(same_system_pair_count)) * 100.0
        if same_system_pair_count > 0
        else 0.0
    )
    velocity_values = [float(item.get("velocity") or 0.0) for item in moving_velocity_samples]
    velocity_jitter_ratio_values = [
        float(item.get("jitterRatioPct") or 0.0)
        for item in velocity_jitter_events
    ]
    velocity_median = _percentile(velocity_values, 0.5)
    velocity_p90 = _percentile(velocity_values, 0.9)
    velocity_jitter_ratio_median = _percentile(velocity_jitter_ratio_values, 0.5)
    velocity_jitter_ratio_p90 = _percentile(velocity_jitter_ratio_values, 0.9)
    velocity_jitter_spikes = [
        item
        for item in velocity_jitter_events
        if velocity_jitter_spike_threshold_pct > 0.0
        and float(item.get("jitterRatioPct") or 0.0) > velocity_jitter_spike_threshold_pct
    ]
    velocity_jitter_spike_count = len(velocity_jitter_spikes)
    smoothness_samples = list((smoothness_dump or {}).get("samples") or []) if isinstance(smoothness_dump, dict) else []
    smoothness_events = list((smoothness_dump or {}).get("events") or []) if isinstance(smoothness_dump, dict) else []
    probe_same_system_pair_count = same_system_pair_count
    probe_stationary_pair_count = stationary_pair_count
    probe_velocity_sample_count = len(moving_velocity_samples)
    probe_velocity_jitter_event_count = len(velocity_jitter_events)
    smoothness_same_system_pair_count, smoothness_stationary_pair_count = _count_stationary_pairs_from_samples(
        smoothness_samples,
        position_key="displayX",
        stationary_pair_dx_px=stationary_pair_dx_px,
    )
    stationary_pair_source = "probe-interval"
    if smoothness_same_system_pair_count > 0:
        same_system_pair_count = smoothness_same_system_pair_count
        stationary_pair_count = smoothness_stationary_pair_count
        stationary_pair_rate = (
            (float(stationary_pair_count) / float(same_system_pair_count)) * 100.0
            if same_system_pair_count > 0
            else 0.0
        )
        stationary_pair_source = "smoothness-raf"
    smoothness_velocity_samples, smoothness_velocity_jitter_events = _build_velocity_jitter_metrics_from_samples(
        smoothness_samples,
        time_key="ts",
        position_key="displayX",
        stationary_pair_dx_px=stationary_pair_dx_px,
    )
    velocity_metric_source = "probe-interval"
    if smoothness_velocity_jitter_events:
        moving_velocity_samples = smoothness_velocity_samples
        velocity_jitter_events = smoothness_velocity_jitter_events
        velocity_values = [float(item.get("velocity") or 0.0) for item in moving_velocity_samples]
        velocity_jitter_ratio_values = [
            float(item.get("jitterRatioPct") or 0.0)
            for item in velocity_jitter_events
        ]
        velocity_median = _percentile(velocity_values, 0.5)
        velocity_p90 = _percentile(velocity_values, 0.9)
        velocity_jitter_ratio_median = _percentile(velocity_jitter_ratio_values, 0.5)
        velocity_jitter_ratio_p90 = _percentile(velocity_jitter_ratio_values, 0.9)
        velocity_jitter_spikes = [
            item
            for item in velocity_jitter_events
            if velocity_jitter_spike_threshold_pct > 0.0
            and float(item.get("jitterRatioPct") or 0.0) > velocity_jitter_spike_threshold_pct
        ]
        velocity_jitter_spike_count = len(velocity_jitter_spikes)
        velocity_metric_source = "smoothness-raf"
    display_hold_event_count = sum(1 for item in smoothness_events if str(item.get("kind") or "") == "display-hold")
    target_jump_event_count = sum(1 for item in smoothness_events if str(item.get("kind") or "") == "target-jump")
    total = len(found_samples)
    visible_count = len(visible_samples)
    systems_traversed = len(systems_seen)
    systems_fail = 0 if systems_traversed >= int(required_systems) else max(1, int(required_systems) - systems_traversed)
    stationary_pair_fail = 1 if stationary_pair_rate > float(max_stationary_pair_rate_pct) else 0
    velocity_jitter_p90_fail = (
        1
        if max_velocity_jitter_p90_pct > 0.0
        and isinstance(velocity_jitter_ratio_p90, (int, float))
        and float(velocity_jitter_ratio_p90) > max_velocity_jitter_p90_pct
        else 0
    )
    velocity_jitter_spike_fail = (
        1
        if velocity_jitter_spike_threshold_pct > 0.0
        and velocity_jitter_spike_count > max_velocity_jitter_spike_count
        else 0
    )
    display_hold_fail = 1 if display_hold_event_count > max_display_hold_event_count else 0
    target_jump_fail = 1 if target_jump_event_count > max_target_jump_event_count else 0
    failed = (
        freeze_count
        + hidden_count
        + len(backward_jumps)
        + long_task_count
        + frame_gap_count
        + audio_stall_count
        + systems_fail
        + stationary_pair_fail
        + velocity_jitter_p90_fail
        + velocity_jitter_spike_fail
        + display_hold_fail
        + target_jump_fail
    )
    penalty = (
        freeze_count * 26
        + hidden_count * 18
        + len(backward_jumps) * 16
        + long_task_count * 10
        + frame_gap_count * 12
        + audio_stall_count * 18
        + systems_fail * 22
        + stationary_pair_fail * 18
        + velocity_jitter_p90_fail * 16
        + velocity_jitter_spike_fail * 16
        + display_hold_fail * 16
        + target_jump_fail * 20
    )
    pass_rate = max(0.0, round(100.0 - penalty, 1))
    verdict = "PASS" if failed == 0 and visible_count >= 30 and systems_traversed >= int(required_systems) else "FAIL"

    summary = {
        "mode": target_mode,
        "total": total,
        "visible": visible_count,
        "failed": failed,
        "freezeCount": freeze_count,
        "hiddenCount": hidden_count,
        "backwardJumpCount": len(backward_jumps),
        "frameGapCount": frame_gap_count,
        "audioStallCount": audio_stall_count,
        "longTaskCount": long_task_count,
        "worstLongTaskMs": round(worst_long_task_ms, 2),
        "worstFrameGapMs": round(worst_frame_gap_ms, 2),
        "sameSystemPairCount": same_system_pair_count,
        "stationaryPairCount": stationary_pair_count,
        "stationaryPairRatePct": round(stationary_pair_rate, 2),
        "maxStationaryPairRatePct": float(max_stationary_pair_rate_pct),
        "stationaryPairDxPx": round(stationary_pair_dx_px, 3),
        "stationaryPairSource": stationary_pair_source,
        "probeSameSystemPairCount": probe_same_system_pair_count,
        "probeStationaryPairCount": probe_stationary_pair_count,
        "movingVelocitySampleCount": len(moving_velocity_samples),
        "velocityMedianPxPerMs": round(float(velocity_median), 6) if isinstance(velocity_median, (int, float)) else None,
        "velocityP90PxPerMs": round(float(velocity_p90), 6) if isinstance(velocity_p90, (int, float)) else None,
        "velocityJitterSampleCount": len(velocity_jitter_events),
        "velocityJitterRatioMedianPct": (
            round(float(velocity_jitter_ratio_median), 2)
            if isinstance(velocity_jitter_ratio_median, (int, float))
            else None
        ),
        "velocityJitterRatioP90Pct": (
            round(float(velocity_jitter_ratio_p90), 2)
            if isinstance(velocity_jitter_ratio_p90, (int, float))
            else None
        ),
        "maxVelocityJitterP90Pct": float(max_velocity_jitter_p90_pct),
        "velocityJitterSpikeThresholdPct": float(velocity_jitter_spike_threshold_pct),
        "velocityJitterSpikeCount": velocity_jitter_spike_count,
        "maxVelocityJitterSpikeCount": max_velocity_jitter_spike_count,
        "velocityJitterSource": velocity_metric_source,
        "probeVelocitySampleCount": probe_velocity_sample_count,
        "probeVelocityJitterEventCount": probe_velocity_jitter_event_count,
        "velocityJitterSpikeDetails": velocity_jitter_spikes[:20],
        "playbackSmoothnessSampleCount": len(smoothness_samples),
        "playbackSmoothnessEventCount": len(smoothness_events),
        "displayHoldEventCount": display_hold_event_count,
        "maxDisplayHoldEventCount": max_display_hold_event_count,
        "targetJumpEventCount": target_jump_event_count,
        "maxTargetJumpEventCount": max_target_jump_event_count,
        "recentSmoothnessEvents": smoothness_events[-12:],
        "systemsTraversed": systems_traversed,
        "requiredSystems": int(required_systems),
        "passRate": pass_rate,
        "verdict": verdict,
        "freezeDetails": freeze_runs[:20],
        "backwardJumps": backward_jumps[:20],
        "frameGapDetails": frame_gap_spikes[:20],
        "audioStallDetails": audio_stalls[:20],
        "cursorFound": any(s.get("found") for s in samples),
        "sampleCadenceMs": int(probe_sample_ms),
        "sampleIntervalMs": sample_interval_ms,
        "probeElapsedMs": round(float((probe_dump or {}).get("elapsedMs") or 0.0), 2),
        "rafCount": int((probe_dump or {}).get("rafCount") or 0),
    }
    safe_print(
        f"[playback-test] mode={target_mode} verdict={verdict} freeze={freeze_count} hidden={hidden_count} "
        f"backward={len(backward_jumps)} frameGaps={frame_gap_count} audioStalls={audio_stall_count} "
        f"stationaryRate={round(stationary_pair_rate, 2)}% "
        f"jitterP90={round(float(velocity_jitter_ratio_p90), 2) if isinstance(velocity_jitter_ratio_p90, (int, float)) else 'n/a'}% "
        f"jitterSpikes={velocity_jitter_spike_count} "
        f"longTasks={long_task_count} visible={visible_count}/{total} "
        f"systems={systems_traversed}/{int(required_systems)} passRate={pass_rate}%"
    )
    return shots, samples, summary


def perform_vertical_line_click_tests(
    page: Any,
    output_dir: Path,
    wait_ms: int = 500,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Click at each note's X position across ALL string line Y positions in ALL systems.

    For every note found, we click at that note's X coordinate at each of the 6 string
    line Y positions.  This reveals which vertical positions along a note column fail to
    register a correct beat/cursor placement.

    Returns (screenshot_paths, click_results, click_summary).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shots: list[str] = []
    results: list[dict[str, Any]] = []

    # --- helpers (same as perform_click_tests) ---
    def _allow_click_through_loading_overlays() -> None:
        try:
            page.evaluate(
                """
() => {
  const selectors = [
    ".play-loader-overlay",
    "[class*='TabSkeleton-module'][class*='skeletonContainer']",
    "[class*='TabSkeleton'][class*='skeletonContainer']",
    "[class*='skeletonContainer']",
  ];
  for (const sel of selectors) {
    for (const node of Array.from(document.querySelectorAll(sel))) {
      if (!(node instanceof HTMLElement)) continue;
      node.style.pointerEvents = "none";
    }
  }
}
"""
            )
        except Exception:
            return

    def _scroll_to_doc_top(doc_top: float) -> None:
        page.evaluate(
            """
(docTop) => {
  const target = Math.max(0, docTop - window.innerHeight * 0.28);
  window.scrollTo(0, target);
}
""",
            float(doc_top),
        )

    def _read_cursor_state(click_x: float | None = None, click_y: float | None = None) -> dict[str, Any]:
        return page.evaluate(
            """
(__args) => {
  const clickX = __args?.clickX ?? null;
  const clickY = __args?.clickY ?? null;
  const debugLast = window.__tabzerCursorDebugLast ?? null;
  const logApi = window.__tabzerDebugLog ?? null;
  let clickEvents = [];
  if (logApi?.recent) {
    try {
      const recent = logApi.recent(120) || [];
      clickEvents = recent
        .filter((entry) => String(entry?.stage || "").startsWith("click."))
        .slice(-36);
    } catch {}
  }

  const selectors = [
    "#songsterr-cursor",
    ".custom-play-cursor",
    ".tabzer-cursor",
    ".at-cursor-beat",
    ".at-cursor-bar",
    "[data-tabzer-cursor]",
    "[class*='cursor']",
    "[id*='cursor']",
  ];
  const uniq = new Set();
  const candidates = [];
  for (const sel of selectors) {
    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (!(el instanceof HTMLElement)) continue;
      if (uniq.has(el)) continue;
      uniq.add(el);
      const r = el.getBoundingClientRect();
      const cs = window.getComputedStyle(el);
      const visible =
        r.width > 1 &&
        r.height > 1 &&
        r.bottom > 0 &&
        r.top < window.innerHeight &&
        cs.display !== "none" &&
        cs.visibility !== "hidden" &&
        cs.visibility !== "collapse" &&
        Number(cs.opacity || "1") > 0.05;
      if (!visible) continue;
      const id = String(el.id || "");
      const className = String(el.className || "");
      const merged = `${id} ${className}`.toLowerCase();
      const isPreferred =
        id === "songsterr-cursor" ||
        merged.includes("custom-play-cursor") ||
        merged.includes("tabzer-cursor");
      const isAlphaCursor = merged.includes("at-cursor");
      const isCursorLikeShape =
        r.width <= 80 &&
        r.height <= Math.max(140, window.innerHeight * 1.05);
      const tooLarge =
        r.height > window.innerHeight * 2.2 ||
        r.width > window.innerWidth * 0.98 ||
        (r.width * r.height) > (window.innerWidth * window.innerHeight * 1.15);
      if (!isPreferred && tooLarge) continue;
      candidates.push({
        tag: el.tagName,
        id: id.slice(0, 120),
        className: className.slice(0, 140),
        isPreferred,
        isAlphaCursor,
        isCursorLikeShape,
        rect: { top: r.top, left: r.left, width: r.width, height: r.height },
      });
    }
  }

  let chosen = null;
  if (candidates.length) {
    let pool = candidates;
    const preferredPool = pool.filter((c) => c.isPreferred);
    if (preferredPool.length) {
      pool = preferredPool;
    } else {
      const alphaPool = pool.filter((c) => c.isAlphaCursor);
      if (alphaPool.length) pool = alphaPool;
      const compactPool = pool.filter((c) => c.isCursorLikeShape);
      if (compactPool.length) pool = compactPool;
    }
    if (Number.isFinite(clickX) && Number.isFinite(clickY)) {
      chosen = pool
        .map((c) => {
          const cx = c.rect.left + c.rect.width / 2;
          const cy = c.rect.top + c.rect.height / 2;
          const dist = Math.hypot(cx - Number(clickX), cy - Number(clickY));
          const penalty = c.isCursorLikeShape ? 0 : 120;
          return { c, score: dist + penalty };
        })
        .sort((a, b) => a.score - b.score)[0]?.c ?? pool[0];
    } else {
      chosen = pool
        .slice()
        .sort((a, b) => {
          const pa = (a.isPreferred ? -4 : 0) + (a.isAlphaCursor ? -2 : 0) + (a.isCursorLikeShape ? -1 : 1) + (a.rect.width * a.rect.height) / 5000;
          const pb = (b.isPreferred ? -4 : 0) + (b.isAlphaCursor ? -2 : 0) + (b.isCursorLikeShape ? -1 : 1) + (b.rect.width * b.rect.height) / 5000;
          return pa - pb;
        })[0] ?? pool[0];
    }
  }
  const cursorRect = chosen ? chosen.rect : null;

  return {
    cursorInfo: debugLast ? {
      phase: debugLast.phase ?? null,
      note: debugLast.note ?? null,
      beat: debugLast.beat ?? null,
      system: debugLast.system ?? null,
      anchor: debugLast.anchor ?? null,
      clickedSvgIdx: debugLast.svg?.clickedSvgIdx ?? null,
      clickLocalX: debugLast.click?.localX ?? null,
      clickLocalY: debugLast.click?.localY ?? null,
      band: debugLast.band ?? null,
      reason: debugLast.reason ?? null
    } : null,
    cursorRect,
    cursorElement: chosen ? { tag: chosen.tag, id: chosen.id, className: chosen.className } : null,
    cursorCandidatesCount: candidates.length,
    lastClick: debugLast,
    clickEvents,
    scrollY: window.scrollY || window.pageYOffset || 0,
    innerHeight: window.innerHeight || 0,
  };
}
""",
            {"clickX": click_x, "clickY": click_y},
        )

    def _match_system(ref_sys: dict[str, Any], refreshed: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not refreshed:
            return None
        ref_top = float(ref_sys.get("docTop") or 0)
        best = min(refreshed, key=lambda s: abs(float(s.get("docTop") or 0) - ref_top))
        if abs(float(best.get("docTop") or 0) - ref_top) > 60:
            return None
        return best

    # --- Gather initial system inventory (for docTops / structure) ---
    systems_initial = _gather_visible_systems(page)
    if not systems_initial:
        safe_print("[vertical-click-test] no tab systems found")
        return [], [], {"total": 0, "passed": 0, "failed": 0, "passRate": 0.0, "failures": []}

    total_systems = len(systems_initial)
    safe_print(f"[vertical-click-test] found {total_systems} systems")

    # --- Process each system: scroll -> re-gather fresh coords -> click ---
    _allow_click_through_loading_overlays()
    click_idx = 0
    fail_screenshot_count = 0
    MAX_FAIL_SCREENSHOTS = 30

    # DIAG: optional system range filter via URL param debugSystemRange=55-60
    _page_url = page.url or ""
    _qs = parse_qs(urlparse(_page_url).query)
    _sys_range_raw = (_qs.get("debugSystemRange") or [None])[0]
    _vertical_any_y = "1" in _qs.get("verticalClickAnyY", []) or "1" in _qs.get("verticalClickDense", [])
    _strict_center = _vertical_any_y or "1" in _qs.get("verticalClickStrictY", [])
    _gap_clicks_enabled = "0" not in _qs.get("verticalGapClicks", ["1"])

    def _is_finite_number(value: Any) -> bool:
        try:
            return math.isfinite(float(value))
        except Exception:
            return False

    _sys_range = None
    if _sys_range_raw and "-" in _sys_range_raw:
        _parts = _sys_range_raw.split("-", 1)
        try:
            _sys_range = (int(_parts[0]), int(_parts[1]))
        except ValueError:
            pass

    systems_to_test = systems_initial
    if _sys_range is None and "1" not in _qs.get("verticalClickAllSystems", []):
        sampled_indices = sorted({
            0,
            max(0, len(systems_initial) // 2),
            max(0, len(systems_initial) - 1),
        })
        systems_to_test = [systems_initial[i] for i in sampled_indices if 0 <= i < len(systems_initial)]
        safe_print(
            f"[vertical-click-test] sampling {len(systems_to_test)}/{total_systems} systems by default"
        )

    tested_gap_pairs: set[tuple[int, int]] = set()

    for sys_ref in systems_to_test:
        doc_top = float(sys_ref.get("docTop") or 0)
        sys_index = sys_ref["index"]

        if _sys_range is not None and (sys_index < _sys_range[0] or sys_index > _sys_range[1]):
            continue

        # Scroll to bring this system into view
        _scroll_to_doc_top(doc_top)
        page.wait_for_timeout(400)
        _allow_click_through_loading_overlays()

        # Re-gather systems with FRESH viewport coordinates
        refreshed = _gather_visible_systems(page)
        current = _match_system(sys_ref, refreshed)
        if not current:
            safe_print(f"  [sys={sys_index}] could not find system after scroll, skipping")
            continue

        unique_ys: list[float] = current.get("uniqueYs") or []
        note_points: list[dict[str, Any]] = current.get("notePoints") or []
        svg_index = current["svgIndex"]
        top_line = current.get("topLine")
        bottom_line = current.get("bottomLine")
        target_line_windows: list[tuple[float, float]] = []
        if _is_finite_number(top_line) and _is_finite_number(bottom_line):
            target_line_windows.append((float(top_line), float(bottom_line)))
        refreshed_idx = next(
            (i for i, sys_item in enumerate(refreshed) if sys_item.get("uid") == current.get("uid")),
            None,
        )
        if refreshed_idx is None:
            curr_doc_top = float(current.get("docTop") or 0.0)
            refreshed_idx = min(
                range(len(refreshed)),
                key=lambda i: abs(float(refreshed[i].get("docTop") or 0.0) - curr_doc_top),
            ) if refreshed else None
        if isinstance(refreshed_idx, int):
            for neighbor_idx in (refreshed_idx - 1, refreshed_idx + 1):
                if neighbor_idx < 0 or neighbor_idx >= len(refreshed):
                    continue
                neighbor = refreshed[neighbor_idx]
                n_top = neighbor.get("topLine")
                n_bottom = neighbor.get("bottomLine")
                if _is_finite_number(n_top) and _is_finite_number(n_bottom):
                    target_line_windows.append((float(n_top), float(n_bottom)))

        if not unique_ys or not note_points:
            safe_print(f"  [sys={sys_index}] no uniqueYs or notePoints, skipping")
            continue

        # Group notes by X lane (within 4px). A vertical click lane can legitimately
        # land on any note symbol in that column (e.g. chords).
        note_columns: list[dict[str, Any]] = []
        for note in note_points:
            nx = float(note.get("x") or 0)
            ny = float(note.get("y") or 0)
            ntext = str(note.get("text") or "?")
            bucket = None
            for col in note_columns:
                if abs(nx - float(col.get("x") or 0)) < 4.0:
                    bucket = col
                    break
            if bucket is None:
                bucket = {"x": nx, "ys": [], "texts": []}
                note_columns.append(bucket)
            bucket["ys"].append(ny)
            bucket["texts"].append(ntext)

        for col in note_columns:
            ys = sorted(float(v) for v in (col.get("ys") or []) if isinstance(v, (int, float)))
            dedup_ys: list[float] = []
            for yv in ys:
                if not dedup_ys or abs(yv - dedup_ys[-1]) > 0.35:
                    dedup_ys.append(yv)
            col["ys"] = dedup_ys

        # Limit notes per system to keep total manageable
        if len(note_columns) > 6:
            step = len(note_columns) / 6.0
            indices = [int(i * step) for i in range(6)]
            note_columns = [note_columns[i] for i in indices]

        probe_ys: list[float] = [float(v) for v in unique_ys]
        if _vertical_any_y and _is_finite_number(top_line) and _is_finite_number(bottom_line):
            extra_ys = [
                float(top_line) - 8.0,
                float(top_line) + 2.0,
                (float(top_line) + float(bottom_line)) / 2.0,
                float(bottom_line) - 2.0,
                float(bottom_line) + 8.0,
            ]
            merged = sorted(probe_ys + extra_ys)
            dedup_probe: list[float] = []
            for yy in merged:
                if not dedup_probe or abs(yy - dedup_probe[-1]) > 0.35:
                    dedup_probe.append(yy)
            probe_ys = dedup_probe

        step_samples = []
        for i in range(1, len(probe_ys)):
            diff = abs(float(probe_ys[i]) - float(probe_ys[i - 1]))
            if diff > 0.35:
                step_samples.append(diff)
        avg_step = (sum(step_samples) / len(step_samples)) if step_samples else 12.0
        outside_offset = max(10.0, min(26.0, avg_step * 1.35))
        outside_probe_ys: list[float] = []
        if _is_finite_number(top_line) and _is_finite_number(bottom_line):
            outside_probe_ys = [
                float(top_line) - outside_offset,
                float(bottom_line) + outside_offset,
            ]

        outside_top_note_indices: set[int] = set()
        outside_bottom_note_indices: set[int] = set()
        if outside_probe_ys and note_columns:
            # Keep top-outside probes on edge lanes, but probe below-lines on
            # every sampled note lane to catch "between systems" breaches.
            outside_top_note_indices.add(0)
            outside_top_note_indices.add(len(note_columns) - 1)
            outside_bottom_note_indices = set(range(len(note_columns)))

        planned_clicks = (
            (len(note_columns) * (len(probe_ys) + 2))
            + len(outside_top_note_indices)
            + len(outside_bottom_note_indices)
        )
        safe_print(
            f"  [sys={sys_index}] {len(note_columns)} notes x {len(probe_ys)} probeY"
            f" + outside={len(outside_top_note_indices) + len(outside_bottom_note_indices)} = {planned_clicks} clicks"
        )

        for note_col_index, note_col in enumerate(note_columns):
            nx = float(note_col.get("x") or 0)
            note_texts = [str(v) for v in (note_col.get("texts") or [])]
            note_text = note_texts[0] if note_texts else "?"
            note_orig_ys = [float(v) for v in (note_col.get("ys") or []) if isinstance(v, (int, float))]
            if not note_orig_ys:
                note_orig_ys = [0.0]

            lane_points: list[tuple[str, float, bool]] = [
                (f"probe-{idx + 1}", float(line_y), False) for idx, line_y in enumerate(probe_ys)
            ]
            if _is_finite_number(top_line) and _is_finite_number(bottom_line):
                note_center_y = (
                    sum(note_orig_ys) / len(note_orig_ys)
                    if note_orig_ys else
                    (float(top_line) + float(bottom_line)) / 2.0
                )
                note_relative_candidates = [
                    ("note-above", note_center_y - (avg_step * 0.75)),
                    ("note-below", note_center_y + (avg_step * 0.75)),
                ]
                for rel_label, rel_y in note_relative_candidates:
                    if rel_y < float(top_line) - 2.0 or rel_y > float(bottom_line) + 2.0:
                        continue
                    if any(abs(float(existing_y) - float(rel_y)) < 0.8 for _, existing_y, _ in lane_points):
                        continue
                    lane_points.append((rel_label, float(rel_y), False))
            if note_col_index in outside_top_note_indices and len(outside_probe_ys) >= 1:
                lane_points.append(("outside-top", float(outside_probe_ys[0]), True))
            if note_col_index in outside_bottom_note_indices and len(outside_probe_ys) >= 2:
                lane_points.append(("outside-bottom", float(outside_probe_ys[1]), True))

            for lane_index, (y_label, line_y, is_outside_probe) in enumerate(lane_points):
                x = round(nx, 1)
                y = round(float(line_y), 1)
                kind = "vertical-line-outside" if is_outside_probe else "vertical-line"

                try:
                    page.mouse.click(x, y)
                    if wait_ms > 0:
                        page.wait_for_timeout(wait_ms)
                    cursor_state = _read_cursor_state(click_x=x, click_y=y)

                    info = (cursor_state.get("cursorInfo") or {}) if isinstance(cursor_state, dict) else {}
                    phase = str(info.get("phase") or "").lower()
                    cursor_reason = str(info.get("reason") or "").lower()
                    beat = info.get("beat") or {}
                    has_beat = beat.get("bar") is not None and beat.get("beat") is not None
                    observed_svg = info.get("clickedSvgIdx")
                    expected_svg_list = [svg_index]
                    same_svg = observed_svg in expected_svg_list if observed_svg is not None else False
                    near_svg = False
                    if not same_svg and observed_svg is not None:
                        near_svg = min(abs(int(observed_svg) - int(v)) for v in expected_svg_list) <= 1

                    anchor = info.get("anchor") or {}
                    click_local_x = info.get("clickLocalX")
                    click_local_y = info.get("clickLocalY")
                    final_cursor_x = anchor.get("finalCursorX") if isinstance(anchor, dict) else None
                    anchor_x = anchor.get("x") if isinstance(anchor, dict) else None
                    x_candidates: list[float] = []
                    if isinstance(final_cursor_x, (int, float)):
                        if isinstance(click_local_x, (int, float)):
                            x_candidates.append(abs(float(final_cursor_x) - float(click_local_x)))
                        x_candidates.append(abs(float(final_cursor_x) - float(x)))
                    if isinstance(anchor_x, (int, float)):
                        # Depending on debug path, anchor.x may be local-to-SVG or viewport X.
                        # Accept the closest interpretation so we measure real landing drift.
                        if isinstance(click_local_x, (int, float)):
                            x_candidates.append(abs(float(anchor_x) - float(click_local_x)))
                        x_candidates.append(abs(float(anchor_x) - float(x)))
                    x_error = min(x_candidates) if x_candidates else None

                    band_info = info.get("band") if isinstance(info, dict) else None
                    band_top = band_info.get("top") if isinstance(band_info, dict) else None
                    band_bottom = band_info.get("bottom") if isinstance(band_info, dict) else None
                    snapped_y = band_info.get("snappedY") if isinstance(band_info, dict) else None
                    cursor_outside_band = None
                    if (
                        _is_finite_number(snapped_y)
                        and _is_finite_number(band_top)
                        and _is_finite_number(band_bottom)
                    ):
                        pad = 2.0
                        cursor_outside_band = (
                            float(snapped_y) < float(band_top) - pad
                            or float(snapped_y) > float(band_bottom) + pad
                        )

                    scroll_y = cursor_state.get("scrollY") if isinstance(cursor_state, dict) else None
                    inner_h = cursor_state.get("innerHeight") if isinstance(cursor_state, dict) else None
                    band_top_view = band_top
                    band_bottom_view = band_bottom
                    local_to_view_offset = None
                    if _is_finite_number(y) and _is_finite_number(click_local_y):
                        local_to_view_offset = float(y) - float(click_local_y)
                    if (
                        local_to_view_offset is None
                        and _is_finite_number(scroll_y)
                        and _is_finite_number(inner_h)
                        and _is_finite_number(band_top)
                        and _is_finite_number(band_bottom)
                        and (
                            float(band_top) > float(inner_h) * 1.5
                            or float(band_bottom) > float(inner_h) * 1.5
                        )
                    ):
                        band_top_view = float(band_top) - float(scroll_y)
                        band_bottom_view = float(band_bottom) - float(scroll_y)
                    elif (
                        local_to_view_offset is not None
                        and _is_finite_number(band_top)
                        and _is_finite_number(band_bottom)
                    ):
                        band_top_view = float(band_top) + float(local_to_view_offset)
                        band_bottom_view = float(band_bottom) + float(local_to_view_offset)

                    cursor_visual_outside_band = None
                    cursor_visual_outside_target_lines = None
                    final_cursor_y = anchor.get("finalCursorY") if isinstance(anchor, dict) else None
                    cursor_y_view = None
                    if _is_finite_number(final_cursor_y) and _is_finite_number(local_to_view_offset):
                        cursor_y_view = float(final_cursor_y) + float(local_to_view_offset)
                    elif _is_finite_number(snapped_y) and _is_finite_number(local_to_view_offset):
                        cursor_y_view = float(snapped_y) + float(local_to_view_offset)
                    if _is_finite_number(cursor_y_view):
                        pad = 3.0
                        if _is_finite_number(band_top_view) and _is_finite_number(band_bottom_view):
                            cursor_visual_outside_band = (
                                float(cursor_y_view) < float(band_top_view) - pad
                                or float(cursor_y_view) > float(band_bottom_view) + pad
                            )
                        if target_line_windows:
                            in_any_window = any(
                                (float(win_top) - pad) <= float(cursor_y_view) <= (float(win_bottom) + pad)
                                for (win_top, win_bottom) in target_line_windows
                            )
                            cursor_visual_outside_target_lines = not in_any_window

                    y_center_error = None
                    if isinstance(final_cursor_y, (int, float)):
                        expected_y_candidates: list[float] = [float(v) for v in note_orig_ys]
                        if isinstance(band_top, (int, float)) and isinstance(top_line, (int, float)):
                            # Convert note center from viewport space to the same space as finalCursorY.
                            converted = [float(v) + (float(band_top) - float(top_line)) for v in note_orig_ys]
                            expected_y_candidates.extend(converted)
                        click_events = cursor_state.get("clickEvents") if isinstance(cursor_state, dict) else None
                        if isinstance(click_events, list):
                            for ev in reversed(click_events):
                                if not isinstance(ev, dict):
                                    continue
                                if str(ev.get("stage") or "") != "click.pick.lane":
                                    continue
                                details = ev.get("details") if isinstance(ev.get("details"), dict) else {}
                                pick_y = details.get("pickY")
                                if isinstance(pick_y, (int, float)):
                                    expected_y_candidates.append(float(pick_y))
                                    break
                        y_center_error = min(abs(float(final_cursor_y) - v) for v in expected_y_candidates)

                    passed = True
                    reasons: list[str] = []
                    if is_outside_probe:
                        if phase not in {"done", "final", "abort"}:
                            reasons.append("phase-unexpected")
                            passed = False
                        if has_beat and not same_svg and not near_svg:
                            reasons.append("wrong-system")
                            passed = False
                    else:
                        if phase in {"abort"} and cursor_reason == "inter-band-gap":
                            # Strict gap guard is expected to abort in some vertical probes
                            # where the sampled Y falls between detected staff bands.
                            pass
                        elif phase not in {"done", "final"}:
                            reasons.append("phase-not-done")
                            passed = False
                        if phase in {"abort"} and cursor_reason == "inter-band-gap":
                            pass
                        elif not has_beat:
                            reasons.append("missing-beat")
                            passed = False
                        if not same_svg and not near_svg:
                            reasons.append("wrong-system")
                            passed = False

                    if cursor_outside_band is True:
                        reasons.append("cursor-outside-lines")
                        passed = False
                    if cursor_visual_outside_target_lines is True and cursor_outside_band is not False:
                        reasons.append("cursor-visual-outside-target-lines")
                        passed = False

                    if (not is_outside_probe) and _strict_center:
                        strict_x_tol = 8.0
                        # Y can drift a few extra pixels from glyph baseline/center
                        # depending on renderer sub-pixel layout and stack compression.
                        strict_y_tol = 11.0
                        if x_error is None or x_error > strict_x_tol:
                            reasons.append("off-note-center-x")
                            passed = False
                        if y_center_error is None or y_center_error > strict_y_tol:
                            reasons.append("off-note-center-y")
                            passed = False

                    result = {
                        "clickIndex": click_idx,
                        "kind": kind,
                        "systemIndex": sys_index,
                        "svgIndex": svg_index,
                        "expectedSvgIndices": expected_svg_list,
                        "clickX": x,
                        "clickY": y,
                        "xLabel": f"note-{note_text}",
                        "yLabel": y_label,
                        "noteText": note_text,
                        "lineIndex": lane_index if not is_outside_probe else None,
                        "isOutsideProbe": is_outside_probe,
                        "noteOriginalY": round(note_orig_ys[0], 1),
                        "noteOriginalYs": [round(v, 1) for v in note_orig_ys],
                        "targetTopLine": top_line,
                        "targetBottomLine": bottom_line,
                        "cursorState": cursor_state.get("cursorInfo"),
                        "cursorRect": cursor_state.get("cursorRect"),
                        "cursorElement": cursor_state.get("cursorElement"),
                        "clickEvents": cursor_state.get("clickEvents"),
                        "assessment": {
                            "passed": passed,
                            "reasons": reasons,
                            "phase": phase,
                            "cursorReason": cursor_reason or None,
                            "hasBeat": has_beat,
                            "observedSvgIndex": observed_svg,
                            "expectedSvgIndices": expected_svg_list,
                            "xError": x_error,
                            "yCenterError": y_center_error,
                            "snappedY": snapped_y,
                            "bandTop": band_top,
                            "bandBottom": band_bottom,
                            "bandTopViewport": band_top_view,
                            "bandBottomViewport": band_bottom_view,
                            "cursorOutsideLines": bool(cursor_outside_band) if cursor_outside_band is not None else None,
                            "cursorVisualOutsideLines": bool(cursor_visual_outside_band) if cursor_visual_outside_band is not None else None,
                            "cursorVisualOutsideTargetLines": (
                                bool(cursor_visual_outside_target_lines)
                                if cursor_visual_outside_target_lines is not None
                                else None
                            ),
                        },
                    }
                    results.append(result)

                    # Only screenshot failures
                    if not passed and fail_screenshot_count < MAX_FAIL_SCREENSHOTS:
                        shot_path = output_dir / f"vclick-fail-{stamp}-{click_idx:03d}.png"
                        page.screenshot(path=str(shot_path), type="png")
                        shots.append(str(shot_path))
                        fail_screenshot_count += 1

                    status = "PASS" if passed else f"FAIL({','.join(reasons)})"
                    safe_print(
                        f"    [{click_idx + 1}] note={note_text} {y_label} "
                        f"({round(x)},{round(y)}) -> {status}"
                    )
                    # Print brief diagnostic for first few failures
                    if not passed and fail_screenshot_count <= 3:
                        last_click = cursor_state.get("lastClick") or {}
                        safe_print(
                            f"      DIAG: phase={last_click.get('phase')} reason={last_click.get('reason')}"
                        )
                    click_idx += 1

                except Exception as exc:
                    results.append({
                        "clickIndex": click_idx,
                        "kind": kind,
                        "clickX": x,
                        "clickY": y,
                        "error": str(exc),
                        "assessment": {"passed": False, "reasons": ["exception"]},
                    })
                    click_idx += 1

        if _gap_clicks_enabled:
            next_ref = next((item for item in systems_to_test if int(item.get("index", -1)) == int(sys_index) + 1), None)
            if next_ref is not None:
                next_sys_index = int(next_ref.get("index", int(sys_index) + 1))
                if _sys_range is not None and (next_sys_index < _sys_range[0] or next_sys_index > _sys_range[1]):
                    continue
                gap_pair = (int(sys_index), int(next_sys_index))
                if gap_pair in tested_gap_pairs:
                    continue
                tested_gap_pairs.add(gap_pair)

                curr_bottom_doc = float(sys_ref.get("docBottom") or doc_top)
                next_top_doc = float(next_ref.get("docTop") or curr_bottom_doc)
                gap_doc_mid = (curr_bottom_doc + next_top_doc) / 2.0
                _scroll_to_doc_top(gap_doc_mid)
                page.wait_for_timeout(380)
                _allow_click_through_loading_overlays()
                refreshed_gap = _gather_visible_systems(page)
                current_gap = _match_system(sys_ref, refreshed_gap)
                next_gap = _match_system(next_ref, refreshed_gap)
                if not current_gap or not next_gap:
                    safe_print(f"  [gap {sys_index}->{next_sys_index}] could not resolve systems after scroll")
                    continue

                current_bottom = float(current_gap.get("bottomLine") or 0)
                next_top = float(next_gap.get("topLine") or 0)
                gap_span = next_top - current_bottom
                if gap_span < 8.0:
                    continue

                curr_rect = current_gap.get("rect") or {}
                next_rect = next_gap.get("rect") or {}
                curr_left = float(curr_rect.get("left") or 0)
                curr_right = float(curr_rect.get("right") or 0)
                next_left = float(next_rect.get("left") or 0)
                next_right = float(next_rect.get("right") or 0)
                overlap_left = max(curr_left, next_left)
                overlap_right = min(curr_right, next_right)
                if overlap_right > overlap_left:
                    span_x = overlap_right - overlap_left
                    gap_x_candidates = [
                        overlap_left + span_x * 0.2,
                        overlap_left + span_x * 0.5,
                        overlap_left + span_x * 0.8,
                    ]
                else:
                    gap_x_candidates = [(curr_left + curr_right + next_left + next_right) / 4.0]

                gap_y_candidates = [
                    current_bottom + gap_span * 0.35,
                    current_bottom + gap_span * 0.5,
                    current_bottom + gap_span * 0.65,
                ]

                for x_idx, gap_x in enumerate(gap_x_candidates):
                    for y_idx, gap_y in enumerate(gap_y_candidates):
                        try:
                            page.mouse.click(round(gap_x, 1), round(gap_y, 1))
                            if wait_ms > 0:
                                page.wait_for_timeout(wait_ms)
                            cursor_state = _read_cursor_state(click_x=round(gap_x, 1), click_y=round(gap_y, 1))
                            info = (cursor_state.get("cursorInfo") or {}) if isinstance(cursor_state, dict) else {}
                            phase = str(info.get("phase") or "").lower()
                            beat = info.get("beat") or {}
                            has_beat = beat.get("bar") is not None and beat.get("beat") is not None
                            observed_svg = info.get("clickedSvgIdx")
                            expected_svg_list = [int(current_gap["svgIndex"]), int(next_gap["svgIndex"])]
                            same_or_expected = observed_svg in expected_svg_list if observed_svg is not None else False
                            near_expected = False
                            if not same_or_expected and observed_svg is not None:
                                near_expected = min(abs(int(observed_svg) - int(v)) for v in expected_svg_list) <= 1

                            band_info = info.get("band") if isinstance(info, dict) else None
                            band_top = band_info.get("top") if isinstance(band_info, dict) else None
                            band_bottom = band_info.get("bottom") if isinstance(band_info, dict) else None
                            snapped_y = band_info.get("snappedY") if isinstance(band_info, dict) else None
                            anchor = info.get("anchor") if isinstance(info, dict) else None
                            click_local_y = info.get("clickLocalY")
                            final_cursor_y = anchor.get("finalCursorY") if isinstance(anchor, dict) else None
                            local_to_view_offset = None
                            if _is_finite_number(gap_y) and _is_finite_number(click_local_y):
                                local_to_view_offset = float(gap_y) - float(click_local_y)
                            cursor_y_view = None
                            if _is_finite_number(final_cursor_y) and _is_finite_number(local_to_view_offset):
                                cursor_y_view = float(final_cursor_y) + float(local_to_view_offset)
                            elif _is_finite_number(snapped_y) and _is_finite_number(local_to_view_offset):
                                cursor_y_view = float(snapped_y) + float(local_to_view_offset)

                            passed = True
                            reasons: list[str] = []
                            if phase not in {"done", "final", "abort"}:
                                reasons.append("phase-unexpected")
                                passed = False
                            if has_beat and not same_or_expected and not near_expected:
                                reasons.append("gap-wrong-system-jump")
                                passed = False
                            if has_beat and _is_finite_number(cursor_y_view):
                                if (not same_or_expected) and near_expected:
                                    # Some compressed layouts expose an interleaved staff
                                    # between the two tested systems. When landing stays on
                                    # an adjacent SVG index, treat it as acceptable.
                                    pass
                                else:
                                    pad = 3.0
                                    line_windows: list[tuple[float, float]] = []
                                    if _is_finite_number(current_gap.get("topLine")) and _is_finite_number(current_gap.get("bottomLine")):
                                        line_windows.append((float(current_gap["topLine"]), float(current_gap["bottomLine"])))
                                    if _is_finite_number(next_gap.get("topLine")) and _is_finite_number(next_gap.get("bottomLine")):
                                        line_windows.append((float(next_gap["topLine"]), float(next_gap["bottomLine"])))
                                    if isinstance(observed_svg, int):
                                        for sys_item in refreshed_gap:
                                            try:
                                                cand_svg = int(sys_item.get("svgIndex"))
                                            except Exception:
                                                continue
                                            if cand_svg != int(observed_svg):
                                                continue
                                            cand_top = sys_item.get("topLine")
                                            cand_bottom = sys_item.get("bottomLine")
                                            if _is_finite_number(cand_top) and _is_finite_number(cand_bottom):
                                                line_windows.append((float(cand_top), float(cand_bottom)))
                                    in_any_window = any(
                                        (top - pad) <= float(cursor_y_view) <= (bottom + pad)
                                        for (top, bottom) in line_windows
                                    )
                                    if not in_any_window:
                                        reasons.append("cursor-between-systems")
                                        passed = False
                            elif has_beat and not _is_finite_number(cursor_y_view):
                                reasons.append("cursor-y-unavailable")
                                passed = False

                            result = {
                                "clickIndex": click_idx,
                                "kind": "inter-system-gap",
                                "systemIndex": int(sys_index),
                                "svgIndex": int(current_gap["svgIndex"]),
                                "expectedSvgIndices": expected_svg_list,
                                "clickX": round(gap_x, 1),
                                "clickY": round(gap_y, 1),
                                "xLabel": f"gap-x-{x_idx + 1}",
                                "yLabel": f"between-systems-{sys_index}-{next_sys_index}-y-{y_idx + 1}",
                                "lineIndex": None,
                                "isOutsideProbe": True,
                                "targetTopLine": current_bottom,
                                "targetBottomLine": next_top,
                                "cursorState": cursor_state.get("cursorInfo"),
                                "cursorRect": cursor_state.get("cursorRect"),
                                "cursorElement": cursor_state.get("cursorElement"),
                                "clickEvents": cursor_state.get("clickEvents"),
                                "assessment": {
                                    "passed": passed,
                                    "reasons": reasons,
                                    "phase": phase,
                                    "hasBeat": has_beat,
                                    "observedSvgIndex": observed_svg,
                                    "expectedSvgIndices": expected_svg_list,
                                    "xError": None,
                                    "yCenterError": None,
                                    "snappedY": snapped_y,
                                    "bandTop": band_top,
                                    "bandBottom": band_bottom,
                                    "bandTopViewport": None,
                                    "bandBottomViewport": None,
                                    "cursorOutsideLines": None,
                                    "cursorVisualOutsideLines": None,
                                    "cursorYViewport": cursor_y_view,
                                    "gapSpan": round(gap_span, 2),
                                },
                            }
                            results.append(result)

                            if not passed and fail_screenshot_count < MAX_FAIL_SCREENSHOTS:
                                shot_path = output_dir / f"vclick-fail-{stamp}-{click_idx:03d}.png"
                                page.screenshot(path=str(shot_path), type="png")
                                shots.append(str(shot_path))
                                fail_screenshot_count += 1

                            status = "PASS" if passed else f"FAIL({','.join(reasons)})"
                            safe_print(
                                f"    [{click_idx + 1}] gap {sys_index}->{next_sys_index} x{x_idx + 1} y{y_idx + 1} "
                                f"({round(gap_x)},{round(gap_y)}) -> {status}"
                            )
                            click_idx += 1
                        except Exception as exc:
                            results.append(
                                {
                                    "clickIndex": click_idx,
                                    "kind": "inter-system-gap",
                                    "systemIndex": int(sys_index),
                                    "clickX": round(gap_x, 1),
                                    "clickY": round(gap_y, 1),
                                    "error": str(exc),
                                    "assessment": {"passed": False, "reasons": ["exception"]},
                                }
                            )
                            click_idx += 1

    summary = summarize_click_results(results)
    summary["totalSystems"] = total_systems

    safe_print(
        f"\n[vertical-click-test] RESULT: {summary['passed']}/{summary['total']} passed "
        f"({summary['passRate']}%)"
    )
    if summary["failures"]:
        safe_print(f"[vertical-click-test] {len(summary['failures'])} failures:")
        for f in summary["failures"][:30]:
            safe_print(
                f"  fail#{f.get('clickIndex','?')} sys={f.get('systemIndex','?')} "
                f"reasons={f.get('reasons')}"
            )

    return shots, results, summary


def _click_first_visible(page: Any, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 6)
        except Exception:
            continue
        for idx in range(count):
            try:
                node = locator.nth(idx)
                if not node.is_visible():
                    continue
                node.click(timeout=2500)
                return True
            except Exception:
                continue
    return False


def _fill_first_visible(page: Any, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 6)
        except Exception:
            continue
        for idx in range(count):
            try:
                node = locator.nth(idx)
                if not node.is_visible():
                    continue
                node.fill(value, timeout=2500)
                return True
            except Exception:
                continue
    return False


def _is_page_dark(page: Any) -> bool:
    try:
        return bool(
            page.evaluate(
                """
() => {
  const html = document.documentElement;
  const body = document.body;
  const attrTheme = (html?.getAttribute("data-theme") || body?.getAttribute("data-theme") || "").toLowerCase();
  const htmlCls = (html?.className || "").toLowerCase();
  const bodyCls = (body?.className || "").toLowerCase();
  if (attrTheme.includes("dark")) return true;
  if (htmlCls.includes("dark") || bodyCls.includes("dark")) return true;

  const pick = () => {
    const bgBody = body ? getComputedStyle(body).backgroundColor : "";
    const bgHtml = html ? getComputedStyle(html).backgroundColor : "";
    return bgBody || bgHtml || "";
  };
  const bg = pick();
  const m = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
  if (!m) return false;
  const r = Number(m[1]);
  const g = Number(m[2]);
  const b = Number(m[3]);
  return (r + g + b) < 390;
}
"""
            )
        )
    except Exception:
        return False


def _songsterr_urls_match(current_url: str, target_url: str) -> bool:
    cur = (current_url or "").strip().lower()
    tgt = (target_url or "").strip().lower()
    if not cur or not tgt:
        return False
    try:
        # Compare by canonical Songsterr path; ignore query/hash noise.
        cur_path = cur.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
        tgt_path = tgt.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
        return cur_path == tgt_path
    except Exception:
        return cur == tgt


def _app_urls_match(current_url: str, target_url: str) -> bool:
    try:
        cur = urlparse((current_url or "").strip())
        tgt = urlparse((target_url or "").strip())
        if not cur.path or not tgt.path:
            return False
        if cur.path.rstrip("/") != tgt.path.rstrip("/"):
            return False
        cur_q = parse_qs(cur.query or "")
        tgt_q = parse_qs(tgt.query or "")
        cur_id = (cur_q.get("id") or [""])[0].strip().lower()
        tgt_id = (tgt_q.get("id") or [""])[0].strip().lower()
        if tgt_id:
            return cur_id == tgt_id
        return True
    except Exception:
        return (current_url or "").strip() == (target_url or "").strip()


def _app_url_id(raw_url: str) -> str:
    try:
        parsed = urlparse((raw_url or "").strip())
        values = parse_qs(parsed.query or "").get("id") or [""]
        return (values[0] or "").strip().lower()
    except Exception:
        return ""


def ensure_target_page_url(
    page: Any,
    target_url: str,
    matcher: Any,
    attempts: int = 4,
    wait_ms: int = 1200,
) -> bool:
    for _ in range(max(1, attempts)):
        current = (page.url or "").strip()
        if matcher(current, target_url):
            return True
        try:
            page.goto(target_url, wait_until="domcontentloaded")
            if wait_ms > 0:
                page.wait_for_timeout(min(wait_ms, 2500))
        except Exception:
            if wait_ms > 0:
                page.wait_for_timeout(min(wait_ms, 2500))
    return matcher((page.url or "").strip(), target_url)


def wait_for_app_full_ready(page: Any, timeout_ms: int = 14000) -> bool:
    try:
        page.wait_for_function(
            """
() => {
  const shell = document.querySelector(".play-shell");
  const viewport = document.querySelector(".sheet-wrap .viewport");
  if (!shell || !viewport) return false;
  if (shell.classList.contains("is-loading")) return false;
  if (!shell.classList.contains("is-ready")) return false;
  if (document.body?.getAttribute("data-tab-loading") === "1") return false;

  const styledSvgs = Array.from(viewport.querySelectorAll("svg[data-tabzer-styled='1']"));
  if (!styledSvgs.length) return false;

  const hasVisibleStyledSvg = styledSvgs.some((svg) => {
    const r = svg.getBoundingClientRect();
    return r.width > 24 && r.height > 24 && r.bottom > 0 && r.right > 0 &&
      r.top < window.innerHeight && r.left < window.innerWidth;
  });
  if (!hasVisibleStyledSvg) return false;

  const lineCount = viewport.querySelectorAll(".tab-string-line").length;
  return lineCount >= 6;
}
""",
            timeout=max(1000, int(timeout_ms)),
        )
        page.wait_for_timeout(120)
        return True
    except Exception:
        return False


def prepare_songsterr_dark_reference(page: Any, wait_ms: int, target_url: str) -> dict[str, Any]:
    email = (
        os.getenv("SONGSTERR_EMAIL", "").strip()
        or os.getenv("UG_EMAIL", "").strip()
        or os.getenv("USER_EMAIL", "").strip()
    )
    password = (
        os.getenv("SONGSTERR_PASSWORD", "").strip()
        or os.getenv("UG_PASSWORD", "").strip()
        or os.getenv("USER_PASSWORD", "").strip()
    )
    cred_source = "songsterr-env"
    if not os.getenv("SONGSTERR_EMAIL", "").strip() and os.getenv("UG_EMAIL", "").strip():
        cred_source = "ug-env"
    if not email or not password:
        cred_source = "none"
    result: dict[str, Any] = {
        "provider": "songsterr",
        "targetUrl": target_url,
        "attemptedLogin": False,
        "loginSucceeded": False,
        "usedCredentialsFromEnv": bool(email and password),
        "credentialSource": cred_source,
        "darkMode": False,
        "notes": [],
    }

    # Ask browser for dark scheme first (many sites respect prefers-color-scheme).
    try:
        page.emulate_media(color_scheme="dark")
    except Exception:
        result["notes"].append("emulate-media-dark-failed")

    # Dismiss common consent banners/popups.
    _click_first_visible(
        page,
        [
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('Got it')",
            "[aria-label*='accept' i]",
        ],
    )

    if email and password:
        result["attemptedLogin"] = True
        opened_login = _click_first_visible(
            page,
            [
                "a:has-text('Sign in')",
                "button:has-text('Sign in')",
                "a:has-text('Log in')",
                "button:has-text('Log in')",
                "[href*='signin' i]",
                "[href*='login' i]",
                "[data-testid*='login' i]",
            ],
        )
        if opened_login:
            page.wait_for_timeout(900)

        filled_email = _fill_first_visible(
            page,
            [
                "input[type='email']",
                "input[name*='email' i]",
                "input[autocomplete='email']",
            ],
            email,
        )
        filled_password = _fill_first_visible(
            page,
            [
                "input[type='password']",
                "input[name*='password' i]",
                "input[autocomplete='current-password']",
            ],
            password,
        )
        if filled_email and filled_password:
            _click_first_visible(
                page,
                [
                    "button[type='submit']",
                    "button:has-text('Sign in')",
                    "button:has-text('Log in')",
                    "button:has-text('Continue')",
                ],
            )
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                page.wait_for_timeout(2500)

        result["loginSucceeded"] = bool(
            page.locator("[href*='logout' i], [data-testid*='profile' i], [aria-label*='profile' i]").count()
        )
        if not result["loginSucceeded"]:
            result["notes"].append("login-not-confirmed")
    else:
        result["notes"].append("missing-songsterr-env-credentials")

    # Try UI toggles for dark mode first.
    _click_first_visible(
        page,
        [
            "button[aria-label*='dark' i]",
            "button[aria-label*='light' i]",
            "button[aria-label*='theme' i]",
            "button[aria-label*='appearance' i]",
            "[data-testid*='theme' i]",
        ],
    )
    _click_first_visible(
        page,
        [
            "button:has-text('Dark')",
            "[role='menuitem']:has-text('Dark')",
            "[data-theme-value='dark']",
            "[data-testid*='dark' i]",
        ],
    )
    page.wait_for_timeout(600)

    if not _is_page_dark(page):
        # Fallback to persisted theme keys used by common frontends.
        try:
            page.evaluate(
                """
() => {
  const keys = [
    "theme",
    "color-theme",
    "colorTheme",
    "appearance",
    "mui-mode",
    "chakra-ui-color-mode",
    "next-theme"
  ];
  for (const k of keys) {
    try { localStorage.setItem(k, "dark"); } catch {}
  }
  try { sessionStorage.setItem("theme", "dark"); } catch {}
  try { sessionStorage.setItem("color-theme", "dark"); } catch {}
  document.documentElement.setAttribute("data-theme", "dark");
  document.documentElement.setAttribute("color-scheme", "dark");
  document.documentElement.classList.add("dark");
  if (document.body) document.body.classList.add("dark");
}
"""
            )
            page.reload(wait_until="domcontentloaded")
            if wait_ms > 0:
                page.wait_for_timeout(min(wait_ms, 3500))
        except Exception:
            pass

    result["darkMode"] = _is_page_dark(page)
    if not result["darkMode"]:
        result["notes"].append("dark-mode-not-confirmed")

    # Ensure final capture is always on the exact target song URL.
    try:
        current = (page.url or "").strip()
        if not _songsterr_urls_match(current, target_url):
            page.goto(target_url, wait_until="domcontentloaded")
            if wait_ms > 0:
                page.wait_for_timeout(min(wait_ms, 3500))
            # Keep dark preference after redirect/navigation.
            if not _is_page_dark(page):
                try:
                    page.emulate_media(color_scheme="dark")
                except Exception:
                    pass
            result["notes"].append("forced-target-url-navigation")
    except Exception:
        result["notes"].append("forced-target-url-failed")
    result["finalUrl"] = (page.url or "").strip()
    result["matchesTargetUrl"] = _songsterr_urls_match(result.get("finalUrl", ""), target_url)
    return result


def build_image_inputs(
    image_paths: list[str],
    max_images: int = 10,
    max_total_bytes: int = 20 * 1024 * 1024,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    inputs: list[dict[str, str]] = []
    sent_manifest: list[dict[str, Any]] = []
    used = 0
    for image_path in image_paths[:max_images]:
        path = Path(image_path)
        if not path.exists():
            continue
        data = path.read_bytes()
        if not data:
            continue
        # Keep payload within safe bounds for API requests.
        if used + len(data) > max_total_bytes:
            break
        used += len(data)
        b64 = base64.b64encode(data).decode("ascii")
        resolved_path = path.resolve()
        try:
            display_path = str(resolved_path.relative_to(Path.cwd().resolve()))
        except Exception:
            display_path = str(resolved_path)
        suffix = path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        inputs.append({
            "type": "input_image",
            "image_url": f"data:{mime};base64,{b64}",
        })
        sent_manifest.append({
            "path": display_path,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return inputs, sent_manifest


def ask_openai(
    client: OpenAI,
    model: str,
    compact_snapshot: dict[str, Any],
    tab_screenshots: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    system = (
        "You are a pragmatic frontend debugging agent for SVG tablature rendering.\n"
        "Analyze the debug snapshot and output:\n"
        "1) likely root cause,\n"
        "2) evidence from fields,\n"
        "3) concrete patch suggestions in priority order,\n"
        "4) a minimal JS snippet to validate fix in browser console.\n"
        "Keep it concise and technical."
    )
    user = (
        "Debug snapshot JSON:\n"
        f"{json.dumps(compact_snapshot, ensure_ascii=False)}"
    )

    user_content: list[dict[str, str]] = [{"type": "input_text", "text": user}]
    image_inputs, sent_manifest = build_image_inputs(tab_screenshots or [])
    user_content.extend(image_inputs)

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": user_content},
        ],
    )
    return response.output_text.strip(), sent_manifest


def _aggregate_iteration_click_summaries(
    iteration_reports: list[dict[str, Any]],
    *,
    require_all_iterations_pass: bool,
) -> dict[str, Any] | None:
    summaries = [
        item.get("click_summary")
        for item in iteration_reports
        if isinstance(item.get("click_summary"), dict) and item.get("click_summary")
    ]
    if not summaries:
        return None

    total_runs = len(summaries)
    pass_indices = [
        idx + 1 for idx, summary in enumerate(summaries)
        if str(summary.get("verdict") or "").upper() == "PASS"
    ]
    fail_indices = [idx + 1 for idx in range(total_runs) if (idx + 1) not in pass_indices]
    passed_runs = len(pass_indices)
    failed_runs = len(fail_indices)

    first = dict(summaries[0])
    aggregate = dict(first)

    numeric_max_fields = [
        "failed",
        "freezeCount",
        "hiddenCount",
        "backwardJumpCount",
        "frameGapCount",
        "audioStallCount",
        "longTaskCount",
        "worstLongTaskMs",
        "worstFrameGapMs",
        "sameSystemPairCount",
        "stationaryPairCount",
        "stationaryPairRatePct",
        "movingVelocitySampleCount",
        "velocityMedianPxPerMs",
        "velocityP90PxPerMs",
        "velocityJitterSampleCount",
        "velocityJitterRatioMedianPct",
        "velocityJitterRatioP90Pct",
        "velocityJitterSpikeCount",
        "playbackSmoothnessSampleCount",
        "playbackSmoothnessEventCount",
        "displayHoldEventCount",
        "targetJumpEventCount",
        "systemsTraversed",
        "probeElapsedMs",
        "rafCount",
    ]
    for field in numeric_max_fields:
        values = [summary.get(field) for summary in summaries if isinstance(summary.get(field), (int, float))]
        if values:
            aggregate[field] = max(values)

    aggregate["totalRuns"] = total_runs
    aggregate["passedRuns"] = passed_runs
    aggregate["failedRuns"] = failed_runs
    aggregate["passIndices"] = pass_indices
    aggregate["failIndices"] = fail_indices
    aggregate["allIterationsRequired"] = bool(require_all_iterations_pass)
    aggregate["passRate"] = round((passed_runs / total_runs) * 100.0, 1)
    aggregate["iterationVerdicts"] = [
        str(summary.get("verdict") or "?").upper() for summary in summaries
    ]

    aggregate["velocityJitterSpikeDetails"] = []
    for idx, summary in enumerate(summaries, start=1):
        details = list(summary.get("velocityJitterSpikeDetails") or [])
        for detail in details[:6]:
            aggregate["velocityJitterSpikeDetails"].append({
                "iteration": idx,
                **detail,
            })
    aggregate["velocityJitterSpikeDetails"] = aggregate["velocityJitterSpikeDetails"][:20]

    aggregate["recentSmoothnessEvents"] = []
    for idx, summary in enumerate(summaries, start=1):
        events = list(summary.get("recentSmoothnessEvents") or [])
        for event in events[-4:]:
            aggregate["recentSmoothnessEvents"].append({
                "iteration": idx,
                **event,
            })
    aggregate["recentSmoothnessEvents"] = aggregate["recentSmoothnessEvents"][-20:]

    if require_all_iterations_pass:
        aggregate["verdict"] = "PASS" if failed_runs == 0 else "FAIL"
    else:
        aggregate["verdict"] = "PASS" if passed_runs > 0 else "FAIL"

    return aggregate


def _build_iteration_aggregate_diagnosis(
    task: TaskSpec | None,
    iteration_reports: list[dict[str, Any]],
    aggregate_click_summary: dict[str, Any] | None,
) -> str:
    if not task or len(iteration_reports) <= 1 or not aggregate_click_summary:
        return ""

    lines = [
        f"[iteration-aggregate] taskRuns={aggregate_click_summary.get('totalRuns', 0)}",
        f"[iteration-aggregate] verdict={aggregate_click_summary.get('verdict', '?')} "
        f"passedRuns={aggregate_click_summary.get('passedRuns', 0)}/"
        f"{aggregate_click_summary.get('totalRuns', 0)} "
        f"requireAll={bool(aggregate_click_summary.get('allIterationsRequired'))}",
    ]
    fail_indices = aggregate_click_summary.get("failIndices") or []
    if fail_indices:
        lines.append(f"[iteration-aggregate] failedIterations={fail_indices}")
    lines.append(
        "[iteration-aggregate] worst freeze={freeze} hidden={hidden} backward={backward} "
        "frameGaps={frame_gaps} audioStalls={audio_stalls} jitterP90={jitter_p90}% "
        "jitterSpikes={jitter_spikes} displayHolds={display_holds} targetJumps={target_jumps}".format(
            freeze=aggregate_click_summary.get("freezeCount", 0),
            hidden=aggregate_click_summary.get("hiddenCount", 0),
            backward=aggregate_click_summary.get("backwardJumpCount", 0),
            frame_gaps=aggregate_click_summary.get("frameGapCount", 0),
            audio_stalls=aggregate_click_summary.get("audioStallCount", 0),
            jitter_p90=aggregate_click_summary.get("velocityJitterRatioP90Pct", 0),
            jitter_spikes=aggregate_click_summary.get("velocityJitterSpikeCount", 0),
            display_holds=aggregate_click_summary.get("displayHoldEventCount", 0),
            target_jumps=aggregate_click_summary.get("targetJumpEventCount", 0),
        )
    )
    return "\n".join(lines)


def _build_task_system_prompt(task: "TaskSpec") -> str:
    """Build an LLM system prompt tailored to the task type."""
    task_id_lower = (task.id or "").lower()
    task_goal_lower = (task.goal or "").lower()

    if "cursor" in task_id_lower or "click" in task_id_lower or "cursor" in task_goal_lower or "click" in task_goal_lower:
        return (
            "You are a strict QA agent for interactive guitar tablature.\n"
            "Analyze the click test results and screenshots to evaluate cursor/click accuracy.\n"
            "For each click test, check:\n"
            "1) Did the cursor move to the correct beat/note position?\n"
            "2) Was the click within the valid staff area detected correctly?\n"
            "3) Did clicks near system boundaries behave correctly (no jumps to wrong systems)?\n"
            "4) Is cursor placement consistent across all systems (first, middle, last)?\n"
            "Return concise actionable output with:\n"
            "1) click accuracy issues found (per-system),\n"
            "2) likely coordinate mapping / hit-test causes,\n"
            "3) exact code-level fixes (functions, constants, coordinate transforms),\n"
            "4) acceptance checklist for cursor click accuracy.\n"
            "Focus on coordinate space mapping, viewBox compression, stack-shift offsets, and system boundary detection."
        )

    return (
        "You are a strict visual QA agent for guitar tablature rendering.\n"
        "Compare APP vs REFERENCE screenshots, focusing only on tablature string lines.\n"
        "Return concise actionable output with:\n"
        "1) visual differences,\n"
        "2) likely CSS/SVG rendering causes,\n"
        "3) exact code-level adjustments (constants/selectors/rendering mode),\n"
        "4) acceptance checklist to declare match.\n"
        "Prioritize line thickness, opacity, anti-aliasing, and consistency across systems."
    )


def ask_openai_task_visual_compare(
    client: OpenAI,
    model: str,
    task: TaskSpec,
    compact_snapshot: dict[str, Any],
    app_screenshots: list[str],
    reference_screenshots: list[str],
    click_results: list[dict[str, Any]] | None = None,
    click_screenshots: list[str] | None = None,
    click_summary: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    system = _build_task_system_prompt(task)

    context_parts = [
        f"Task id: {task.id}",
        f"Task name: {task.name}",
        f"Goal: {task.goal}",
        f"Instructions: {task.instructions or '(none)'}",
    ]

    if click_results:
        context_parts.append(f"Click test results ({len(click_results)} clicks):")
        context_parts.append(json.dumps(click_results, ensure_ascii=False))
    if click_summary:
        context_parts.append("Click test summary:")
        context_parts.append(json.dumps(click_summary, ensure_ascii=False))
    context_parts.append("Compact debug snapshot (app):")
    context_parts.append(json.dumps(compact_snapshot, ensure_ascii=False))

    context_parts.append("Compare APP images first, then REFERENCE images.")
    context_text = "\n".join(context_parts)

    content: list[dict[str, str]] = [{"type": "input_text", "text": context_text}]

    # Click screenshots go first (most relevant for cursor tasks)
    if click_screenshots:
        content.append({"type": "input_text", "text": f"CLICK TEST screenshots ({len(click_screenshots)} images):"})
        click_inputs, _ = build_image_inputs(click_screenshots)
        content.extend(click_inputs)

    content.append({"type": "input_text", "text": "APP screenshots:"})
    app_inputs, app_manifest = build_image_inputs(app_screenshots)
    content.extend(app_inputs)

    content.append({"type": "input_text", "text": "REFERENCE screenshots:"})
    ref_inputs, ref_manifest = build_image_inputs(reference_screenshots)
    content.extend(ref_inputs)

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": content},
        ],
    )
    return response.output_text.strip(), app_manifest, ref_manifest


def local_diagnosis(compact_snapshot: dict[str, Any], tab_screenshots: list[str]) -> str:
    summary = compact_snapshot.get("summary") or {}
    scan = compact_snapshot.get("scan") or {}
    debug_log_summary = compact_snapshot.get("debugLogSummary") or {}
    debug_smart_summary = compact_snapshot.get("debugSmartSummary") or {}
    by_status = summary.get("byStatus") or scan.get("byStatus") or {}
    by_cause = summary.get("byCause") or scan.get("byCause") or {}
    total = summary.get("total") or scan.get("analyzed") or 0
    failures = compact_snapshot.get("failures") or []
    suspects = compact_snapshot.get("suspects") or []
    errors = compact_snapshot.get("errors") or []
    lines = [
        "[local-diagnosis] OpenAI disabled (--no-openai).",
        f"total={total}",
        f"byStatus={json.dumps(by_status, ensure_ascii=False)}",
        f"byCause={json.dumps(by_cause, ensure_ascii=False)}",
        f"failures={len(failures)} suspects={len(suspects)} errors={len(errors)}",
        f"tab_screenshots={len(tab_screenshots)}",
    ]
    if debug_smart_summary:
        pair_entries = int(debug_smart_summary.get("pairEntries") or 0)
        pair_p50 = debug_smart_summary.get("pairFinalGapP50")
        pair_p90 = debug_smart_summary.get("pairFinalGapP90")
        lines.append(
            f"debugSmart pairEntries={pair_entries} pairFinalGapP50={pair_p50} pairFinalGapP90={pair_p90}"
        )
    if debug_log_summary:
        lines.append(
            f"debugLog total={debug_log_summary.get('total', 0)} byStage={json.dumps(debug_log_summary.get('byStage', {}), ensure_ascii=False)}"
        )

    if not by_status and not scan and not debug_smart_summary and not debug_log_summary:
        lines.append("hint=no-scan-data (verify /play URL, debugSave=1 or debugSystemLines=1 and page render timing)")
    elif (by_status.get("weak", 0) or by_status.get("missing", 0) or by_status.get("non-tab", 0)) > 0:
        top_cause = None
        if by_cause:
            top_cause = sorted(by_cause.items(), key=lambda kv: kv[1], reverse=True)[0][0]
        lines.append(f"hint=has-problems topCause={top_cause or 'unknown'}")
    elif debug_smart_summary:
        lines.append("hint=debug-log-present")
    else:
        lines.append("hint=status-looks-ok")
    return "\n".join(lines)


def local_task_diagnosis(
    task: TaskSpec,
    compact_snapshot: dict[str, Any],
    app_screenshots: list[str],
    reference_screenshots: list[str],
) -> str:
    base = local_diagnosis(compact_snapshot, app_screenshots)
    lines = [
        base,
        f"[task] id={task.id}",
        f"[task] name={task.name}",
        f"[task] goal={task.goal}",
        f"[task] app_shots={len(app_screenshots)} reference_shots={len(reference_screenshots)}",
        "[task] hint=run without --no-openai to get visual comparison guidance",
    ]
    return "\n".join(lines)


def save_run(output_dir: Path, payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = output_dir / f"run-{stamp}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file


def build_latest_codex_payload(payload: dict[str, Any], run_file: Path) -> dict[str, Any]:
    snapshot = payload.get("snapshot") or {}
    summary = snapshot.get("summary") or {}
    task_info = payload.get("task") or None
    return {
        "createdAt": payload.get("createdAt"),
        "runFile": str(run_file),
        "url": payload.get("config", {}).get("url"),
        "model": payload.get("config", {}).get("model"),
        "openaiUsed": bool((payload.get("env") or {}).get("openai_used", True)),
        "tabScreenshotsCount": len(payload.get("tab_screenshots") or []),
        "tabScreenshotsSentCount": len(payload.get("tab_screenshots_sent") or []),
        "byStatus": summary.get("byStatus"),
        "byCause": summary.get("byCause"),
        "failuresCount": len(snapshot.get("failures") or []),
        "suspectsCount": len(snapshot.get("suspects") or []),
        "task": task_info,
        "referenceScreenshotsCount": len(payload.get("reference_screenshots") or []),
        "referenceScreenshotsSentCount": len(payload.get("reference_screenshots_sent") or []),
        "clickSummary": payload.get("click_summary") or None,
        "iterationAggregate": payload.get("iteration_aggregate") or None,
        "diagnosis": payload.get("diagnosis"),
    }


def save_latest_codex_payload(output_dir: Path, codex_payload: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_file = output_dir / "latest-codex.json"
    latest_file.write_text(json.dumps(codex_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest_file


def main() -> int:
    config = parse_args()
    task = load_task_spec(config.task, config.task_dir)
    click_task_mode = is_click_task_spec(task)
    playback_task_mode = is_playback_task_spec(task)
    # Playback tasks are a specialised cursor task — don't run generic click tests for them
    if playback_task_mode:
        click_task_mode = False
    user_supplied_url = (config.url or "").strip()
    user_url_explicit = bool(user_supplied_url) and user_supplied_url != DEFAULT_TAB_URL
    if task:
        task_url = resolve_target_url(task.app_url)
        config.url = resolve_target_url(user_supplied_url) if user_url_explicit else task_url
        if user_url_explicit and config.url != task_url:
            safe_print(
                "[tab-debug-agent] using explicit --url instead of task app_url "
                f"(task app_url={task.app_url})"
            )
        config.wait_ms = task.wait_ms
        config.tab_shots_max = task.tab_shots_max
        config.task_iterations = max(config.task_iterations, task.task_iterations)
    else:
        config.url = resolve_target_url(config.url)
    env_path = load_backend_env()
    key = ""
    client: OpenAI | None = None
    if not config.no_openai:
        key = require_openai_key()
        if OpenAI is None:
            raise RuntimeError("openai package is not installed. Run with --no-openai or install openai.")
        client = OpenAI(api_key=key)

    browser = None
    page = None
    screenshot_path: str | None = None
    tab_screenshot_paths: list[str] = []
    reference_screenshot_paths: list[str] = []
    tab_screenshots_sent: list[dict[str, Any]] = []
    reference_screenshots_sent: list[dict[str, Any]] = []
    reference_prep_info: dict[str, Any] | None = None
    url_mismatch_info: dict[str, Any] | None = None
    click_summary: dict[str, Any] = {}
    aggregate_click_summary: dict[str, Any] | None = None
    iteration_reports: list[dict[str, Any]] = []
    snapshot: dict[str, Any] = {}
    compact: dict[str, Any] = {}
    diagnosis = ""
    interrupted = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=config.headless)
            page = browser.new_page()
            loops = config.task_iterations if task else 1
            ref_page = browser.new_page() if (task and not click_task_mode) else None
            for i in range(loops):
                url_mismatch_info = None
                page.goto(config.url, wait_until="domcontentloaded")
                page.wait_for_timeout(config.wait_ms)
                # Some app states auto-redirect to previously opened tabs.
                # Always lock onto the requested URL before collecting/capturing.
                ensure_target_page_url(
                    page=page,
                    target_url=config.url,
                    matcher=_app_urls_match,
                    attempts=5,
                    wait_ms=config.wait_ms,
                )
                app_ready = wait_for_app_full_ready(
                    page=page,
                    timeout_ms=max(6000, config.wait_ms * 4),
                )
                if not app_ready:
                    safe_print("[tab-debug-agent] app not fully ready before snapshot/capture (continuing anyway)")

                current_url = (page.url or "").strip()
                if not _app_urls_match(current_url, config.url):
                    requested_id = _app_url_id(config.url)
                    current_id = _app_url_id(current_url)
                    url_mismatch_info = {
                        "requestedUrl": config.url,
                        "currentUrl": current_url,
                        "requestedId": requested_id or None,
                        "currentId": current_id or None,
                    }
                    safe_print(
                        f"[tab-debug-agent] warning: app redirected to a different URL/id "
                        f"(requested id={requested_id or '-'} current id={current_id or '-'})"
                    )

                snapshot = collect_debug_snapshot(
                    page=page,
                    include_non_tab=config.include_non_tab,
                    recent_limit=config.recent_limit,
                )
                compact = compact_for_llm(snapshot, config.recent_limit)

                tab_screenshot_paths = []
                if config.tab_shots:
                    try:
                        ensure_target_page_url(
                            page=page,
                            target_url=config.url,
                            matcher=_app_urls_match,
                            attempts=3,
                            wait_ms=900,
                        )
                        wait_for_app_full_ready(
                            page=page,
                            timeout_ms=max(5000, config.wait_ms * 3),
                        )
                        tab_screenshot_paths = capture_tab_screenshots(
                            page=page,
                            output_dir=config.output_dir,
                            max_shots=config.tab_shots_max,
                            wait_ms=config.tab_shot_wait_ms,
                        )
                    except Exception as exc:
                        tab_screenshot_paths = []
                        safe_print(f"[tab-debug-agent] tab screenshot capture failed: {exc}")

                reference_screenshot_paths = []
                reference_prep_info = None
                if task and ref_page and not click_task_mode:
                    try:
                        ref_page.goto(task.reference_url, wait_until="domcontentloaded")
                        if "songsterr.com" in task.reference_url.lower():
                            try:
                                reference_prep_info = prepare_songsterr_dark_reference(
                                    page=ref_page,
                                    wait_ms=config.wait_ms,
                                    target_url=task.reference_url,
                                )
                            except Exception as prep_exc:
                                safe_print(f"[tab-debug-agent] songsterr dark prep failed (continuing capture): {prep_exc}")
                                reference_prep_info = {
                                    "status": "prepare-failed",
                                    "error": str(prep_exc),
                                    "finalUrl": ref_page.url,
                                }
                        reference_screenshot_paths = capture_reference_screenshots(
                            page=ref_page,
                            output_dir=config.output_dir,
                            max_shots=max(1, min(config.tab_shots_max, 6)),
                            wait_ms=max(config.wait_ms, 2000),
                        )
                    except Exception as exc:
                        reference_screenshot_paths = []
                        safe_print(f"[tab-debug-agent] reference screenshot capture failed: {exc}")

                # --- Click tests (for cursor/click tasks) ---
                click_screenshot_paths: list[str] = []
                click_results: list[dict[str, Any]] = []
                click_summary: dict[str, Any] = {}

                # Check if vertical-line click testing is requested
                _url_qs = parse_qs(urlparse(config.url).query)
                _vertical_click_mode = (
                    "1" in _url_qs.get("verticalClickTest", [])
                    or (task and "vertical" in (task.instructions or "").lower())
                )

                if _vertical_click_mode:
                    try:
                        click_screenshot_paths, click_results, click_summary = perform_vertical_line_click_tests(
                            page=page,
                            output_dir=config.output_dir,
                            wait_ms=500,
                        )
                        safe_print(
                            f"[tab-debug-agent] vertical click tests: {len(click_results)} clicks, "
                            f"passRate={click_summary.get('passRate', 0.0)}%"
                        )
                    except Exception as exc:
                        safe_print(f"[tab-debug-agent] vertical click tests failed: {exc}")
                elif click_task_mode:
                    try:
                        click_screenshot_paths, click_results, click_summary = perform_click_tests(
                            page=page,
                            output_dir=config.output_dir,
                            max_clicks=16,
                            wait_ms=600,
                        )
                        safe_print(
                            f"[tab-debug-agent] click tests: {len(click_results)} clicks, {len(click_screenshot_paths)} screenshots, "
                            f"passRate={click_summary.get('passRate', 0.0)}%"
                        )
                    except Exception as exc:
                        safe_print(f"[tab-debug-agent] click tests failed: {exc}")
                elif playback_task_mode:
                    try:
                        playback_mode = "original" if (
                            task
                            and (
                                "original" in (task.id or "").lower()
                                or "original" in (task.goal or "").lower()
                                or "offset" in (task.goal or "").lower()
                            )
                        ) else "synthetic"
                        if task and task.playback_mode:
                            playback_mode = "original" if task.playback_mode.startswith("orig") else "synthetic"
                        click_screenshot_paths, click_results, click_summary = perform_playback_cursor_tests(
                            page=page,
                            output_dir=config.output_dir,
                            mode=playback_mode,
                            sample_interval_ms=500,
                            total_duration_ms=task.probe_duration_ms if task else 5000,
                            probe_sample_ms=task.probe_sample_ms if task else 16,
                            freeze_min_duration_ms=task.freeze_min_duration_ms if task else 180,
                            required_systems=task.required_systems if task else 1,
                            max_frame_gap_ms=task.max_frame_gap_ms if task else 80,
                            max_long_task_ms=task.max_long_task_ms if task else 80,
                            max_audio_stall_ms=task.max_audio_stall_ms if task else 180,
                            max_stationary_pair_rate_pct=(
                                task.max_stationary_pair_rate_pct if task else 12.0
                            ),
                            stationary_pair_dx_px=(
                                task.stationary_pair_dx_px if task else 0.1
                            ),
                            max_velocity_jitter_p90_pct=(
                                task.max_velocity_jitter_p90_pct if task else 0.0
                            ),
                            velocity_jitter_spike_threshold_pct=(
                                task.velocity_jitter_spike_threshold_pct if task else 0.0
                            ),
                            max_velocity_jitter_spike_count=(
                                task.max_velocity_jitter_spike_count if task else 0
                            ),
                            max_display_hold_event_count=(
                                task.max_display_hold_event_count if task else 999999
                            ),
                            max_target_jump_event_count=(
                                task.max_target_jump_event_count if task else 999999
                            ),
                        )
                        safe_print(
                            f"[tab-debug-agent] playback cursor tests: {len(click_results)} samples, "
                            f"verdict={click_summary.get('verdict','?')} passRate={click_summary.get('passRate', 0.0)}%"
                        )
                    except Exception as exc:
                        safe_print(f"[tab-debug-agent] playback cursor tests failed: {exc}")

                if config.no_openai:
                    if task:
                        diagnosis = local_task_diagnosis(
                            task=task,
                            compact_snapshot=compact,
                            app_screenshots=tab_screenshot_paths,
                            reference_screenshots=reference_screenshot_paths,
                        )
                        if click_results:
                            if playback_task_mode:
                                verdict = click_summary.get("verdict", "?")
                                diagnosis += (
                                    f"\n[playback-cursor-tests] {len(click_results)} samples, "
                                    f"verdict={verdict} passRate={click_summary.get('passRate', 0.0)}% "
                                    f"freeze={click_summary.get('freezeCount', 0)} "
                                    f"hidden={click_summary.get('hiddenCount', 0)} "
                                    f"systems={click_summary.get('systemsTraversed', 0)} "
                                    f"visible={click_summary.get('visible', 0)}/{click_summary.get('total', 0)}"
                                )
                                for fd in (click_summary.get("freezeDetails") or [])[:10]:
                                    diagnosis += (
                                        f"\n  freeze samplePair={fd.get('samplePair')} "
                                        f"x={fd.get('x')} sys={fd.get('systemIndex')}"
                                    )
                            else:
                                diagnosis += (
                                    f"\n[click-tests] {len(click_results)} clicks, {len(click_screenshot_paths)} screenshots, "
                                    f"passRate={click_summary.get('passRate', 0.0)}% "
                                    f"({click_summary.get('passed', 0)}/{click_summary.get('total', 0)})"
                                )
                                for failure in (click_summary.get("failures") or [])[:12]:
                                    diagnosis += (
                                        f"\n  fail#{failure.get('clickIndex','?')} kind={failure.get('kind','?')} "
                                        f"sys={failure.get('systemIndex','?')} expected={failure.get('expectedSvgIndices')} "
                                        f"observed={failure.get('observedSvgIndex')} reasons={failure.get('reasons')}"
                                    )
                        tab_screenshots_sent = []
                        reference_screenshots_sent = []
                    else:
                        diagnosis = local_diagnosis(compact, tab_screenshot_paths)
                        tab_screenshots_sent = []
                        reference_screenshots_sent = []
                else:
                    if task:
                        diagnosis, tab_screenshots_sent, reference_screenshots_sent = ask_openai_task_visual_compare(
                            client=client,
                            model=config.model,
                            task=task,
                            compact_snapshot=compact,
                            app_screenshots=tab_screenshot_paths,
                            reference_screenshots=reference_screenshot_paths,
                            click_results=click_results if click_results else None,
                            click_screenshots=click_screenshot_paths if click_screenshot_paths else None,
                            click_summary=click_summary if click_summary else None,
                        )
                    else:
                        diagnosis, tab_screenshots_sent = ask_openai(
                            client,
                            config.model,
                            compact,
                            tab_screenshots=tab_screenshot_paths,
                        )
                        reference_screenshots_sent = []

                iteration_reports.append(
                    {
                        "index": i + 1,
                        "createdAt": now_iso(),
                        "snapshot_summary": (snapshot.get("summary") or {}),
                        "app_screenshots": tab_screenshot_paths,
                        "reference_screenshots": reference_screenshot_paths,
                        "reference_prep": reference_prep_info,
                        "url_mismatch": url_mismatch_info,
                        "click_screenshots": click_screenshot_paths,
                        "click_results": click_results,
                        "click_summary": click_summary,
                        "diagnosis": diagnosis,
                    }
                )

            aggregate_click_summary = _aggregate_iteration_click_summaries(
                iteration_reports,
                require_all_iterations_pass=bool(task.require_all_iterations_pass) if task else False,
            )
            if aggregate_click_summary:
                click_summary = aggregate_click_summary
                aggregate_diagnosis = _build_iteration_aggregate_diagnosis(
                    task,
                    iteration_reports,
                    aggregate_click_summary,
                )
                if aggregate_diagnosis:
                    diagnosis = f"{diagnosis}\n{aggregate_diagnosis}" if diagnosis else aggregate_diagnosis

            if config.screenshot:
                if tab_screenshot_paths:
                    screenshot_path = tab_screenshot_paths[0]
                else:
                    try:
                        single_tab_shot = capture_tab_screenshots(
                            page=page,
                            output_dir=config.output_dir,
                            max_shots=1,
                            wait_ms=0,
                        )
                        screenshot_path = single_tab_shot[0] if single_tab_shot else None
                    except Exception as exc:
                        screenshot_path = None
                        safe_print(f"[tab-debug-agent] screenshot capture failed: {exc}")

            run_payload = {
                "createdAt": now_iso(),
                "config": {
                    **asdict(config),
                    "output_dir": str(config.output_dir),
                    "task_dir": str(config.task_dir),
                },
                "env": {
                    "dotenv_path": str(env_path),
                    "openai_key_present": bool(key),
                    "openai_used": not config.no_openai,
                },
                "task": asdict(task) if task else None,
                "snapshot": snapshot,
                "compact_snapshot": compact,
                "url_mismatch": url_mismatch_info,
                "diagnosis": diagnosis,
                "screenshot": screenshot_path,
                "tab_screenshots": tab_screenshot_paths,
                "tab_screenshots_sent": tab_screenshots_sent,
                "reference_screenshots": reference_screenshot_paths,
                "reference_screenshots_sent": reference_screenshots_sent,
                "reference_prep": reference_prep_info,
                "click_summary": click_summary,
                "iteration_aggregate": aggregate_click_summary,
                "iterations": iteration_reports,
            }
            run_file = save_run(config.output_dir, run_payload)
            codex_payload = build_latest_codex_payload(run_payload, run_file)
            codex_file = save_latest_codex_payload(config.output_dir, codex_payload)

            if not config.codex_stdout_only:
                safe_print(f"[tab-debug-agent] url={config.url}")
                safe_print(f"[tab-debug-agent] run_file={run_file}")
                safe_print(f"[tab-debug-agent] codex_file={codex_file}")
                summary = snapshot.get("summary") or {}
                safe_print(f"[tab-debug-agent] byStatus={summary.get('byStatus')}")
                safe_print(f"[tab-debug-agent] byCause={summary.get('byCause')}")
                safe_print(f"[tab-debug-agent] tab_screenshots={len(tab_screenshot_paths)}")
                safe_print(f"[tab-debug-agent] tab_screenshots_sent={len(tab_screenshots_sent)}")
                safe_print(f"[tab-debug-agent] reference_screenshots={len(reference_screenshot_paths)}")
                safe_print(f"[tab-debug-agent] reference_screenshots_sent={len(reference_screenshots_sent)}")
                if reference_prep_info:
                    safe_print(f"[tab-debug-agent] reference_prep={json.dumps(reference_prep_info, ensure_ascii=True)}")
                if task:
                    safe_print(f"[tab-debug-agent] task={task.id} ({task.name})")
                safe_print("\n[tab-debug-agent] diagnosis:\n")
                safe_print(diagnosis)

            if config.emit_codex_stdout or config.codex_stdout_only:
                # Keep stdout JSON ASCII-only for robust subprocess parsing on Windows cp1252.
                safe_print(json.dumps(codex_payload, ensure_ascii=True))

            if config.keep_open and not config.headless:
                safe_print("\n[tab-debug-agent] Browser aberto. Pressione Ctrl+C para sair.")
                try:
                    while True:
                        page.wait_for_timeout(1000)
                except KeyboardInterrupt:
                    pass
    except KeyboardInterrupt:
        interrupted = True
        safe_print("[tab-debug-agent] interrupted by user")

    finally:
        if browser and not config.keep_open:
            try:
                browser.close()
            except Exception:
                pass
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
