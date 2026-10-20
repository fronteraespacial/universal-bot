# Sidecar `cursor-sdk` (contrato v1)

Proceso Node autocontenido que expone `@cursor/sdk` **1.0.40** (fijado en `package.json` / `package-lock.json`) con una interfaz de proceso: **un request JSON por stdin → JSONL por stdout**. Lo puede usar cualquier host (Universal-bot, FE-BOT) sin importar código del otro.

## Invocación

```bash
echo '{"prompt":"Respondé solo OK"}' | bin/cursor-sdk-sidecar [--key-file <ruta>]
# o directo: <node>=22.13+ runner.mjs [--key-file <ruta>]
```

- **Node**: requiere ≥ 22.13. El lanzador `bin/cursor-sdk-sidecar` elige, en orden: `$CURSOR_SDK_NODE` → el `node` más nuevo que trae cursor-agent (`~/.local/share/cursor-agent/versions/*/node`, resuelto con `readlink -f`) → `node` del PATH. No toca el Node global. Con un Node viejo responde `NODE_TOO_OLD`.
- **Key** (nunca por argumento ni en el request): `--key-file <ruta>` → `$CURSOR_SDK_KEY_FILE` → `~/.secrets/cursor_api_key_frontera` → variable `CURSOR_API_KEY`. La key se redacta (`<redacted>`) de **todo** stdout/stderr del proceso, incluidos errores y logs del SDK.
- **Dependencias**: `npm ci --omit=dev` dentro de la carpeta (≈54 MB, incluye el binario `@cursor/sdk-linux-x64`).
- **Herramientas MCP**: deshabilitadas por defecto (`disallowedTools: ["mcp"]`) para que el agente local no herede servidores MCP del host.

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

Regla para el host: si `fallback` es `true`, reintentar **una vez** con `cursor-agent` (mismo prompt). El exit code y `code` siempre coinciden.

## Pruebas

```bash
npm test                          # node --test con SDK fake (47 tests; OLD_NODE=/usr/bin/node agrega el caso NODE_TOO_OLD real)
smoke/offline.sh                  # sin red (unshare -rn): BAD_REQUEST, NO_KEY, NETWORK con fallback, NODE_TOO_OLD; key falsa nunca filtrada
smoke/real.sh                     # gasta cuota mínima: "OK" + un steer corto
```

Medición 2026-10-20 (box Frontera, composer-2.5): sidecar wall 6,9 s (`duration_ms` 3,7 s, `sdk_duration_ms` 2,4 s); steer entregado (`complete_delivered`) y el run respondió `STEERED` en 9,1 s wall. `cursor-agent -p` con la misma consigna: 11,8 s (composer-2.5) y 11,1 s (composer-2.5-fast).
