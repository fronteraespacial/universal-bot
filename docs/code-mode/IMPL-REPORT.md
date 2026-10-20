# Modo código — informe de implementación

Trabajo en el worktree `<repo>`, rama `feat/code-mode-labcode`. No se hizo push. El adaptador de Discord es el spool del puente (`FileOutboxDiscordPort`). No hay token y no se usa discord.py para hablar con Discord.

## Cómo correr los tests

```bash
cd <repo>
.venv/bin/python -m pytest -q
```

Resumen de la suite completa, corrida después del feat e2e `4e7cf7a`:

```
........................................................................ [ 87%]
................................                                         [100%]
248 passed in 1.72s
```

La salida de cada par rojo/verde está en `docs/code-mode/evidence/`.

La fase 2 cierra en `0493ca0` (347 passed). La fase 3 cierra en `88e135e`. Suite vigente:

```
392 passed in 7.94s
```

## Cómo arrancar el runtime cuando Julian prenda el toggle

El spool de producción es `<fe-bot>/data/labcode/`. El heartbeat es el archivo `runtime.heartbeat` adentro de ese directorio. FE-BOT mira ese archivo: si falta o tiene más de 60 s, responde «code mode no disponible». El runtime lo tiene que tocar cada 20 s o menos.

El heartbeat tiene que estar fresco **antes** de prender `data/labcode.txt`. Si el toggle se prende primero, el puente contesta que el modo código no está y no encola el mensaje.

1. Arrancar el runtime (sin `--once`, para que siga latiendo):

```bash
cd <repo>
.venv/bin/python -m universal_bot.labcode_runtime \
  --spool <fe-bot>/data/labcode \
  --db <repo>/state/labcode.sqlite \
  --interval 10
```

`--interval` queda clavado en 20 s como máximo. La base sqlite no va dentro del repo de FE-BOT: vive en `state/`, que este repo ignora. El spool solo recibe el heartbeat, el `state.json` de cada job y las ops del outbox.

2. Confirmar que `<fe-bot>/data/labcode/runtime.heartbeat` existe y que la fecha de adentro tiene menos de 20 s.

3. Recién ahí, escribir `on` como primera línea no vacía ni comentario de `<fe-bot>/data/labcode.txt`. `FE_LABCODE=on` también lo prende y gana sobre el archivo.

No hace falta `UBLAB_DISCORD_TOKEN`. Este proceso no abre una conexión a Discord: escribe JSON en el outbox y el puente de FE-BOT es el que habla con el canal.

Esta sesión no arrancó ese comando contra el spool real.

## Servicios

| Servicio | Responsabilidad |
| --- | --- |
| `session_manager` | Sesión pegajosa por ubicación, pin, aviso, salida y expiración. Al salir o vencer, el proyecto en curso queda en PAUSED con checkpoint. |
| `proposer` | Una sola propuesta por pedido T2/T3 con confianza suficiente. Botones de canal, hilo, acá (1 h / 4 h / hasta salir) o «como siempre». |
| `project_provisioner` | Crea `#p-<slug>` o un hilo `p-<slug>`. Sin permiso pregunta al admin con dos mensajes. Tope lleno u oferta de hilo. Slug único. |
| `stage_router` | Etapas en orden. `02-lab` antes de `03-plan`. Modo hilo con prefijo. O2 reusa 04/05. El texto simple saca la jerga. |
| `ask_bridge` | Pregunta, botones y resume. El job termina en `waiting_human` y libera el slot. El primero que responde gana. |
| `security_gate` | Secretos de prod, hosts, escrituras, comandos destructivos y servicios reales. FAIL no corre tests. `security_check: off` en servidor compartido es error de config. |
| `prod_gate` | Única aprobación obligatoria. T3 solo un dev. El rechazo vuelve a RUNNING. |
| `plan_validator` | Publica el plan solo con evidencia real o un «sin probar» consultado. No pide aprobación. |
| `project_machine` | Tabla de transiciones de Project. Lo que no está no pasa. |
| `job_runner` | Corre un comando local en `<ts>-<slug>/` con prompt, stdout, stderr y meta. El timeout conserva la salida parcial. |
| `custom_id` | `ublab:<kind>:<id>:<opt>`. Tres partes, tope 100. `ublab:stop:` es distinto de `ub:stop:`. |
| `inbox_job` | Parsea `job.json` + `prompt.txt` a `InboxJob`. La ubicación de la sesión es `session_key`. |
| `file_outbox` | `FileOutboxDiscordPort`: ops atómicas al outbox, menciones apagadas, espera el `.result.json` con reloj inyectable. |
| `answers` | El click `pq` entra al ask, `prod` al gate y `stop` pausa el job con checkpoint. El archivo ya aplicado no se repite. |
| `heartbeat` | Toca `runtime.heartbeat`. Fresco hasta 20 s. A los 60 s el estado es «no disponible». |
| `labcode_runtime` | `python -m universal_bot.labcode_runtime --spool <dir>`. Late, consume el inbox una vez y aplica answers/stop. |
| `app` | Los tres recorridos e2e: sesión manual, hilo T2 hasta DONE sin aprobación, deploy T3 con un dev. |
| yaml | `load_code_mode_config`. Defaults del diseño. Ejemplo en `instances/frontera-labcode.example.yaml`. |

