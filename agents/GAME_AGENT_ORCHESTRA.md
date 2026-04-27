# Game Agent Orchestra

Contexto para adaptar a pasta `agents/` ao projeto Godot deste repositório.

## Projeto

Jogo 2D em Godot com:

- cenas em `scenes/`
- gameplay em `scripts/`
- sprites e spritesheets em `art/`
- audio em `audio/`
- recursos em `resources/`
- ferramentas de geração/processamento em `tools/`

## Agentes Especializados

- `game_director_agent`: transforma pedidos em critérios de aceite jogáveis.
- `godot_repo_mapper_agent`: encontra scripts, cenas, assets e recursos afetados.
- `level_designer_agent`: cria ou adapta cenários, plataformas, spawns e ritmo.
- `level_qa_agent`: valida colisões, travamentos, posicionamento e travessia do mapa.
- `mechanics_agent`: implementa movimento, combate, defesa, dano e interações.
- `enemy_ai_agent`: evolui estados de IA, percepção, ataque, recuo, morte e patrulha.
- `character_animation_agent`: integra spritesheets e animações do player/inimigos.
- `asset_pipeline_agent`: limpa transparência, gera frames e audita imports.
- `render_perf_agent`: ajusta câmera, z-index, render, parallax, iluminação e FPS.
- `audio_agent`: integra música, SFX, mixagem e gatilhos de gameplay.
- `godot_test_agent`: roda validações headless e smoke tests.
- `reviewer_game_agent`: revisa risco, escopo, jogabilidade e regressões.

## Workflows

- `game_specialized`: tarefas amplas de gameplay Godot.
- `level_design`: cenários, mapas, plataformas, spawns e progressão.
- `enemy_ai`: comportamento de inimigos e personagens controlados por IA.
- `asset_pipeline`: spritesheets, transparência, frames e import settings.
- `render_pass`: câmera, composição visual, layers e performance.
- `mechanic`: movimentos, combate, defesa, hitboxes e regras de jogo.

## Fluxo Para Criar Cenas Por Descrição

O fluxo ideal é:

```text
descrição do usuário
  -> level_designer_agent
  -> scene_brief.json
  -> game_workflow plan.json
  -> agents especializados
  -> validação Godot/assets
  -> revisão jogável
```

O usuário pode escrever algo como:

```text
Crie uma cena em um data center destruído, com chuva azul ao fundo,
duas plataformas, um inimigo patrulhando no chão, um atirador em cima,
cabos no foreground, câmera acompanhando o player e uma saída à direita.
O player precisa conseguir passar agachado por baixo de uma barreira.
```

O `scene_brief.json` deve quebrar isso em:

- tema e clima
- objetivo do jogador
- layout macro
- plataformas e colisões
- hazards
- inimigos e posicionamento
- props e background
- render/iluminação
- áudio
- mecânicas necessárias
- câmera e limites
- critérios de aceite

Nenhum agent deve sair criando cenário antes desse brief existir.

## Validações Esperadas

- estrutura Godot: `project.godot`, `scenes/`, `scripts/`, `art/`
- smoke headless via `GODOT_BIN` quando disponível
- auditoria de assets e `.import`
- verificação manual da `scenes/main.tscn`
- checks específicos de colisão, câmera e animações por tarefa

## Regras

- Preferir mudanças pequenas e verticais.
- Preservar nomes de nodes e caminhos `res://` quando possível.
- Não mexer em assets fora do escopo do pedido.
- Para cenários, sempre definir chão, limites, câmera, spawn do player e spawn de inimigos.
- Para IA, manter estados explícitos e cooldowns previsíveis.
- Para sprites, conferir transparência, bounds, baseline e escala.
