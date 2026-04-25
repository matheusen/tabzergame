# Tabzer Game

Projeto migrado para Godot 4.6.2-stable, estruturado como um jogo 2D de acao/plataforma com os assets gerados.

## Como abrir

1. Abra o Godot 4.6.2 ou mais recente da serie 4.x.
2. Clique em **Import**.
3. Selecione `project.godot` nesta pasta: `c:\Users\Matheus\Documents\tabzerGame`.
4. Abra `scenes/main.tscn` ou rode o projeto diretamente.

## Controles

- `A` / seta esquerda: mover para esquerda.
- `D` / seta direita: mover para direita.
- `W` / seta para cima / `Space`: pular.
- `S` / seta baixo: abaixar.
- `J` / `Ctrl`: ataque leve.
- `K`: ataque pesado.

## Estrutura

- `art/UI`: mockup de HUD e atlas visual de interface.
- `art/Environment`: cenario de sala/escritorio e tiles/partes do ambiente.
- `art/VFX`: efeitos de ataque, impacto, magia e particulas.
- `art/Props`: props de escritorio, canecas, computador, teclado e itens.
- `art/Enemies`: spritesheets do inimigo escuro.
- `art/Player`: spritesheets do personagem principal.
- `art/DesignReferences`: telas de referencia do modo Focus Quest.
- `Docs/asset_contact_sheet.png`: folha de contato com todos os PNGs originais.
- `scenes/main.tscn`: cena inicial jogavel.
- `scripts/player_controller.gd`: movimento base do personagem.
- `scripts/follow_camera.gd`: camera 2D seguindo o personagem.
- `art/Player/Generated`: frames recortados com fundo transparente para animacao.
- `tools/generate_player_frames.gd`: ferramenta usada para regenerar os frames do player a partir dos spritesheets.
- `audio/music`: temas musicais do jogo.
- `resources/music`: configuracoes `MusicTrack` usadas pelas cenas.
- `scripts/music_director.gd`: gerenciador global de musica de fundo.
- `Docs/riff_protocol_game_context.md`: documento mestre com historia, lore, fases, bosses, inimigos e escopo do game.

## Proximo passo recomendado

No editor do Godot, configure regioes/animacoes dos spritesheets em `art/Player` e `art/Enemies`, depois substitua a regiao temporaria do `Sprite2D` do Hero por um `AnimatedSprite2D`.

## Adicionando temas

Coloque o arquivo de audio em `audio/music`, crie um recurso `.tres` em `resources/music` usando `MusicTrack`, e atribua esse recurso ao campo `background_music` da cena.
