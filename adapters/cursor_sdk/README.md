# Sidecar `cursor-sdk` (contrato v2, 0.2.0)

Proceso Node autocontenido que expone `@cursor/sdk` **1.0.40** (fijado en `package.json` / `package-lock.json`) con una interfaz de proceso: **un request JSON por stdin → JSONL por stdout** (one-shot) o **muchos requests JSONL por stdin en un proceso de larga vida** (`--serve`). stdout es solo JSONL: cualquier otra escritura (logs del SDK) se desvía a stderr. Cambios respecto de v1: `CHANGELOG-v2.md`. Lo puede usar cualquier host (Universal-bot, FE-BOT) sin importar código del otro.

## Invocación

```bash
echo '{"prompt":"Respondé solo OK"}' | bin/cursor-sdk-sidecar [--key-file <ruta>]     # one-shot
bin/cursor-sdk-sidecar --serve [--key-file <ruta>]                                    # larga vida (ver abajo)
bin/cursor-sdk-sidecar --capabilities        # JSON: versión, protocolo, campos, modos, ops, stores (no lee stdin ni key)
bin/cursor-sdk-sidecar --version
# o directo: <node>=22.13+ runner.mjs [...]
```

- **Node**: requiere ≥ 22.13. El lanzador `bin/cursor-sdk-sidecar` elige, en orden: `$CURSOR_SDK_NODE` → el `node` más nuevo que trae cursor-agent (`<home>/.local/share/cursor-agent/versions/*/node`, resuelto con `readlink -f`; el home sale de `$HOME` o, sin `$HOME`, de `getent passwd`) → `node` del PATH. No toca el Node global. Con un Node viejo responde `NODE_TOO_OLD`. `npm test` también pasa por el lanzador (`--exec-node`), así que funciona aunque el `node` del PATH sea 20.
- **Señales**: SIGTERM/SIGINT en cualquier momento (incluso antes de que Node cargue) dejan una línea final `CANCELLED` (exit 10).
- **Key** (nunca por argumento ni en el request): `--key-file <ruta>` → `$CURSOR_SDK_KEY_FILE` → `~/.secrets/cursor_api_key_frontera` → variable `CURSOR_API_KEY`. La key se redacta (`<redacted>`) de **todo** stdout/stderr del proceso, incluidos errores y logs del SDK.
- **Dependencias**: `npm ci --omit=dev` dentro de la carpeta (≈54 MB, incluye el binario `@cursor/sdk-linux-x64`).
- **Herramientas MCP**: deshabilitadas por defecto (`disallowedTools: ["mcp"]`). Con `mcp:true` se habilitan y se pasan `mcp_servers`. **Ojo**: `setting_sources` con `"user"` y `mcp:true` carga además los servidores de `~/.cursor/mcp.json` (verificado: el server del mcp.json de usuario se lanza) y las skills de usuario.
- **Store de agentes**: por defecto `ephemeral` (JSONL en un dir temporal que se borra al cerrar). Sin esto el SDK persiste en `~/.cursor/projects/<cwd-slug>/sdk-agent-store/` (SQLite, crece sin límite). Con store efímero sólo queda `~/.cursor/projects/<cwd-slug>/agent-transcripts/agent-*/…jsonl` (unos KB por run).

## Request (stdin, un objeto JSON)

| campo | tipo | default | notas |
|---|---|---|---|
| `prompt` | string no vacío | — | obligatorio |
| `system` | string | null | se pasa como `systemPrompt` del agente |
| `model` | string | `composer-2.5` | id de modelo de Cursor |
| `cwd` | string | cwd del proceso | directorio de trabajo del agente local |
| `timeout_s` | número > 0 | 120 | al vencer: `run.cancel()` + `TIMEOUT` |
| `stream` | bool | false | si es true, emite eventos `event` |
| `steer_file` | string | null | bandeja de steer (ruta absoluta o relativa a `cwd`): cada línea nueva `{"text":"…"}` (o texto plano) se entrega con `run.steer()` sin cortar el run |
| `cancel_file` | string | null | si aparece ese archivo, se cancela el run (`CANCELLED`) |
| `tools` | lista | null | allowlist de herramientas del SDK (`shell`, `read`, `edit`, …) |
| `mcp` | bool | false | habilita herramientas MCP (si es false: `disallowedTools:["mcp"]`) |
| `mcp_servers` | objeto | null | `mcpServers` del SDK; sólo se pasa con `mcp:true` |
| `setting_sources` | lista | null | capas de settings (`project`, `user`, `team`, `mdm`, `plugins`, `all`) |
| `model_params` | lista | `[{"id":"fast","value":"true"}]` para `composer-2.5` | params del modelo; explícitos ganan. Alias `composer-2.5-fast` = `composer-2.5` + fast |
| `http1` | bool | false | `Cursor.configure({local:{useHttp1ForAgent:true}})` |
| `session_id` | string | null | sólo `--serve`: reutiliza el agente entre requests |
| `store` | `ephemeral`\|`default`\|`dir` | `ephemeral` | ver "Store de agentes" |
| `store_dir` | string | null | con `store:"dir"` |
| `max_event_bytes` | int > 0 | 65536 | eventos más grandes se recortan (strings largos con `…[+N]`, conserva la forma; `truncated:true`) |
| `max_result_chars` | int > 0 | 200000 | `text` se corta; `text_truncated:true`, `text_len` = largo original |

**Validación estricta**: un campo desconocido es `BAD_REQUEST` y el mensaje lo nombra. Usá `--capabilities` para saber qué campos acepta el sidecar instalado.

