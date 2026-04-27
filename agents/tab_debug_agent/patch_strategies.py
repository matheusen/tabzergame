from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from random import Random
from typing import Any

from failure_classifier import FailureClassification
from regression_suite import evaluate_payload_for_task
from run_loop import (
    TUNE_PARAM_SPACE,
    _format_params,
    _indices_signature,
    _initial_indices,
    _metrics,
    _next_candidate_indices,
    _url_from_indices,
    run_once,
)


@dataclass
class StrategyContext:
    repo_root: Path
    task_id: str
    task_dir: Path
    target_url: str
    headless: int
    timeout_sec: int
    classification: FailureClassification
    baseline_payload: dict[str, Any]
    baseline_score: float
    max_attempts: int
    sleep_ms: int


@dataclass
class StrategyResult:
    name: str
    applied: bool
    changed: bool
    summary: str
    candidate_url: str | None = None
    files_touched: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    rollback_token: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseStrategy:
    name = "base"

    def applies(self, classification: FailureClassification) -> bool:
        return True

    def apply(self, context: StrategyContext) -> StrategyResult:
        raise NotImplementedError

    def rollback(self, _context: StrategyContext, result: StrategyResult) -> None:
        token = result.rollback_token or {}
        backup = token.get("backup")
        target = token.get("target")
        if not backup or not target:
            return
        backup_path = Path(str(backup))
        target_path = Path(str(target))
        if backup_path.exists():
            shutil.copyfile(backup_path, target_path)
            backup_path.unlink(missing_ok=True)


class TuneLayoutParamsStrategy(BaseStrategy):
    name = "tune_layout_params"

    def applies(self, classification: FailureClassification) -> bool:
        return classification.task_kind != "playback" or classification.primary in {
            "layout_spacing_bad",
            "click_misaligned",
            "unknown_regression",
        }

    def _tune_params(self, classification: FailureClassification) -> list[str]:
        if classification.primary == "click_misaligned":
            return ["gapTarget", "topCropSafety", "bottomCropSafety", "stackFinalStaffGap", "stackSafetyGap"]
        return list(TUNE_PARAM_SPACE.keys())

    def apply(self, context: StrategyContext) -> StrategyResult:
        params = self._tune_params(context.classification)
        current_indices = _initial_indices(context.target_url, params)
        best_indices = dict(current_indices)
        best_url = _url_from_indices(context.target_url, current_indices, params)
        best_score = context.baseline_score
        history: list[dict[str, Any]] = []
        tried: set[tuple[int, ...]] = set()
        rng = Random(42)

        for idx in range(1, max(1, context.max_attempts) + 1):
            candidate_url = _url_from_indices(context.target_url, current_indices, params)
            payload = run_once(
                repo_root=context.repo_root,
                url=candidate_url,
                headless=context.headless,
                timeout_sec=context.timeout_sec,
                task=context.task_id,
            )
            evaluation = evaluate_payload_for_task(payload, task_id=context.task_id, task_dir=context.task_dir)
            metrics = _metrics(payload)
            history.append(
                {
                    "attempt": idx,
                    "url": candidate_url,
                    "score": evaluation.score,
                    "passed": evaluation.passed,
                    "tuned": _format_params(current_indices, params),
                    "metrics": metrics,
                }
            )
            tried.add(_indices_signature(current_indices, params))
            if evaluation.score > best_score:
                best_score = evaluation.score
                best_url = candidate_url
                best_indices = dict(current_indices)
            if evaluation.passed:
                best_url = candidate_url
                best_score = evaluation.score
                best_indices = dict(current_indices)
                break
            current_indices = _next_candidate_indices(
                best_indices=best_indices,
                params=params,
                tried=tried,
                max_neighbor_step=2,
                rng=rng,
            )
            if current_indices is None:
                break
            if context.sleep_ms > 0:
                time.sleep(context.sleep_ms / 1000.0)

        changed = best_url != context.target_url and best_score > context.baseline_score
        summary = (
            f"Best tuned URL score={round(best_score, 3)} params={_format_params(best_indices, params)}"
            if changed
            else "No tuned URL improved the baseline score."
        )
        return StrategyResult(
            name=self.name,
            applied=True,
            changed=changed,
            summary=summary,
            candidate_url=best_url if changed else None,
            details={
                "history": history,
                "params": params,
                "bestScore": best_score,
            },
        )


