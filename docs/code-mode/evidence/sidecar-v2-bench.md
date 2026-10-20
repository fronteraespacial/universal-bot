# Sidecar v2: medición real (2026-10-20, ~19:49–19:56 ART)

Condiciones: composer-2.5 con fast=true, una muestra por fila (ruido alto: el modelo decide cuántas llamadas hace),
consigna "Decime qué hora es ahora en Buenos Aires (usá una herramienta si hace falta) y respondé en una sola línea."
MCP de medición inofensivo (`dummy`, 70 herramientas sin efectos + `get_time`); **no** se usó el MCP del pack.
HOME falso con copia de rules/skills/plugins del usuario y un `mcp.json` de usuario con otro server inofensivo (`userdummy`).
"tokens" = totalTokens del SDK (suma de todas las llamadas al modelo del run, incluye cache read).

| caso | wall s | tokens | in | cache read | out |
|---|---|---|---|---|---|
| one-shot sin MCP, sin settings (default v2) | 4,46 | 35 287 | 21 665 | 13 376 | 246 |
| one-shot tipo FE-BOT (mcp dummy + settings user,project) | 5,90 | 48 133 | 26 505 | 21 312 | 316 |
| serve sin MCP, 1er request (sesión a) | 5,19 / 5,27 | 35 513 / 27 108 | | | |
| serve sin MCP, 2do request misma sesión (seguimiento corto) | 2,25 / 1,31 | 13 947 / 22 241 | | | |
| serve tipo FE-BOT, 1er request (sesión b) | 4,79 | 41 576 | 26 409 | 14 880 | 287 |
| serve tipo FE-BOT, 2do request misma sesión | 2,02 | 18 293 | 9 071 | 8 960 | 262 |
| serve mcp dummy sin settings | 5,05 | 31 892 | 25 130 | 6 464 | 298 |
| serve settings user,project sin MCP | 3,86 | 62 755 | 35 940 | 26 496 | 319 |
| serve mcp:true + settings ["user"] sin mcp_servers | 5,75 / 5,57 | 44 722 / 46 485 | | | |
| serve tipo FE-BOT con settings ["project"] | 3,70 | 44 374 | 24 974 | 19 200 | 200 |
| serve tools ["shell"] (allowlist) | 2,46 | 13 630 | 8 258 | 5 216 | 156 |
| one-shot "Respondé solo OK" (store efímero) | 3,0 (duration) | 13 308 | 10 707 | 2 560 | 41 |
| cursor-agent -p sin MCP (HOME real, cwd nuevo, sin MCP lanzados) | 17,71 (duration 7,31) | 57 851 | 13 217 | 44 256 | 378 |

Referencia FE-BOT (con el MCP del pack, consigna real suya): SDK 27,9 s / 144,8k tokens; cursor-agent 24,4 s / 107,5k.

## Lectura
- **Arranque**: el primer request de un proceso/agente cuesta ~4,5–5,3 s; en `--serve` los siguientes de la misma sesión 1,3–2,3 s. El ~3 s por llamada que midió FE-BOT se paga una vez por sesión.
- **Capa `user`**: con `mcp:true` lanza los servers de `~/.cursor/mcp.json` (marcador de arranque del `userdummy` escrito) y carga 19 skills. Es la causa más probable del +35% de FE-BOT: en el box real esa capa suma otra vez `fe-bot-pack` + `playwright` + `box-desktop`.
- **Herramientas**: el allowlist `tools:["shell"]` bajó a 13,6k (vs 27–35k): los esquemas de herramientas pesan más que el prompt.
- **Propuesta**: `setting_sources: ["project"]` (o `[]`) + `mcp_servers` explícito; `tools` mínimo para la conversación; `--serve` con `session_id` para no pagar el arranque ni re-mandar contexto frío. `systemPrompt` propio reemplaza el del harness pero está detrás de un flag del servidor: no medido.
- **Store**: con el store efímero no se creó `sdk-agent-store`; queda sólo `agent-transcripts/agent-*.jsonl` (≈KB) bajo `~/.cursor/projects/<slug>/`.

Corridas reales gastadas: sidecar ≈19 (2 one-shot, 8 serve, 2 sondas, 1 "OK", ≈6 en dos series de serve cortadas por el bug de stdout que se arregló), cursor-agent 1 OK + 1 colgado con HOME falso (sin login, cortado a 150 s, sin cuota).
