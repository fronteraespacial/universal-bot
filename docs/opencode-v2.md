# OpenCode V2 (Universal Bot) — guía para agentes instaladores

Documento en español para montar OpenCode V2 en un host con Universal Bot.
Neutral: sin nombres de canales, IDs, tokens ni credenciales de ningún pack de referencia.

Fuentes oficiales verificadas (2026-10-19):

- Server: <https://opencode.ai/docs/server/>
- Config: <https://opencode.ai/docs/config/>
- Zen / Console (pay-as-you-go + Free): <https://opencode.ai/docs/zen/>
- Go (suscripción): <https://opencode.ai/docs/go/>
- Providers / login: <https://opencode.ai/docs/providers/>
- MCP: <https://opencode.ai/docs/mcp-servers/>
- Skills: <https://opencode.ai/docs/skills/>
- CLI / env: <https://opencode.ai/docs/cli/>

No inventar flags ni endpoints: si algo no está en esas páginas o en `opencode --help`, no lo documentes como hecho.

## 1. Login y cuentas (auth)

1. Instalá el binario (`curl -fsSL https://opencode.ai/install | bash` u otro método de la doc).
2. En la TUI: `/connect`, o en CLI: `opencode auth login`.
3. **Zen / Console (pay-as-you-go)**: entrá a <https://opencode.ai/auth>, creá key, pegala. Modelos `opencode/<id>`.
4. **Go (suscripción)**: plan aparte en Console; `/connect` → OpenCode Go. Modelos `opencode-go/<id>`. Tener key Zen **no** otorga Go.
5. Variables documentadas por la comunidad/CLI: `OPENCODE_API_KEY` (alias Zen) y, donde aplique, key Go. Preferí `opencode auth login` en cada host.
6. **Nunca** copies `auth.json`, keys ni el password del serve al pack/repo. Cada host inicia sesión solo.

### Free Zen vs Go (HTTP / CLI)

- Modelos Free listados en la doc Zen (p. ej. `deepseek-v4.1-flash-free`, `glm-5.3-flash-free`) existen en el catálogo Console.
- Aprendizaje operativo del pack de referencia (2026-10): algunos ids Free **rechazan** el HTTP bare `zen/v1` (403 FreeTier) y solo responden bien vía **CLI** (`opencode run`). Por eso Universal Bot fuerza Free por CLI + serve compartido y remapea pins Free desconocidos a `UB_OPENCODE_FREE_MODEL` (default `deepseek-v4.1-flash-free`).
- Go expone HTTP/API bajo `https://opencode.ai/inference/go/...` (ver doc Go). El camino recomendado en bots sigue siendo CLI `opencode run --server` con provider `opencode-go/…`.
- Si aparece `api_key_expired` / 401: renovar key en Console y `opencode auth login` en **ese** host. El remap Free no arregla auth vencida.

## 2. Password del serve (`opencode service` / `OPENCODE_SERVER_PASSWORD`)

Según doc Server:

- `OPENCODE_SERVER_PASSWORD` protege `opencode serve` / `opencode web` con HTTP basic auth (usuario default `opencode`, override `OPENCODE_SERVER_USERNAME`).

CLI V2 en el binario actual también expone:

```bash
opencode service set password <valor>   # lo guarda OpenCode (p. ej. service.json bajo config de usuario)
opencode service get password           # lo lee el cliente; NO lo imprimas en logs/Discord
opencode service start|restart|status|stop
```

Clientes `opencode run --server` pueden usar `OPENCODE_PASSWORD` (lo que usa el helper de Universal Bot) o `OPENCODE_SERVER_PASSWORD`.

**Reglas:**

- El password vive en el host (gestionado por OpenCode). **Nunca** en el pack, PR ni ledger.
- Bind solo `127.0.0.1` (default oficial de `opencode serve --hostname`).
- Puerto configurable: `UB_OPENCODE_PORT` (default de este molde: `49374`). Doc upstream default: `4096`.

## 3. Modo de trabajo V2 (shared serve)

