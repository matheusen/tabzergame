#!/usr/bin/env python3
"""
Bug Team Orchestrator
Runs frontend and backend bug agents in parallel, aggregates results.

Usage:
  python backend/agents/bug_team/run_orchestrator.py           # both
  python backend/agents/bug_team/run_orchestrator.py --frontend
  python backend/agents/bug_team/run_orchestrator.py --backend
  python backend/agents/bug_team/run_orchestrator.py --all --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNS_DIR = _REPO_ROOT / "backend" / "agents" / "bug_team" / "runs"
_RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Import agents relative to repo root
sys.path.insert(0, str(_REPO_ROOT / "backend" / "agents" / "frontend_bug_agent"))
sys.path.insert(0, str(_REPO_ROOT / "backend" / "agents" / "backend_bug_agent"))


def _run_frontend(url: str, use_playwright: bool) -> dict[str, Any]:
    import run_agent as fe_agent  # type: ignore[import]
    return fe_agent.run(use_playwright=use_playwright, url=url)


def _run_backend(url: str) -> dict[str, Any]:
    import run_agent as be_agent  # type: ignore[import]
    return be_agent.run(fastapi_url=url)


def run(
    run_frontend: bool = True,
    run_backend: bool = True,
    frontend_url: str = "http://localhost:3000",
    backend_url: str = "http://localhost:8000",
    use_playwright: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
        "agents": {},
        "summary": {},
    }

    futures: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        if run_frontend:
            futures["frontend"] = pool.submit(_run_frontend, frontend_url, use_playwright)
        if run_backend:
            futures["backend"] = pool.submit(_run_backend, backend_url)

        for name, future in futures.items():
            try:
                report["agents"][name] = future.result(timeout=300)
            except Exception as exc:
                report["agents"][name] = {"error": str(exc), "summary": {"verdict": "ERROR"}}

    # Aggregate summary
    all_verdicts = [
        agent.get("summary", {}).get("verdict", "ERROR")
        for agent in report["agents"].values()
    ]
    total_errors = sum(
        agent.get("summary", {}).get("totalErrors", 0)
        for agent in report["agents"].values()
    )
    fe_summary = report["agents"].get("frontend", {}).get("summary", {})
    be_summary = report["agents"].get("backend", {}).get("summary", {})

    report["summary"] = {
        "verdict": "PASS" if all(v == "PASS" for v in all_verdicts) else "FAIL",
        "totalErrors": total_errors,
        "frontend": {
            "verdict": fe_summary.get("verdict", "SKIPPED"),
            "tscErrors": fe_summary.get("tscErrors", 0),
            "eslintErrors": fe_summary.get("eslintErrors", 0),
            "browserErrors": fe_summary.get("browserErrors", 0),
        },
        "backend": {
            "verdict": be_summary.get("verdict", "SKIPPED"),
            "lintErrors": be_summary.get("lintErrors", 0),
            "lintWarnings": be_summary.get("lintWarnings", 0),
            "apiUp": be_summary.get("apiUp", False),
            "importFailures": be_summary.get("importFailures", 0),
        },
    }

    # Save
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = _RUNS_DIR / f"bug-team-{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_RUNS_DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[bug_team] Report saved: {out_path}", file=sys.stderr)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Bug Team Orchestrator")
    parser.add_argument("--frontend", action="store_true", help="Run only frontend agent")
    parser.add_argument("--backend", action="store_true", help="Run only backend agent")
    parser.add_argument("--all", action="store_true", dest="run_all", help="Run both (default)")
    parser.add_argument("--playwright", action="store_true", help="Enable Playwright browser check")
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON to stdout")
    args = parser.parse_args()

    # Default: run both unless a specific flag is given
    run_fe = args.frontend or args.run_all or not args.backend
    run_be = args.backend or args.run_all or not args.frontend

    report = run(
        run_frontend=run_fe,
        run_backend=run_be,
        frontend_url=args.frontend_url,
        backend_url=args.backend_url,
        use_playwright=args.playwright,
    )

    s = report["summary"]
    fe = s.get("frontend", {})
    be = s.get("backend", {})
    print(
        f"\n[bug_team] {s['verdict']} | Total errors: {s['totalErrors']}\n"
        f"  Frontend: {fe.get('verdict','SKIPPED')} | "
        f"TSC={fe.get('tscErrors',0)} ESLint={fe.get('eslintErrors',0)} Browser={fe.get('browserErrors',0)}\n"
        f"  Backend:  {be.get('verdict','SKIPPED')} | "
        f"Lint={be.get('lintErrors',0)} Warnings={be.get('lintWarnings',0)} "
        f"API={'UP' if be.get('apiUp') else 'DOWN'} ImportFail={be.get('importFailures',0)}"
    )

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False))

    sys.exit(0 if s["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
