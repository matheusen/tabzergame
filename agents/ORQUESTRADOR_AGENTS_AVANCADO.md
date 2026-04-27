# Orquestrador Avançado de Agents para Correção Automática de Bugs e Criação de Features

> Blueprint técnico para evoluir a pasta `agents/` atual para um sistema robusto de desenvolvimento automatizado com agentes especializados, execução segura, validação por testes, memória, observabilidade e abertura controlada de Pull Requests.

---

## 1. Objetivo do projeto

Criar um **orquestrador de agents de desenvolvimento de software** capaz de receber comandos em linguagem natural, entender o contexto do repositório, diagnosticar bugs, propor correções, implementar features, rodar validações e entregar um relatório técnico confiável.

O foco não é criar um “chatbot que mexe no código”. O foco é criar um **Agent OS de engenharia**, com estado, políticas, validação, isolamento e rastreabilidade.

O sistema deve ser capaz de:

1. receber pedidos como:
   - “corrija o bug do cursor travando no player”; 
   - “crie uma feature de Explain Tab por compasso”;
   - “melhore a performance do AlphaTab”;
   - “corrija os testes que falham no backend”;
   - “implemente uma nova tela de estudo com modos gregos”.
2. classificar a tarefa como `bugfix`, `feature`, `refactor`, `visual-regression`, `performance`, `docs`, `test-generation` ou `tabzer-specialized`;
3. criar uma task rastreável com ID único;
4. abrir uma `git worktree` isolada;
5. executar validações de baseline;
6. mapear arquivos impactados;
7. criar um plano de ação;
8. aplicar patches pequenos e reversíveis;
9. rodar testes e validações visuais;
10. revisar o próprio patch;
11. gerar relatório final;
12. opcionalmente criar branch, commit e Pull Request.

---

## 2. Diagnóstico da estrutura atual enviada no ZIP

O ZIP enviado já contém uma base relevante de agentes:

```text
agents/
  backend_bug_agent/
    run_agent.py
    runs/
  bug_team/
    run_orchestrator.py
    runs/
  commander/
    command_parser.py
    copilot_adapter.py
    dispatcher.py
    run_commander.py
    voice_server.py
    README.md
  frontend_bug_agent/
    run_agent.py
  study_agent/
    content_generator.py
    run_agent.py
    tasks/
    ts_patcher.py
  tab_debug_agent/
    run_agent.py
    run_loop.py
    run_fix_loop.py
    cursor_smooth_agent.py
    failure_classifier.py
    fix_orchestrator.py
    patch_strategies.py
    regression_suite.py
    tasks/
```

### 2.1 O que já está bom

A estrutura atual já tem bons sinais de maturidade:

- existe separação entre agentes de backend, frontend, estudos e debug de tab;
- existe um `commander`, que já funciona como camada de entrada;
- existe um `bug_team`, que já orquestra múltiplos agentes;
- existe persistência simples em `runs/*.json`;
- o `tab_debug_agent` é o componente mais avançado, pois já possui:
  - tarefas especializadas;
  - loop de correção;
  - classificador de falhas;
  - estratégias de patch;
  - suíte de regressão;
  - agente específico para suavidade do cursor;
  - validações visuais e comportamentais.

### 2.2 O que falta para virar um sistema avançado

Hoje a arquitetura parece estar mais próxima de um conjunto de scripts especializados. O próximo salto é transformar isso em uma plataforma com:

- estado global por task;
- workflow formal;
- contratos JSON/Pydantic entre agentes;
- worktree isolada por execução;
- política de segurança;
- rollback automático;
- validação determinística;
- reviewer agent;
- tracing com OpenTelemetry;
- memória de execuções anteriores;
- integração com GitHub;
- aprovação humana para ações perigosas.

---

## 3. Princípios de arquitetura

### 3.1 Segurança primeiro

O agente nunca deve alterar diretamente a branch principal. Toda execução deve acontecer em uma área isolada:

```text
.agent-worktrees/<task-id>/
.agent-runs/<task-id>/
```

A branch principal deve permanecer intacta.

### 3.2 Pequenos patches

O agente deve aplicar mudanças pequenas e explicáveis. Uma correção automática boa é aquela que:

- altera poucos arquivos;
- tem escopo claro;
- é validada por teste;
- pode ser revertida facilmente;
- possui relatório técnico.

### 3.3 Validação determinística antes de raciocínio livre

O LLM pode sugerir, interpretar e planejar. Mas quem decide se funcionou são comandos determinísticos:

- `npm run typecheck`;
- `npm run lint`;
- `npm test`;
- `pytest`;
- `ruff`;
- `playwright`;
- screenshot diff;
- performance budget;
- smoke tests do player.

### 3.4 Estado explícito

Cada workflow precisa salvar tudo:

```text
intent.json
plan.json
baseline.json
attempts/attempt-001/patch.diff
attempts/attempt-001/validation.json
attempts/attempt-001/reviewer.json
final-report.md
```

Sem estado explícito, o sistema vira um agente imprevisível.

### 3.5 Humano aprova ações sensíveis

O agente pode diagnosticar, criar patch em worktree e rodar testes. Mas algumas ações devem exigir aprovação:

- deletar arquivos;
- alterar `.env`;
- mexer em secrets;
- instalar pacotes;
- alterar lockfiles;
- criar migration;
- mudar autenticação;
- commitar;
- abrir Pull Request;
- fazer merge.

---

## 4. Visão geral da arquitetura

