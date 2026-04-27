# Tabzer Agent Orchestrator

MVP seguro para rodar diagnostico, bugfix e feature em worktree isolada.

## Uso rapido

```bash
python backend/agents/orchestrator/main.py providers

python backend/agents/orchestrator/main.py diagnose \
  --request "Por que o cursor da micro-pausas no player?" \
  --provider none

python backend/agents/orchestrator/main.py bugfix \
  --request "Corrigir micro-pausas do cursor no player" \
  --autonomy 3 \
  --provider claude-code
```

Tambem funciona com modulo Python:

```bash
python -m backend.agents.orchestrator.main bugfix \
  --request "Corrigir flicker da tab no carregamento" \
  --autonomy 3 \
  --provider codex
```

python backend/agents/orchestrator/main.py bugfix --request "Corrigir micro-pausas do cursor no player" --autonomy 3 --provider codex


## Providers

- `auto`: detecta o primeiro provider disponivel.
- `claude-code`: usa o Claude Code CLI ou a extensao do VS Code quando encontrada.
- `codex`: usa `codex exec` em modo read-only para gerar JSON/diffs.
- `copilot`: usa `gh copilot` quando o GitHub CLI e a extensao estiverem instalados.
- `openai` / `anthropic`: usam SDKs se instalados e com API keys.
- `none`: modo deterministico, sem LLM. Gera diagnostico, plano e relatorio.

## Saidas

Cada execucao cria:

```text
.agent-runs/<task-id>/
  intent.json
  state.json
  baseline/results.json
  plan.json
  final-report.md
```

Com `--autonomy 3` ou maior, o orquestrador tenta criar:

```text
.agent-worktrees/<task-id>/
```

Se a worktree isolada nao puder ser criada, nenhum patch automatico e aplicado.