## Pares test / feat

| Unidad | test | feat | Evidencia |
| --- | --- | --- | --- |
| session manager | `f84b53a` | `c64b33c` | `01-session-manager-red.txt`, `01-session-manager-green.txt` |
| proposer | `c1aeb85` | `6b5df14` | `02-proposer-red.txt`, `02-proposer-green.txt` |
| project provisioner | `cfca479` | `5ab173d` | `03-project-provisioner-red.txt`, `03-project-provisioner-green.txt` |
| stage router | `aa91c86` | `1e5d515` | `04-stage-router-red.txt`, `04-stage-router-green.txt` |
| ask bridge | `b0db5f6` | `4c5d406` | `05-ask-bridge-red.txt`, `05-ask-bridge-green.txt` |
| security gate | `391f3c9` | `83447c8` | `06-security-gate-red.txt`, `06-security-gate-green.txt` |
| prod gate | `d07664c` | `7dbf54c` | `07-prod-gate-red.txt`, `07-prod-gate-green.txt` |
| plan validator | `3bb9a01` | `efae022` | `08-plan-validator-red.txt`, `08-plan-validator-green.txt` |
| custom_id | `84e42d4` | `b7d7a40` | `09-custom-id-red.txt`, `09-custom-id-green.txt` |
| InboxJob | `fbaad73` | `38d5cc6` | `10-inbox-job-red.txt`, `10-inbox-job-green.txt` |
| FileOutboxDiscordPort | `9582760` | `6762db7` | `11-file-outbox-red.txt`, `11-file-outbox-green.txt` |
| answers / stop | `c66df43` | `23fb80d` | `12-answers-red.txt`, `12-answers-green.txt` |
| heartbeat | `966b7e7` | `06e0f0a` | `13-heartbeat-red.txt`, `13-heartbeat-green.txt` |
| runtime run_once | `b03fbc4` | `5c466bd` | `14-runtime-red.txt`, `14-runtime-green.txt` |
| job runner | `e6b490f` | `bdb81c1` | `15-job-runner-red.txt`, `15-job-runner-green.txt` |
| máquina de Project | `c8a5950` | `f3c9c7c` | `16-project-machine-red.txt`, `16-project-machine-green.txt` |
| yaml | `27d702e` | `b37bb43` | `17-instance-config-red.txt`, `17-instance-config-green.txt` |
| e2e | `0cf48d3` | `4e7cf7a` | `18-e2e-red.txt`, `18-e2e-green.txt` |

El contrato del puente entró en el primer commit de esta parte (`84e42d4`): `docs/code-mode/ref/labcode-bridge-2026-10-20.md`.

## Simplificaciones