```text
┌─────────────────────────────────────────────────────────────┐
│                        User / UI / CLI                       │
│  Texto, voz, botão no dashboard, comando de terminal, PR      │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Commander / Intake Agent                 │
│  Normaliza pedido, cria TaskIntent, identifica risco/escopo   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Planner / Triage Agent                   │
│  Decide workflow, agentes envolvidos, validações e limites    │
└───────────────┬─────────────────────┬───────────────────────┘
                │                     │
                ▼                     ▼
┌──────────────────────────┐  ┌───────────────────────────────┐
│     Bugfix Workflow      │  │       Feature Workflow         │
│  reproduzir -> corrigir  │  │  spec -> tests -> implement    │
└──────────────┬───────────┘  └───────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│                Specialized Workers / Existing Agents         │
│  frontend_bug_agent, backend_bug_agent, tab_debug_agent, etc. │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Validation + Review Layer                 │
│  Typecheck, lint, tests, Playwright, screenshots, reviewer    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Report / Commit / Pull Request            │
│  final-report.md, diff, métricas, opção de PR                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Stack recomendada

### 5.1 Linguagem principal

Use **Python** para o orquestrador.

Motivos:

- você já tem agentes em Python;
- é mais simples controlar subprocessos, Playwright, logs e arquivos;
- integra bem com OpenTelemetry, Git, APIs e bancos vetoriais;
- combina bem com FastAPI caso você queira painel web depois.

### 5.2 Orquestração

Recomendação prática:

```text
MVP: Python puro + Pydantic + subprocess seguro + git worktree
Fase 2: LangGraph para workflows com estado e transições
Fase 3: OpenAI Agents SDK para agentes especialistas, handoffs, guardrails e tracing
Fase 4: MCP para plugar ferramentas externas de forma padronizada
```

### 5.3 Ferramentas modernas que fazem sentido

#### LangGraph

Use para workflows com estado, por exemplo:

```text
INTAKE -> BASELINE -> PLAN -> PATCH -> VALIDATE -> REVIEW -> REPORT
```

Ele é útil quando o sistema começa a ter branching, retries, checkpoints e múltiplos agentes.

#### OpenAI Agents SDK

Use para agentes especialistas com:

- handoffs;
- guardrails;
- tracing;
- tools;
- estado de execução;
- execução em sandbox.

#### MCP — Model Context Protocol

Use para padronizar ferramentas e fontes de contexto:

- GitHub;
- banco de dados;
- documentação interna;
- logs;
- filesystem;
- execução de testes;
- browser automation.

#### OpenTelemetry

Use para observar:

- tempo por agente;
- custo por modelo;
- número de tentativas;
- comandos executados;
- falhas de validação;
- arquivos alterados;
- patches aceitos/rejeitados.

---

## 6. Níveis de autonomia

O sistema deve suportar níveis explícitos de autonomia.

```text
Nível 0: somente leitura
Nível 1: diagnóstico e relatório
Nível 2: gera patch sugerido, mas não aplica
Nível 3: aplica patch em worktree isolada
Nível 4: cria branch, commit e PR
Nível 5: merge automático
```

### Recomendação para começar

Comece no **Nível 3**.

Isso permite que o agente corrija bugs e implemente features em ambiente isolado, sem risco de destruir o repositório principal.

O Nível 4 deve entrar depois que você tiver:

- taxa de sucesso medida;
- reviewer agent funcionando;
- testes confiáveis;
- política de arquivos sensíveis;
- logs completos;
- aprovação humana.

O Nível 5 não é recomendado no início.

---

## 7. Tipos de task

```python
TaskType = Literal[
    "bugfix",
    "feature",
    "refactor",
    "visual_regression",
    "performance",
    "test_generation",
    "documentation",
    "tabzer_specialized",
    "infra",
    "security"
]
```

### 7.1 Bugfix

Corrige comportamento quebrado.

Exemplos:

- cursor travando;
- tela piscando;
- erro de TypeScript;
- endpoint quebrando;
- memory leak;
- Playwright falhando.

### 7.2 Feature

Cria uma funcionalidade nova.

Exemplos:

- Explain Tab por compasso;
- modo editor visual;
- tela de exercícios de modos gregos;
- dashboard de agentes;
- integração com GitHub.

### 7.3 Visual regression

Compara screenshots e comportamento visual.

Exemplos:

- tab precisa parecer com Songsterr;
- linhas da pauta mudaram de cor;
- cursor não cobre as seis cordas;
- números da tab desalinhados.

### 7.4 Performance

Mede e corrige performance.

Exemplos:

- AlphaTab consumindo 2 GB;
- loader renderizando pauta por pauta;
- micro-pausas no cursor;
- re-render desnecessário.

### 7.5 Tabzer specialized

Workflow especializado para seu app de guitarra.

Exemplos:

- sincronização YouTube + tab;
- cursor do player;
- renderização AlphaTab;
- edição visual de notas;
- análise musical por compasso;
- geração de exercícios.

---

## 8. Estado da task

Cada task deve ser representada por uma máquina de estados.

```text
CREATED
  ↓
INTAKE_PARSED
  ↓
WORKTREE_CREATED
  ↓
BASELINE_RUNNING
  ↓
BASELINE_FAILED or BASELINE_PASSED
  ↓
PLANNING
  ↓
PATCHING
  ↓
VALIDATING
  ↓
REVIEWING
  ↓
WAITING_HUMAN_APPROVAL or COMPLETED or FAILED
```

### 8.1 Estados finais

```text
COMPLETED
FAILED
CANCELLED
NEEDS_HUMAN
OUT_OF_SCOPE
UNSAFE
```

---

## 9. Contratos de dados com Pydantic

Crie contratos rígidos para os agentes conversarem entre si.

### 9.1 TaskIntent

```python
from pydantic import BaseModel, Field
from typing import Literal, list

class TaskIntent(BaseModel):
    task_id: str
    task_type: Literal[
        "bugfix",
        "feature",
        "refactor",
        "visual_regression",
        "performance",
        "test_generation",
        "documentation",
        "tabzer_specialized",
        "infra",
        "security",
    ]
    title: str
    user_request: str
    target_area: Literal["frontend", "backend", "fullstack", "tabzer", "infra", "unknown"]
    risk: Literal["low", "medium", "high", "critical"]
    autonomy_level: int = Field(ge=0, le=5)
    acceptance_criteria: list[str] = []
    target_url: str | None = None
    allowed_paths: list[str] = []
    blocked_paths: list[str] = []
```

### 9.2 AgentResult

```python
class AgentResult(BaseModel):
    agent_name: str
    status: Literal["passed", "failed", "skipped", "needs_human"]
    summary: str
    findings: list[str] = []
    artifacts: list[str] = []
    metrics: dict = {}
    error: str | None = None
```

### 9.3 ValidationResult

```python
class ValidationResult(BaseModel):
    name: str
    command: list[str]
    status: Literal["passed", "failed", "timeout", "skipped"]
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    duration_sec: float | None = None
```

### 9.4 PatchAttempt

```python
class PatchAttempt(BaseModel):
    attempt_no: int
    plan_summary: str
    files_changed: list[str]
    patch_path: str
    validation_results: list[ValidationResult]
    reviewer_status: Literal["approved", "rejected", "needs_human"]
    rollback_performed: bool = False
