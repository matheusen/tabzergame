# Tab Debug Agent

Agente para abrir a página `/play`, coletar `__tabzerSystemDebug` no browser e pedir diagnóstico para a OpenAI.

## Requisitos

1. Instalar dependências:

```bash
pip install -r backend/agents/tab_debug_agent/requirements.txt
```

2. Instalar browser do Playwright:

```bash
playwright install chromium
```

3. Garantir `OPENAI_API_KEY` em `backend/.env`.

4. (Opcional, tarefas Songsterr) adicionar credenciais no ambiente:

```env
SONGSTERR_EMAIL=seu_email
SONGSTERR_PASSWORD=sua_senha
```

Essas credenciais são usadas apenas em runtime para login e tentativa de ativar modo dark.
Elas não são salvas no `run-*.json`.

Fallback aceito: `UG_EMAIL` / `UG_PASSWORD`.

## Uso

```bash
python backend/agents/tab_debug_agent/run_agent.py ^
  --url "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugSystemLines=1" ^
  --headless 0
```

Modo tarefa (via markdown):

```bash
python backend/agents/tab_debug_agent/run_agent.py ^
  --task songsterr-lines-match ^
  --headless 0
```

Opções principais:

- `--url`: URL alvo da página.
- `--headless`: `1` para headless, `0` para abrir browser visível.
- `--model`: modelo OpenAI (default: `gpt-5.2`).
- `--wait-ms`: espera após abrir a página (default: `3500`).
- `--recent-limit`: tamanho do recorte de logs enviados ao LLM.
- `--keep-open`: mantém o browser aberto no final.
- `--screenshot`: salva apenas screenshot da TAB (não da página inteira).
- `--tab-shots`: captura prints da TAB e envia para OpenAI (`1` padrão, `0` desativa).
- `--tab-shots-max`: máximo de prints por execução (default: `8`).
- `--tab-shot-wait-ms`: espera entre passos de scroll na captura (default: `160`).
- `--emit-codex-stdout`: imprime também no stdout o JSON de `latest-codex`.
- `--codex-stdout-only`: imprime apenas o JSON (1 linha), ideal para integração direta.
- `--task`: id do arquivo de tarefa (`tasks/<id>.md`) ou caminho para `.md`.
- `--task-dir`: pasta das tarefas (default: `backend/agents/tab_debug_agent/tasks`).
- `--task-iterations`: número de rodadas de análise na mesma execução.

## Saída

O agente salva artefatos em `backend/agents/tab_debug_agent/runs/`:

- snapshot completo do debug (`scan/summary/failures/suspects/recent`);
- diagnóstico textual da OpenAI;
- metadados de execução.
- `latest-codex.json` com resumo sempre atualizado para consumo rápido no Codex.
- prints da TAB em `runs/tab-*.jpeg` (quando `--tab-shots=1`).
- no `run-*.json`: `tab_screenshots_sent` com o que foi realmente enviado (path, bytes, sha256).
- no `run-*.json` em modo tarefa: `reference_screenshots`, `reference_screenshots_sent` e `task`.

Observação: o agente só captura a área da TAB (container do player). Se não detectar contexto de TAB (`/play`/`__tabzerSystemDebug`), ele não salva screenshot.

## Retorno para Codex

Após cada execução, o agente imprime:

```txt
[tab-debug-agent] codex_file=.../backend/agents/tab_debug_agent/runs/latest-codex.json
```

Esse arquivo já contém:

- `byStatus` e `byCause` do scan;
- caminho do `runFile` completo;
- `diagnosis` pronto para ingestão no Codex.

Integração direta (stdout JSON):

```bash
python backend/agents/tab_debug_agent/run_agent.py ^
  --url "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugSystemLines=1" ^
  --headless 1 ^
  --codex-stdout-only
```

Exemplo para tarefa de comparação com Songsterr:

```bash
python backend/agents/tab_debug_agent/run_agent.py ^
  --task songsterr-lines-match ^
  --headless 1 ^
  --codex-stdout-only
```

Exemplo Node.js:

```js
import { execFile } from "node:child_process";

execFile(
  "python",
  [
    "backend/agents/tab_debug_agent/run_agent.py",
    "--headless", "1",
    "--codex-stdout-only"
  ],
  { cwd: process.cwd() },
  (err, stdout, stderr) => {
    if (err) throw err;
    const payload = JSON.parse(stdout.trim());
    console.log(payload.byStatus, payload.byCause);
  }
);
```

Exemplo para a task especializada em cursor perceptual:

```bash
python backend/agents/tab_debug_agent/run_agent.py ^
  --task synthetic-cursor-perceptual-smoothness ^
  --headless 1 ^
  --no-openai ^
  --codex-stdout-only
```

Essa task adiciona métricas de suavidade perceptual ao `clickSummary`, incluindo:

- `velocityJitterRatioP90Pct`
- `velocityJitterSpikeCount`
- `displayHoldEventCount`
- `targetJumpEventCount`

## Loop de Autoajuste (Sem OpenAI)

Modo local (hill-climb):

```bash
python backend/agents/tab_debug_agent/run_loop.py ^
  --optimizer local ^
  --auto-tune ^
  --headless 1
```

Modo DSPy 3 + GEPA (proposer local/offline):

```bash
python backend/agents/tab_debug_agent/run_loop.py ^
  --optimizer dspy-gepa ^
  --headless 1 ^
  --dspy-max-metric-calls 24 ^
  --stable-runs 2
```

Notas:

- O loop sempre chama `run_agent.py` com `--no-openai`.
- No modo `dspy-gepa`, a otimização usa `dspy.GEPA` com proposer local (sem LLM externo).
- Para auditoria, use `--history-json backend/agents/tab_debug_agent/runs/history.json`.

## Loop de Autocorreção

MVP para classificar a falha, tentar uma correção restrita e rerodar regressões:

```bash
python backend/agents/tab_debug_agent/run_fix_loop.py ^
  --task synthetic-cursor-smooth-sync ^
  --headless 1
```

O loop:

- executa a task alvo com `run_agent.py --no-openai --codex-stdout-only`;
- classifica a falha em assinatura conhecida;
- tenta `tune_layout_params` e, quando permitido, `fix_synth_cursor_clock`;
- reroda a task alvo;
- só aceita a correção se a task alvo passar e a regressão configurada também passar.

Opções principais:

- `--regression-tasks`: lista CSV de tasks de regressão.
- `--allow-code-patches`: habilita patches restritos em código para assinaturas conhecidas.
- `--json-only`: imprime apenas o relatório JSON final.

Artefatos:

- `backend/agents/tab_debug_agent/runs/autofix/latest-fix-loop.json`
- `backend/agents/tab_debug_agent/runs/autofix/autofix-history.json`

Integração via backend FastAPI (`backend/realtime_tab_server.py`):

```bash
# Executa o agente e retorna payload JSON
curl -X POST "http://localhost:8000/api/debug/tab-agent/run" ^
  -H "Content-Type: application/json" ^
  -d "{\"headless\": true, \"url\": \"http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugSystemLines=1\"}"
```

```bash
# Lê apenas o último latest-codex.json
curl "http://localhost:8000/api/debug/tab-agent/latest"
```


python backend/agents/tab_debug_agent/run_agent.py --task synthetic-cursor-perceptual-smoothness --headless 1 --no-openai --codex-stdout-only

python backend/agents/tab_debug_agent/run_agent.py --task synthetic-cursor-perceptual-smoothness --headless 1 --no-openai --codex-stdout-only
