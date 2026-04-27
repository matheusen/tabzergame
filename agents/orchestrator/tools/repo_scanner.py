"""Scan the repository for relevant files and code patterns."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def grep(
    pattern: str,
    root: Path,
    glob: str | None = None,
    case_insensitive: bool = False,
    max_results: int = 50,
) -> list[dict]:
    """Run ripgrep (rg) or fallback to git grep to find pattern occurrences."""
    results = _try_rg(pattern, root, glob, case_insensitive, max_results)
    if results is None:
        results = _try_git_grep(pattern, root, case_insensitive, max_results)
    return results or []


def _try_rg(pattern: str, root: Path, glob: str | None, ci: bool, limit: int) -> list[dict] | None:
    cmd = ["rg", "--json", "-n", f"-m{limit}"]
    if ci:
        cmd.append("-i")
    if glob:
        cmd += ["-g", glob]
    cmd += [pattern, str(root)]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=15, shell=False)
        stdout = proc.stdout.decode("utf-8", errors="replace")
        matches = []
        for line in stdout.splitlines():
            try:
                obj = json.loads(line)
                if obj.get("type") == "match":
                    data = obj["data"]
                    matches.append(
                        {
                            "file": data["path"]["text"],
                            "line": data["line_number"],
                            "text": data["lines"]["text"].rstrip(),
                        }
                    )
            except (json.JSONDecodeError, KeyError):
                continue
        return matches
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _try_git_grep(pattern: str, root: Path, ci: bool, limit: int) -> list[dict] | None:
    cmd = ["git", "grep", "-n"]
    if ci:
        cmd.append("-i")
    cmd += [pattern]
    try:
        proc = subprocess.run(cmd, capture_output=True, cwd=str(root), timeout=15, shell=False)
        stdout = proc.stdout.decode("utf-8", errors="replace")
        results = []
        for line in stdout.splitlines()[:limit]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                results.append({"file": parts[0], "line": int(parts[1]), "text": parts[2]})
        return results
    except Exception:
        return []


def find_files(root: Path, patterns: list[str], max_results: int = 100) -> list[str]:
    """Find files (not directories) matching glob patterns relative to root."""
    found = []
    for pattern in patterns:
        for p in sorted(root.glob(pattern))[:max_results]:
            if not p.is_file():
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            found.append(rel)
    return list(dict.fromkeys(found))


def read_file_safe(path: Path, max_chars: int = 8000) -> str:
    """Read a file, truncating if large."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n... (truncated, {len(content)} chars total)"
        return content
    except Exception as e:
        return f"<error reading {path}: {e}>"


def build_repo_context(
    root: Path,
    keywords: list[str],
    file_patterns: list[str] | None = None,
    max_files: int = 15,
) -> dict:
    """Build a context dict with relevant files and grep matches for the LLM."""
    context: dict = {"keywords": keywords, "matches": [], "files": []}

    for kw in keywords[:5]:
        matches = grep(kw, root, case_insensitive=True, max_results=10)
        context["matches"].extend(matches[:10])

    if file_patterns:
        context["files"] = find_files(root, file_patterns, max_results=max_files)

    return context
