#!/usr/bin/env python3
"""
Backend Bug Agent
Runs ruff lint, verifies FastAPI health, and spot-checks critical imports.

Usage:
  python backend/agents/backend_bug_agent/run_agent.py
  python backend/agents/backend_bug_agent/run_agent.py --url http://localhost:8000
  python backend/agents/backend_bug_agent/run_agent.py --json
"""
from __future__ import annotations

import argparse
import datetime
import importlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
_RUNS_DIR = _REPO_ROOT / "backend" / "agents" / "backend_bug_agent" / "runs"
_RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Modules that must be importable for the backend to function
_CRITICAL_MODULES = [
    "fastapi",
    "uvicorn",
    "pydantic",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "TIMEOUT"}
    except FileNotFoundError as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


def _parse_ruff(output: str) -> list[dict[str, Any]]:
    issues = []
    import re
    for line in output.splitlines():
        # Format: path/file.py:line:col: CODE message
        m = re.match(r"^(.+?):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)$", line)
        if m:
            issues.append({
                "file": m.group(1),
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "code": m.group(4),
                "message": m.group(5),
                "severity": "warning" if m.group(4).startswith(("W", "C")) else "error",
            })
    return issues


def _check_health(url: str, timeout: int = 5) -> dict[str, Any]:
    endpoints = [url.rstrip("/") + "/health", url.rstrip("/") + "/docs"]
    for endpoint in endpoints:
        try:
            req = urllib.request.Request(endpoint, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                return {"up": True, "endpoint": endpoint, "status": status}
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return {"up": True, "endpoint": endpoint, "status": e.code}
        except Exception:
            continue
    return {"up": False, "endpoint": url, "status": None}


def _check_imports(modules: list[str]) -> list[dict[str, Any]]:
    results = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            results.append({"module": mod, "ok": True})
        except ImportError as e:
            results.append({"module": mod, "ok": False, "error": str(e)})
    return results


# ── main ──────────────────────────────────────────────────────────────────────

def run(fastapi_url: str = "http://localhost:8000") -> dict[str, Any]:
    report: dict[str, Any] = {
        "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
        "backendDir": str(_BACKEND_DIR),
        "lint": {},
        "health": {},
        "imports": [],
        "summary": {},
    }

    # 1. Ruff lint
    print("[backend_bug_agent] Running ruff check ...", file=sys.stderr)
    ruff_result = _run(
        ["ruff", "check", "backend/", "--output-format", "text"],
        cwd=_REPO_ROOT,
        timeout=60,
    )
    if ruff_result["returncode"] == -1 and "No such file" in ruff_result["stderr"]:
        # ruff not installed — try pip
        ruff_result = _run(
            [sys.executable, "-m", "ruff", "check", "backend/", "--output-format", "text"],
            cwd=_REPO_ROOT,
            timeout=60,
        )
    ruff_issues = _parse_ruff(ruff_result["stdout"] + ruff_result["stderr"])
    report["lint"] = {
        "returncode": ruff_result["returncode"],
        "issues": ruff_issues,
        "errorCount": len([i for i in ruff_issues if i["severity"] == "error"]),
        "warningCount": len([i for i in ruff_issues if i["severity"] == "warning"]),
        "raw": ruff_result["stdout"][:3000] if ruff_issues else "",
    }

    # 2. Health check
    print(f"[backend_bug_agent] Checking FastAPI at {fastapi_url} ...", file=sys.stderr)
    report["health"] = _check_health(fastapi_url)

    # 3. Import checks
    print("[backend_bug_agent] Checking critical imports ...", file=sys.stderr)
    report["imports"] = _check_imports(_CRITICAL_MODULES)

    # 4. Summary
    import_failures = [i for i in report["imports"] if not i["ok"]]
    total_errors = report["lint"]["errorCount"] + len(import_failures)
    report["summary"] = {
        "totalErrors": total_errors,
        "lintErrors": report["lint"]["errorCount"],
        "lintWarnings": report["lint"]["warningCount"],
        "apiUp": report["health"]["up"],
        "importFailures": len(import_failures),
        "verdict": "PASS" if total_errors == 0 else "FAIL",
    }

    # 5. Save
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = _RUNS_DIR / f"backend-bug-{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (_RUNS_DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[backend_bug_agent] Report saved: {out_path}", file=sys.stderr)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend Bug Agent")
    parser.add_argument("--url", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON to stdout")
    args = parser.parse_args()

    report = run(fastapi_url=args.url)
    summary = report["summary"]
    verdict = summary["verdict"]
    api_status = "UP" if summary["apiUp"] else "DOWN"
    print(
        f"[backend_bug_agent] {verdict} | "
        f"Lint errors: {summary['lintErrors']} | "
        f"Warnings: {summary['lintWarnings']} | "
        f"API: {api_status} | "
        f"Import failures: {summary['importFailures']}"
    )

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False))

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
