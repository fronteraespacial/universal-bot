# Puente CodeMode de `#labcode` — 2026-10-20

El puente une exclusivamente `#labcode` (`<LABCODE_CHANNEL_ID>`) con el runtime local de CodeMode-BOT mediante un spool en disco. Solo Julian y Emanuel, sin prefijo de cerebro ni sticky de hilo, entran al puente. Prefijos o sticky siguen el routing normal.

El toggle es `data/labcode.txt`: la primera línea no vacía ni comentario acepta `on`, `1`, `true` o `yes`; todo lo demás falla cerrado en `off`. `FE_LABCODE=on|off` tiene prioridad. Rollback rápido: escribir `off`, sin bounce. Rollback completo: restaurar `backups/labcode-20261020/` y recién entonces hacer el bounce normal con `listener_health restart`.

Si aparece **“code mode no disponible”**, el heartbeat está vencido o falta: el runtime debe tocar `data/labcode/runtime.heartbeat` al menos cada 20 s. Si las operaciones quedan en outbox, verificar el toggle, que el loop haya iniciado al ready y los logs del listener. El puente nunca debe tirar el listener: los hooks capturan y registran excepciones.

| Lugar | Mensaje de Julian/Emanuel sin prefijo/sticky | Resto |
| --- | --- | --- |
| `#labcode`, sus hilos, p- registrados | job al spool si heartbeat fresco | routing normal / no bridge |
| Cualquier otro canal | routing normal | routing normal |

## Contrato para CodeMode-BOT

El runtime lee directorios `data/labcode/inbox/lc_<message_id>/`. Cada uno se publica atómicamente y contiene `job.json` y `prompt.txt`. `prompt.txt` es el prompt sin menciones del bot o rol.

`job.json` es versión `1` y tiene: `job_id` (string), `instance` (`fe-labcode`), `source` (`discord`), `guild_id`, `channel_id`, `thread_id` (string o `null`), `parent_channel_id`, `message_id`, `author` (`id`, `display_name`), `author_context` (string), `content_raw`, `prompt`, `attachments` (lista), `audio_transcripts` (lista), `previous_messages` (lista), `location_key`, `session_key` (igual a location), `created_ts` y `deadline_ts` (float; plazo 1800 s), `button_prefix` (`ublab:`), `reply_to_message_id`, `outbox_dir` y `answers_dir` (paths absolutos).

El runtime es dueño de `state.json` dentro del job. Se sugieren `version`, `status`, `updated_ts`, `summary`, `active_step`, `error` y referencias a op ids. El listener no lo interpreta ni mantiene inflight, lock de canal, progreso unificado ni footer de cuota en esta fase.

El runtime toca `data/labcode/runtime.heartbeat` cada <=20 s. Escribe operaciones JSON versión `1` en `data/labcode/outbox/<op_id>.json`; cada una recibe `<op_id>.result.json` y se mueve a `outbox/done/` luego del intento. El resultado incluye `version`, `op_id`, `ok`, `ts`, `error` si falló y el id creado (`message_id`, `thread_id` o `channel_id`) si corresponde.

Operaciones:

- `send`: `channel_id`, `content` (1..2000, salvo embeds), opcional `reply_to`, `components`, `embeds` (máximo 10).
- `edit`: `channel_id`, `message_id`, y alguno de `content`, `components`, `embeds`.
- `thread`: `channel_id` base, `name` (1..100) y opcional `from_message_id`.
- `pin`: `channel_id`, `message_id`.
- `create_channel`: `name` `p-[a-z0-9][a-z0-9-]{0,90}`, `topic` opcional (<=1024), y opcional `parent_id` que solo puede ser la categoría ADMINISTRACIÓN.

Todos los ids Discord deben ser numéricos. El bridge fuerza siempre `allowed_mentions` a `{"parse": [], "replied_user": false}`. Componentes con `custom_id` solo aceptan `ublab:<kind>:<id>:<opt>`: exactamente tres partes de 1..64 caracteres `[A-Za-z0-9_.-]`, total <=100. Incluye `ublab:stop:<id>:<opt>`; es distinto de `ub:stop:` y no dispara el control de stop existente.

