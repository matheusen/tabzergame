from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from regression_suite import TaskEvaluation


@dataclass
class FailureClassification:
    primary: str
    confidence: float
    recommended_strategy: str
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    task_kind: str = "generic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_failure(
    payload: dict[str, Any],
    evaluation: TaskEvaluation,
) -> FailureClassification:
    click = payload.get("clickSummary") or {}
    by_status = payload.get("byStatus") or {}
    metrics = {
        "weak": int(by_status.get("weak", 0) or 0),
        "missing": int(by_status.get("missing", 0) or 0),
        "ok": int(by_status.get("ok", 0) or 0),
        "failuresCount": int(payload.get("failuresCount", 0) or 0),
        "suspectsCount": int(payload.get("suspectsCount", 0) or 0),
        "clickFailed": int(click.get("failed", 0) or 0),
        "passRate": float(click.get("passRate", 0.0) or 0.0),
        "freezeCount": int(click.get("freezeCount", 0) or 0),
        "hiddenCount": int(click.get("hiddenCount", 0) or 0),
        "backwardJumpCount": int(click.get("backwardJumpCount", 0) or 0),
        "frameGapCount": int(click.get("frameGapCount", 0) or 0),
        "audioStallCount": int(click.get("audioStallCount", 0) or 0),
        "longTaskCount": int(click.get("longTaskCount", 0) or 0),
        "systemsTraversed": int(click.get("systemsTraversed", 0) or 0),
        "requiredSystems": int(click.get("requiredSystems", 0) or 0),
        "stationaryPairRatePct": float(click.get("stationaryPairRatePct", 0.0) or 0.0),
        "maxStationaryPairRatePct": float(click.get("maxStationaryPairRatePct", 0.0) or 0.0),
        "velocityJitterRatioP90Pct": float(click.get("velocityJitterRatioP90Pct", 0.0) or 0.0),
        "maxVelocityJitterP90Pct": float(click.get("maxVelocityJitterP90Pct", 0.0) or 0.0),
        "velocityJitterSpikeCount": int(click.get("velocityJitterSpikeCount", 0) or 0),
        "maxVelocityJitterSpikeCount": int(click.get("maxVelocityJitterSpikeCount", 0) or 0),
        "displayHoldEventCount": int(click.get("displayHoldEventCount", 0) or 0),
        "maxDisplayHoldEventCount": int(click.get("maxDisplayHoldEventCount", 0) or 0),
        "targetJumpEventCount": int(click.get("targetJumpEventCount", 0) or 0),
        "maxTargetJumpEventCount": int(click.get("maxTargetJumpEventCount", 0) or 0),
    }
    reasons = list(evaluation.reasons)

    if evaluation.passed:
        return FailureClassification(
            primary="stable",
            confidence=0.99,
            recommended_strategy="none",
            reasons=reasons or ["Target task already passes."],
            metrics=metrics,
            task_kind=evaluation.task_kind,
        )

    if evaluation.task_kind == "playback":
        if metrics["backwardJumpCount"] > 0:
            reasons.append("Playback probe saw backward X jumps on the same system.")
            return FailureClassification(
                primary="same_system_backward_jump",
                confidence=0.92,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if metrics["audioStallCount"] > 0:
            reasons.append("Playback progress stalled while the cursor should have been advancing.")
            return FailureClassification(
                primary="clock_not_advancing",
                confidence=0.93,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if (
            metrics["maxVelocityJitterP90Pct"] > 0.0
            and metrics["velocityJitterRatioP90Pct"] > metrics["maxVelocityJitterP90Pct"]
        ) or (
            metrics["maxVelocityJitterSpikeCount"] > 0
            and metrics["velocityJitterSpikeCount"] > metrics["maxVelocityJitterSpikeCount"]
        ) or (
            metrics["displayHoldEventCount"] > metrics["maxDisplayHoldEventCount"]
        ) or (
            metrics["targetJumpEventCount"] > metrics["maxTargetJumpEventCount"]
        ):
            reasons.append("Playback stayed moving, but frame-to-frame cursor speed wobble exceeded the smoothness budget.")
            if metrics["targetJumpEventCount"] > 0:
                reasons.append("Playback debug also recorded synthetic target jumps in the recent smoothness window.")
            return FailureClassification(
                primary="cursor_velocity_wobble",
                confidence=0.88,
                recommended_strategy="fix_continuous_cursor_geometry",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if metrics["freezeCount"] > 0 or (
            metrics["stationaryPairRatePct"] > 0.0
            and metrics["stationaryPairRatePct"] > metrics["maxStationaryPairRatePct"]
        ):
            reasons.append("Cursor stayed effectively stationary on the same system.")
            return FailureClassification(
                primary="cursor_target_frozen",
                confidence=0.9,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if metrics["frameGapCount"] > 0 or metrics["longTaskCount"] > 0:
            reasons.append("Playback probe saw frame gaps or long tasks correlated with motion hitching.")
            return FailureClassification(
                primary="cursor_render_jank",
                confidence=0.84,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if metrics["systemsTraversed"] < metrics["requiredSystems"]:
            reasons.append("Playback did not traverse the expected systems.")
            return FailureClassification(
                primary="cursor_not_progressing",
                confidence=0.8,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )
        if metrics["hiddenCount"] > 0:
            reasons.append("Cursor became hidden during playback.")
            return FailureClassification(
                primary="cursor_hidden_during_playback",
                confidence=0.78,
                recommended_strategy="fix_synth_cursor_clock",
                reasons=reasons,
                metrics=metrics,
                task_kind=evaluation.task_kind,
            )

    if metrics["clickFailed"] > 0:
        reasons.append("Click probes are landing outside the expected column or system.")
        return FailureClassification(
            primary="click_misaligned",
            confidence=0.9,
            recommended_strategy="tune_layout_params",
            reasons=reasons,
            metrics=metrics,
            task_kind=evaluation.task_kind,
        )

    if (
        metrics["weak"] > 0
        or metrics["missing"] > 0
        or metrics["failuresCount"] > 0
        or metrics["suspectsCount"] > 0
    ):
        reasons.append("System/layout scan still reports weak or missing tab structures.")
        return FailureClassification(
            primary="layout_spacing_bad",
            confidence=0.74,
            recommended_strategy="tune_layout_params",
            reasons=reasons,
            metrics=metrics,
            task_kind=evaluation.task_kind,
        )

    reasons.append("The task is failing but the payload does not match a stronger signature yet.")
    return FailureClassification(
        primary="unknown_regression",
        confidence=0.45,
        recommended_strategy="tune_layout_params" if evaluation.task_kind != "playback" else "fix_synth_cursor_clock",
        reasons=reasons,
        metrics=metrics,
        task_kind=evaluation.task_kind,
    )
