# Progreso unificado

Un mensaje de progreso por job, editado en el lugar, más un log opcional del recorrido y un tablero de cuota que **arranca apagado**. El paquete no abre HTTP: el gateway inyecta un transporte con `send`, `edit` y `pin`.

Código: `src/universal_bot/unified_progress/`.

| Módulo | Rol |
| --- | --- |
| `config.py` | Dataclass desde `[unified_progress]` y el entorno |
| `scope.py` | `off` / `scoped` / `on`, con `parent_channel_id` para hilos |
| `trail.py` | Embed en vivo, edit-in-place, marker y eventos por `(canal, job)` |
| `quota.py` | Bloque por CLI (barras de 20 celdas, fallback, tag free) |
| `cli_logs.py` | Un embed por job; si no entra, adjunta `trail.txt`. File lock |
| `quota_pin.py` | Mensaje pineado opcional; 404 lo recrea y lo vuelve a fijar |
| `transport.py` | Protocolo y reintento ante 429 |
| `stop_control.py` | Botón «Detener pedido» (components v2 + `custom_id`) |
| `stop_interaction.py` | Parseo de `INTERACTION_CREATE`, ACL y callback JSON |

## Configuración

En `instance.toml` (ver `config/instance.example.toml`):

```toml
[unified_progress]
mode = "off"                 # off | scoped | on
scoped_channel_ids = []      # solo si mode = "scoped"
cli_logs_channel_id = ""
quota_pin_enabled = false
quota_pin_channel_id = ""
timezone = "UTC"
rate_limit_retries = 8
display_name = "Bot"
stop_button_enabled = true   # UB_STOP_BUTTON=off lo desactiva en vivo

[unified_progress.colors]
cursor = "5865F2"
```

`paths.state_dir` guarda `live_trail/<canal>__<job>.json`, el jsonl de eventos, `quota_pin.json` y los locks.

Entorno (gana sobre el archivo, se lee en cada decisión):

| Variable | Valores |
| --- | --- |
| `UB_TRAIL_UNIFIED` | `off`, `scoped`, `on` |
| `UB_QUOTA_PIN` | `on` / `off` (si no está, manda `quota_pin_enabled`) |
| `UB_QUOTA_PIN_CHANNEL` | canal del pin, si se quiere pisar el toml |
| `UB_STOP_BUTTON` | `on` / `off` (si no está, manda `stop_button_enabled`) |

`scoped` incluye el canal listado y cualquier hilo cuyo `parent_channel_id` esté en la lista. `on` no filtra. `off` no publica trail, no absorbe tools y no escribe el log.

Los snapshots de cuota entran por callables (`kind -> registro`). Si fallan: `` `Codex: quota unavailable` ``. El tier gratis es `` `Free tier · free` ``. Cursor y Grok no reciben bloque al pie (el host ya lo muestra por su cuenta, igual que en el diseño de origen).

El pin, con el flag en false, no llama al transporte. Si el edit devuelve 404, se manda un mensaje nuevo, se pinea y el id se guarda con replace atómico.

Cada instalación completa sus propios ids en su toml. El host pasa `job_id` al construir `LiveTrail` y a `push_event`. Pasos repetidos seguidos se descartan. Terminar un job borra solo su marker.

## Botón detener

Mientras el job está **running**, la tarjeta es un contenedor (components v2) y el botón rojo **Detener pedido** va **adentro** del contenedor. Al cerrar, el edit deja el contenedor sin la fila del botón. Si la nota es una cancelación manual (`cancelad…`), el acento pasa a `0xE74C3C` y el texto de la tarjeta dice que se canceló; un error sigue en ámbar. Un job que ya no está activo se pinta en gris (`0x99AAB5`), también sin botón.

- `custom_id`: `ub:stop:<channel_id>:<job_id>` (parsear con `parse_stop_button_custom_id`).
- El marker guarda `author_id` cuando el host lo pasa en `LiveTrail(..., meta={"author_id": ...})`.
- El gateway atiende `INTERACTION_CREATE` con `handle_stop_interaction`: ACL = autor del pedido o ids admin configurados; `cancel_job(channel_id, job_id)` mata el subprocess; el host debe llamar `LiveTrail.finish(ok=False, note=…)` en el mismo camino.
- Respondé al click con `interaction_response` (ephemeral) **antes** de un kill lento, para evitar el timeout de Discord.

En el pack FE-BOT de referencia, el toggle en vivo es `data/stop_button_unified.txt` (`on` / `lab3` / `off`); aquí el equivalente es `stop_button_enabled` + `UB_STOP_BUTTON`.
