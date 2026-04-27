from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from run_agent import is_click_task_spec, is_playback_task_spec, load_task_spec
from run_loop import _default_metrics, _metrics, _score, is_stable, run_once


@dataclass
class TaskEvaluation:
    task_id: str
    task_kind: str
    passed: bool
    score: float
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _task_kind(task_id: str, task_dir: Path) -> str:
    task = load_task_spec(task_id, task_dir)
    if not task:
        return "generic"
    if is_playback_task_spec(task):
        return "playback"
    if is_click_task_spec(task):
        return "click"
    return "generic"


def evaluate_payload_for_task(payload: dict[str, Any], task_id: str, task_dir: Path) -> TaskEvaluation:
    kind = _task_kind(task_id, task_dir)
    by_status = payload.get("byStatus") or {}
    weak = int(by_status.get("weak", 0) or 0)
    missing = int(by_status.get("missing", 0) or 0)
    failures_count = int(payload.get("failuresCount", 0) or 0)
    suspects_count = int(payload.get("suspectsCount", 0) or 0)
    click = payload.get("clickSummary") or {}

    if kind == "playback":
        verdict = str(click.get("verdict") or "").upper() == "PASS"
        systems_traversed = int(click.get("systemsTraversed", 0) or 0)
        required_systems = int(click.get("requiredSystems", 0) or 0)
        stationary_pair_rate = float(click.get("stationaryPairRatePct", 0.0) or 0.0)
        max_stationary_pair_rate = float(click.get("maxStationaryPairRatePct", 0.0) or 0.0)
        velocity_jitter_ratio_p90 = float(click.get("velocityJitterRatioP90Pct", 0.0) or 0.0)
        max_velocity_jitter_p90 = float(click.get("maxVelocityJitterP90Pct", 0.0) or 0.0)
        velocity_jitter_spike_count = int(click.get("velocityJitterSpikeCount", 0) or 0)
        max_velocity_jitter_spike_count = int(click.get("maxVelocityJitterSpikeCount", 0) or 0)
        display_hold_event_count = int(click.get("displayHoldEventCount", 0) or 0)
        max_display_hold_event_count = int(click.get("maxDisplayHoldEventCount", 0) or 0)
        target_jump_event_count = int(click.get("targetJumpEventCount", 0) or 0)
        max_target_jump_event_count = int(click.get("maxTargetJumpEventCount", 0) or 0)
        hidden_count = int(click.get("hiddenCount", 0) or 0)
        backward_jump_count = int(click.get("backwardJumpCount", 0) or 0)
        reasons: list[str] = []
        if int(click.get("freezeCount", 0) or 0) > 0:
            reasons.append(f"freezeCount={int(click.get('freezeCount', 0) or 0)}")
        if hidden_count > 0:
            reasons.append(f"hiddenCount={hidden_count}")
        if backward_jump_count > 0:
            reasons.append(f"backwardJumpCount={backward_jump_count}")
        if int(click.get("audioStallCount", 0) or 0) > 0:
            reasons.append(f"audioStallCount={int(click.get('audioStallCount', 0) or 0)}")
        if int(click.get("frameGapCount", 0) or 0) > 0:
            reasons.append(f"frameGapCount={int(click.get('frameGapCount', 0) or 0)}")
        if int(click.get("longTaskCount", 0) or 0) > 0:
            reasons.append(f"longTaskCount={int(click.get('longTaskCount', 0) or 0)}")
        if systems_traversed < required_systems:
            reasons.append(f"systemsTraversed={systems_traversed}/{required_systems}")
        if stationary_pair_rate > max_stationary_pair_rate > 0.0:
            reasons.append(
                f"stationaryPairRatePct={round(stationary_pair_rate, 2)}/{round(max_stationary_pair_rate, 2)}"
            )
        if velocity_jitter_ratio_p90 > max_velocity_jitter_p90 > 0.0:
            reasons.append(
                f"velocityJitterRatioP90Pct={round(velocity_jitter_ratio_p90, 2)}/{round(max_velocity_jitter_p90, 2)}"
            )
        if velocity_jitter_spike_count > max_velocity_jitter_spike_count > 0:
            reasons.append(
                f"velocityJitterSpikeCount={velocity_jitter_spike_count}/{max_velocity_jitter_spike_count}"
            )
        if display_hold_event_count > max_display_hold_event_count >= 0:
            reasons.append(
                f"displayHoldEventCount={display_hold_event_count}/{max_display_hold_event_count}"
            )
        if target_jump_event_count > max_target_jump_event_count >= 0:
            reasons.append(
                f"targetJumpEventCount={target_jump_event_count}/{max_target_jump_event_count}"
            )
        if weak or missing or failures_count or suspects_count:
            reasons.append(
                f"scan weak={weak} missing={missing} failures={failures_count} suspects={suspects_count}"
            )

        pass_rate = float(click.get("passRate", 0.0) or 0.0)
        score = pass_rate * 30.0
        score -= int(click.get("freezeCount", 0) or 0) * 600.0
        score -= hidden_count * 540.0
        score -= backward_jump_count * 420.0
        score -= int(click.get("frameGapCount", 0) or 0) * 360.0
        score -= int(click.get("audioStallCount", 0) or 0) * 500.0
        score -= int(click.get("longTaskCount", 0) or 0) * 210.0
        score -= max(0.0, stationary_pair_rate - max_stationary_pair_rate) * 18.0
        if max_velocity_jitter_p90 > 0.0:
            score -= max(0.0, velocity_jitter_ratio_p90 - max_velocity_jitter_p90) * 10.0
        if max_velocity_jitter_spike_count > 0:
            score -= max(0, velocity_jitter_spike_count - max_velocity_jitter_spike_count) * 8.0
        score -= max(0, display_hold_event_count - max_display_hold_event_count) * 18.0
        score -= max(0, target_jump_event_count - max_target_jump_event_count) * 24.0
        score -= weak * 160.0 + missing * 240.0 + failures_count * 140.0 + suspects_count * 80.0
        passed = verdict and weak == 0 and missing == 0 and failures_count == 0 and suspects_count == 0
        if passed:
            score += 100000.0
        return TaskEvaluation(
            task_id=task_id,
            task_kind=kind,
            passed=passed,
            score=round(score, 3),
            reasons=reasons,
            metrics=dict(click),
        )

    if kind == "click":
        passed = is_stable(
            payload,
            require_click_summary=True,
            min_click_pass_rate=100.0,
            max_click_failures=0,
        )
        score = _score(payload, require_click_summary=True, stable=passed)
        reasons = []
        if not passed:
            failures = list((click.get("failures") or [])[:10]) if isinstance(click, dict) else []
            if failures:
                reasons.extend(
                    str(item.get("reasons") or item.get("kind") or "click failure") for item in failures
                )
            else:
                reasons.append("Click regression did not meet 100% pass rate.")
        return TaskEvaluation(
            task_id=task_id,
            task_kind=kind,
            passed=passed,
            score=round(score, 3),
            reasons=reasons,
            metrics=_metrics(payload),
        )

    metrics = _default_metrics()
    metrics.update(_metrics(payload))
    passed = weak == 0 and missing == 0 and failures_count == 0 and suspects_count == 0
    score = 1000.0 + metrics["ok"] * 5.0
    score -= weak * 180.0 + missing * 260.0 + failures_count * 120.0 + suspects_count * 60.0
    if passed:
        score += 100000.0
    reasons = []
    if not passed:
        reasons.append(f"scan weak={weak} missing={missing} failures={failures_count} suspects={suspects_count}")
    return TaskEvaluation(
        task_id=task_id,
        task_kind=kind,
        passed=passed,
        score=round(score, 3),
        reasons=reasons,
        metrics=metrics,
    )


