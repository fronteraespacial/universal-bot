# cursor-sdk-sidecar 0.2.0 (contrato v2) — cambios desde v1

Compatible con lo que FE-BOT manda hoy (`prompt, model, model_params, cwd, timeout_s, stream, mcp, mcp_servers,
setting_sources, http1, steer_file, cancel_file`) y con su sonda de capacidades (los tokens `mcp_servers` /
`setting_sources` / `model_params` en `lib/protocol.mjs` y `mcpServers` / `settingSources` en `lib/main.mjs` siguen).

## Nuevo
- **Passthroughs de FE-BOT adoptados con la misma semántica**: `mcp`, `mcp_servers`, `setting_sources`, `model_params`, `http1`.
- **Fast por defecto**: `composer-2.5` sin `model_params` → `[{"id":"fast","value":"true"}]`. Alias `composer-2.5-fast`. `model_params` explícitos ganan (FE-BOT manda `fast=false` para el slug lento).
- **`--serve` (larga vida)**: un proceso, requests JSONL por stdin (`run`/`steer`/`cancel`/`close`/`ping`/`shutdown`), agente reutilizado por `session_id`, steer/cancel por `target`, `BUSY` (exit 12) si la sesión ya corre. Paga el arranque una sola vez.
- **`--capabilities` y `--version`** (sin stdin ni key): versión, protocolo 2, campos, modos, ops, stores, alias.
- **Store efímero por defecto** (`store: ephemeral|default|dir`, `store_dir`): JSONL en un dir temporal que se borra al cerrar. Evita el crecimiento de `~/.cursor/projects/<slug>/sdk-agent-store/` (hoy ~451 MB en 27 dirs `tmp-*` en este box).
- **Truncado**: `max_event_bytes` (64 KiB; recorta strings largos conservando la forma del evento) y `max_result_chars` (200 000; `text_truncated`, `text_len`).

## Arreglos
- **Validación estricta**: un campo desconocido → `BAD_REQUEST` que lo nombra (antes se ignoraba en silencio).
- **SIGTERM temprano**: los handlers se registran antes de cargar el resto; el lanzador también atrapa la señal. Siempre hay línea final `CANCELLED` (exit 10).
- **`timeout_s` cubre create + send** (antes solo el stream); un create tardío se cierra al llegar.
- **Carrera resultado vs cancel/timeout**: si el run ya terminó, gana el resultado.
- **Redacción con buffer**: una key partida entre dos writes ya no se escapa.
- **stdout es solo JSONL**: logs del SDK / `console.log` van a stderr.
- **Host que cierra stdout (EPIPE)**: serve corta los runs, cierra agentes y sale; los stores efímeros se borran también en `process.exit`/excepción.
- **Lanzador sin `$HOME`**: usa `getent passwd`. `npm test` pasa por el lanzador (`--exec-node`) → Node ≥ 22 aunque el PATH tenga 20.
- **El test "MCP apagado"** ahora verifica de verdad `disallowedTools:["mcp"]` y que no viajen `mcpServers`.
- **`smoke/real.sh`** usa el lanzador y no falla si el steer corta antes de crear `n.txt`.

## Hallazgo para FE-BOT (tokens)
`setting_sources: ["user", …]` + `mcp:true` carga **también** los servidores de `~/.cursor/mcp.json` (verificado: el server
del mcp.json de usuario se lanzó) y las 19 skills de usuario. En este box eso suma `fe-bot-pack` otra vez, `playwright`
y `box-desktop` (mouse/teclado) a la conversación. Recomendado: `setting_sources: ["project"]` (o `[]`) + `mcp_servers`
explícito; si la conversación no edita archivos, `tools` con allowlist. Números en `docs/code-mode/evidence/sidecar-v2-bench.md`.

## Migración
1. Apuntar `SIDECAR_DIR` a la carpeta v2 (la v1 queda intacta para volver atrás).
2. Sin cambios de request obligatorios. Opcional: `session_id` + `--serve` para reutilizar el proceso; `setting_sources: ["project"]`.
3. Si FE-BOT mandaba algún campo extra, ahora da `BAD_REQUEST`: chequear con `--capabilities`.
