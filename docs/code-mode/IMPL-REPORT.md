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
