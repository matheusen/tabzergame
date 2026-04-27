from __future__ import annotations

import argparse
import json
from pathlib import Path

from fix_orchestrator import FixLoopConfig, run_fix_loop


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run tab_debug_agent, classify the failure, try a constrained autofix, and rerun regressions."
    )
    parser.add_argument(
        "--task",
        default="synthetic-cursor-smooth-sync",
        help="Target task id or markdown path.",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:3000/play?id=joe-satriani-if-could-fly-v2",
        help="Target /play URL override for the task run.",
    )
    parser.add_argument("--headless", type=int, default=1, choices=[0, 1], help="1=headless, 0=visible browser.")
    parser.add_argument("--run-timeout-sec", type=int, default=300, help="Timeout per task execution.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum autofix strategies to try.")
    parser.add_argument("--sleep-ms", type=int, default=600, help="Delay between tuning candidates.")
    parser.add_argument(
        "--task-dir",
        default="backend/agents/tab_debug_agent/tasks",
        help="Directory containing task markdown specs.",
    )
    parser.add_argument(
        "--output-dir",
        default="backend/agents/tab_debug_agent/runs/autofix",
        help="Directory for autofix reports/history.",
    )
    parser.add_argument(
        "--regression-tasks",
        default="synthetic-cursor-smooth-sync,cursor-click-accuracy,vertical-line-click-test",
        help="Comma-separated regression task ids.",
    )
    parser.add_argument(
        "--allow-code-patches",
        type=int,
        default=1,
        choices=[0, 1],
        help="Allow constrained source patches for known issues.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the final JSON report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[3]
    regression_tasks = [item.strip() for item in str(args.regression_tasks or "").split(",") if item.strip()]
    config = FixLoopConfig(
        repo_root=repo_root,
        task_id=str(args.task or "").strip(),
        task_dir=(repo_root / str(args.task_dir)).resolve(),
        target_url=str(args.url or "").strip(),
        headless=int(args.headless),
        timeout_sec=max(30, int(args.run_timeout_sec)),
        max_attempts=max(1, int(args.max_attempts)),
        sleep_ms=max(0, int(args.sleep_ms)),
        output_dir=(repo_root / str(args.output_dir)).resolve(),
        regression_tasks=regression_tasks,
        allow_code_patches=bool(args.allow_code_patches),
    )
    report = run_fix_loop(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    latest = config.output_dir / "latest-fix-loop.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json_only:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"[tab-debug-fix] accepted={report.get('accepted')} task={config.task_id}")
        print(f"[tab-debug-fix] report={latest}")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