- El lab del e2e corre `python -c` vía `job_runner` y arma un `LabEvidence` con esa salida. No llama a un CLI de IA.
- Maverick no tiene runtime: el plan lleva el texto `CONSULT: sin cambios`.
- El stage router guarda los hilos en memoria, no en sqlite.
- El pedido al admin del provisioner son dos mensajes de texto, no una pregunta del ask bridge.
- Los recordatorios y la pausa de una `PendingQuestion` están en `ask_bridge.tick`. El loop del runtime no lo llama.
- `CodeModeApp` cubre los tres recorridos. No es el orquestador completo del diseño (replanteos, O2, presupuesto de labs, archivado).
- `unpin` y la respuesta efímera no existen en el puente: el port las rechaza. En los tests las cubre `FakeDiscord`.
- El tope de 10 canales `p-` lo aplica el bridge en `channels.json`. Acá el tope es `max_open_projects`.
- `create_channel` del port solo acepta como padre la categoría ADMINISTRACIÓN. El provisioner sigue pidiendo la categoría por nombre; el port escribe el `parent_id` configurado.
- La sección `lab` del yaml se acepta y no se guarda en un objeto propio. El resto de las claves del diseño sí carga, y lo que falta usa el default.
- No se escribió un adaptador discord.py. `discord.py` sigue en `pyproject.toml` porque el paquete del bot ya lo declaraba; nada del modo código lo importa. No se buscó ni se usó un token.

## Qué quedó afuera

- El runtime consume el inbox y lo marca `done`, aplica clicks y frena con stop. No llama a `CodeModeApp` con el prompt del job. Prender el toggle con el proceso arriba late el heartbeat y evita el «no disponible», pero el texto del mensaje todavía no recorre proposer, lab y plan solos.
- No hay conexión a Discord desde este proceso. Las menciones van apagadas en cada op (`allowed_mentions` con `parse` vacío y `replied_user` false).
- No hay progreso unificado, footer de cuota ni registro de los `p-` en el store de auto-activación. Eso es del puente.
- No se leyó ni se escribió `<fe-bot>` en esta sesión, y no se arrancó el runtime contra el spool real.

## Fase 2

El inbox ya entra por `CodeModeApp`. El lab es un CLI inyectado (`lab_runner`), con sandbox, presupuesto y Maverick. Los tests no llaman a grok.

| Unidad | test | feat | Evidencia |
| --- | --- | --- | --- |
| lab runner | `77637bf` | `5448c83` | `19-lab-runner-red.txt`, `19-lab-runner-green.txt` |
| inbox por CodeModeApp | `a0764e3` | `4ae2457` | `20-inbox-flow-red.txt`, `20-inbox-flow-green.txt` |
| ticks, hilos sqlite, prod T3 | `9ad7536` | `e7babe3` | `21-phase1-debts-red.txt`, `21-phase1-debts-green.txt` |
| e2e del job real del puente | `663865a` | `0493ca0` | `22-bridge-e2e-red.txt`, `22-bridge-e2e-green.txt` |
| flags del entrypoint | `72f8512` | `98a5b8d` | `23-cli-lab-red.txt`, `23-cli-lab-green.txt` |

El verde del e2e (`0493ca0`) quedó después del entrypoint. El rojo `663865a` es anterior. No se reescribió la historia.

### Ids de hilo sin result

El bridge no corre en tests ni en el humo, así que `run_once` usa el port con `defer_results=True`: publica la op y no espera el `.result.json`.

- `thread` se encola igual (`02-lab`, `03-plan`). `create_thread` devuelve `None`.
- El detalle técnico no entra a un hilo inventado. Va al canal, o al hilo raíz si el proyecto ya tiene uno, con prefijo `[02-lab]` o `[03-plan]`.
- `pin` no se escribe: sin id real de Discord no hay qué fijar. El mensaje del botón de salida sí se encola.
- `reply_ephemeral` y `unpin` no existen en el puente. Con resultados diferidos son no-op, para que una sesión vencida no corte la pasada.
- `allowed_mentions` sigue apagado. La respuesta al usuario lleva `reply_to` al mensaje original.
- Si más adelante hay un id de hilo (FakeDiscord en los tests, o un result que esta fase no consume), el post va adentro del hilo y sin prefijo. Ese id se guarda en sqlite (`stage_threads`) y otra instancia del router sobre el mismo archivo lo reutiliza.

### Humo

No se corrió contra grok ni contra el spool de FE-BOT. Lo hace el supervisor. Sin los flags de lab, el default es raíz `<tmp>/ub-labcode`, política `<codemode-base>/catalog/routing-policy.yaml`, 900 s de lab, 300 s de Maverick, tope 2 labs en T2 y 3 en T3. `--max-labs N` tapa los dos tiers con N.

