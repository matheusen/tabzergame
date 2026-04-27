from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from random import Random
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TUNE_PARAM_SPACE: dict[str, list[int]] = {
    "gapTarget": [84, 90, 96, 102, 108],
    "topCropSafety": [18, 22, 26, 30, 34, 38],
    "bottomCropSafety": [80, 90, 100, 110, 120],
    "cropMin": [4, 8, 12, 16, 20],
    "stackFinalStaffGap": [84, 92, 100, 108, 116],
    "stackSafetyGap": [14, 18, 22, 26, 30],
    "stackGap": [0, 2, 4, 6],
    "stackBoost": [0, 2, 4, 6],
}

DEFAULT_TUNE_PARAMS = ",".join(TUNE_PARAM_SPACE.keys())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run tab_debug_agent in loop (no OpenAI) until stable."
    )
    parser.add_argument("--iterations", type=int, default=12, help="Max loop iterations.")
    parser.add_argument("--sleep-ms", type=int, default=900, help="Delay between iterations.")
    parser.add_argument("--stable-runs", type=int, default=2, help="Consecutive stable runs to stop.")
    parser.add_argument("--headless", type=int, default=1, choices=[0, 1], help="1=headless, 0=visible browser.")
    parser.add_argument(
        "--optimizer",
        default="local",
        choices=["local", "dspy-gepa"],
        help="Tuning optimizer. local=hill-climb, dspy-gepa=DSPy 3 + GEPA (offline proposer).",
    )
    parser.add_argument(
        "--require-click-summary",
        action="store_true",
        help="Require clickSummary to be present and stable (for vertical/click tests).",
    )
    parser.add_argument(
        "--min-click-pass-rate",
        type=float,
        default=100.0,
        help="Minimum clickSummary.passRate to consider a run stable.",
    )
    parser.add_argument(
        "--max-click-failures",
        type=int,
        default=0,
        help="Maximum clickSummary.failed allowed to consider a run stable.",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugSystemLines=1&debugSave=1",
        help="Target /play URL.",
    )
    parser.add_argument(
        "--task",
        default="",
        help="Optional task id/path to forward to run_agent.py.",
    )
    parser.add_argument(
        "--run-timeout-sec",
        type=int,
        default=300,
        help="Timeout for each run_agent execution.",
    )
    parser.add_argument(
        "--auto-tune",
        action="store_true",
        help="Enable URL param tuning in local mode.",
    )
    parser.add_argument(
        "--tune-params",
        default=DEFAULT_TUNE_PARAMS,
        help="Comma-separated params to tune.",
    )
    parser.add_argument(
        "--max-neighbor-step",
        type=int,
        default=2,
        help="Max discrete step distance from the current best when generating neighbors.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for candidate sampling.",
    )
    parser.add_argument(
        "--history-json",
        default="",
        help="Optional path to save loop history JSON.",
    )
    parser.add_argument(
        "--max-run-errors",
        type=int,
        default=5,
        help="Abort after this many run_agent execution errors/timeouts.",
    )
    parser.add_argument(
        "--dspy-max-metric-calls",
        type=int,
        default=24,
        help="GEPA budget: maximum metric calls.",
    )
    parser.add_argument(
        "--dspy-profiles",
        type=int,
        default=28,
        help="How many profile candidates to build for DSPy GEPA.",
    )
    parser.add_argument(
        "--dspy-trainset-size",
        type=int,
        default=6,
        help="Trainset size for DSPy GEPA.",
    )
    parser.add_argument(
        "--dspy-valset-size",
        type=int,
        default=3,
        help="Valset size for DSPy GEPA.",
    )
    parser.add_argument(
        "--dspy-log-dir",
        default="",
        help="Optional log directory for GEPA artifacts.",
    )
    return parser.parse_args()