Al click permitido, la primera respuesta gana y se escribe atómicamente `answers/<kind>__<id>.json` con `version`, `kind`, `id`, `opt`, `user_id`, `channel_id`, `message_id`, `interaction_id`, `ts`. Repetidos no sobrescriben la decisión.

El scope de entrega es `#labcode`, p- channels registrados, y sus hilos. `create_channel` fuerza la categoría ADMINISTRACIÓN, permisos para @everyone denegados y acceso para Julian, Emanuel y el bot; tiene cap de 10 y registra cada resultado en `data/labcode/channels.json`. No modifica el store de auto-activación: el bridge reconoce esos p- directamente.

## Notas operativas (verificación Grok Bot, 2026-10-20)

**Archivos:** `labcode_bridge.py` (nuevo), `listener.py` (hooks), `lab_channels.py` (`LABCODE_CHANNEL_ID`), `data/labcode.txt` (toggle, `off`), `data/channel_auto_activate.json` (fila `<LABCODE_CHANNEL_ID>`, auto ON, parent ADMINISTRACIÓN), `test_labcode_bridge.py`. Backup: `backups/labcode-20261020/`.

**Hooks en `listener.py`:**
- `on_message`: gate `_lc_ctx = lcb.enabled() and lcb.in_context(...)` justo después del bloque LAB3 y antes de `in_main`. Con toggle `off` no se ejecuta nada nuevo.
- `handle_labcode_message`: prefijo (`wants_cli_brain`) o sticky de hilo → `False` (routing normal). Sin heartbeat fresco → respuesta sin ping `code mode no disponible` y no encola. Sin inflight, sin lock de canal, sin typing. Reacción 🔷 al encolar.
- `on_interaction`: `ublab:` se despacha antes del `ub:stop:` (que no cambió). Guard falla → efímero `no disponible acá`. OK → `defer()` y luego `answers/`.
- `labcode_outbox_loop`: cada 2 s, solo si el toggle está `on`; máx. 20 ops por pasada.

**Escritura atómica del runtime:** escribir `outbox/.<op_id>.tmp` (o cualquier nombre que empiece con `.` o no termine en `.json`) y `rename` a `outbox/<op_id>.json`. Se procesan en orden de nombre (usar prefijo ordenable, p. ej. `20261020T183501-0001-send`). No reusar `op_id`: si existe `<op_id>.result.json` la op se saltea.

**`ublab:stop:<job_id>:<opt>`:** el bridge solo registra `answers/stop__<job_id>.json`; el runtime es quien frena (checkpoint). No toca `cli_channel_guard` ni el `ub:stop:` existente.

**Límites fase 1:** los p- channels NO están en el store de auto-activación, así que el routing FE-BOT normal (prefijos) no responde ahí; solo el bridge. El progreso unificado/#cli-logs/footer de cuota no aplica al runtime (sí a los mensajes con prefijo en `#labcode`, que van por la ruta normal). Clicks en hilos no cacheados resuelven el padre vía caché del gateway; si no se puede, responden `no disponible acá`.

**Logs a buscar** (`logs/listener.log`): `labcode queued`, `labcode message hook failed`, `labcode interaction hook failed`, `labcode outbox loop failed`, `labcode outbox loop started`.

**Síntomas → acción:**
- Mensaje sin prefijo en `#labcode` responde Composer en vez de 🔷 → toggle `off`, autor no permitido, o sticky de hilo.
- `code mode no disponible` → heartbeat >60 s o falta.
- Ops sin `.result.json` → toggle `off` o loop no iniciado (bounce pendiente).
- Resultado `out_of_scope` → canal fuera de `#labcode`/p- registrados/sus hilos. `toggle_off` → se apagó con ops pendientes.

**Tests:** `<repo>/discord-venv/bin/python -m unittest test_labcode_bridge -v` (offline, temp dirs, nunca toca el toggle real).