```bash
cd <repo>
.venv/bin/python -m universal_bot.labcode_runtime \
  --spool <fe-bot>/data/labcode \
  --db <repo>/state/labcode.sqlite \
  --lab-root <tmp>/ub-labcode \
  --routing-policy <codemode-base>/catalog/routing-policy.yaml \
  --lab-timeout 900 \
  --maverick-timeout 300 \
  --interval 10
```

Hace falta el binario `grok` en el PATH. Esta sesión no lo invocó.

### Qué falta para prender el toggle

1. El heartbeat tiene que estar fresco antes de escribir `on` en `data/labcode.txt`. El proceso de arriba, sin `--once`, es el que late.
2. El puente de FE-BOT tiene que estar consumiendo el outbox. Hasta que no escriba `.result.json`, los hilos de etapa no tienen id de Discord y el detalle queda en el canal con prefijo.
3. `grok` tiene que poder correr en `<tmp>/ub-labcode` con la política de ruteo. Si no está, el lab no arranca.
4. Los botones `create_channel` y `create_thread` se muestran y no provisionan: solo `here_*`, `decline`, el stop y la pregunta de sandbox siguen el flujo.
5. El aviso de «no tenés permiso» es efímero. El puente no tiene esa op, así que con el port diferido no llega a Discord.
6. El pin de «modo activo» tampoco se encola mientras no haya id real.
7. No se tocó `<fe-bot>`, no hay token y no hay conexión a Discord desde este proceso.

## Fase 3

Arreglos previos al toggle y saneo del árbol público. Los ids reales y los paths internos no están en el código versionado: viven en `config/local.yaml` (gitignored) o en `UBLAB_*`. Sin allowlist, `handle_job` deja el job en `skipped` y no contesta. Los tests usan ids cortos (`100`, `200`). El guard `tests/test_no_internal_data.py` recorre `git ls-files` y falla si aparece un snowflake o un path interno del workspace o del home del box. No se editaron los cuatro archivos heredados de `origin/main`: `AGENTS.md`, `docs/architecture-review-codex-astra.md`, `tests/test_config.py`, `tests/test_progress_contract.py`.

| Unidad | test | feat | Evidencia |
| --- | --- | --- | --- |
| 24 sanitización y allowlist cerrada | `4f7eeb8` | `65c4f23` | `24-sanitizacion-red.txt`, `24-sanitizacion-green.txt` |
| 25 detalle técnico solo en el hilo | `15760ce` | `a8549a7` | `25-hilos-red.txt`, `25-hilos-green.txt` |
| 26 botones que encolan ops | `2e56cc2` | `78208be` | `26-botones-red.txt`, `26-botones-green.txt` |
| 27 sandbox bwrap | `57a3c7e` | `62b2d01` | `27-sandbox-red.txt`, `27-sandbox-green.txt` |
| 28 un argv por CLI y cuota | `7a314d3` | `946e391` | `28-adaptadores-red.txt`, `28-adaptadores-green.txt` |
| 29 frase de activación fuera de la hipótesis | `ab2d2aa` | `88e135e` | `29-hipotesis-red.txt`, `29-hipotesis-green.txt` |
| 30 runtime como servicio | `de96919` | `a562892` | `30-servicio-red.txt`, `30-servicio-green.txt` |

Los feat de 27 y 29 quedaron después del de 30. El código ya estaba verde; los commits de feat se hicieron al final, sin reescribir historia. Cada rojo es ancestro de su verde.

### Sandbox real

`bwrap_command` arma bubblewrap 0.12. Aísla esto:

- Filesystem de solo lectura: `/usr`, `/bin`, `/lib`, `/lib64` y `/etc` entero (no un recorte de certs).
- Escritura solo en el labdir (`--bind`). `/tmp` es tmpfs y va antes del bind, porque el lab suele vivir bajo `/tmp`.
- `HOME` es un tmpfs (`--tmpfs $HOME`): el home real queda tapado. `--unshare-all`, `--die-with-parent`, `--chdir` al labdir.
- Sin red por default. Un `python -c` adentro no lee un archivo fuera del labdir y no abre un socket.

No aísla esto:

