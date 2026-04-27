"""cursor_smooth_agent.py

Autonomous cursor-smoothness agent for Tabzer /play page.

Detects quicadas (kicks/bounces), pausas (pauses) and travadas (freezes)
during synthetic playback, then applies targeted source-code patches,
waits for Next.js HMR hot-reload, and validates improvements.

Usage
-----
python backend/agents/tab_debug_agent/cursor_smooth_agent.py
python backend/agents/tab_debug_agent/cursor_smooth_agent.py --iterations 4 --headless 0
python backend/agents/tab_debug_agent/cursor_smooth_agent.py --url http://localhost:3000/play?id=my-tab --json-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent
REPO_ROOT = _DIR.parents[2]
PAGE_TSX = REPO_ROOT / "frontend" / "src" / "app" / "play" / "page.tsx"
CONTINUOUS_CURSOR_TS = REPO_ROOT / "frontend" / "src" / "app" / "play" / "_lib" / "continuous-cursor.ts"
OUTPUT_DIR = _DIR / "runs" / "cursor-smooth"

# ── Smoothness score weights ──────────────────────────────────────────────────

_SCORE_WEIGHTS = {
    "freeze": 20.0,
    "kick": 15.0,
    "stall": 15.0,
    "hidden": 10.0,
    "frame_gap": 8.0,
    "long_task": 4.0,
    "stationary_rate_excess": 0.8,    # per %-point over budget
    "jitter_p90_excess": 0.4,          # per %-point over budget
    "jitter_spike": 3.0,
    "display_hold": 2.0,
    "target_jump": 3.0,
    "systems_short": 25.0,
}


# ── Patch candidate definitions ───────────────────────────────────────────────

@dataclass
class PatchVariant:
    old: str
    new: str


@dataclass
class PatchCandidate:
    name: str
    failure_modes: list[str]   # which primary failure modes this targets
    target_file: Path          # file to patch
    variants: list[PatchVariant]
    description: str

    def find_applicable_variant(self) -> PatchVariant | None:
        """Return the first variant whose 'old' string is present in the target file."""
        text = self.target_file.read_text(encoding="utf-8")
        for v in self.variants:
            if v.old in text:
                return v
        return None

    def apply(self, variant: PatchVariant) -> dict[str, Any]:
        """Patch the file in-place; return a rollback token."""
        text = self.target_file.read_text(encoding="utf-8")
        if variant.old not in text:
            return {"ok": False, "reason": "old_string_not_found"}
        backup = self.target_file.with_suffix(self.target_file.suffix + ".csm.bak")
        shutil.copyfile(self.target_file, backup)
        patched = text.replace(variant.old, variant.new, 1)
        self.target_file.write_text(patched, encoding="utf-8")
        return {
            "ok": True,
            "backup": str(backup),
            "target": str(self.target_file),
            "variant_name": f"{self.name}",
        }

    @staticmethod
    def rollback(token: dict[str, Any]) -> bool:
        backup = token.get("backup")
        target = token.get("target")
        if not backup or not target:
            return False
        backup_path = Path(str(backup))
        target_path = Path(str(target))
        if backup_path.exists():
            shutil.copyfile(backup_path, target_path)
            backup_path.unlink(missing_ok=True)
            return True
        return False


def _build_patch_catalog(page_tsx: Path, continuous_ts: Path) -> list[PatchCandidate]:
    return [
        # ── Kick / backward-jump fixes ─────────────────────────────────────
        PatchCandidate(
            name="reduce_max_backward_step_v1",
            failure_modes=["kick", "jitter"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="          const maxBackwardStepPx = 1.75;",
                    new="          const maxBackwardStepPx = 0.8;",
                ),
            ],
            description="Reduce per-frame backward cap 1.75→0.8px (soften anchor-handoff kicks)",
        ),
        PatchCandidate(
            name="reduce_max_backward_step_v2",
            failure_modes=["kick"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="          const maxBackwardStepPx = 1.75;",
                    new="          const maxBackwardStepPx = 0.5;",
                ),
                PatchVariant(
                    old="          const maxBackwardStepPx = 0.8;",
                    new="          const maxBackwardStepPx = 0.5;",
                ),
            ],
            description="Reduce per-frame backward cap to 0.5px (aggressive anti-kick)",
        ),
        # ── Freeze / display-hold / rest-drift fixes ───────────────────────
        PatchCandidate(
            name="raise_drift_floor_v1",
            failure_modes=["freeze", "display_hold", "stall"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="            const driftSpeed = Math.max(0.015, Math.min(0.12, continuationSpeed));",
                    new="            const driftSpeed = Math.max(0.025, Math.min(0.12, continuationSpeed));",
                ),
            ],
            description="Raise rest-drift floor 0.015→0.025 px/ms (ensures visible motion through rests)",
        ),
        PatchCandidate(
            name="raise_drift_floor_v2",
            failure_modes=["freeze", "display_hold"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="            const driftSpeed = Math.max(0.015, Math.min(0.12, continuationSpeed));",
                    new="            const driftSpeed = Math.max(0.04, Math.min(0.12, continuationSpeed));",
                ),
                PatchVariant(
                    old="            const driftSpeed = Math.max(0.025, Math.min(0.12, continuationSpeed));",
                    new="            const driftSpeed = Math.max(0.04, Math.min(0.12, continuationSpeed));",
                ),
            ],
            description="Raise rest-drift floor 0.015→0.04 px/ms (more aggressive anti-freeze)",
        ),
        PatchCandidate(
            name="raise_fallback_drift_floor",
            failure_modes=["freeze", "display_hold"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="            const driftSpeedPxPerMs = Math.max(0.015, Math.min(0.06, fallbackAdvance / Math.max(1, continuationSpanMs)));",
                    new="            const driftSpeedPxPerMs = Math.max(0.025, Math.min(0.06, fallbackAdvance / Math.max(1, continuationSpanMs)));",
                ),
            ],
            description="Raise fallback-path drift floor 0.015→0.025 px/ms",
        ),
        # ── Audio buffer / stall fixes ──────────────────────────────────────
        PatchCandidate(
            name="lower_buffer_time",
            failure_modes=["stall"],
            target_file=page_tsx,
            variants=[
                PatchVariant(
                    old="    playerSettings.bufferTimeInMilliseconds = 1000;",
                    new="    playerSettings.bufferTimeInMilliseconds = 320;",
                ),
            ],
            description="Lower AlphaTab audio buffer 1000→320ms (improves synth responsiveness)",
        ),
        # ── Jitter / uneven speed fixes ─────────────────────────────────────
        PatchCandidate(
            name="widen_monotonic_hermite_guard",
            failure_modes=["jitter"],
            target_file=continuous_ts,
            variants=[
                PatchVariant(
                    old="    nextAnchorX > immediateStartX + 1;",
                    new="    nextAnchorX > immediateStartX + 2;",
                ),
            ],
            description="Require next anchor to be > 2px ahead (reduce degenerate Hermite runs)",
        ),
    ]


# ── Scoring ───────────────────────────────────────────────────────────────────

def compute_score(click_summary: dict[str, Any]) -> float:
    """Compute a smoothness score 0–100 from clickSummary. Higher = smoother."""
    if not click_summary:
        return 0.0
    w = _SCORE_WEIGHTS
    penalty = 0.0
    penalty += click_summary.get("freezeCount", 0) * w["freeze"]
    penalty += click_summary.get("backwardJumpCount", 0) * w["kick"]
    penalty += click_summary.get("audioStallCount", 0) * w["stall"]
    penalty += click_summary.get("hiddenCount", 0) * w["hidden"]
    penalty += click_summary.get("frameGapCount", 0) * w["frame_gap"]
    penalty += click_summary.get("longTaskCount", 0) * w["long_task"]
    penalty += click_summary.get("velocityJitterSpikeCount", 0) * w["jitter_spike"]
    penalty += click_summary.get("displayHoldEventCount", 0) * w["display_hold"]
    penalty += click_summary.get("targetJumpEventCount", 0) * w["target_jump"]
    stat_rate = float(click_summary.get("stationaryPairRatePct") or 0.0)
    max_stat = float(click_summary.get("maxStationaryPairRatePct") or 8.0)
    if stat_rate > max_stat:
        penalty += (stat_rate - max_stat) * w["stationary_rate_excess"]
    jitter_p90 = click_summary.get("velocityJitterRatioP90Pct")
    max_jitter = float(click_summary.get("maxVelocityJitterP90Pct") or 35.0)
    if isinstance(jitter_p90, (int, float)) and max_jitter > 0 and float(jitter_p90) > max_jitter:
        penalty += (float(jitter_p90) - max_jitter) * w["jitter_p90_excess"]
    systems = int(click_summary.get("systemsTraversed") or 0)
    required = int(click_summary.get("requiredSystems") or 2)
    if systems < required:
        penalty += (required - systems) * w["systems_short"]
    return round(max(0.0, 100.0 - penalty), 2)


# ── Failure classification ────────────────────────────────────────────────────

def classify_failure(click_summary: dict[str, Any]) -> str:
    """Return the dominant failure mode string or 'smooth'."""
    if not click_summary:
        return "unknown"
    if click_summary.get("audioStallCount", 0) > 0:
        return "stall"
    if click_summary.get("backwardJumpCount", 0) > 0:
        return "kick"
    freeze_count = int(click_summary.get("freezeCount") or 0)
    display_hold = int(click_summary.get("displayHoldEventCount") or 0)
    if freeze_count > 0 or display_hold > 2:
        return "freeze"
    if click_summary.get("velocityJitterSpikeCount", 0) > 4:
        jitter_p90 = float(click_summary.get("velocityJitterRatioP90Pct") or 0.0)
        if jitter_p90 > 40:
            return "jitter"
    if click_summary.get("hiddenCount", 0) > 0:
        return "hidden"
    if click_summary.get("frameGapCount", 0) > 0:
        return "gap"
    stat_rate = float(click_summary.get("stationaryPairRatePct") or 0.0)
    max_stat = float(click_summary.get("maxStationaryPairRatePct") or 5.0)
    if stat_rate > max_stat:
        return "freeze"
    if click_summary.get("targetJumpEventCount", 0) > 1:
        return "kick"
    if click_summary.get("displayHoldEventCount", 0) > 0:
        return "display_hold"
    return "smooth"


def failure_summary(click_summary: dict[str, Any]) -> str:
    """Return a short human-readable description of failures."""
    if not click_summary:
        return "no data"
    parts = []
    if click_summary.get("freezeCount", 0):
        parts.append(f"freeze×{click_summary['freezeCount']}")
    if click_summary.get("backwardJumpCount", 0):
        parts.append(f"kick×{click_summary['backwardJumpCount']}")
    if click_summary.get("audioStallCount", 0):
        parts.append(f"stall×{click_summary['audioStallCount']}")
    if click_summary.get("hiddenCount", 0):
        parts.append(f"hidden×{click_summary['hiddenCount']}")
    if click_summary.get("frameGapCount", 0):
        parts.append(f"gap×{click_summary['frameGapCount']}")
    if click_summary.get("displayHoldEventCount", 0):
        parts.append(f"hold×{click_summary['displayHoldEventCount']}")
    if click_summary.get("targetJumpEventCount", 0):
        parts.append(f"jump×{click_summary['targetJumpEventCount']}")
    stat_rate = float(click_summary.get("stationaryPairRatePct") or 0.0)
    max_stat = float(click_summary.get("maxStationaryPairRatePct") or 5.0)
    if stat_rate > max_stat:
        parts.append(f"stationary={stat_rate:.1f}%>{max_stat:.0f}%")
    jitter_p90 = click_summary.get("velocityJitterRatioP90Pct")
    if isinstance(jitter_p90, (int, float)) and float(jitter_p90) > float(click_summary.get("maxVelocityJitterP90Pct") or 35.0):
        parts.append(f"jitterP90={jitter_p90:.1f}%")
    if not parts:
        verdict = str(click_summary.get("verdict") or "")
        return "PASS" if verdict == "PASS" else "ok (below thresholds)"
    return ", ".join(parts)


# ── Subprocess runner ─────────────────────────────────────────────────────────

def run_probe(
    task: str,
    url: str,
    headless: int,
    timeout_sec: int,
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run run_agent.py with --no-openai --codex-stdout-only and return the parsed payload."""
    cmd = [
        sys.executable,
        str(_DIR / "run_agent.py"),
        "--task", task,
        "--url", url,
        "--no-openai",
        "--codex-stdout-only",
        "--headless", str(headless),
        "--wait-ms", "15000",
        "--tab-shots", "0",
    ]
    if verbose:
        print(f"[csm] probe cmd: {' '.join(cmd)}", flush=True)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(REPO_ROOT),
        )
        stdout = result.stdout.strip()
        # The agent prints exactly one JSON line when --codex-stdout-only
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        if verbose:
            print(f"[csm] probe stderr: {result.stderr[-1200:]}", flush=True)
        return {}
    except subprocess.TimeoutExpired:
        return {"error": "probe_timeout"}
    except Exception as exc:
        return {"error": str(exc)}


