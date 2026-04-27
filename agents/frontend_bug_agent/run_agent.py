#!/usr/bin/env python3
"""
Frontend Bug Agent
Runs TypeScript compilation and ESLint checks on the Next.js frontend.
Optionally captures browser console.error via Playwright.

Usage:
  python backend/agents/frontend_bug_agent/run_agent.py
  python backend/agents/frontend_bug_agent/run_agent.py --no-playwright
  python backend/agents/frontend_bug_agent/run_agent.py --url http://localhost:3000 --json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_DIR = _REPO_ROOT / "frontend"
_RUNS_DIR = _REPO_ROOT / "backend" / "agents" / "frontend_bug_agent" / "runs"
_RUNS_DIR.mkdir(parents=True, exist_ok=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "TIMEOUT"}
    except FileNotFoundError as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)}


def _parse_tsc_errors(output: str) -> list[dict[str, Any]]:
    errors = []
    for line in output.splitlines():
        # Format: path/file.ts(line,col): error TS1234: message
        import re
        m = re.match(r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)$", line)
        if m:
            errors.append({
                "file": m.group(1),
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "severity": m.group(4),
                "code": m.group(5),
                "message": m.group(6),
            })
    return errors


def _parse_eslint_json(output: str) -> list[dict[str, Any]]:
    try:
        raw = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return []
    issues = []
    for file_result in raw:
        for msg in file_result.get("messages", []):
            issues.append({
                "file": file_result.get("filePath", ""),
                "line": msg.get("line"),
                "col": msg.get("column"),
                "severity": "error" if msg.get("severity") == 2 else "warning",
                "ruleId": msg.get("ruleId"),
                "message": msg.get("message"),
            })
    return issues


def _playwright_console_errors(url: str, wait_ms: int = 5000) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [{"error": "playwright not installed — run: pip install playwright && playwright install chromium"}]

    console_errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def on_console(msg: Any) -> None:
                if msg.type in ("error", "warning"):
                    console_errors.append({"type": msg.type, "text": msg.text, "url": url})

            page.on("console", on_console)
            page.goto(url, timeout=wait_ms * 2)
            page.wait_for_timeout(wait_ms)
            browser.close()
    except Exception as exc:
        console_errors.append({"error": str(exc)})

    return console_errors


# ── main ──────────────────────────────────────────────────────────────────────

def run(
    use_playwright: bool = True,
    url: str = "http://localhost:3000",
    wait_ms: int = 5000,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "createdAt": datetime.datetime.utcnow().isoformat() + "Z",
        "frontendDir": str(_FRONTEND_DIR),
        "tsc": {},
        "eslint": {},
        "browser": [],
        "summary": {},
    }

    # 1. TypeScript check
    print("[frontend_bug_agent] Running tsc --noEmit ...", file=sys.stderr)
    tsc_result = _run(
        ["npx", "--yes", "tsc", "--noEmit", "--pretty", "false"],
        cwd=_FRONTEND_DIR,
        timeout=180,
    )
    tsc_errors = _parse_tsc_errors(tsc_result["stdout"] + tsc_result["stderr"])
    report["tsc"] = {
        "returncode": tsc_result["returncode"],
        "errors": tsc_errors,
        "errorCount": len([e for e in tsc_errors if e["severity"] == "error"]),
        "warningCount": len([e for e in tsc_errors if e["severity"] == "warning"]),
        "raw": tsc_result["stderr"][:4000] if tsc_result["returncode"] != 0 else "",
    }

    # 2. ESLint
    print("[frontend_bug_agent] Running eslint ...", file=sys.stderr)
    eslint_result = _run(
        ["npx", "--yes", "eslint", "src/", "--format", "json", "--max-warnings", "0"],
        cwd=_FRONTEND_DIR,
        timeout=180,
    )
    eslint_issues = _parse_eslint_json(eslint_result["stdout"])
    report["eslint"] = {
        "returncode": eslint_result["returncode"],
        "issues": eslint_issues,
        "errorCount": len([i for i in eslint_issues if i["severity"] == "error"]),
        "warningCount": len([i for i in eslint_issues if i["severity"] == "warning"]),
    }

    # 3. Browser console (optional)
    if use_playwright:
        print(f"[frontend_bug_agent] Checking browser console at {url} ...", file=sys.stderr)
        console_errs = _playwright_console_errors(url, wait_ms)
        report["browser"] = console_errs
    else:
        report["browser"] = []

    # 4. Summary
    total_errors = (
        report["tsc"]["errorCount"]
        + report["eslint"]["errorCount"]
        + len([e for e in report["browser"] if e.get("type") == "error" and "error" not in e])
    )
    report["summary"] = {
        "totalErrors": total_errors,
        "tscErrors": report["tsc"]["errorCount"],
        "eslintErrors": report["eslint"]["errorCount"],
        "browserErrors": len([e for e in report["browser"] if e.get("type") == "error"]),
        "verdict": "PASS" if total_errors == 0 else "FAIL",
    }

    # 5. Save
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = _RUNS_DIR / f"frontend-bug-{ts}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # update latest
    latest = _RUNS_DIR / "latest.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[frontend_bug_agent] Report saved: {out_path}", file=sys.stderr)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Frontend Bug Agent")
    parser.add_argument("--no-playwright", action="store_true", help="Skip browser console check")
    parser.add_argument("--url", default="http://localhost:3000", help="App URL for browser check")
    parser.add_argument("--wait-ms", type=int, default=5000, help="Browser wait time (ms)")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Print JSON report to stdout")
    args = parser.parse_args()

    report = run(
        use_playwright=not args.no_playwright,
        url=args.url,
        wait_ms=args.wait_ms,
    )

    summary = report["summary"]
    verdict = summary["verdict"]
    print(
        f"[frontend_bug_agent] {verdict} | "
        f"TSC errors: {summary['tscErrors']} | "
        f"ESLint errors: {summary['eslintErrors']} | "
        f"Browser errors: {summary['browserErrors']}"
    )

    if args.json_output:
        print(json.dumps(report, ensure_ascii=False))

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