- No hay allowlist de hosts. `--share-net` comparte toda la red o no comparte ninguna.
- grok, cursor-agent y opencode reciben `--share-net` siempre. La config del CLI entra como overlay efímero copy-on-write (`--overlay-src X --tmp-overlay X`): `~/.grok`; `~/.cursor` y `~/.config/cursor` (más `~/.local/share/cursor-agent` de solo lectura); `~/.local/share/opencode` y `~/.config/opencode` (más `~/.opencode` de solo lectura). Lo que el CLI escribe ahí se descarta al salir, pero las credenciales se leen desde el sandbox. El binario entra por su realpath. El resto del home no se monta.
- `lab.allow_network` o `--lab-allow-network` prenden `--share-net` también para el comando genérico.

### Servicio

```bash
cd <repo>
scripts/labcode-runtime.sh start \
  --spool <spool> \
  --db <repo>/state/labcode.sqlite \
  --log <repo>/state/labcode.log \
  --pidfile <repo>/state/labcode.pid \
  --interval 10
scripts/labcode-runtime.sh status --spool <spool> --pidfile <repo>/state/labcode.pid
scripts/labcode-runtime.sh stop --spool <spool> --pidfile <repo>/state/labcode.pid
```

`status` imprime `activo edad=<n>s` cuando el pid vive. La edad sale del texto ISO de `runtime.heartbeat`, no del mtime. `deploy/labcode-runtime.user.service` es una plantilla systemd `--user` con `<repo>` y `<spool>`. Esta sesión no arrancó el servicio contra el spool real.

La cuota de producción lee un JSON (`grok_remaining`) con `FileQuotaReader`. No hay lector por comando. Si el restante es 40 % o menos, elige `cursor-agent` con modelo `grok-4.7-high-fast`. Si el lector falla, usa la ruta de la política. La política por default está vacía: hay que pasarla en `config/local.yaml` o `UBLAB_ROUTING_POLICY`.

### Qué falta para prender el toggle

1. Heartbeat fresco antes de escribir `on` en `data/labcode.txt`. Sirve el módulo o `scripts/labcode-runtime.sh start` contra el spool del puente.
2. El puente tiene que consumir el outbox. Sin `.result.json` el detalle técnico queda en sqlite (`pending_stage_posts`) y se reintenta; no se manda al canal del usuario. El canal solo recibe el texto sin jerga, con `reply_to`.
3. Allowlist en `config/local.yaml` o `UBLAB_ALLOWED_CHANNELS`. Si no hay, no se sirve nada.
4. Binario del CLI en el PATH y, si se quiere el corte del 40 %, un JSON de cuota. Sin política de ruteo el lab no elige modelo.
5. La red del CLI no se puede limitar por host. Quien prenda el toggle acepta `--share-net` para grok, cursor-agent y opencode.
6. El aviso de «no tenés permiso» sigue siendo efímero. El puente no tiene esa op.
7. El pin necesita el id que devuelve el puente. Sin result no se encola.
8. No se tocó `<fe-bot>`, no hay token y esta sesión no arrancó el runtime contra el spool real.

## Fase 3b: warm, MAIN orquestador y humos

| Unidad | test | feat | Evidencia |
| --- | --- | --- | --- |
| 34 lab sin evidencia válida pregunta; job roto no tumba el runtime | `05bf0f2` | `ca7f83b` | `34-*` |
| 35 HOME tmpfs y overlays por CLI | `fc2a748` | `f4076e7` | `35-*` |
| 36 modo warm de 4 CLIs con pool | `49f298c` | `e2941f4` | `36-*` |
| 37 ids string del puente real | `9b2578b` | `0389c47` | `37-*` |
| 38 botones reales en el runtime diferido, heartbeat en hilo | `817cecb` | `98c79ec` | `38-*` |
| 39 opencode toma el texto final de los mensajes | `76a3a5c` | `84cf8dc` | `39-*` |
| 40/41 agy ERROR/interrupted y carrera de resume | `0de1a9f` | `acd3d53`, `fcd93a0` | `40-*`, `41-*` |
| 42 grok steer en vivo por `_x.ai/interject` | `cd4f5c8` | `e4211c0` | `42-*` |
| 43 MAIN orquestador | `03b1fb3` | `38bd5f6` | `43-*` |
| 44 runtime arma MAIN y workers | `980d9c0` | `e34a7ff`, `3249a2a` | `44-*` |

### Modo warm