`timeout_s` cubre todo (create + send + stream). Si el run ya terminó cuando llega un cancel/timeout, gana el resultado.

También cancelan `SIGTERM` y `SIGINT` (→ `CANCELLED`).

## Respuesta (stdout, JSONL)

Siempre termina con **exactamente una** línea final `result` o `error`.

```jsonc
{"type":"event","event":"status","data":{...}}          // solo con stream:true; data = mensaje del SDK tal cual (redactado)
{"type":"steer","ok":true,"outcome":"complete_delivered","text_len":59}   // por cada línea de la bandeja
{"type":"result","ok":true,"text":"OK",
 "usage":{"inputTokens":10543,"outputTokens":61,"cacheReadTokens":4480,"totalTokens":15084},
 "cost":null,                      // {"chargedCents":n} si getUsage() responde; en local hoy da feature_unavailable → null
 "duration_ms":3666,               // medido por el sidecar (create+send+wait)
 "sdk_duration_ms":2411,           // durationMs del RunResult
 "run_id":"run-…","agent_id":"agent-…","model":"composer-2.5"}
{"type":"error","ok":false,"code":"USAGE_LIMIT","message":"…","fallback":true,"exit_code":8}
```

`outcome` de steer: `complete_delivered` (el run lo tomó) o `revert_to_followup` (el turno ya terminó; el host debe mandarlo como mensaje nuevo). Si el SDK no soporta steer: `{"type":"steer","ok":false,"code":"STEER_UNSUPPORTED"}` (no es fatal).

## Códigos de error y exit codes (estables)

| code | exit | fallback a cursor-agent | cuándo |
|---|---|---|---|
| (ok) | 0 | — | resultado |
| `BAD_REQUEST` | 2 | **no** | request inválido: arreglar el host |
| `NO_KEY` | 3 | sí | no hay key en archivo ni env |
| `AUTH_INVALID` | 4 | sí | key rechazada (401 / AuthenticationError) |
| `NODE_TOO_OLD` | 5 | sí | Node < 22.13 |
| `SDK_MISSING` | 6 | sí | no se pudo cargar `@cursor/sdk` (falta `npm ci`) |
| `TIMEOUT` | 7 | sí | venció `timeout_s` (run cancelado) |
| `USAGE_LIMIT` | 8 | sí* | 429 / RateLimitError / "usage limit". *El SDK usa la key de API; cursor-agent usa la sesión del CLI: puede tener otra pool. Si cursor-agent también da límite, pasar al siguiente CLI de la cadena |
| `SDK_ERROR` | 9 | sí | cualquier otro error del SDK o run terminado en `error` |
| `CANCELLED` | 10 | **no** | `cancel_file`, SIGTERM o SIGINT: lo pidió el host |
| `NETWORK` | 11 | sí | sin red / DNS / conexión rechazada |
| `BUSY` | 12 | **no** | `--serve`: la sesión ya tiene un run en curso |

Regla para el host: si `fallback` es `true`, reintentar **una vez** con `cursor-agent` (mismo prompt). El exit code y `code` siempre coinciden.

## Modo `--serve` (larga vida)

Un proceso, muchas líneas JSON por stdin; cada línea de salida lleva `id` (y `session_id` en los runs). EOF en stdin o `{"op":"shutdown"}` → cancela lo vivo, cierra agentes, borra stores, exit 0. SIGTERM → cada run vivo emite su línea final `CANCELLED`. Si el host cierra stdout, el proceso corta y sale.

```jsonc
{"op":"run","id":"r1","session_id":"s1","prompt":"…", /* + cualquier campo del request */}
{"op":"steer","id":"x","target":"r1","text":"…"}     // → {"id":"x","target":"r1","type":"steer","ok":true,"outcome":"complete_delivered"}
{"op":"cancel","id":"y","target":"r1"}               // → ack + línea final CANCELLED del run
{"op":"close","id":"z","session_id":"s1"}           // cierra el agente de la sesión
{"op":"ping","id":"p"}                               // → {"type":"pong","sessions":[…],"running":[…]}
{"op":"shutdown"}
```

Con el mismo `session_id` el agente se crea una vez y los runs siguientes son turnos del mismo agente (historial incluido); sin `session_id` cada run usa un agente propio que se cierra al terminar. Un segundo `run` en una sesión ocupada → `BUSY`. Una línea inválida → `error` con `id` (o `null`), el proceso sigue.

## Pruebas

```bash
npm test                          # node --test con SDK fake (64 tests) vía el lanzador; OLD_NODE=/usr/bin/node agrega el caso NODE_TOO_OLD real
smoke/offline.sh                  # sin red (unshare -rn): BAD_REQUEST, NO_KEY, NETWORK con fallback, NODE_TOO_OLD; key falsa nunca filtrada
smoke/real.sh                     # vía el lanzador; gasta cuota mínima: "OK" + un steer corto
```

Medición 2026-10-20 (box Frontera, composer-2.5): sidecar wall 6,9 s (`duration_ms` 3,7 s, `sdk_duration_ms` 2,4 s); steer entregado (`complete_delivered`) y el run respondió `STEERED` en 9,1 s wall. `cursor-agent -p` con la misma consigna: 11,8 s (composer-2.5) y 11,1 s (composer-2.5-fast).

Medición v2 2026-10-20 (composer-2.5 fast, una muestra por fila; detalle en `docs/code-mode/evidence/sidecar-v2-bench.md`): one-shot sin MCP 4,5 s / 35k tokens; `--serve` primer request 5,2 s, siguiente en la misma sesión 1,3–2,3 s; `cursor-agent -p` sin MCP 17,7 s wall / 58k tokens.