1. **Un serve compartido por host** (o por bot si hay varios y querés aislar puertos):  
   `opencode serve --hostname 127.0.0.1 --port $UB_OPENCODE_PORT`
2. **Todas las llamadas** del bot: `opencode run … --server http://127.0.0.1:$PORT` (no `--standalone` salvo `UB_OPENCODE_USE_SERVE=0`).
3. Modelo: `-m provider/model#variant` (`#low` / `#high` vía esfuerzo).
4. **`--auto` exige PTY**: sin TTY el proceso se cuelga. Linux: `pty.openpty` (helper `universal_bot.opencode.pty_spawn`). Windows: ConPTY/`pywinpty` opcional; si no hay PTY → fallback serve-only (sin `--auto` o error claro).
5. **MCP** en el `opencode.json` **por bot** vía wrapper `run_mcp.sh` (venv + `mcp_server.py` del bot). No uses un único `~/.config/opencode` global si hay varios bots en el mismo host.
6. **Skills** en `.opencode/skills/<bot>-pack-rules` y `get-time` (plantillas en `install/templates/opencode/skills/`).
7. Config por bot: `UB_OPENCODE_CONFIG` (archivo) y/o `UB_OPENCODE_CONFIG_DIR` (dir tipo `.opencode`). Ver precedence en doc Config (`OPENCODE_CONFIG`, `OPENCODE_CONFIG_DIR`).

Healthcheck oficial: `GET /global/health` → `{ "healthy": true, "version": "…" }`.

## 4. Variables de entorno Universal Bot

| Variable | Default | Rol |
| --- | --- | --- |
| `UB_OPENCODE_USE_SERVE` | `1` | `0` → `--standalone` |
| `UB_OPENCODE_HOST` | `127.0.0.1` | Solo loopback (helpers rechazan `0.0.0.0`) |
| `UB_OPENCODE_PORT` | `49374` | Puerto del serve |
| `UB_OPENCODE_FREE_MODEL` | `deepseek-v4.1-flash-free` | Remap Free |
| `UB_OPENCODE_DEFAULT_SERVE_MODEL` | `deepseek-v4.1-flash` | Default Go sin pin |
| `UB_OPENCODE_CONFIG` | vacío | `OPENCODE_CONFIG` por bot |
| `UB_OPENCODE_CONFIG_DIR` | vacío | `OPENCODE_CONFIG_DIR` por bot |
| `UB_OPENCODE_BIN` | `opencode` | Binario |
| `UB_OPENCODE_REQUIRE_PTY` | `1` | Exigir PTY con `--auto` |

**FE / packs de referencia:** pueden conservar aliases `FE_OPENCODE_*` **solo en ese pack**, mapeándolos a `UB_OPENCODE_*` al llamar esta librería. Este repo **no** lee `FE_*`.

## 5. Systemd (Linux) y Scheduled Task (Windows)

- Plantilla user unit: `install/linux/ub-opencode-serve.service`
- Hook watchdog: `install/linux/ensure_opencode_serve.sh`
- Windows: `install/windows/opencode-serve-task.ps1` (`-Install` / `-Ensure`)

Reinicio: `systemctl --user restart ub-opencode-serve.service` o `opencode service restart`.

## 6. Smoke del instalador

```bash
bash install/linux/smoke_opencode_serve.sh
```

Flujo: health → `opencode run` Free (`deepseek-v4.1-flash-free`) con `--server` → el modelo puede llamar MCP `get_current_time` si el `opencode.json` del bot lo cableó. No escribe credenciales al pack.

## 7. Librería Python

Paquete: `universal_bot.opencode`

- `load_opencode_env` / `build_run_argv` / `plan_run` / `prepare_run_env`
- `spawn_with_pty` / `healthcheck` / `restart_serve_hint`
- `remap_free_model` / `format_model_arg` / `format_go_model`
- `write_bot_opencode_layout` / renderers de MCP + skills

Tests unitarios: `tests/test_opencode_*.py` (sin red ni login real).

## 8. Qué queda fuera de este PR / host

- Listener Discord portable (otro PR).
- Copiar auth de un humano o de otro host.
- Exponer el serve fuera de loopback.