```

### 9.5 FinalReport

```python
class FinalReport(BaseModel):
    task_id: str
    status: Literal["completed", "failed", "needs_human"]
    summary: str
    files_changed: list[str]
    validations: list[ValidationResult]
    attempts: list[PatchAttempt]
    recommendations: list[str]
    pr_url: str | None = None
```

---

## 10. Estrutura de pastas recomendada

```text
backend/agents/orchestrator/
  __init__.py
  main.py
  config.py
  schemas.py
  state.py

  workflows/
    __init__.py
    bugfix_workflow.py
    feature_workflow.py
    refactor_workflow.py
    visual_regression_workflow.py
    performance_workflow.py
    tabzer_workflow.py

  agents/
    __init__.py
    intake_agent.py
    planner_agent.py
    repo_mapper_agent.py
    reproducer_agent.py
    root_cause_agent.py
    patch_agent.py
    test_writer_agent.py
    regression_agent.py
    reviewer_agent.py
    docs_agent.py
    pr_agent.py

  adapters/
    __init__.py
    frontend_bug_adapter.py
    backend_bug_adapter.py
    bug_team_adapter.py
    tab_debug_adapter.py
    study_agent_adapter.py

  tools/
    __init__.py
    safe_shell.py
    git_worktree.py
    patch_applier.py
    test_runner.py
    playwright_runner.py
    screenshot_diff.py
    file_scanner.py
    github_client.py

  policies/
    __init__.py
    approval_policy.py
    command_policy.py
    file_scope_policy.py
    risk_policy.py
    secret_policy.py

  memory/
    __init__.py
    run_store.py
    vector_memory.py
    repo_index.py

  observability/
    __init__.py
    tracing.py
    metrics.py
    logging.py

  prompts/
    planner.md
    bugfix.md
    feature_spec.md
    patch_agent.md
    reviewer.md
    docs_agent.md
```

---

## 11. Integração com seus agentes atuais

Você não deve apagar seus agentes atuais. Eles viram **workers** plugáveis.

### 11.1 Contrato de adapter

```python
from pathlib import Path
from typing import Protocol

class AgentAdapter(Protocol):
    name: str

    def run(self, task: TaskIntent, workspace: Path) -> AgentResult:
        ...
```

### 11.2 Adapter para frontend_bug_agent

```python
class FrontendBugAdapter:
    name = "frontend_bug_agent"

    def run(self, task: TaskIntent, workspace: Path) -> AgentResult:
        result = safe_run(
            ["python", "agents/frontend_bug_agent/run_agent.py"],
            cwd=workspace,
            timeout_sec=180,
        )
        return AgentResult(
            agent_name=self.name,
            status="passed" if result.exit_code == 0 else "failed",
            summary="Frontend validation executed",
            artifacts=[result.stdout_path, result.stderr_path],
            metrics={"exit_code": result.exit_code},
        )
```

### 11.3 Adapter para backend_bug_agent

```python
class BackendBugAdapter:
    name = "backend_bug_agent"

    def run(self, task: TaskIntent, workspace: Path) -> AgentResult:
        result = safe_run(
            ["python", "agents/backend_bug_agent/run_agent.py"],
            cwd=workspace,
            timeout_sec=180,
        )
        return AgentResult(
            agent_name=self.name,
            status="passed" if result.exit_code == 0 else "failed",
            summary="Backend validation executed",
            artifacts=[result.stdout_path, result.stderr_path],
            metrics={"exit_code": result.exit_code},
        )
```

### 11.4 Adapter para tab_debug_agent

```python
class TabDebugAdapter:
    name = "tab_debug_agent"

    def run(self, task: TaskIntent, workspace: Path) -> AgentResult:
        command = [
            "python",
            "agents/tab_debug_agent/run_agent.py",
            "--codex-stdout-only",
        ]

        if task.target_url:
            command.extend(["--url", task.target_url])

        result = safe_run(command, cwd=workspace, timeout_sec=600)

        return AgentResult(
            agent_name=self.name,
            status="passed" if result.exit_code == 0 else "failed",
            summary="Tabzer specialized validation executed",
            artifacts=[result.stdout_path, result.stderr_path],
            metrics={"exit_code": result.exit_code},
        )
```

---

## 12. Workflows principais

## 12.1 Bugfix Workflow

### Objetivo

Corrigir bugs com segurança, reproduzindo a falha antes de tentar corrigir.

### Fluxo

```text
1. Parse do pedido
2. Classificação de risco
3. Criação da worktree
4. Baseline
5. Reprodução do bug
6. Mapeamento de arquivos prováveis
7. Plano técnico
8. Patch pequeno
9. Validação
10. Review automático
11. Retry se necessário
12. Relatório final
```

### Pseudocódigo

```python
def run_bugfix_workflow(task: TaskIntent) -> FinalReport:
    state = create_initial_state(task)

    workspace = create_worktree(task.task_id)
    state.workspace = workspace

    baseline = run_baseline(task, workspace)
    state.baseline = baseline

    reproduction = run_reproducer(task, workspace)
    state.reproduction = reproduction

    plan = planner_agent.create_bugfix_plan(task, baseline, reproduction)
    state.plan = plan

    for attempt_no in range(1, MAX_ATTEMPTS + 1):
        patch = patch_agent.generate_patch(task, plan, state)
        apply_patch(workspace, patch)

        validation = run_validations(task, workspace)
        review = reviewer_agent.review(task, patch, validation)

        if validation.passed and review.approved:
            return build_final_report(state, status="completed")

        rollback_patch(workspace)
        state.add_failed_attempt(patch, validation, review)

    return build_final_report(state, status="failed")