def _set_query_params(url: str, updates: dict[str, Any]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in updates.items():
        query[str(key)] = str(value)
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _ensure_click_url_flags(url: str, require_click_summary: bool) -> str:
    if not require_click_summary:
        return url
    return _set_query_params(
        url,
        {
            "verticalClickTest": 1,
            "debugSystemLines": 1,
            "debugSave": 1,
        },
    )


def _parse_tune_params(raw: str) -> list[str]:
    names = [p.strip() for p in str(raw or "").split(",") if p.strip()]
    if not names:
        return []
    unknown = [name for name in names if name not in TUNE_PARAM_SPACE]
    if unknown:
        raise ValueError(f"Unknown tune params: {unknown}. Allowed: {sorted(TUNE_PARAM_SPACE.keys())}")
    dedup: list[str] = []
    for name in names:
        if name not in dedup:
            dedup.append(name)
    return dedup


def _nearest_index(values: list[int], raw_value: str | None) -> int:
    if raw_value is None:
        return len(values) // 2
    try:
        target = float(raw_value)
    except Exception:
        return len(values) // 2
    best_idx = 0
    best_dist = float("inf")
    for idx, val in enumerate(values):
        dist = abs(float(val) - target)
        if dist < best_dist:
            best_idx = idx
            best_dist = dist
    return best_idx


def _initial_indices(url: str, params: list[str]) -> dict[str, int]:
    query = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    out: dict[str, int] = {}
    for name in params:
        out[name] = _nearest_index(TUNE_PARAM_SPACE[name], query.get(name))
    return out


def _indices_signature(indices: dict[str, int], params: list[str]) -> tuple[int, ...]:
    return tuple(int(indices[name]) for name in params)


def _url_from_indices(base_url: str, indices: dict[str, int], params: list[str]) -> str:
    updates: dict[str, Any] = {}
    for name in params:
        updates[name] = TUNE_PARAM_SPACE[name][indices[name]]
    return _set_query_params(base_url, updates)


def _next_candidate_indices(
    best_indices: dict[str, int],
    params: list[str],
    tried: set[tuple[int, ...]],
    max_neighbor_step: int,
    rng: Random,
) -> dict[str, int] | None:
    for step in range(1, max(1, int(max_neighbor_step)) + 1):
        for name in params:
            base_idx = best_indices[name]
            for delta in (step, -step):
                idx = base_idx + delta
                if idx < 0 or idx >= len(TUNE_PARAM_SPACE[name]):
                    continue
                cand = dict(best_indices)
                cand[name] = idx
                sig = _indices_signature(cand, params)
                if sig not in tried:
                    return cand

    for _ in range(120):
        cand = dict(best_indices)
        mutate_count = 1 if len(params) < 3 else rng.randint(1, min(3, len(params)))
        chosen = rng.sample(params, k=mutate_count)
        for name in chosen:
            cand[name] = rng.randrange(len(TUNE_PARAM_SPACE[name]))
        sig = _indices_signature(cand, params)
        if sig not in tried:
            return cand

    return None


def run_once(repo_root: Path, url: str, headless: int, timeout_sec: int, task: str = "") -> dict[str, Any]:
    cmd = [
        sys.executable,
        "backend/agents/tab_debug_agent/run_agent.py",
        "--no-openai",
        "--codex-stdout-only",
        "--headless",
        str(headless),
    ]
    if task:
        cmd.extend(["--task", task])
    if url:
        cmd.extend(["--url", url])
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=max(30, int(timeout_sec)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"run_agent timeout after {timeout_sec}s for url={url}") from exc

    if cp.returncode != 0:
        raise RuntimeError(f"run_agent failed: code={cp.returncode}\nSTDERR:\n{cp.stderr[-1200:]}")
    lines = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    raise RuntimeError(f"Could not parse JSON from stdout:\n{cp.stdout[-1200:]}")


def is_stable(
    payload: dict[str, Any],
    *,
    require_click_summary: bool,
    min_click_pass_rate: float,
    max_click_failures: int,
) -> bool:
    click = payload.get("clickSummary")
    by_status = payload.get("byStatus") or {}
    weak = int(by_status.get("weak", 0) or 0)
    missing = int(by_status.get("missing", 0) or 0)
    failures = int(payload.get("failuresCount", 0) or 0)
    suspects = int(payload.get("suspectsCount", 0) or 0)
    ok = int(by_status.get("ok", 0) or 0)
    has_status_counters = bool(by_status)
    status_ok = weak == 0 and missing == 0 and failures == 0 and suspects == 0 and (
        ok > 0 or (not has_status_counters and click is not None)
    )

    if click is None:
        return status_ok and not require_click_summary

    click_total = int(click.get("total", 0) or 0)
    click_failed = int(click.get("failed", 0) or 0)
    click_pass_rate = float(click.get("passRate", 0.0) or 0.0)
    click_ok = (
        click_total > 0
        and click_failed <= max_click_failures
        and click_pass_rate >= float(min_click_pass_rate)
    )
    return status_ok and click_ok


def _default_metrics() -> dict[str, Any]:
    return {
        "by_status": {},
        "weak": 0,
        "missing": 0,
        "ok": 0,
        "failures_count": 0,
        "suspects_count": 0,
        "click_total": 0,
        "click_failed": 0,
        "click_pass_rate": 0.0,
        "has_click_summary": False,
        "systems_traversed": 0,
        "required_systems": 0,
        "frame_gap_count": 0,
        "audio_stall_count": 0,
        "long_task_count": 0,
        "stationary_pair_count": 0,
        "stationary_pair_rate_pct": 0.0,
        "max_stationary_pair_rate_pct": 0.0,
        "velocity_jitter_ratio_p90_pct": 0.0,
        "max_velocity_jitter_p90_pct": 0.0,
        "velocity_jitter_spike_count": 0,
        "max_velocity_jitter_spike_count": 0,
        "worst_frame_gap_ms": 0.0,
        "worst_long_task_ms": 0.0,
    }


def _metrics(payload: dict[str, Any]) -> dict[str, Any]:
    by_status = payload.get("byStatus") or {}
    click = payload.get("clickSummary") or None
    return {
        "by_status": by_status,
        "weak": int(by_status.get("weak", 0) or 0),
        "missing": int(by_status.get("missing", 0) or 0),
        "ok": int(by_status.get("ok", 0) or 0),
        "failures_count": int(payload.get("failuresCount", 0) or 0),
        "suspects_count": int(payload.get("suspectsCount", 0) or 0),
        "click_total": int(click.get("total", 0) or 0) if isinstance(click, dict) else 0,
        "click_failed": int(click.get("failed", 0) or 0) if isinstance(click, dict) else 0,
        "click_pass_rate": float(click.get("passRate", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "has_click_summary": isinstance(click, dict),
        "systems_traversed": int(click.get("systemsTraversed", 0) or 0) if isinstance(click, dict) else 0,
        "required_systems": int(click.get("requiredSystems", 0) or 0) if isinstance(click, dict) else 0,
        "frame_gap_count": int(click.get("frameGapCount", 0) or 0) if isinstance(click, dict) else 0,
        "audio_stall_count": int(click.get("audioStallCount", 0) or 0) if isinstance(click, dict) else 0,
        "long_task_count": int(click.get("longTaskCount", 0) or 0) if isinstance(click, dict) else 0,
        "stationary_pair_count": int(click.get("stationaryPairCount", 0) or 0) if isinstance(click, dict) else 0,
        "stationary_pair_rate_pct": float(click.get("stationaryPairRatePct", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "max_stationary_pair_rate_pct": float(click.get("maxStationaryPairRatePct", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "velocity_jitter_ratio_p90_pct": float(click.get("velocityJitterRatioP90Pct", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "max_velocity_jitter_p90_pct": float(click.get("maxVelocityJitterP90Pct", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "velocity_jitter_spike_count": int(click.get("velocityJitterSpikeCount", 0) or 0) if isinstance(click, dict) else 0,
        "max_velocity_jitter_spike_count": int(click.get("maxVelocityJitterSpikeCount", 0) or 0) if isinstance(click, dict) else 0,
        "worst_frame_gap_ms": float(click.get("worstFrameGapMs", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
        "worst_long_task_ms": float(click.get("worstLongTaskMs", 0.0) or 0.0) if isinstance(click, dict) else 0.0,
    }


def _score(payload: dict[str, Any], *, require_click_summary: bool, stable: bool) -> float:
    m = _metrics(payload)
    score = 0.0
    score += m["click_pass_rate"] * 20.0
    score += min(m["click_total"], 32) * 1.5
    score -= m["click_failed"] * 380.0
    score -= m["frame_gap_count"] * 260.0
    score -= m["audio_stall_count"] * 320.0
    score -= m["long_task_count"] * 140.0
    score -= m["stationary_pair_count"] * 4.0
    if (
        m["max_stationary_pair_rate_pct"] > 0.0
        and m["stationary_pair_rate_pct"] > m["max_stationary_pair_rate_pct"]
    ):
        score -= (m["stationary_pair_rate_pct"] - m["max_stationary_pair_rate_pct"]) * 80.0
    if (
        m["max_velocity_jitter_p90_pct"] > 0.0
        and m["velocity_jitter_ratio_p90_pct"] > m["max_velocity_jitter_p90_pct"]
    ):
        score -= (m["velocity_jitter_ratio_p90_pct"] - m["max_velocity_jitter_p90_pct"]) * 42.0
    if (
        m["max_velocity_jitter_spike_count"] > 0
        and m["velocity_jitter_spike_count"] > m["max_velocity_jitter_spike_count"]
    ):
        score -= (m["velocity_jitter_spike_count"] - m["max_velocity_jitter_spike_count"]) * 24.0
    if m["required_systems"] > 0 and m["systems_traversed"] < m["required_systems"]:
        score -= (m["required_systems"] - m["systems_traversed"]) * 420.0
    score -= m["weak"] * 180.0
    score -= m["missing"] * 260.0
    score -= m["failures_count"] * 120.0
    score -= m["suspects_count"] * 60.0
    if require_click_summary and not m["has_click_summary"]:
        score -= 7000.0
    if stable:
        score += 100000.0
    return score


def _normalized_score_0_1(payload: dict[str, Any], *, require_click_summary: bool, stable: bool) -> float:
    m = _metrics(payload)
    if require_click_summary and (not m["has_click_summary"] or m["click_total"] <= 0):
        return 0.0

    score = 1.0
    if m["has_click_summary"]:
        score *= max(0.0, min(1.0, m["click_pass_rate"] / 100.0))

    penalties = 0.0
    penalties += m["weak"] * 0.08
    penalties += m["missing"] * 0.18
    penalties += m["failures_count"] * 0.08
    penalties += m["suspects_count"] * 0.02
    penalties += m["click_failed"] * 0.18
    if (
        m["max_stationary_pair_rate_pct"] > 0.0
        and m["stationary_pair_rate_pct"] > m["max_stationary_pair_rate_pct"]
    ):
        penalties += min(0.28, (m["stationary_pair_rate_pct"] - m["max_stationary_pair_rate_pct"]) / 100.0)
    if (
        m["max_velocity_jitter_p90_pct"] > 0.0
        and m["velocity_jitter_ratio_p90_pct"] > m["max_velocity_jitter_p90_pct"]
    ):
        penalties += min(0.24, (m["velocity_jitter_ratio_p90_pct"] - m["max_velocity_jitter_p90_pct"]) / 100.0)
    if (
        m["max_velocity_jitter_spike_count"] > 0
        and m["velocity_jitter_spike_count"] > m["max_velocity_jitter_spike_count"]
    ):
        penalties += min(0.24, (m["velocity_jitter_spike_count"] - m["max_velocity_jitter_spike_count"]) * 0.01)
    score -= min(0.95, penalties)
    if stable:
        score = min(1.0, score + 0.25)
    return max(0.0, min(1.0, score))


def _format_params(indices: dict[str, int] | None, params: list[str]) -> str:
    if not indices or not params:
        return "-"
    parts = [f"{name}={TUNE_PARAM_SPACE[name][indices[name]]}" for name in params]
    return ",".join(parts)


def _save_history(path: str, history: list[dict[str, Any]]) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[loop] history_json={out}")

def run_local_loop(args: argparse.Namespace, repo_root: Path, base_url: str) -> int:
    max_iterations = max(1, int(args.iterations))
    sleep_ms = max(0, int(args.sleep_ms))
    stable_needed = max(1, int(args.stable_runs))
    run_timeout_sec = max(30, int(args.run_timeout_sec))

    auto_tune = bool(args.auto_tune)
    tune_params = _parse_tune_params(args.tune_params) if auto_tune else []
    rng = Random(int(args.seed))

    current_url = base_url
    current_indices: dict[str, int] | None = _initial_indices(base_url, tune_params) if auto_tune else None
    best_url = current_url
    best_indices = dict(current_indices) if current_indices is not None else None
    best_score = float("-inf")
    tried_signatures: set[tuple[int, ...]] = set()
    history: list[dict[str, Any]] = []
    run_errors = 0

    stable_streak = 0
    for i in range(1, max_iterations + 1):
        stable = False
        score = float("-inf")
        m = _default_metrics()
        run_error: str | None = None

        try:
            payload = run_once(repo_root, current_url, args.headless, run_timeout_sec, str(args.task or ""))
            stable = is_stable(
                payload,
                require_click_summary=bool(args.require_click_summary),
                min_click_pass_rate=float(args.min_click_pass_rate),
                max_click_failures=int(args.max_click_failures),
            )
            score = _score(
                payload,
                require_click_summary=bool(args.require_click_summary),
                stable=stable,
            )
            m = _metrics(payload)
        except Exception as exc:
            run_errors += 1
            run_error = str(exc)
            stable = False
            score = -1_000_000.0 - run_errors * 1000.0
            print(f"[loop] run={i} error={run_error}")
            if run_errors >= max(1, int(args.max_run_errors)):
                print(f"[loop] abort: too many run errors ({run_errors})")
                return 2

        print(
            f"[loop] run={i} score={score:.1f} stable={stable} "
            f"byStatus={m['by_status']} failures={m['failures_count']} suspects={m['suspects_count']} "
            f"clickTotal={m['click_total']} clickFailed={m['click_failed']} clickPassRate={m['click_pass_rate']} "
            f"systems={m['systems_traversed']}/{m['required_systems']} frameGaps={m['frame_gap_count']} "
            f"audioStalls={m['audio_stall_count']} longTasks={m['long_task_count']} "
            f"stationary={m['stationary_pair_count']} stationaryRate={m['stationary_pair_rate_pct']:.2f}% "
            f"tuned={_format_params(current_indices, tune_params)}"
        )

        if auto_tune and current_indices is not None:
            tried_signatures.add(_indices_signature(current_indices, tune_params))

        if score > best_score:
            best_score = score
            best_url = current_url
            if auto_tune and current_indices is not None:
                best_indices = dict(current_indices)
            print(f"[loop] new_best score={best_score:.1f} url={best_url}")

        history.append(
            {
                "run": i,
                "url": current_url,
                "stable": stable,
                "score": round(score, 3),
                "metrics": m,
                "error": run_error,
                "tuned_params": {name: TUNE_PARAM_SPACE[name][current_indices[name]] for name in tune_params}
                if (auto_tune and current_indices is not None)
                else {},
            }
        )

        if stable:
            stable_streak += 1
            print(f"[loop] stable_streak={stable_streak}/{stable_needed}")
            if stable_streak >= stable_needed:
                print(f"[loop] done: stabilized at run {i}")
                print(f"[loop] best_url={best_url}")
                _save_history(args.history_json, history)
                return 0
        else:
            stable_streak = 0

        if i < max_iterations:
            if auto_tune:
                if stable_streak > 0:
                    current_url = best_url
                    current_indices = dict(best_indices) if best_indices is not None else None
                else:
                    if best_indices is None:
                        best_indices = _initial_indices(base_url, tune_params)
                    cand = _next_candidate_indices(
                        best_indices=best_indices,
                        params=tune_params,
                        tried=tried_signatures,
                        max_neighbor_step=max(1, int(args.max_neighbor_step)),
                        rng=rng,
                    )
                    if cand is None:
                        current_indices = dict(best_indices)
                        current_url = _url_from_indices(base_url, current_indices, tune_params)
                        print("[loop] tuner exhausted candidates near best; retrying best config")
                    else:
                        current_indices = cand
                        current_url = _url_from_indices(base_url, current_indices, tune_params)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)

    print("[loop] done: reached max iterations without stable streak")
    print(f"[loop] best_score={best_score:.1f}")
    print(f"[loop] best_url={best_url}")
    _save_history(args.history_json, history)
    return 1


def _indices_to_values(indices: dict[str, int], params: list[str]) -> dict[str, int]:
    return {name: TUNE_PARAM_SPACE[name][indices[name]] for name in params}


def _build_profile_library(base_url: str, params: list[str], seed: int, max_profiles: int) -> list[dict[str, int]]:
    rng = Random(int(seed))
    max_profiles = max(2, int(max_profiles))
    initial = _initial_indices(base_url, params)

    profiles: list[dict[str, int]] = []
    seen: set[tuple[int, ...]] = set()

    def add_indices(indices: dict[str, int]) -> None:
        sig = _indices_signature(indices, params)
        if sig in seen:
            return
        seen.add(sig)
        profiles.append(_indices_to_values(indices, params))

    add_indices(initial)

    for name in params:
        base_idx = initial[name]
        for delta in (1, -1, 2, -2):
            idx = base_idx + delta
            if 0 <= idx < len(TUNE_PARAM_SPACE[name]):
                cand = dict(initial)
                cand[name] = idx
                add_indices(cand)
                if len(profiles) >= max_profiles:
                    return profiles

    while len(profiles) < max_profiles:
        cand = {}
        for name in params:
            cand[name] = rng.randrange(len(TUNE_PARAM_SPACE[name]))
        add_indices(cand)
        if len(seen) >= 5000:
            break

    return profiles


def _profile_token(index: int) -> str:
    return f"PROFILE_{index}"


def _extract_profile_token(text: str, tokens: list[str]) -> str | None:
    if not text:
        return None
    active_match = re.search(r"Active profile token:\s*(PROFILE_\d+)", text)
    if active_match:
        active = active_match.group(1)
        if active in tokens:
            return active
    pattern = r"\b(PROFILE_\d+)\b"
    matches = [m.group(1) for m in re.finditer(pattern, text)]
    for token in reversed(matches):
        if token in tokens:
            return token
    return None


def _replace_profile_token(text: str, token: str) -> str:
    raw = text or ""
    active_pattern = r"(Active profile token:\s*)PROFILE_\d+"
    if re.search(active_pattern, raw):
        return re.sub(active_pattern, rf"\1{token}", raw, count=1)
    if re.search(r"\bPROFILE_\d+\b", raw):
        return re.sub(r"\bPROFILE_\d+\b", token, raw, count=1)
    base = raw.strip()
    if base:
        return f"{base}\nActive profile token: {token}"
    return f"Active profile token: {token}"


def _parse_predicted_param_values(raw: Any, params: list[str]) -> dict[str, int] | None:
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    out: dict[str, int] = {}
    for name in params:
        if name not in data:
            return None
        idx = _nearest_index(TUNE_PARAM_SPACE[name], str(data.get(name)))
        out[name] = TUNE_PARAM_SPACE[name][idx]
    return out


def _extract_suggested_profile(records: Any, tokens: list[str]) -> str | None:
    if not isinstance(records, (list, tuple)):
        return None
    for rec in reversed(records):
        if not isinstance(rec, dict):
            continue
        for value in rec.values():
            if not isinstance(value, str):
                continue
            match = re.search(r"SUGGEST_PROFILE=(PROFILE_\d+)", value)
            if not match:
                continue
            token = match.group(1)
            if token in tokens:
                return token
    return None


def _suggest_profile_token(
    current_token: str,
    tokens: list[str],
    token_scores: dict[str, float],
    stable: bool,
    metrics: dict[str, Any],
) -> str:
    if stable:
        return current_token

    best_known = None
    best_score = float("-inf")
    for token, score in token_scores.items():
        if token == current_token:
            continue
        if score > best_score:
            best_known = token
            best_score = score

    if best_known and best_score > token_scores.get(current_token, -1.0):
        return best_known

    idx = tokens.index(current_token) if current_token in tokens else 0
    severity = int(metrics.get("missing", 0) or 0) + int(metrics.get("weak", 0) or 0) + int(metrics.get("click_failed", 0) or 0)
    step = 2 if severity >= 2 else 1
    return tokens[(idx + step) % len(tokens)]

def run_dspy_gepa_loop(args: argparse.Namespace, repo_root: Path, base_url: str, tune_params: list[str]) -> int:
    try:
        import dspy
        from dspy.adapters.chat_adapter import ChatAdapter, FieldInfoWithName
        from dspy.clients.lm import LM
        from dspy.signatures.field import OutputField
    except Exception as exc:
        print(f"[loop] dspy-gepa unavailable: {exc}")
        return 2

    run_timeout_sec = max(30, int(args.run_timeout_sec))
    stable_needed = max(1, int(args.stable_runs))
    max_confirm_runs = max(1, int(args.iterations))
    sleep_ms = max(0, int(args.sleep_ms))
    max_run_errors = max(1, int(args.max_run_errors))

    params = tune_params or list(TUNE_PARAM_SPACE.keys())
    profiles = _build_profile_library(
        base_url=base_url,
        params=params,
        seed=int(args.seed),
        max_profiles=max(2, int(args.dspy_profiles)),
    )
    tokens = [_profile_token(i) for i in range(len(profiles))]
    token_to_values = {token: profiles[i] for i, token in enumerate(tokens)}
    values_sig_to_token = {
        tuple(int(token_to_values[token][name]) for name in params): token for token in tokens
    }
    default_token = tokens[0]

    class RuleProfileLM(LM):
        def __init__(self, mapping: dict[str, dict[str, int]], default_profile: str):
            super().__init__("tabzer-rule-lm", "chat", 0.0, 1200, True)
            self.mapping = mapping
            self.default_profile = default_profile
            self.adapter = ChatAdapter()

        def _pick_token(self, messages: Any) -> str:
            text = "\n".join(str((m or {}).get("content", "")) for m in (messages or []))
            token = _extract_profile_token(text, tokens)
            return token or self.default_profile

        def __call__(self, prompt=None, messages=None, **kwargs):
            token = self._pick_token(messages)
            values = self.mapping.get(token, self.mapping[self.default_profile])
            params_json = json.dumps(values, ensure_ascii=True, separators=(",", ":"))

            fields = {
                FieldInfoWithName(name="params_json", info=OutputField()): params_json,
            }
            formatted = self.adapter.format_field_with_value(fields)
            n = max(1, int(kwargs.get("n", 1) or 1))
            outputs = [formatted for _ in range(n)]

            clean_kwargs = {k: v for k, v in kwargs.items() if not str(k).startswith("api_")}
            self.update_history(
                {
                    "prompt": prompt,
                    "messages": messages,
                    "kwargs": clean_kwargs,
                    "outputs": outputs,
                    "usage": 0,
                    "cost": 0,
                }
            )
            return outputs

        async def acall(self, prompt=None, messages=None, **kwargs):
            return self.__call__(prompt=prompt, messages=messages, **kwargs)

    class TuneSignature(dspy.Signature):
        context: str = dspy.InputField()
        params_json: str = dspy.OutputField(desc="Compact JSON object for tuning params.")

    class TuneProgram(dspy.Module):
        def __init__(self, initial_instruction: str):
            super().__init__()
            self.tune = dspy.Predict(TuneSignature)
            self.tune.signature.instructions = initial_instruction

        def forward(self, context: str):
            return self.tune(context=context)

    initial_values = token_to_values[default_token]
    initial_parts = [f"{name}={initial_values[name]}" for name in params]
    initial_instruction = (
        "Choose one profile token and output params_json as compact JSON only. "
        f"Allowed tokens: {', '.join(tokens)}. "
        f"Active profile token: {default_token}. "
        f"Current values: {', '.join(initial_parts)}."
    )

    context_text = (
        "Tune /play layout params for stable tab lines and click positioning. "
        f"Base URL: {base_url}. "
        "Keep params_json valid and complete."
    )

    trainset = [
        dspy.Example(context=f"{context_text} train#{i + 1}").with_inputs("context")
        for i in range(max(1, int(args.dspy_trainset_size)))
    ]
    valset = [
        dspy.Example(context=f"{context_text} val#{i + 1}").with_inputs("context")
        for i in range(max(1, int(args.dspy_valset_size)))
    ]

    eval_cache: dict[str, dict[str, Any]] = {}
    token_scores: dict[str, float] = {}
    metric_history: list[dict[str, Any]] = []
    run_errors = 0

    def evaluate_url(url: str, *, force: bool = False) -> dict[str, Any]:
        nonlocal run_errors
        if not force and url in eval_cache:
            return eval_cache[url]

        result = {
            "url": url,
            "payload": None,
            "stable": False,
            "score01": 0.0,
            "metrics": _default_metrics(),
            "error": None,
        }

        try:
            payload = run_once(repo_root, url, args.headless, run_timeout_sec, str(args.task or ""))
            stable = is_stable(
                payload,
                require_click_summary=bool(args.require_click_summary),
                min_click_pass_rate=float(args.min_click_pass_rate),
                max_click_failures=int(args.max_click_failures),
            )
            result["payload"] = payload
            result["stable"] = stable
            result["metrics"] = _metrics(payload)
            result["score01"] = _normalized_score_0_1(
                payload,
                require_click_summary=bool(args.require_click_summary),
                stable=stable,
            )
        except Exception as exc:
            run_errors += 1
            result["error"] = str(exc)
            if run_errors >= max_run_errors:
                print(f"[loop] warning: reached max run errors ({run_errors}) during GEPA evals")

        if not force:
            eval_cache[url] = result
        return result

    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        raw_params = getattr(pred, "params_json", None)
        values = _parse_predicted_param_values(raw_params, params)

        if values is None:
            score = 0.0
            feedback = (
                "Invalid params_json format. "
                f"SUGGEST_PROFILE={default_token} "
                "Expected a JSON object with all required tuning keys."
            )
        else:
            sig = tuple(int(values[name]) for name in params)
            token = values_sig_to_token.get(sig, default_token)
            url = _set_query_params(base_url, values)
            eval_result = evaluate_url(url, force=False)
            score = float(eval_result["score01"])
            metrics = dict(eval_result["metrics"])
            stable = bool(eval_result["stable"])
            token_scores[token] = max(token_scores.get(token, -1.0), score)
            suggested = _suggest_profile_token(token, tokens, token_scores, stable, metrics)
            feedback = (
                f"url={url} "
                f"stable={stable} "
                f"score01={score:.4f} "
                f"weak={metrics.get('weak', 0)} "
                f"missing={metrics.get('missing', 0)} "
                f"click_failed={metrics.get('click_failed', 0)} "
                f"click_pass={metrics.get('click_pass_rate', 0.0)} "
                f"SUGGEST_PROFILE={suggested}"
            )

            metric_history.append(
                {
                    "type": "metric",
                    "token": token,
                    "url": url,
                    "score01": round(score, 6),
                    "stable": stable,
                    "metrics": metrics,
                    "suggested_profile": suggested,
                    "error": eval_result.get("error"),
                }
            )

        if pred_name is None and pred_trace is None and trace is None:
            return float(score)
        return {"score": float(score), "feedback": feedback}

    class LocalInstructionProposer:
        def __init__(self, available_tokens: list[str], seed: int):
            self.tokens = available_tokens
            self.rng = Random(seed)
            self.cursor = 0
            self.last_choice: dict[str, str] = {}

        def __call__(self, candidate: dict[str, str], reflective_dataset, components_to_update):
            updates: dict[str, str] = {}
            for component in components_to_update:
                current_text = str(candidate.get(component, ""))
                current_token = _extract_profile_token(current_text, self.tokens) or default_token
                suggested = _extract_suggested_profile(reflective_dataset.get(component), self.tokens)
                chosen = suggested
                if (
                    not chosen
                    or chosen == current_token
                    or chosen == self.last_choice.get(component)
                ):
                    # Force exploration when GEPA keeps rejecting the same proposal.
                    for _ in range(max(1, len(self.tokens))):
                        probe = self.tokens[self.cursor % len(self.tokens)]
                        self.cursor += 1
                        if probe != current_token:
                            chosen = probe
                            break
                if not chosen:
                    chosen = _suggest_profile_token(
                        current_token,
                        self.tokens,
                        token_scores,
                        stable=False,
                        metrics=_default_metrics(),
                    )
                self.last_choice[component] = chosen
                updates[component] = _replace_profile_token(current_text, chosen)
            return updates

    dspy.configure(lm=RuleProfileLM(token_to_values, default_token))
    student = TuneProgram(initial_instruction=initial_instruction)

    gepa_kwargs: dict[str, Any] = {}
    if str(args.dspy_log_dir or "").strip():
        gepa_kwargs["log_dir"] = str(args.dspy_log_dir).strip()

    optimizer = dspy.GEPA(
        metric=metric,
        max_metric_calls=max(4, int(args.dspy_max_metric_calls)),
        instruction_proposer=LocalInstructionProposer(tokens, int(args.seed)),
        use_merge=False,
        num_threads=1,
        track_stats=True,
        warn_on_score_mismatch=False,
        seed=int(args.seed),
        **gepa_kwargs,
    )

    print(
        f"[loop] dspy-gepa starting with {len(tokens)} profiles, "
        f"max_metric_calls={max(4, int(args.dspy_max_metric_calls))}"
    )
    optimized = optimizer.compile(student, trainset=trainset, valset=valset)

    best_token = max(token_scores.items(), key=lambda kv: kv[1])[0] if token_scores else default_token
    best_values = token_to_values[best_token]
    best_url = _set_query_params(base_url, best_values)

    try:
        final_pred = optimized(context=context_text)
        parsed_final = _parse_predicted_param_values(getattr(final_pred, "params_json", None), params)
        if parsed_final is not None:
            sig = tuple(int(parsed_final[name]) for name in params)
            token_from_pred = values_sig_to_token.get(sig)
            if token_from_pred:
                best_token = token_from_pred
                best_values = token_to_values[best_token]
                best_url = _set_query_params(base_url, best_values)
    except Exception as exc:
        print(f"[loop] warning: could not read final DSPy prediction: {exc}")

    print(f"[loop] dspy-gepa selected token={best_token} values={json.dumps(best_values, ensure_ascii=True)}")
    print(f"[loop] best_url={best_url}")

    history: list[dict[str, Any]] = list(metric_history)
    stable_streak = 0
    for i in range(1, max_confirm_runs + 1):
        eval_result = evaluate_url(best_url, force=True)
        stable = bool(eval_result["stable"])
        metrics = eval_result["metrics"]
        score01 = float(eval_result["score01"])
        print(
            f"[loop] confirm={i} stable={stable} score01={score01:.4f} "
            f"byStatus={metrics.get('by_status', {})} "
            f"clickFailed={metrics.get('click_failed', 0)} clickPassRate={metrics.get('click_pass_rate', 0.0)} "
            f"systems={metrics.get('systems_traversed', 0)}/{metrics.get('required_systems', 0)} "
            f"frameGaps={metrics.get('frame_gap_count', 0)} audioStalls={metrics.get('audio_stall_count', 0)} "
            f"longTasks={metrics.get('long_task_count', 0)} "
            f"stationary={metrics.get('stationary_pair_count', 0)} "
            f"stationaryRate={float(metrics.get('stationary_pair_rate_pct', 0.0)):.2f}%"
        )
        history.append(
            {
                "type": "confirm",
                "run": i,
                "url": best_url,
                "stable": stable,
                "score01": round(score01, 6),
                "metrics": metrics,
                "error": eval_result.get("error"),
                "token": best_token,
                "values": best_values,
            }
        )

        if stable:
            stable_streak += 1
            print(f"[loop] stable_streak={stable_streak}/{stable_needed}")
            if stable_streak >= stable_needed:
                print(f"[loop] done: stabilized with dspy-gepa at confirm run {i}")
                _save_history(args.history_json, history)
                return 0
        else:
            stable_streak = 0

        if i < max_confirm_runs and sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    print("[loop] done: dspy-gepa confirm runs exhausted without stable streak")
    _save_history(args.history_json, history)
    return 1


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[3]

    base_url = _ensure_click_url_flags(args.url, bool(args.require_click_summary))
    if base_url != args.url:
        print(f"[loop] url normalized for click-summary mode: {base_url}")

    if args.optimizer == "dspy-gepa":
        tune_params = _parse_tune_params(args.tune_params)
        return run_dspy_gepa_loop(args, repo_root, base_url, tune_params)

    return run_local_loop(args, repo_root, base_url)


if __name__ == "__main__":
    raise SystemExit(main())
