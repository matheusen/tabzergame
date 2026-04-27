"""
Tabzer Agent Orchestrator — CLI entry point.

Usage:
  python -m backend.agents.orchestrator.main bugfix --request "Fix cursor micro-pauses" --autonomy 3
  python -m backend.agents.orchestrator.main feature --request "Add Explain Tab button" --autonomy 3
  python -m backend.agents.orchestrator.main diagnose --request "Why is memory high?" --autonomy 1
  python -m backend.agents.orchestrator.main providers        # list available LLM providers
  python -m backend.agents.orchestrator.main list-runs
  python -m backend.agents.orchestrator.main show-run <task-id>

Provider options (--provider flag):
  auto         auto-detect best available (default)
  anthropic    Anthropic SDK (ANTHROPIC_API_KEY required, pip install anthropic)
  claude-code  Claude Code CLI (uses logged-in VSCode extension)
  openai       OpenAI SDK (OPENAI_API_KEY required)
  copilot      GitHub Copilot CLI (gh copilot, limited)
  codex        OpenAI Codex CLI
  none         deterministic mode, no LLM
"""
import sys
from pathlib import Path

if __package__ in (None, ""):
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir in sys.path:
        sys.path.remove(script_dir)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "agents.orchestrator"

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import argparse
import json


def _repo_root() -> Path:
    """Walk up from this file to find the repo root."""
    candidate = Path(__file__).resolve()
    for _ in range(6):
        candidate = candidate.parent
        if (candidate / "project.godot").exists():
            return candidate
        if (candidate / "frontend").exists() and (candidate / "backend").exists():
            return candidate
    return Path.cwd()


def _apply_provider(cfg, args: argparse.Namespace) -> None:
    """Override cfg.llm_provider from --provider flag if given."""
    provider = getattr(args, "provider", None)
    if provider:
        cfg.llm_provider = provider
        # Reset cached client so new provider is used
        from .tools.llm_client import get_client
        get_client(provider, cfg.llm_model, cfg.llm_model_fast, force_new=True)


def cmd_bugfix(args: argparse.Namespace, repo_root: Path) -> None:
    from .config import OrchestratorConfig
    from .agents.intake_agent import parse_request
    from .state import TaskState
    from .memory.run_store import RunStore
    from .workflows import bugfix_workflow, game_workflow, tabzer_workflow

    cfg = OrchestratorConfig.load()
    _apply_provider(cfg, args)
    runs_dir = repo_root / cfg.runs_dir

    task = parse_request(
        request=args.request,
        autonomy_level=args.autonomy,
        cfg=cfg,
        target_url=args.url,
    )

    print(f"\n[AgentOS] Task created: {task.task_id}")
    print(f"[AgentOS] Type: {task.task_type} | Area: {task.target_area} | Risk: {task.risk}")
    if task.acceptance_criteria:
        print("[AgentOS] Acceptance criteria:")
        for ac in task.acceptance_criteria:
            print(f"  ✓ {ac}")
    print()

    store = RunStore(runs_dir)

    # Check for similar past runs BEFORE recording this one
    similar = store.find_similar(task.title.split()[:3])
    if similar:
        print(f"[AgentOS] Found {len(similar)} similar past run(s):")
        for s in similar:
            print(f"  - {s['task_id']} ({s['status']}): {s.get('title', '')[:60]}")
        print()

    store.record_start(task)
    state = TaskState(task, runs_dir)

    # Select workflow
    if task.task_type in {"game_specialized", "level_design", "enemy_ai", "asset_pipeline", "render_pass", "mechanic"} or task.target_area in {"game", "player", "enemy_ai", "level", "asset_pipeline", "render", "audio", "ui"}:
        report = game_workflow.run(task, state, repo_root, cfg)
    elif task.task_type == "tabzer_specialized":
        report = tabzer_workflow.run(task, state, repo_root, cfg)
    else:
        report = bugfix_workflow.run(task, state, repo_root, cfg)

    store.record_finish(report)

    report_path = runs_dir / task.task_id / "final-report.md"
    print(f"\n[AgentOS] Done: {report_path}")
    print(f"[AgentOS] Status: {report.status.upper()}")
    print(f"[AgentOS] Duration: {report.duration_sec:.1f}s")
    if report.files_changed:
        print(f"[AgentOS] Files changed: {', '.join(report.files_changed)}")
    if report.recommendations:
        print("[AgentOS] Recommendations:")
        for r in report.recommendations[:3]:
            print(f"  → {r}")