def run_task_and_evaluate(
    repo_root: Path,
    *,
    task_id: str,
    url: str,
    headless: int,
    timeout_sec: int,
    task_dir: Path,
) -> tuple[dict[str, Any], TaskEvaluation]:
    payload = run_once(repo_root=repo_root, url=url, headless=headless, timeout_sec=timeout_sec, task=task_id)
    evaluation = evaluate_payload_for_task(payload, task_id=task_id, task_dir=task_dir)
    return payload, evaluation


def run_regression_suite(
    repo_root: Path,
    *,
    task_ids: list[str],
    url: str,
    headless: int,
    timeout_sec: int,
    task_dir: Path,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    passed_all = True
    for task_id in task_ids:
        payload, evaluation = run_task_and_evaluate(
            repo_root,
            task_id=task_id,
            url=url,
            headless=headless,
            timeout_sec=timeout_sec,
            task_dir=task_dir,
        )
        if not evaluation.passed:
            passed_all = False
        results.append(
            {
                "taskId": task_id,
                "passed": evaluation.passed,
                "score": evaluation.score,
                "reasons": evaluation.reasons,
                "metrics": evaluation.metrics,
                "payloadSummary": {
                    "byStatus": payload.get("byStatus"),
                    "failuresCount": payload.get("failuresCount"),
                    "suspectsCount": payload.get("suspectsCount"),
                    "clickSummary": payload.get("clickSummary"),
                },
            }
        )
    return {
        "passed": passed_all,
        "results": results,
    }