`code_mode/warm.py` tiene una interfaz común (`start`, `prompt`, `steer`, `cancel`, `close`) y capacidades declaradas (`supports_live_steer`). `WarmPool` mantiene un proceso por (cli, modelo), con idle timeout, como máximo un reinicio (después avisa `restart_exhausted`) y fallback a one-shot.

| CLI | Proceso | Steer | Arranque | OK 1 | OK 2 |
| --- | --- | --- | --- | --- | --- |
| codex (gpt-6-luna) | `codex app-server` | en vivo (`turn/steer`) | 0.81 s | 4.23 s | 2.00 s |
| opencode (nemotron free) | `opencode serve` | en vivo (delivery steer) | 1.26 s | 2.10 s | 0.77 s |
| agy (gemini-3.8-flash low) | stream-json | SIGINT + resume | — | 2.81 s | 1.27–1.52 s |
| grok (grok-4.7 low) | `grok agent stdio` (ACP) | en vivo (`_x.ai/interject`) | 0.18 s | 2.00 s | 1.89 s |

Pendientes del warm:

- agy: el steer real falló porque el proceso muere tras el SIGINT. Con stream-json el MAIN no queda libre. Para hacer steer a través del MAIN hace falta manejar la TUI por PTY/tmux (o evaluar `agy remote-control serve`). No está implementado.
- opencode: el texto final real no se volvió a verificar después del fix.

### MAIN orquestador

Con `main.enabled`, un mensaje en una sesión con job activo no crea otro job: va al MAIN de esa sesión. El MAIN es un cerebro warm (por default grok-4.7 low) con un prompt de orquestador. Delega siempre, contesta corto y termina con `ACCION: {tipo: ninguna|steer|relanzar|frenar}`.

- El worker es un proceso aparte. En el runtime es el lab dentro del sandbox. Su steer es matar y relanzar con las instrucciones acumuladas.
- Ante una corrección urgente o un pedido de frenar, el MAIN corta (`relanzar`/`frenar`) en vez de esperar, porque un steer a un subagente recién entra entre pasos.
- La respuesta va con `reply_to` al mensaje del usuario.
- Botón «Frenar» (`ublab:main:<job>:frenar`). «Salir» frena el job y cierra la sesión.
- El estado vive en SQLite (`main_jobs`). Después de un crash el job se relanza una vez y, si no se puede, se avisa.

Humo (`evidence/smoke-20261020/main-run*.txt`): runtime real, puente simulado, MAIN grok real y worker largo simulado. Se probaron estado, cambio de orden con relanzamiento, resultado final y Frenar (respuesta 0.1 s después del click). Hubo 0 duplicados y el outbox quedó vacío. La latencia del MAIN fue de 2 a 10 s.

### Qué falta para prender el toggle (además de lo de arriba)

1. El MAIN publica en el canal o hilo de la sesión, pero no pasa por el pipeline de hilos de etapa (lab/plan). El resultado del worker lo resume el MAIN.
2. El cerebro del MAIN con cursor-sdk (`run.steer`) no está cableado. Hoy usa sesiones warm de `warm.py`. Si grok cae a 40 % o menos, hay que configurar `main.cli: cursor-agent`, que no tiene warm (habría que usar cursor-sdk).
3. agy por TUI para hacer steer a través del MAIN.
4. En modo canal con hilo conocido, el resumen plano también va al canal principal (el diseño actual de los tests lo pide así).
5. `pinned_message_id` es un placeholder local: el puente no tiene unpin.
6. Prueba en Discord real: la coordinan con Julian.

## Fase 3c: MAIN cursor-sdk, hilos de etapa, unpin, agy TUI y sidecar v2

| Unidad | test | feat | Evidencia |
| --- | --- | --- | --- |
| 45 cerebros del MAIN (sidecar, fallback, cursor-agent relanzar, selección por cuota) | `96af595` | `a0459cd` | `45-*` |
| 46 el runtime arma el MAIN con cursor-sdk primero; cuota de grok rutea MAIN y lab | `e558b6f` | `e6fe419` | `46-*` |
| 47 modo canal con hilo conocido: sin resumen duplicado en el canal | `1cb1244` | `b31d387` | `47-*` |
| 48 resultado del worker por 02-lab y 03-plan | `933bb44` | `5b9a329` | `48-*` |
| 49 sin unpin en el puente: el cierre edita el fijado | `e7a381d` | `e19b434` | `49-*` |
| 50/54 spike agy MAIN por TUI (tmux) | `56e315c`, `6481d02` | `9d74221` | `50-*`, `54-*` |
| 51 sidecar cursor-sdk v2 | `6ba7519` | `14a05b7` | `51-*` |
| 52 stdout del sidecar solo JSONL | `393b053` | `9d25847` | `52-*` |
| 53 serve sale limpio si el host cierra stdout | `976a0c6` | `64982e3` | `53-*` |