# ── Wait for Next.js HMR ──────────────────────────────────────────────────────

def wait_for_hmr(delay_sec: int, *, verbose: bool = False) -> None:
    """Sleep for delay_sec to allow Next.js HMR to pick up file changes."""
    if verbose:
        print(f"[csm] waiting {delay_sec}s for Next.js HMR hot-reload …", flush=True)
    time.sleep(delay_sec)


# ── Main loop ─────────────────────────────────────────────────────────────────

@dataclass
class AttemptRecord:
    iteration: int
    patch_name: str
    patch_description: str
    failure_mode_before: str
    score_before: float
    score_after: float
    improved: bool
    accepted: bool
    rejection_reason: str = ""
    rollback_ok: bool = False


@dataclass
class AgentReport:
    task: str
    url: str
    headless: int
    started_at: str
    baseline_score: float
    baseline_failure_mode: str
    baseline_summary: str
    final_score: float
    final_failure_mode: str
    final_summary: str
    accepted_patches: list[str]
    attempts: list[dict[str, Any]]
    best_click_summary: dict[str, Any]
    accepted: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_agent(args: argparse.Namespace) -> AgentReport:
    verbose = not args.json_only
    task = args.task
    url = args.url
    headless = args.headless
    timeout_sec = args.run_timeout_sec
    hmr_delay = args.hmr_delay_sec
    iterations = args.iterations
    min_improvement = args.min_improvement

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    patch_catalog = _build_patch_catalog(PAGE_TSX, CONTINUOUS_CURSOR_TS)

    if verbose:
        print(f"[csm] === Cursor Smooth Agent ===", flush=True)
        print(f"[csm] task={task}  url={url}  headless={headless}  iterations={iterations}", flush=True)
        print(f"[csm] page.tsx: {PAGE_TSX}", flush=True)

    # ── Baseline probe ──
    if verbose:
        print(f"\n[csm] -- BASELINE PROBE --", flush=True)
    baseline_payload = run_probe(task, url, headless, timeout_sec, verbose=verbose)
    baseline_click = baseline_payload.get("clickSummary") or {}
    baseline_score = compute_score(baseline_click)
    baseline_failure = classify_failure(baseline_click)
    baseline_summ = failure_summary(baseline_click)
    if verbose:
        print(f"[csm] baseline: score={baseline_score}  failure={baseline_failure}  detail={baseline_summ}", flush=True)

    best_score = baseline_score
    best_click = dict(baseline_click)
    best_failure = baseline_failure
    best_summ = baseline_summ
    accepted_patches: list[str] = []
    attempts: list[dict[str, Any]] = []
    active_token: dict[str, Any] | None = None

    if baseline_failure == "smooth" and baseline_score >= 95.0:
        if verbose:
            print(f"[csm] baseline is already smooth (score={baseline_score}). Nothing to fix.", flush=True)
        return AgentReport(
            task=task,
            url=url,
            headless=headless,
            started_at=datetime.now(timezone.utc).isoformat(),
            baseline_score=baseline_score,
            baseline_failure_mode=baseline_failure,
            baseline_summary=baseline_summ,
            final_score=baseline_score,
            final_failure_mode=baseline_failure,
            final_summary=baseline_summ,
            accepted_patches=[],
            attempts=[],
            best_click_summary=best_click,
            accepted=True,
            message="Baseline already smooth — no patches needed.",
        )

    tried_patches: set[str] = set()
    iteration = 0

    while iteration < iterations and best_failure != "smooth":
        iteration += 1
        current_failure = best_failure
        if verbose:
            print(f"\n[csm] -- ITERATION {iteration}/{iterations}  failure={current_failure}  score={best_score} --", flush=True)

        # Pick the next untried patch candidate that targets current failure mode
        candidate = None
        for pc in patch_catalog:
            if pc.name in tried_patches:
                continue
            if current_failure in pc.failure_modes or current_failure == "unknown":
                candidate = pc
                break
        # If no targeted patch, try any untried patch
        if candidate is None:
            for pc in patch_catalog:
                if pc.name in tried_patches:
                    continue
                candidate = pc
                break

        if candidate is None:
            if verbose:
                print(f"[csm] no more patch candidates to try.", flush=True)
            break

        tried_patches.add(candidate.name)
        variant = candidate.find_applicable_variant()
        if variant is None:
            if verbose:
                print(f"[csm] [{candidate.name}] no applicable variant found (old string not in file). Skipping.", flush=True)
            attempts.append({
                "iteration": iteration,
                "patch_name": candidate.name,
                "status": "skipped",
                "reason": "old_string_not_found",
            })
            continue

        if verbose:
            print(f"[csm] [{candidate.name}] applying: {candidate.description}", flush=True)

        token = candidate.apply(variant)
        if not token.get("ok"):
            if verbose:
                print(f"[csm] [{candidate.name}] apply failed: {token.get('reason')}", flush=True)
            attempts.append({
                "iteration": iteration,
                "patch_name": candidate.name,
                "status": "skipped",
                "reason": token.get("reason", "apply_failed"),
            })
            continue

        active_token = token
        wait_for_hmr(hmr_delay, verbose=verbose)

        if verbose:
            print(f"[csm] [{candidate.name}] re-probing …", flush=True)
        post_payload = run_probe(task, url, headless, timeout_sec, verbose=verbose)
        post_click = post_payload.get("clickSummary") or {}
        post_score = compute_score(post_click)
        post_failure = classify_failure(post_click)
        post_summ = failure_summary(post_click)
        improved = post_score >= best_score + min_improvement

        if verbose:
            print(
                f"[csm] [{candidate.name}] before={best_score}  after={post_score}  "
                f"improved={improved}  failure={post_failure}  detail={post_summ}",
                flush=True,
            )

        record: dict[str, Any] = {
            "iteration": iteration,
            "patch_name": candidate.name,
            "patch_description": candidate.description,
            "failure_mode_before": current_failure,
            "score_before": best_score,
            "score_after": post_score,
            "improved": improved,
        }

        if improved:
            accepted_patches.append(candidate.name)
            best_score = post_score
            best_click = dict(post_click)
            best_failure = post_failure
            best_summ = post_summ
            active_token = None
            record["accepted"] = True
            if verbose:
                print(f"[csm] [{candidate.name}] ACCEPTED — new best score={best_score}", flush=True)
        else:
            # Roll back
            rollback_ok = PatchCandidate.rollback(token)
            active_token = None
            wait_for_hmr(max(2, hmr_delay // 2), verbose=verbose)
            record["accepted"] = False
            record["rollback_ok"] = rollback_ok
            record["rejection_reason"] = (
                f"score did not improve by >= {min_improvement}pts "
                f"({best_score:.1f} → {post_score:.1f})"
            )
            if verbose:
                print(f"[csm] [{candidate.name}] REJECTED + rolled back (rollback_ok={rollback_ok})", flush=True)

        attempts.append(record)

        # If perfect, stop early
        if best_failure == "smooth" and best_score >= 95.0:
            if verbose:
                print(f"[csm] reached smooth state after patch. Stopping early.", flush=True)
            break

    if active_token:
        PatchCandidate.rollback(active_token)
        active_token = None

    accepted = best_failure == "smooth" or best_score >= 95.0
    message = (
        f"Smooth after {len(accepted_patches)} patch(es): {', '.join(accepted_patches)}"
        if accepted_patches and accepted
        else f"Best score={best_score:.1f}, failure={best_failure}. Patches tried: {len(attempts)}."
    )
    if not accepted and not accepted_patches:
        message = f"No patch improved smoothness. Baseline={baseline_score:.1f}, best={best_score:.1f}."

    return AgentReport(
        task=task,
        url=url,
        headless=headless,
        started_at=datetime.now(timezone.utc).isoformat(),
        baseline_score=baseline_score,
        baseline_failure_mode=baseline_failure,
        baseline_summary=baseline_summ,
        final_score=best_score,
        final_failure_mode=best_failure,
        final_summary=best_summ,
        accepted_patches=accepted_patches,
        attempts=attempts,
        best_click_summary=best_click,
        accepted=accepted,
        message=message,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous cursor smoothness agent: detects quicadas/pausas/travadas and patches them away."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugCursor=1",
        help="Target /play URL (debugCursor=1 is appended automatically if missing).",
    )
    parser.add_argument(
        "--task",
        default="cursor-glide-quality",
        help="Task id to run (default: cursor-glide-quality).",
    )
    parser.add_argument(
        "--headless",
        type=int,
        default=1,
        choices=[0, 1],
        help="1=headless browser, 0=visible (useful for debugging).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=4,
        help="Maximum number of patch-and-probe iterations.",
    )
    parser.add_argument(
        "--min-improvement",
        type=float,
        default=5.0,
        help="Minimum score improvement (pts) to accept a patch.",
    )
    parser.add_argument(
        "--hmr-delay-sec",
        type=int,
        default=5,
        help="Seconds to wait for Next.js HMR hot-reload after patching.",
    )
    parser.add_argument(
        "--run-timeout-sec",
        type=int,
        default=180,
        help="Timeout per probe invocation.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Directory to save run reports.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only final JSON report (no progress logs).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Ensure debugCursor=1 is in the URL for smoothness event tracking
    url = args.url
    if "debugCursor=1" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}debugCursor=1"
    args.url = url

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load .env so run_agent.py can find OPENAI_API_KEY if needed
    env_path = REPO_ROOT / "backend" / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass

    report = run_agent(args)
    report_dict = report.to_dict()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = output_dir / f"csm-{stamp}.json"
    report_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = output_dir / "latest-csm.json"
    latest_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report_dict, ensure_ascii=False))
    else:
        print(f"\n[csm] ══════════════ RESULT ══════════════")
        print(f"[csm] accepted={report.accepted}")
        print(f"[csm] baseline:  score={report.baseline_score}  failure={report.baseline_failure_mode}  ({report.baseline_summary})")
        print(f"[csm] final:     score={report.final_score}  failure={report.final_failure_mode}  ({report.final_summary})")
        print(f"[csm] patches:   {report.accepted_patches or '(none)'}")
        print(f"[csm] message:   {report.message}")
        print(f"[csm] report:    {report_path}")

    return 0 if report.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
