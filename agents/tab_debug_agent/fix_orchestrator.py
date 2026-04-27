from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from attempt_memory import AttemptMemory
from failure_classifier import FailureClassification, classify_failure
from patch_strategies import StrategyContext, available_strategies
from regression_suite import evaluate_payload_for_task, run_regression_suite, run_task_and_evaluate


@dataclass
class FixLoopConfig:
    repo_root: Path
    task_id: str
    task_dir: Path
    target_url: str
    headless: int
    timeout_sec: int
    max_attempts: int
    sleep_ms: int
    output_dir: Path
    regression_tasks: list[str]
    allow_code_patches: bool


def _attempt_signature(strategy_name: str, result: dict[str, Any]) -> str:
    candidate_url = str(result.get("candidate_url") or "")
    files = ",".join(sorted(str(item) for item in (result.get("files_touched") or [])))
    return f"{strategy_name}|{candidate_url}|{files}"


def run_fix_loop(config: FixLoopConfig) -> dict[str, Any]:
    memory_path = config.output_dir / "autofix-history.json"
    memory = AttemptMemory.load(memory_path)

    baseline_payload, baseline_eval = run_task_and_evaluate(
        config.repo_root,
        task_id=config.task_id,
        url=config.target_url,
        headless=config.headless,
        timeout_sec=config.timeout_sec,
        task_dir=config.task_dir,
    )
    baseline_classification = classify_failure(baseline_payload, baseline_eval)

    report: dict[str, Any] = {
        "taskId": config.task_id,
        "targetUrl": config.target_url,
        "baseline": {
            "evaluation": baseline_eval.to_dict(),
            "classification": baseline_classification.to_dict(),
            "payloadSummary": {
                "byStatus": baseline_payload.get("byStatus"),
                "failuresCount": baseline_payload.get("failuresCount"),
                "suspectsCount": baseline_payload.get("suspectsCount"),
                "clickSummary": baseline_payload.get("clickSummary"),
                "runFile": baseline_payload.get("runFile"),
            },
        },
        "attempts": [],
        "accepted": False,
    }

    if baseline_eval.passed:
        report["accepted"] = True
        report["message"] = "Target task already passes; no fix attempt was needed."
        return report

    ordered = available_strategies(allow_code_patches=config.allow_code_patches)
    ordered.sort(
        key=lambda item: 0 if item.name == baseline_classification.recommended_strategy else 1
    )

    attempted = 0
    for strategy in ordered:
        if attempted >= max(1, config.max_attempts):
            break
        if not strategy.applies(baseline_classification):
            continue

        attempted += 1
        context = StrategyContext(
            repo_root=config.repo_root,
            task_id=config.task_id,
            task_dir=config.task_dir,
            target_url=config.target_url,
            headless=config.headless,
            timeout_sec=config.timeout_sec,
            classification=baseline_classification,
            baseline_payload=baseline_payload,
            baseline_score=baseline_eval.score,
            max_attempts=max(2, config.max_attempts),
            sleep_ms=config.sleep_ms,
        )
        result = strategy.apply(context)
        signature = _attempt_signature(
            strategy.name,
            {
                "candidate_url": result.candidate_url,
                "files_touched": result.files_touched,
            },
        )
        if memory.has_rejected_signature(strategy=strategy.name, signature=signature):
            report["attempts"].append(
                {
                    "strategy": strategy.name,
                    "status": "skipped",
                    "reason": "Previously rejected identical attempt.",
                    "result": result.to_dict(),
                }
            )
            continue

        post_url = result.candidate_url or config.target_url
        accepted = False
        rejection_reason = ""
        post_payload: dict[str, Any] | None = None
        post_eval = None
        post_classification: FailureClassification | None = None
        regression_result: dict[str, Any] | None = None

        if result.applied:
            post_payload, post_eval = run_task_and_evaluate(
                config.repo_root,
                task_id=config.task_id,
                url=post_url,
                headless=config.headless,
                timeout_sec=config.timeout_sec,
                task_dir=config.task_dir,
            )
            post_classification = classify_failure(post_payload, post_eval)
            if post_eval.score <= baseline_eval.score:
                rejection_reason = (
                    f"Score did not improve (baseline={baseline_eval.score}, post={post_eval.score})."
                )
            elif not post_eval.passed:
                rejection_reason = "Target task still fails after the strategy."
            else:
                regression_result = run_regression_suite(
                    config.repo_root,
                    task_ids=config.regression_tasks,
                    url=post_url,
                    headless=config.headless,
                    timeout_sec=config.timeout_sec,
                    task_dir=config.task_dir,
                )
                if regression_result.get("passed"):
                    accepted = True
                else:
                    rejection_reason = "Regression suite failed after the target-task fix."
        else:
            rejection_reason = result.summary

        if not accepted and result.rollback_token:
            strategy.rollback(context, result)

        attempt_record = {
            "taskId": config.task_id,
            "strategy": strategy.name,
            "signature": signature,
            "accepted": accepted,
            "candidateUrl": post_url,
            "result": result.to_dict(),
            "postEvaluation": post_eval.to_dict() if post_eval else None,
            "postClassification": post_classification.to_dict() if post_classification else None,
            "regression": regression_result,
            "rejectionReason": rejection_reason or None,
        }
        report["attempts"].append(attempt_record)
        memory.append(attempt_record)

        if accepted:
            report["accepted"] = True
            report["final"] = {
                "url": post_url,
                "strategy": strategy.name,
                "evaluation": post_eval.to_dict() if post_eval else None,
                "classification": post_classification.to_dict() if post_classification else None,
                "regression": regression_result,
                "filesTouched": result.files_touched,
            }
            return report

    report["message"] = "No automatic strategy produced an accepted fix."
    return report