### MAIN con cursor-sdk

`main.cli: auto` (default) o `cursor-sdk`: el MAIN es `SidecarSession` (un run del sidecar por turno, historial corto en el prompt, `tools: ["read"]`, steer/cancel por archivos absolutos por turno). Si el sidecar pide fallback (`fallback: true`), `FallbackSession` pasa de forma pegajosa a grok warm si la cuota de grok es > 40 %, o a cursor-agent (`--mode ask`, grok-4.7-high-fast) con steer = matar y relanzar. Un cancel no dispara fallback.

La cuota sale de `main.quota_file` (JSON con el restante de grok). No hay escritor todavía: sin archivo se asume grok disponible. El escritor natural es un cron que vuelque `cli_quota grok_cli` a ese archivo (hoy `cli_quota grok_cli` responde HTTP 401).

Humo (`evidence/smoke-20261020/main-sdk-run1.txt`, spool temporal, puente simulado, sidecar real): 5 turnos del MAIN por cursor-sdk sin fallback, 4–9 s por turno. Hubo estado, cambio de alcance con relanzamiento del worker, el resultado en el hilo `02-lab` y la respuesta final con `reply_to`. 0 duplicados reales (el contador del driver marca 1 por los `content` vacíos de pin y thread). El outbox quedó vacío. `03-plan` no sale en el humo porque necesita `lab_runner.consult_maverick` (sólo existe con el runner de producción).

### Unpin

El puente no tiene `unpin`. Al salir, el runtime edita el mensaje fijado a «Modo programación terminado.» sin botones. En modo diferido, el id local (negativo, persistido en `spool/local_messages.json`) se resuelve contra el resultado del `send`. Si el resultado todavía no llegó, queda pendiente y se reintenta en el próximo tick. El mensaje queda fijado; agregar `unpin` al puente es del lado de FE-BOT.

### opencode

Texto final real re-verificado: «OK» en los dos turnos (arranque 1,30 s, OK1 1,87 s, OK2 0,71 s).

### agy por TUI (spike)

`AgyTuiSession` maneja `agy --model … --dangerously-skip-permissions` en un tmux con socket propio. Contesta el diálogo de confianza una sola vez, detecta la caja `>` entre separadores con el pie abajo, y la respuesta es lo nuevo entre lo tecleado y la caja. steer = escribir con el subagente vivo, cancel = Escape, close = matar el server y borrar el socket. En real (2 de 2): arranque 3,6 s, «OK» en 4,0 s (la corrida 1, antes del arreglo, se colgó en el diálogo).

Falta:

- cerrar el aviso «Verbosity…» dentro de la sesión (hoy lo hace el probe con Escape);
- un steer real con subagente;
- configurar Queued Messages = Send Immediately;
- el spinner;
- cablearlo en `select_main_session`.

### Sidecar cursor-sdk v2

Ver `adapters/cursor_sdk/CHANGELOG-v2.md` y `evidence/sidecar-v2-bench.md`.

- Passthroughs de FE-BOT (`mcp`, `mcp_servers`, `setting_sources`, `model_params`, `http1`).
- fast por defecto.
- Validación estricta y `--capabilities`.
- SIGTERM temprano con línea final.
- `timeout_s` sobre create+send.
- El resultado le gana al cancel tardío.
- Redacción con buffer.
- Truncado.
- Store efímero.
- stdout sólo JSONL.
- `--serve` de larga vida con `session_id`.

En `--serve`, el primer request de una sesión tarda ~5 s y los siguientes 1,3–2,3 s. El MAIN todavía usa one-shot por turno: pasarlo a `--serve` es el próximo paso para bajar los 4–9 s por turno.