class FixSynthCursorClockStrategy(BaseStrategy):
    name = "fix_synth_cursor_clock"
    _old_deps = (
        "  }, [alphaTabApi, getAuthoritativeSyntheticPlayerClock, getEstimatedSyntheticCursorMs, "
        "getSyntheticAudioContext, getSyntheticCursorVisualLeadMs, rebaseSyntheticCursorClock, "
        "refreshSyntheticCursorLead, stopCursorPolling]);"
    )
    _new_deps = (
        "  }, [alphaTabApi, audioMode, isPlaying, getAuthoritativeSyntheticPlayerClock, "
        "getEstimatedSyntheticCursorMs, getSyntheticAudioContext, getSyntheticCursorVisualLeadMs, "
        "rebaseSyntheticCursorClock, refreshSyntheticCursorLead, stopCursorPolling]);"
    )

    def applies(self, classification: FailureClassification) -> bool:
        return classification.primary in {
            "clock_not_advancing",
            "cursor_target_frozen",
            "cursor_render_jank",
            "cursor_not_progressing",
            "cursor_hidden_during_playback",
            "unknown_regression",
        }

    def apply(self, context: StrategyContext) -> StrategyResult:
        target = context.repo_root / "frontend/src/app/play/page.tsx"
        if not target.exists():
            return StrategyResult(
                name=self.name,
                applied=False,
                changed=False,
                summary="Target file not found for synth clock patch.",
            )

        raw = target.read_text(encoding="utf-8")
        if self._new_deps in raw:
            return StrategyResult(
                name=self.name,
                applied=True,
                changed=False,
                summary="Synth clock dependency patch already present.",
                files_touched=[str(target)],
            )
        if self._old_deps not in raw:
            return StrategyResult(
                name=self.name,
                applied=False,
                changed=False,
                summary="Expected synth clock dependency pattern was not found; refusing broad patch.",
                files_touched=[str(target)],
            )

        backup = target.with_suffix(".autofix.bak")
        shutil.copyfile(target, backup)
        target.write_text(raw.replace(self._old_deps, self._new_deps, 1), encoding="utf-8")
        return StrategyResult(
            name=self.name,
            applied=True,
            changed=True,
            summary="Added audioMode/isPlaying to the synthetic cursor polling effect dependencies.",
            files_touched=[str(target)],
            rollback_token={"backup": str(backup), "target": str(target)},
        )


class PatchCursorMaxBackwardCapStrategy(BaseStrategy):
    """Reduce maxBackwardStepPx to soften anchor-handoff kicks / same-band backward jumps."""

    name = "patch_cursor_max_backward_cap"

    # Try progressively smaller caps: 0.8 first, then 0.5 if 0.8 didn't help.
    _variants: list[tuple[str, str]] = [
        (
            "          const maxBackwardStepPx = 1.75;",
            "          const maxBackwardStepPx = 0.8;",
        ),
        (
            "          const maxBackwardStepPx = 0.8;",
            "          const maxBackwardStepPx = 0.5;",
        ),
    ]

    def applies(self, classification: FailureClassification) -> bool:
        return classification.primary in {
            "clock_not_advancing",
            "cursor_target_frozen",
            "cursor_render_jank",
            "cursor_not_progressing",
            "unknown_regression",
        } or classification.task_kind == "playback"

    def apply(self, context: StrategyContext) -> StrategyResult:
        target = context.repo_root / "frontend/src/app/play/page.tsx"
        if not target.exists():
            return StrategyResult(
                name=self.name,
                applied=False,
                changed=False,
                summary="Target page.tsx not found.",
            )
        raw = target.read_text(encoding="utf-8")
        for old, new in self._variants:
            if old in raw:
                backup = target.with_suffix(".maxbwd.bak")
                shutil.copyfile(target, backup)
                target.write_text(raw.replace(old, new, 1), encoding="utf-8")
                return StrategyResult(
                    name=self.name,
                    applied=True,
                    changed=True,
                    summary=f"Patched maxBackwardStepPx: {old.strip()} → {new.strip()}",
                    files_touched=[str(target)],
                    rollback_token={"backup": str(backup), "target": str(target)},
                )
        return StrategyResult(
            name=self.name,
            applied=False,
            changed=False,
            summary="maxBackwardStepPx pattern not found (may already be at minimum or file changed).",
        )


class PatchCursorDriftFloorStrategy(BaseStrategy):
    """Raise the rest-drift speed floor so the cursor keeps moving visibly through musical rests."""

    name = "patch_cursor_drift_floor"

    _variants: list[tuple[str, str]] = [
        (
            "            const driftSpeed = Math.max(0.015, Math.min(0.12, continuationSpeed));",
            "            const driftSpeed = Math.max(0.025, Math.min(0.12, continuationSpeed));",
        ),
        (
            "            const driftSpeed = Math.max(0.025, Math.min(0.12, continuationSpeed));",
            "            const driftSpeed = Math.max(0.04, Math.min(0.12, continuationSpeed));",
        ),
    ]

    def applies(self, classification: FailureClassification) -> bool:
        return classification.primary in {
            "clock_not_advancing",
            "cursor_target_frozen",
            "cursor_not_progressing",
            "unknown_regression",
        } or classification.task_kind == "playback"

    def apply(self, context: StrategyContext) -> StrategyResult:
        target = context.repo_root / "frontend/src/app/play/page.tsx"
        if not target.exists():
            return StrategyResult(
                name=self.name,
                applied=False,
                changed=False,
                summary="Target page.tsx not found.",
            )
        raw = target.read_text(encoding="utf-8")
        for old, new in self._variants:
            if old in raw:
                backup = target.with_suffix(".drift.bak")
                shutil.copyfile(target, backup)
                target.write_text(raw.replace(old, new, 1), encoding="utf-8")
                return StrategyResult(
                    name=self.name,
                    applied=True,
                    changed=True,
                    summary=f"Raised drift floor: {old.strip()} → {new.strip()}",
                    files_touched=[str(target)],
                    rollback_token={"backup": str(backup), "target": str(target)},
                )
        return StrategyResult(
            name=self.name,
            applied=False,
            changed=False,
            summary="driftSpeed pattern not found in page.tsx.",
        )


def available_strategies(*, allow_code_patches: bool) -> list[BaseStrategy]:
    strategies: list[BaseStrategy] = [TuneLayoutParamsStrategy()]
    if allow_code_patches:
        strategies.extend([
            FixSynthCursorClockStrategy(),
            PatchCursorMaxBackwardCapStrategy(),
            PatchCursorDriftFloorStrategy(),
        ])
    return strategies