```

### Validações mínimas

Frontend:

```bash
npm run typecheck
npm run lint
npm test
npx playwright test
```

Backend:

```bash
python -m ruff check .
python -m pytest
```

Tabzer específico:

```bash
python agents/tab_debug_agent/run_agent.py --codex-stdout-only
python agents/tab_debug_agent/run_fix_loop.py
```

---

## 12.2 Feature Workflow

### Objetivo

Transformar uma ideia em uma feature pequena, testada e documentada.

### Fluxo

```text
1. Intake
2. Product Spec Agent
3. Acceptance Criteria
4. Repo Mapper
5. Technical Planner
6. Test Writer
7. Implementation/Patch Agent
8. Validation
9. UX/Visual Review
10. Docs Agent
11. Reviewer Agent
12. Relatório/PR
```

### Regra principal

O agente não deve criar uma feature gigante de uma vez. Ele deve criar um **vertical slice mínimo**.

Exemplo ruim:

```text
Criar todo o sistema Explain Tab completo com IA, cache, UI avançada, histórico, permissões e analytics.
```

Exemplo bom:

```text
Criar botão “Explain” ao selecionar um compasso, chamar endpoint mockado e renderizar resposta em um painel lateral.
```

### Template de especificação

```json
{
  "feature_name": "Explain Tab por Compasso",
  "problem": "O usuário quer entender musicalmente um trecho da tab sem sair do player.",
  "goal": "Permitir selecionar um compasso e solicitar explicação contextual.",
  "non_goals": [
    "Treinar modelo próprio nesta etapa",
    "Criar análise perfeita de teoria musical",
    "Implementar colaboração em tempo real"
  ],
  "user_flow": [
    "Usuário abre uma música",
    "Usuário seleciona um compasso",
    "Botão Explain aparece",
    "Usuário clica no botão",
    "Painel lateral exibe explicação"
  ],
  "acceptance_criteria": [
    "O botão só aparece quando há seleção de compasso",
    "O carregamento não trava o player",
    "A resposta aparece em painel lateral",
    "Erros são exibidos de forma amigável",
    "Existe teste de UI cobrindo o fluxo básico"
  ]
}
```

---

## 12.3 Visual Regression Workflow

### Objetivo

Validar aparência e comportamento visual, especialmente no player do Tabzer.

### Fluxo

```text
1. Abrir URL alvo com Playwright
2. Esperar app estabilizar
3. Capturar screenshot baseline
4. Executar interação
5. Capturar screenshot pós-interação
6. Comparar regiões críticas
7. Gerar relatório visual
```

### Regiões críticas para Tabzer

```text
- altura do cursor
- opacidade do cursor
- alinhamento do cursor com as seis cordas
- cor das linhas da tab
- espessura das linhas
- posição dos números
- stem/beam rendering
- símbolos de ligados/slides/bends
- flicker de loader
- re-render de pauta
- deslocamento horizontal durante playback
```

### Métricas visuais

```json
{
  "cursor_height_px": 78,
  "cursor_opacity": 0.35,
  "line_color": "#6e6e6e",
  "tab_number_color": "#dedede",
  "flicker_frames": 0,
  "layout_shift_score": 0.01,
  "frame_drops": 2
}
```

---

## 12.4 Performance Workflow

### Objetivo

Encontrar gargalos reais antes de mudar código.

### Coletas importantes

Frontend:

```text
- memory usage
- React re-renders
- long tasks
- FPS
- animation frame jitter
- bundle size
- network waterfall
- layout shifts
```

Backend:

```text
- tempo de resposta
- queries lentas
- uso de CPU
- uso de memória
- filas Kafka/Redis
- logs de exceção
```

Tabzer:

```text
- consumo de RAM do AlphaTab
- tempo até primeira renderização completa
- tempo até player estar sincronizado
- jitter do cursor
- quantidade de re-renders por segundo
- carregamento de soundfont/audio
```

### Performance budget inicial

```yaml
performance_budget:
  frontend:
    max_initial_load_ms: 3000
    max_player_ready_ms: 5000
    max_layout_shift: 0.05
    max_long_tasks: 5
  tabzer:
    max_cursor_jitter_ms: 16
    max_flicker_frames: 0
    max_tab_memory_mb: 700
```

---

## 13. Catálogo de agentes

## 13.1 Intake Agent

Responsável por transformar linguagem natural em `TaskIntent`.

Entrada:

```text
"corrija o cursor que dá umas travadinhas no player"
```

Saída:

```json
{
  "task_type": "bugfix",
  "target_area": "tabzer",
  "risk": "medium",
  "title": "Corrigir micro-pausas do cursor no player",
  "acceptance_criteria": [
    "cursor deve deslizar sem micro-pausas perceptíveis",
    "sincronização com áudio deve ser preservada",
    "não deve causar flicker no carregamento da tab"
  ]
}
```

## 13.2 Planner Agent

Responsável por decidir:

- workflow;
- agentes necessários;
- validações;
- arquivos prováveis;
- limites de autonomia;
- necessidade de aprovação humana.

## 13.3 Repo Mapper Agent

Responsável por mapear:

- arquivos relevantes;
- dependências;
- testes existentes;
- pontos de entrada;
- componentes React;
- endpoints FastAPI/Spring/Node;
- scripts package.json;
- configs de lint/test.

Ferramentas:

```bash
rg "AlphaTab|cursor|player|playback|selection"
rg "Explain|Study|Tab"
find . -name "package.json"
find . -name "pytest.ini" -o -name "pyproject.toml"
```

## 13.4 Reproducer Agent

Responsável por reproduzir o bug.

Ele não corrige nada. Ele prova que o bug existe.

Saídas possíveis:

```text
REPRODUCED
NOT_REPRODUCED
PARTIALLY_REPRODUCED
ENVIRONMENT_FAILURE
```

## 13.5 Root Cause Agent

Recebe logs, screenshots, stack traces e resultados de teste.

Gera hipóteses ordenadas:

```json
{
  "hypotheses": [
    {
      "cause": "cursor position is updated from audio time with coarse timer",
      "confidence": 0.74,
      "evidence": ["jitter spikes every ~1000ms", "requestAnimationFrame not used consistently"]
    }
  ]
}
```

## 13.6 Patch Agent

Responsável por criar o patch.

Regras:

- mudar o mínimo possível;
- preservar API pública;
- não alterar lockfile sem aprovação;
- não remover testes;
- não suprimir erro com `any` sem justificativa;
- não fazer refactor gigante dentro de bugfix.

## 13.7 Test Writer Agent

Responsável por criar teste de regressão.

Exemplos:

- Playwright para fluxo visual;
- unit test para parser;
- integration test para endpoint;
- snapshot controlado para componente;
- teste sintético de jitter do cursor.

## 13.8 Regression Agent

Roda validações pós-patch.

Deve comparar:

```text
baseline_errors vs final_errors
baseline_warnings vs final_warnings
screenshots_before vs screenshots_after
performance_before vs performance_after
```

## 13.9 Reviewer Agent

Revisa o patch como um senior engineer.

Checklist:

```text
- O patch resolve o problema pedido?
- O diff está pequeno?
- Alterou arquivos fora do escopo?
- Criou dívida técnica?
- Quebrou teste?
- Introduziu risco de segurança?
- Precisa de aprovação humana?
```

## 13.10 PR Agent

Opcional. Só entra no Nível 4.

Responsável por:

- criar branch;
- commitar;
- abrir PR;
- preencher descrição;
- anexar relatório;
- marcar labels.

---

## 14. Políticas de segurança

## 14.1 Arquivos bloqueados por padrão

```yaml
blocked_paths:
  - ".env"
  - ".env.*"
  - "**/secrets/**"
  - "**/*secret*"
  - "**/*credential*"
  - "**/id_rsa"
  - "**/id_ed25519"
  - "package-lock.json"
  - "pnpm-lock.yaml"
  - "yarn.lock"
  - "poetry.lock"
  - "Pipfile.lock"
  - "docker-compose.prod.yml"
  - "infra/prod/**"
