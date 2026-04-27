# Commander Agent

CLI REPL that dispatches natural-language commands to Tabzer's agent subsystems. Supports both keyboard input and hands-free voice mode via the browser's Web Speech API.

---

## Quick Start

```bash
# Text mode
python backend/agents/commander/run_commander.py

# Voice mode (opens browser with microphone UI)
python backend/agents/commander/run_commander.py --voice
```

No extra dependencies — voice server uses Python stdlib only.

---

## Architecture

```
run_commander.py
      │
      ▼
command_parser.py   ← keyword scoring → CommandIntent
      │
      ▼
dispatcher.py       ← subprocess call to the correct agent
      │
      ├─ study_agent/run_agent.py
      ├─ bug_team/run_orchestrator.py
      ├─ tab_debug_agent/run_agent.py
      └─ copilot_adapter.py → gh copilot suggest/explain

voice_server.py     ← stdlib http.server on :7432
                       SpeechRecognition API → POST /transcript
                       threading.Queue → commander REPL
```

---

## Example Commands

### Study Agent

```
gera 2 exercicios para escalas
cria teoria para campo harmonico
gera 3 exercicios tecnicos de postura
adiciona exercicios para arpejos
```

The agent reads `OPENAI_API_KEY` from `backend/.env`. If the key is absent it generates template exercises offline.

### Bug Team

```
fix bugs
verifica erros de frontend
verifica backend
fix frontend
```

Runs `tsc`, `eslint`, `ruff`, health checks in parallel. Saves results to `backend/agents/bug_team/runs/`.

### Copilot (gh copilot)

```
explica git rebase -i HEAD~3
sugere como otimizar uma query SQL lenta
como fazer um cherry-pick sem conflito
```

Requires the `gh` CLI and the `gh copilot` extension:

```bash
gh extension install github/gh-copilot
```

### Tab Debug / Cursor Probe

```
debug cursor
probe playback
```

Runs `cursor-glide-quality` task (headless=0 so you can watch the browser).

### Internal Commands

| Command | Effect |
|---------|--------|
| `help` / `?` | Show help |
| `status` | Show gh/copilot availability |
| `quit` / `exit` | Exit REPL |

---

## Voice Mode

Voice mode opens `http://localhost:7432` in your default browser.

Requirements:
- **Chrome or Edge** (Firefox does not support Web Speech API)
- Microphone permission granted in the browser
- HTTPS is **not** required for `localhost` (Chrome exception)

Workflow:
1. Click **▶ Iniciar** in the browser
2. Speak your command in Portuguese or English
3. The transcript is sent to the local server and dispatched automatically
4. The browser automatically restarts listening after each command

---

## Integration

The dispatcher uses `subprocess` with **list args** (no `shell=True`) for security. Each agent call runs in a child process, isolated from the Commander process.

Study agent exercises are appended directly to `frontend/src/app/study/studyExercises.ts`. Use `--dry-run` prefix... or type `"dry run: gera 3 exercicios"` — the parser will honour it when the `dry_run` param is set manually.

---

## Files

| File | Purpose |
|------|---------|
| `run_commander.py` | Main entry point — text and voice REPL |
| `command_parser.py` | Keyword scoring → `CommandIntent` |
| `dispatcher.py` | Routes intent to agent subprocess / copilot |
| `copilot_adapter.py` | Wraps `gh copilot suggest/explain` |
| `voice_server.py` | Stdlib HTTP server + Web Speech API HTML |