def cmd_feature(args: argparse.Namespace, repo_root: Path) -> None:
    from .config import OrchestratorConfig
    from .agents.intake_agent import parse_request
    from .state import TaskState
    from .memory.run_store import RunStore
    from .workflows import feature_workflow, game_workflow

    cfg = OrchestratorConfig.load()
    _apply_provider(cfg, args)
    runs_dir = repo_root / cfg.runs_dir

    task = parse_request(
        request=args.request,
        autonomy_level=args.autonomy,
        cfg=cfg,
        target_url=getattr(args, "url", None),
    )
    if (repo_root / "project.godot").exists() and task.target_area not in {"frontend", "backend", "tabzer"}:
        task = task.model_copy(update={"task_type": "game_specialized", "target_area": "game"})
    else:
        task = task.model_copy(update={"task_type": "feature"})

    print(f"\n[AgentOS] Feature task: {task.task_id}")
    print(f"[AgentOS] Title: {task.title}")
    print()

    store = RunStore(runs_dir)
    store.record_start(task)
    state = TaskState(task, runs_dir)

    if task.task_type == "game_specialized":
        report = game_workflow.run(task, state, repo_root, cfg)
    else:
        report = feature_workflow.run(task, state, repo_root, cfg)
    store.record_finish(report)

    report_path = runs_dir / task.task_id / "final-report.md"
    print(f"\n[AgentOS] Done: {report_path}")
    print(f"[AgentOS] Status: {report.status.upper()}")
    if report.files_changed:
        print(f"[AgentOS] Files changed: {', '.join(report.files_changed)}")


def cmd_diagnose(args: argparse.Namespace, repo_root: Path) -> None:
    """Diagnosis only — no patching, autonomy forced to 1."""
    args.autonomy = 1
    cmd_bugfix(args, repo_root)


def cmd_list_runs(args: argparse.Namespace, repo_root: Path) -> None:
    from .config import OrchestratorConfig
    from .memory.run_store import RunStore

    cfg = OrchestratorConfig.load()
    store = RunStore(repo_root / cfg.runs_dir)
    runs = store.list_runs(limit=20)

    if not runs:
        print("[AgentOS] No runs found.")
        return

    print(f"\n{'ID':<35} {'Type':<20} {'Status':<12} {'Title'}")
    print("-" * 90)
    for r in runs:
        print(f"{r['task_id']:<35} {r['task_type']:<20} {r['status']:<12} {r.get('title', '')[:40]}")


def cmd_show_run(args: argparse.Namespace, repo_root: Path) -> None:
    from .config import OrchestratorConfig
    from .memory.run_store import RunStore

    cfg = OrchestratorConfig.load()
    store = RunStore(repo_root / cfg.runs_dir)
    report = store.get_final_report(args.task_id)

    if not report:
        print(f"[AgentOS] No report found for: {args.task_id}")
        return

    report_path = repo_root / cfg.runs_dir / args.task_id / "final-report.md"
    if report_path.exists():
        print(report_path.read_text(encoding="utf-8"))
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))


def cmd_providers(args: argparse.Namespace, repo_root: Path) -> None:
    """List all LLM providers and their availability."""
    from .tools.llm_client import list_providers

    print("\n[AgentOS] Available LLM providers:\n")
    print(f"  {'Provider':<15} {'Available':<10} {'Note'}")
    print("  " + "-" * 60)
    for p in list_providers():
        status = "YES" if p.available else "no"
        print(f"  {p.name:<15} {status:<10} {p.note}")
    print()
    print("  Use --provider <name> to select a specific provider.")
    print("  Default: auto (uses first available in priority order)")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Tabzer Agent Orchestrator — automated bugfix & feature development",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    _PROVIDER_CHOICES = ["auto", "anthropic", "claude-code", "openai", "copilot", "codex", "none"]

    # bugfix
    p_bugfix = sub.add_parser("bugfix", help="Fix a bug automatically")
    p_bugfix.add_argument("--request", "-r", required=True, help="Bug description in natural language")
    p_bugfix.add_argument("--autonomy", "-a", type=int, default=3, choices=range(0, 6), help="Autonomy level 0-5")
    p_bugfix.add_argument("--url", help="Target URL for browser-based validation")
    p_bugfix.add_argument("--provider", choices=_PROVIDER_CHOICES, default=None, help="LLM provider to use")
    p_bugfix.set_defaults(func=cmd_bugfix)

    # feature
    p_feat = sub.add_parser("feature", help="Implement a new feature")
    p_feat.add_argument("--request", "-r", required=True, help="Feature description")
    p_feat.add_argument("--autonomy", "-a", type=int, default=3, choices=range(0, 6))
    p_feat.add_argument("--provider", choices=_PROVIDER_CHOICES, default=None, help="LLM provider to use")
    p_feat.set_defaults(func=cmd_feature)

    # diagnose
    p_diag = sub.add_parser("diagnose", help="Diagnosis only — no code changes")
    p_diag.add_argument("--request", "-r", required=True, help="Issue to diagnose")
    p_diag.add_argument("--autonomy", "-a", type=int, default=1)
    p_diag.add_argument("--provider", choices=_PROVIDER_CHOICES, default=None, help="LLM provider to use")
    p_diag.add_argument("--url", help="Target URL")
    p_diag.set_defaults(func=cmd_diagnose)

    # list-runs
    p_list = sub.add_parser("list-runs", help="List past agent runs")
    p_list.set_defaults(func=cmd_list_runs)

    # show-run
    p_show = sub.add_parser("show-run", help="Show report for a specific run")
    p_show.add_argument("task_id", help="Task ID to inspect")
    p_show.set_defaults(func=cmd_show_run)

    # providers
    p_prov = sub.add_parser("providers", help="List available LLM providers")
    p_prov.set_defaults(func=cmd_providers)

    args = parser.parse_args()
    repo_root = _repo_root()
    print(f"[AgentOS] Repo root: {repo_root}")

    args.func(args, repo_root)


if __name__ == "__main__":
    main()