```

Lockfiles não são proibidos para sempre. Eles apenas precisam de aprovação humana.

## 14.2 Comandos proibidos

```yaml
forbidden_commands:
  - "rm -rf"
  - "del /s"
  - "format"
  - "shutdown"
  - "reboot"
  - "git reset --hard"
  - "git clean -fdx"
  - "docker system prune"
  - "docker volume rm"
  - "npm publish"
  - "pip upload"
```

## 14.3 Comandos permitidos inicialmente

```yaml
allowed_commands:
  - ["git", "status"]
  - ["git", "diff"]
  - ["git", "worktree"]
  - ["python", "-m", "pytest"]
  - ["python", "-m", "ruff", "check", "."]
  - ["npm", "run", "typecheck"]
  - ["npm", "run", "lint"]
  - ["npm", "test"]
  - ["npx", "playwright", "test"]
```

## 14.4 Regra de subprocess

Nunca usar:

```python
subprocess.run(command, shell=True)
```

Sempre usar:

```python
subprocess.run(["npm", "run", "typecheck"], shell=False)
```

## 14.5 Safe shell runner

```python
import subprocess
from pathlib import Path
from dataclasses import dataclass

@dataclass
class ShellResult:
    command: list[str]
    exit_code: int
    stdout_path: str
    stderr_path: str
    duration_sec: float


def safe_run(command: list[str], cwd: Path, timeout_sec: int = 120) -> ShellResult:
    if not command:
        raise ValueError("Empty command is not allowed")

    if any("&&" in part or ";" in part or "|" in part for part in command):
        raise ValueError(f"Unsafe shell operator detected: {command}")

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_sec,
        shell=False,
    )

    # salvar stdout/stderr em arquivos reais dentro de .agent-runs
    # retornar ShellResult
```

---

## 15. Configuração YAML do orquestrador

Crie `orchestrator_config.yaml`:

```yaml
project:
  name: tabzer
  root: .
  default_autonomy_level: 3

paths:
  runs_dir: .agent-runs
  worktrees_dir: .agent-worktrees
  artifacts_dir: .agent-artifacts

policies:
  max_attempts: 3
  require_human_approval_for:
    - commit
    - pull_request
    - lockfile_change
    - package_install
    - migration
    - delete_file
    - auth_change
    - infra_change

validation:
  frontend:
    enabled: true
    commands:
      - ["npm", "run", "typecheck"]
      - ["npm", "run", "lint"]
      - ["npm", "test"]
  backend:
    enabled: true
    commands:
      - ["python", "-m", "ruff", "check", "."]
      - ["python", "-m", "pytest"]
  browser:
    enabled: true
    commands:
      - ["npx", "playwright", "test"]

tabzer:
  enabled: true
  target_url: "http://localhost:3000/play?debugCursor=1"
  commands:
    - ["python", "agents/tab_debug_agent/run_agent.py", "--codex-stdout-only"]
    - ["python", "agents/tab_debug_agent/run_fix_loop.py"]

observability:
  opentelemetry: true
  service_name: tabzer-agent-orchestrator
  traces_exporter: otlp
  metrics_exporter: prometheus
```

---

## 16. CLI desejada

### 16.1 Diagnosticar bug

```bash
python backend/agents/orchestrator/main.py bugfix \
  --request "Corrigir micro-pausas do cursor no player" \
  --target-url "http://localhost:3000/play?id=joe-satriani-if-could-fly-v2&debugCursor=1" \
  --autonomy 3
```

### 16.2 Criar feature

```bash
python backend/agents/orchestrator/main.py feature \
  --request "Criar botão Explain Tab ao selecionar um compasso" \
  --autonomy 3
```

### 16.3 Rodar somente diagnóstico

```bash
python backend/agents/orchestrator/main.py bugfix \
  --request "A tela de estudo está quebrando no mobile" \
  --autonomy 1
```

### 16.4 Gerar relatório sem patch

```bash
python backend/agents/orchestrator/main.py bugfix \
  --request "Investigar consumo alto de RAM no player" \
  --autonomy 1 \
  --report-only
```

### 16.5 Criar PR após aprovação

```bash
python backend/agents/orchestrator/main.py pr \
  --task-id bugfix-20260427-001 \
  --approved-by Matheus
```

---

## 17. Estrutura de saída por execução

```text
.agent-runs/
  bugfix-20260427-001/
    intent.json
    state.json
    baseline/
      frontend_typecheck.stdout.txt
      frontend_typecheck.stderr.txt
      eslint.stdout.txt
      pytest.stdout.txt
    reproduction/
      browser-console.json
      screenshot-before.png
      performance.json
    plan.json
    attempts/
      attempt-001/
        patch.diff
        files_changed.json
        validation.json
        reviewer.json
      attempt-002/
        patch.diff
        validation.json
        reviewer.json
    final-report.md
    metrics.json
```

---

## 18. Modelo de relatório final

```md
# Agent Run Report: bugfix-20260427-001

## Status
COMPLETED

## Pedido original
Corrigir micro-pausas do cursor no player.

## Resumo
O agente identificou que a posição do cursor estava sendo atualizada de forma irregular durante o playback. Foi aplicado patch para estabilizar a atualização usando `requestAnimationFrame` e reduzir updates redundantes.

## Arquivos alterados
- frontend/src/player/CursorOverlay.tsx
- frontend/src/player/usePlaybackCursor.ts
- frontend/tests/player-cursor.spec.ts

## Validações
| Validação | Status |
|---|---|
| TypeScript | passed |
| ESLint | passed |
| Playwright cursor smoke | passed |
| Tab debug regression | passed |

## Tentativas
- Attempt 1: falhou por layout shift no carregamento.
- Attempt 2: aprovado.

## Riscos restantes
- Teste visual depende da resolução de viewport.
- Recomendado adicionar métrica de jitter em CI.

