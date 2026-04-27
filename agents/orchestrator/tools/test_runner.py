"""Run validation suites (typecheck, lint, tests) and return structured results."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ..schemas import ValidationResult
from .safe_shell import safe_run


def run_validation(
    name: str,
    command: list[str],
    cwd: Path,
    timeout_sec: int = 180,
) -> ValidationResult:
    result = safe_run(command, cwd=cwd, timeout_sec=timeout_sec)
    status: str
    if result.exit_code == -1:
        status = "timeout"
    elif result.exit_code == -2:
        status = "error"
    elif result.ok:
        status = "passed"
    else:
        status = "failed"

    return ValidationResult(
        name=name,
        command=command,
        status=status,
        exit_code=result.exit_code,
        stdout=result.stdout[:4000],  # cap to avoid huge JSON
        stderr=result.stderr[:2000],
        duration_sec=result.duration_sec,
    )


def run_frontend_validations(repo_root: Path, commands: list[list[str]]) -> list[ValidationResult]:
    frontend_dir = repo_root / "frontend"
    if not frontend_dir.exists():
        return [
            ValidationResult(
                name="frontend",
                command=[],
                status="skipped",
                stderr="frontend/ directory not found",
            )
        ]
    results = []
    for cmd in commands:
        name = " ".join(cmd)
        if _missing_npm_script(frontend_dir, cmd):
            results.append(
                ValidationResult(
                    name=name,
                    command=cmd,
                    status="skipped",
                    stderr=f"npm script not found: {cmd[2]}",
                )
            )
            continue
        if _npm_needs_missing_node_modules(frontend_dir, cmd):
            results.append(
                ValidationResult(
                    name=name,
                    command=cmd,
                    status="skipped",
                    stderr="frontend/node_modules not found in this workspace",
                )
            )
            continue
        results.append(run_validation(name, cmd, cwd=frontend_dir))
    return results


def run_backend_validations(repo_root: Path, commands: list[list[str]]) -> list[ValidationResult]:
    backend_dir = repo_root / "backend"
    if not backend_dir.exists():
        return [
            ValidationResult(
                name="backend",
                command=[],
                status="skipped",
                stderr="backend/ directory not found",
            )
        ]
    results = []
    for cmd in commands:
        name = " ".join(cmd)
        results.append(run_validation(name, cmd, cwd=backend_dir))
    return results


def run_generic_validations(repo_root: Path, commands: list[list[str]], cwd_relative: str = ".") -> list[ValidationResult]:
    cwd = repo_root / cwd_relative
    results = []
    for cmd in commands:
        name = " ".join(cmd)
        results.append(run_validation(name, cmd, cwd=cwd))
    return results


def run_game_validations(repo_root: Path, commands: list[list[str]] | None = None) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    results.append(_validate_godot_project_files(repo_root))
    results.extend(run_asset_validations(repo_root))

    configured = commands or []
    if configured:
        for cmd in configured:
            results.append(run_validation(" ".join(cmd), cmd, cwd=repo_root, timeout_sec=240))
        return results

    godot_bin = _find_godot_binary()
    if godot_bin is None:
        results.append(
            ValidationResult(
                name="godot headless smoke",
                command=[],
                status="skipped",
                stderr="Set GODOT_BIN or add godot/godot4 to PATH to run headless validation",
            )
        )
        return results

    results.append(
        run_validation(
            "godot project import",
            [godot_bin, "--headless", "--path", str(repo_root), "--editor", "--quit"],
            cwd=repo_root,
            timeout_sec=240,
        )
    )
    return results


def run_asset_validations(repo_root: Path) -> list[ValidationResult]:
    findings: list[str] = []
    warnings: list[str] = []
    for required in [
        "scenes/main.tscn",
        "scripts/player_controller.gd",
        "scripts/enemy_agent.gd",
    ]:
        if not (repo_root / required).exists():
            findings.append(f"Missing expected project file: {required}")

    root_pngs = [p.name for p in repo_root.glob("*.png")]
    if len(root_pngs) > 20:
        warnings.append("Many PNGs live at repo root; prefer art/Player, art/Enemies, art/Environment")

    orphan_imports = []
    for import_file in repo_root.rglob("*.import"):
        source = import_file.with_suffix("")
        if not source.exists():
            orphan_imports.append(str(import_file.relative_to(repo_root)).replace("\\", "/"))
    if orphan_imports:
        findings.append(f"Orphan .import files: {', '.join(orphan_imports[:5])}")

    return [
        ValidationResult(
            name="asset/project structure audit",
            command=[],
            status="failed" if findings else "passed",
            stdout="\n".join(findings + warnings),
        )
    ]


def all_passed(results: list[ValidationResult]) -> bool:
    return all(r.status in ("passed", "skipped") for r in results)


def _validate_godot_project_files(repo_root: Path) -> ValidationResult:
    findings = []
    if not (repo_root / "project.godot").exists():
        findings.append("project.godot not found")
    if not (repo_root / "scenes").exists():
        findings.append("scenes/ not found")
    if not (repo_root / "scripts").exists():
        findings.append("scripts/ not found")
    if not (repo_root / "art").exists():
        findings.append("art/ not found")

    return ValidationResult(
        name="godot project structure",
        command=[],
        status="failed" if findings else "passed",
        stdout="\n".join(findings),
    )


def _find_godot_binary() -> str | None:
    env_bin = os.environ.get("GODOT_BIN")
    if env_bin:
        return env_bin
    return shutil.which("godot4") or shutil.which("godot")


def _missing_npm_script(cwd: Path, command: list[str]) -> bool:
    if len(command) < 3 or command[0] != "npm" or command[1] != "run":
        return False
    package_json = cwd / "package.json"
    if not package_json.exists():
        return False
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    scripts = data.get("scripts", {})
    return command[2] not in scripts


def _npm_needs_missing_node_modules(cwd: Path, command: list[str]) -> bool:
    if not command or command[0] != "npm":
        return False
    return (cwd / "package.json").exists() and not (cwd / "node_modules").exists()
