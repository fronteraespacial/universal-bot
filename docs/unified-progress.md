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

`scoped` incluye el canal listado y cualquier hilo cuyo `parent_channel_id` esté en la lista. `on` no filtra. `off` no publica trail, no absorbe tools y no escribe el log.

Los snapshots de cuota entran por callables (`kind -> registro`). Si fallan: `` `Codex: quota unavailable` ``. El tier gratis es `` `Free tier · free` ``. Cursor y Grok no reciben bloque al pie (el host ya lo muestra por su cuenta, igual que en el diseño de origen).

El pin, con el flag en false, no llama al transporte. Si el edit devuelve 404, se manda un mensaje nuevo, se pinea y el id se guarda con replace atómico.

Cada instalación completa sus propios ids en su toml. El host pasa `job_id` al construir `LiveTrail` y a `push_event`. Pasos repetidos seguidos se descartan. Terminar un job borra solo su marker.