## Próximos passos
- Abrir PR.
- Adicionar performance budget para cursor.
```

---

## 19. Dashboard web recomendado

Você pode criar uma tela no Next.js para visualizar as execuções.

### Componentes

```text
AgentDashboard
  ├── TaskInputPanel
  ├── RunningTasksList
  ├── AgentTimeline
  ├── ValidationResults
  ├── DiffViewer
  ├── ScreenshotViewer
  ├── ApprovalGateModal
  └── FinalReportPanel
```

### Estados visuais

```text
created
running
waiting_approval
failed
completed
cancelled
```

### Ações no dashboard

```text
- Criar task
- Ver plano
- Aprovar patch
- Rejeitar patch
- Rodar nova tentativa
- Ver diff
- Ver logs
- Abrir PR
- Cancelar execução
```

---

## 20. Observabilidade

### 20.1 Traces

Cada task deve gerar trace com spans:

```text
agent.task.created
agent.intake.parse
agent.worktree.create
agent.baseline.run
agent.reproducer.run
agent.planner.plan
agent.patch.generate
agent.patch.apply
agent.validation.run
agent.review.run
agent.report.generate
```

### 20.2 Métricas

```text
agent_task_total
agent_task_success_total
agent_task_failed_total
agent_attempt_count
agent_validation_duration_seconds
agent_patch_files_changed
agent_model_tokens_input
agent_model_tokens_output
agent_model_cost_usd
agent_human_approval_count
agent_rollback_count
```

### 20.3 Logs estruturados

```json
{
  "timestamp": "2026-04-27T10:15:00-03:00",
  "task_id": "bugfix-20260427-001",
  "agent": "patch_agent",
  "event": "patch_generated",
  "files_changed": 2,
  "risk": "medium"
}
```

### 20.4 Stack sugerida

```text
OpenTelemetry SDK
OTLP Collector
Jaeger para traces
Prometheus para métricas
Grafana para dashboard
Loki para logs
```

---

## 21. Memória do sistema

O agente deve aprender com execuções anteriores sem “inventar”. Para isso, salve histórico estruturado.

### 21.1 Memória curta

Dentro da task atual:

```text
state.json
attempts/*
logs
screenshots
patches
```

### 21.2 Memória longa

Banco de dados:

```text
Postgres
  agent_runs
  agent_attempts
  agent_findings
  agent_patches
  agent_validations

pgvector ou Qdrant
  embeddings de bugs anteriores
  embeddings de patches
  embeddings de relatórios
  embeddings de arquivos relevantes
```

### 21.3 Casos de uso da memória

```text
- “Já corrigimos bug parecido?”
- “Qual patch resolveu flicker de cursor antes?”
- “Quais arquivos costumam quebrar o player?”
- “Quais agentes falham mais?”
- “Quais validações detectam regressão de verdade?”
```

---

## 22. Repo index / Code intelligence

Antes de deixar o agente alterar código, ele precisa entender o repositório.

Crie um indexador simples:

```text
repo_index.json
  files
  imports
  exports
  package scripts
  python modules
  endpoints
  React components
  test files
  config files
```

### 22.1 Indexação básica

```bash
rg "export function|export const|class |def |function "
rg "useEffect|useMemo|useCallback|requestAnimationFrame"
rg "FastAPI|APIRouter|@app|router"
rg "AlphaTab|player|cursor|playback"
```

### 22.2 Futuro: AST

Depois do MVP, use AST para mapear com mais precisão:

- TypeScript AST;
- Python AST;
- import graph;
- dependency graph;
- chamadas entre módulos;
- impacto por alteração.

---

## 23. Estratégia de patch

### 23.1 Patches permitidos

```text
- correção pequena e local
- adicionar teste
- melhorar tratamento de erro
- corrigir tipo TypeScript
- ajustar CSS/local style
- reduzir re-render
- adicionar logs controlados
```

### 23.2 Patches que exigem aprovação

```text
- instalar dependência
- alterar estrutura de banco
- alterar autenticação
- alterar contrato público de API
- mexer em infra
- alterar lockfile
- deletar arquivo
- refatorar muitos módulos
```

### 23.3 Patches proibidos

```text
- remover teste para passar validação
- silenciar erro sem resolver causa
- envolver tudo em try/catch genérico
- adicionar `any` sem justificativa
- comentar código quebrado sem explicar
- ignorar falhas de lint/test
- mexer em secrets
```

---

## 24. Reviewer Agent checklist

O reviewer deve responder em JSON:

```json
{
  "approved": false,
  "risk": "medium",
  "summary": "Patch melhora cursor, mas altera hook compartilhado sem teste de regressão suficiente.",
  "blocking_issues": [
    "Não há teste cobrindo pausa/resume do player"
  ],
  "non_blocking_suggestions": [
    "Adicionar métrica de jitter no relatório"
  ],
  "requires_human_approval": false
}
```

### Checklist interno

```text
- Resolve o pedido original?
- O patch é mínimo?
- Os critérios de aceite foram testados?
- Existe risco de regressão?
- Arquivos sensíveis foram alterados?
- O relatório explica a mudança?
- O patch deveria ser dividido?
```

---

## 25. Estratégia específica para o Tabzer

Seu app Tabzer tem necessidades específicas. O orquestrador deve ter um workflow próprio para ele.

### 25.1 Áreas críticas

```text
- player
- AlphaTab renderer
- cursor overlay
- YouTube/audio sync
- tab loading
- study page
- compose page
- explain tab
- editor mode
```

### 25.2 Bugs comuns esperados

```text
- micro-pausas do cursor
- flicker no loader
- renderização pauta por pauta
- cursor aparece antes da tab
- afinação aparece antes do conteúdo
- desalinhamento da tab
- consumo alto de RAM
- re-render excessivo
- offset incorreto com YouTube
```

### 25.3 Validações específicas

```text
- cursor smoothness test
- screenshot visual parity
- alphaTab load stability
- tab line color validation
- tab number positioning
- zoom/resize stability
- click accuracy
- selected beat highlight
```

### 25.4 Reaproveitamento do seu tab_debug_agent

O `tab_debug_agent` deve ser tratado como agente especializado de alta prioridade.

Fluxo:

```text
Orchestrator
  ↓
TabzerWorkflow
  ↓
TabDebugAdapter
  ↓
tab_debug_agent/run_agent.py
  ↓
RegressionSuite
  ↓
ReviewerAgent
```

---

## 26. Feature Creator avançado

O criador de features precisa evitar sair codando sem especificação.

### 26.1 Pipeline ideal

```text
User Request
  ↓
Product Spec Agent
  ↓
Acceptance Criteria Agent
  ↓
Technical Design Agent
  ↓
Repo Mapper Agent
  ↓
Test Writer Agent
  ↓
Implementation Agent
  ↓
Validation Agent
  ↓
Docs Agent
  ↓
Reviewer Agent
```

### 26.2 Exemplo: Feature Explain Tab

Pedido:

```text
"quero um botão Explain Tab que explique o compasso selecionado"
```

O agente deve gerar:

```text
Spec:
- problema
- objetivo
- user flow
- critérios de aceite
- não objetivos

Plano técnico:
- componentes alterados
- endpoint necessário
- estado frontend
- cache
- teste Playwright

Implementação MVP:
- botão no overlay
- endpoint mockado ou serviço real mínimo
- painel lateral
- estado de loading/error
```

### 26.3 Definition of Done para feature

```text
- Critérios de aceite implementados
- Teste mínimo criado
- TypeScript passa
- Lint passa
- UI não quebra fluxo existente
- Documentação curta adicionada
- Reviewer aprovado
```

---

## 27. AGENTS.md para o repositório

Crie um arquivo `AGENTS.md` na raiz do repo.

```md
# AGENTS.md

## Project
Tabzer — plataforma de guitarra com player de tabs, estudo, composição, Explain Tab e recursos avançados similares/superiores ao Songsterr.

## Core rules
- Never modify `.env` or secrets.
- Never run destructive shell commands.
- Never remove tests to make validation pass.
- Prefer small patches.
- Always explain changed files.
- For bugfixes, reproduce before patching whenever possible.
- For features, write acceptance criteria before implementation.

## Frontend commands
- npm run typecheck
- npm run lint
- npm test
- npx playwright test

## Backend commands
- python -m ruff check .
- python -m pytest

## Tabzer-specific validation
- python agents/tab_debug_agent/run_agent.py --codex-stdout-only
- python agents/tab_debug_agent/run_fix_loop.py

## High-risk areas
- AlphaTab rendering
- cursor synchronization
- YouTube/audio offset
- editor mode selection
- package manager files
- authentication
- database migrations

## Preferred implementation style
- Small vertical slices
- Clear contracts
- Explicit loading/error states
- Avoid global side effects
- Avoid unnecessary re-renders
- Preserve current UX unless the task asks otherwise
```

---

## 28. Prompt mestre para Codex implementar o MVP

Use este prompt no Codex:

```md
Você está trabalhando no meu repositório Tabzer.

Eu já tenho uma pasta `agents/` com:

- backend_bug_agent
- frontend_bug_agent
- bug_team
- commander
- study_agent
- tab_debug_agent

Quero criar um orquestrador avançado em Python para correção automática de bugs e criação de features.

Crie a pasta:

backend/agents/orchestrator/

Com esta estrutura inicial:

- __init__.py
- main.py
- schemas.py
- state.py
- config.py
- workflows/bugfix_workflow.py
- workflows/feature_workflow.py
- workflows/tabzer_workflow.py
- tools/safe_shell.py
- tools/git_worktree.py
- tools/test_runner.py
- policies/command_policy.py
- policies/file_scope_policy.py
- adapters/frontend_bug_adapter.py
- adapters/backend_bug_adapter.py
- adapters/tab_debug_adapter.py

Requisitos obrigatórios:

1. Usar Python.
2. Incluir `sys.stdout.reconfigure(encoding="utf-8")` nos entrypoints.
3. Usar Pydantic para schemas.
4. Não usar `shell=True`.
5. Todo subprocess deve receber lista de argumentos.
6. Criar `.agent-runs/<task-id>` para cada execução.
7. Criar `.agent-worktrees/<task-id>` usando `git worktree`.
8. Não modificar `.env`, secrets ou lockfiles sem aprovação.
9. Reaproveitar os agentes existentes via adapters.
10. MVP não precisa chamar LLM ainda; pode gerar plano e relatório determinísticos.
11. Criar CLI com comandos:
   - bugfix
   - feature
   - diagnose
12. Cada execução deve gerar `final-report.md`.

Primeira entrega esperada:

- o comando abaixo deve funcionar:

```bash
python backend/agents/orchestrator/main.py bugfix --request "Corrigir micro-pausas do cursor no player" --autonomy 3
```

Mesmo que ainda não aplique patch real, ele deve:

- criar task_id;
- criar run dir;
- criar worktree se possível;
- rodar baseline básico;
- chamar adapters disponíveis;
- salvar JSONs;
- gerar relatório final.
```

---

## 29. Prompt para criar o Bugfix Agent real

```md
Agora evolua o `bugfix_workflow.py` para um workflow real de correção.

Requisitos:

1. Rodar baseline antes do patch.
2. Salvar logs em `.agent-runs/<task-id>/baseline`.
3. Criar `plan.json` com:
   - arquivos prováveis;
   - hipótese de causa;
   - validações necessárias;
   - risco.
4. Criar `attempts/attempt-001`.
5. Permitir aplicar patch somente dentro da worktree.
6. Rodar validações após patch.
7. Gerar `reviewer.json`.
8. Se validação falhar, fazer rollback do patch.
9. Limitar a 3 tentativas.
10. Nunca alterar arquivos bloqueados.

Não implemente LLM se não for necessário. Deixe interfaces limpas para plugar LLM depois.
```

---

## 30. Prompt para criar o Feature Agent real

```md
Evolua `feature_workflow.py`.

O fluxo deve ser:

1. Receber request.
2. Criar `feature_spec.json`.
3. Criar critérios de aceite.
4. Mapear arquivos prováveis.
5. Criar plano técnico.
6. Criar testes mínimos.
7. Implementar vertical slice.
8. Rodar validações.
9. Gerar documentação.
10. Gerar final-report.md.

Para o MVP, implemente o fluxo sem LLM usando templates e TODOs estruturados.
Depois vamos plugar LLM no planner e patch agent.
```

---

## 31. Prompt para integrar LLM depois

```md
Integre um LLM ao orquestrador com segurança.

Crie interfaces:

- LLMClient
- PlannerLLM
- PatchLLM
- ReviewerLLM

Regras:

1. O LLM nunca executa comando diretamente.
2. O LLM só retorna JSON validado por Pydantic.
3. O LLM só pode sugerir comandos da allowlist.
4. O LLM só pode sugerir arquivos dentro de allowed_paths.
5. O PatchLLM deve gerar unified diff.
6. O ReviewerLLM deve retornar aprovação/reprovação em JSON.
7. Se o JSON for inválido, retry com prompt de correção.
8. Se continuar inválido, marcar task como failed.
```

---

## 32. Roadmap recomendado

## Fase 1 — MVP seguro

Objetivo: criar estrutura confiável sem LLM.

Entregas:

```text
- schemas Pydantic
- CLI
- run directory
- worktree manager
- safe shell
- adapters para agentes atuais
- baseline validation
- final-report.md
```

## Fase 2 — Bugfix automático controlado

Objetivo: permitir correções pequenas.

Entregas:

```text
- patch applier
- rollback
- attempts
- reviewer
- file policy
- command policy
- blocked paths
```

## Fase 3 — Feature creator

Objetivo: criar features pequenas com spec.

Entregas:

```text
- feature spec generator
- acceptance criteria
- test writer
- docs agent
- vertical slice implementation
```

## Fase 4 — Dashboard

Objetivo: acompanhar agentes visualmente.

Entregas:

```text
- tela Next.js de execuções
- timeline de agentes
- viewer de diff
- viewer de logs
- botão aprovar/rejeitar
- botão abrir PR
```

## Fase 5 — Memória e aprendizado

Objetivo: reaproveitar histórico.

Entregas:

```text
- banco de execuções
- embeddings de bugs/patches
- busca por bugs similares
- métricas de sucesso por agente
```

## Fase 6 — PR automático

Objetivo: integrar com GitHub.

Entregas:

```text
- branch automática
- commit assinado/opcional
- PR description
- labels
- link para relatório
```

## Fase 7 — Agent OS completo

Objetivo: plataforma avançada.

Entregas:

```text
- LangGraph workflows
- OpenAI Agents SDK
- MCP tools
- OpenTelemetry completo
- sandbox/container execution
- CI agent
- visual regression agent
```

---

## 33. Plano de implementação em 14 dias

### Dia 1

Criar estrutura `backend/agents/orchestrator`.

### Dia 2

Implementar `schemas.py`, `state.py`, `config.py`.

### Dia 3

Implementar `safe_shell.py` e `command_policy.py`.

### Dia 4

Implementar `git_worktree.py`.

### Dia 5

Implementar `run_store.py` e geração de `.agent-runs`.

### Dia 6

Criar adapters para `frontend_bug_agent` e `backend_bug_agent`.

### Dia 7

Criar adapter para `tab_debug_agent`.

### Dia 8

Implementar `bugfix_workflow.py` MVP.

### Dia 9

Implementar `feature_workflow.py` MVP.

### Dia 10

Criar `reviewer_agent.py` determinístico.

### Dia 11

Adicionar patch attempts e rollback.

### Dia 12

Adicionar `final-report.md` completo.

### Dia 13

Criar dashboard básico em Next.js.

### Dia 14

Criar integração opcional com GitHub PR.

---

## 34. Riscos técnicos

### 34.1 Agente mexer demais

Mitigação:

```text
- allowed_paths
- blocked_paths
- max_files_changed
- reviewer obrigatório
```

### 34.2 Corrigir sintoma e não causa

Mitigação:

```text
- reproducer obrigatório
- teste de regressão
- root cause summary
```

### 34.3 Loop infinito de tentativas

Mitigação:

```text
- max_attempts = 3
- max_duration
- custo máximo
- rollback por tentativa
```

### 34.4 Quebrar UX do Tabzer

Mitigação:

```text
- Playwright
- screenshot diff
- visual parity checks
- teste específico de cursor
```

### 34.5 Comando perigoso

Mitigação:

```text
- command allowlist
- subprocess sem shell
- human approval
```

---

## 35. Definition of Done do orquestrador

O sistema pode ser considerado utilizável quando:

```text
- cria task_id automaticamente
- cria worktree isolada
- roda baseline
- chama agentes atuais via adapters
- salva logs e artefatos
- gera relatório final
- respeita blocked paths
- não usa shell=True
- suporta no mínimo bugfix e feature
- tem reviewer automático
- suporta aprovação humana para ações sensíveis
```

---

## 36. Resultado esperado do MVP

Entrada:

```bash
python backend/agents/orchestrator/main.py bugfix \
  --request "Corrigir flicker da tab no carregamento" \
  --autonomy 3
```

Saída:

```text
[AgentOS] Task created: bugfix-20260427-101530
[AgentOS] Worktree created: .agent-worktrees/bugfix-20260427-101530
[AgentOS] Running baseline validations...
[AgentOS] Running frontend_bug_agent...
[AgentOS] Running tab_debug_agent...
[AgentOS] Creating plan...
[AgentOS] Generating final report...
[AgentOS] Done: .agent-runs/bugfix-20260427-101530/final-report.md
```

---

## 37. Referências técnicas oficiais

- OpenAI Agents SDK: https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK — Sandboxes: https://developers.openai.com/api/docs/guides/agents/sandboxes
- OpenAI Cookbook — Agents: https://developers.openai.com/cookbook/topic/agents
- LangGraph / LangChain multi-agent docs: https://docs.langchain.com/oss/python/langchain/multi-agent
- Microsoft Agent Framework: https://learn.microsoft.com/en-us/agent-framework/overview/
- Model Context Protocol specification: https://modelcontextprotocol.io/specification/2025-11-25
- OpenTelemetry: https://opentelemetry.io/

---

## 38. Recomendação final

A melhor estratégia para o seu caso é evoluir em camadas:

```text
1. Não apagar os agentes atuais.
2. Criar um orquestrador central.
3. Padronizar contratos com Pydantic.
4. Executar tudo em git worktree.
5. Rodar baseline antes de qualquer patch.
6. Criar reviewer automático.
7. Adicionar feature workflow.
8. Criar dashboard.
9. Adicionar memória vetorial.
10. Só depois abrir PR automaticamente.
```

O `tab_debug_agent` que você já tem é o embrião mais forte. Ele deve virar um worker especializado dentro do novo Agent OS.

A meta final é que você consiga escrever:

```text
"Corrija o problema do cursor que fica dando micro-pausas no player e abra um PR se os testes passarem."
```

E o sistema faça:

```text
intake -> worktree -> baseline -> reproducer -> plan -> patch -> validate -> review -> report -> PR
```

com segurança, rastreabilidade e controle humano.
