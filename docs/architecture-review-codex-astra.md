# Revisión técnica de arquitectura: Universal Bot para Discord

**Destinatario:** Julian Cohen (@cejotastarship), Core Developer / Admin de Frontera Espacial.  
**Revisor:** OpenAI Codex / gpt-6-astra, reasoning_effort=low, según contexto de ejecución solicitado.  
**Fecha de revisión:** 2026-09-11 UTC / 2026-09-10 ART.  
**Proyecto:** `fronteraespacial/universal-bot`.  
**Origen de la iniciativa:** Julian Cohen; propuesta inicial atribuida a AGY, septiembre de 2026.  
**Estado del documento:** revisión y diseño recomendado; no implementación ni certificación de producción.

## 1. Veredicto ejecutivo

**Aprobar la estrategia incremental, con cambios obligatorios antes de implementar el primer listener.** El proyecto debe extraer patrones de FE-BOT, TyR y LaPosta, conservando su experiencia operacional y eliminando dependencias de instalaciones concretas. LAB3 debe aportar contratos y componentes verificables, no convertirse en una dependencia importada desde una carpeta externa.

La propuesta acierta en separar configuración y secretos, usar una aplicación Discord por instalación, mantener el Gateway liviano y evitar portar el monolito. Sin embargo, todavía no define el propietario durable de cada job, la recuperación después de un crash, la entrega de resultados ni una frontera suficiente entre un usuario de Discord y un agente con acceso al host.

Cinco correcciones son bloqueantes:

1. **Allowlist vacía significa denegar ejecución.** Nunca habilitar a todo el servidor por omisión.
2. **Autorización, deduplicación, cola acotada y exclusión por conversación deben existir en Fase 1.**
3. **Desacoplar procesos no vuelve recuperables los jobs.** Es necesario persistir aceptación, ejecución y entrega, con un supervisor explícito.
4. **Windows necesita una implementación de plataforma probada.** Los flags de procesos, ACL y rutas no son equivalentes a POSIX.
5. **No declarar un CLI listo por encontrar una carpeta o una API key.** Instalación, autenticación, acceso al modelo y disponibilidad son estados distintos.

El repositorio local ya contiene un scaffold, con README, licencia MIT, configuración e instaladores. Esta revisión no necesita recrearlo. El checkout inspeccionado estaba limpio y su HEAD era `b0f3f649dd0c29a351f40a2da55487053a83ede2`. No se verificó aquí el estado remoto de GitHub ni se publicó contenido.

## 2. Alcance y calidad de la evidencia

Se leyó la propuesta completa mediante el almacén de documentación; también está truncada al final de su sección 6 en la fuente guardada. Se inspeccionaron selectivamente el scaffold, el lock y revive de FE-BOT, el filtro y lanzamiento de procesos de TyR, el inflight y unidad systemd de LaPosta, y contratos/políticas/router de LAB3.

La revisión combina **hallazgos estáticos verificables**, **contraste con documentación oficial** y **recomendaciones de diseño**. No se realizaron pruebas de fallo sobre producción, autenticación de proveedores, instalaciones de CLIs ni ejecución en Windows. Las afirmaciones sobre despliegues reales de los tres proyectos no equivalen a una certificación de su estado actual.

Se consultó Context7 para `discord.py` y se contrastó con fuentes primarias. La búsqueda del grafo de recursos no devolvió coincidencias para esta arquitectura; no se atribuyen recursos ni aportantes inexistentes. Las referencias técnicas aparecen junto a los puntos que respaldan. Esta copia omite enlaces de canales privados, credenciales y detalles operativos ajenos al diseño.

## 3. Puntos fuertes que deben preservarse

| Decisión | Valor | Condición para conservarla |
|---|---|---|
| Aplicación Discord propia por instalación | Aísla credenciales y administración | Verificar identidad del bot al conectar |
| Configuración declarativa | Facilita despliegue reproducible | Esquema versionado, validación estricta y defaults seguros |
| Gateway pequeño | Reduce fallos y latencia de heartbeat | Sin procesos síncronos, inferencia ni lógica de negocio pesada |
| Jobs fuera del Gateway | Permite mantenimiento independiente | Propietario, persistencia y recuperación definidos |
| Supervisión nativa | Evita otra plataforma pesada | Un supervisor por componente, sin bucles rivales |
| Progreso y plazos explícitos | Evita el silencio operacional | Separar actividad observada de avance estimado |
| Portado gradual de LAB3 | Reduce alcance inicial | Contratos estables y pruebas de compatibilidad |
| Core con pocas dependencias directas | Simplifica soporte | No confundirlo con cero dependencias transitivas |

La meta de 400–500 líneas para el listener puede ser orientativa. No debe convertirse en una restricción que obligue a mezclar autorización, persistencia, subprocess y Discord en un solo archivo.

## 4. Hallazgos priorizados

**P0:** bloquea ejecución segura de CLIs. **P1:** bloquea una versión operable y portable. **P2:** mejora posterior.

| ID | Nivel | Hallazgo / evidencia | Corrección requerida |
|---|---|---|---|
| A01 | P0 | La propuesta permite acceso general con allowlist vacía | Deny-by-default; acceso público debe requerir una opción explícita y otro modelo de aislamiento |
| A02 | P0 | Políticas de acceso y mutex se postergan a fases 3/4 | Autorización y serialización básica desde Fase 1 |
| A03 | P0 | CLI local puede leer secretos y modificar el host | Cuenta dedicada, permisos mínimos y contrato de capacidades; cwd no es sandbox |
| A04 | P1 | Inflight JSON no define recuperación ni deduplicación | Job store transaccional, leases e inbox/outbox |
| A05 | P1 | Flags detached se presentan como garantía de independencia | Worker separado y pruebas bajo systemd/Task Scheduler |
| A06 | P1 | RedactFilter de TyR solo reemplaza TOKEN en getMessage | Redacción en handlers y texto final formateado, incluyendo excepciones |
| A07 | P1 | Rutas generadas no coinciden con directorios creados | Resolver una única configuración efectiva por instancia |
| A08 | P1 | `python = "py -3"` mezcla ejecutable y argumentos | Usar `sys.executable` o argv estructurado |
| A09 | P1 | Detector infiere readiness de archivos/variables | Estados separados, probes limitados y versionados |
| A10 | P1 | Se asume “5 req/s por canal” como regla | Respetar buckets/headers reales y 429 mediante biblioteca |
| A11 | P1 | Timezone IANA arbitraria con stdlib estricta en Windows | Proveer datos IANA o degradar explícitamente a UTC |
| A12 | P1 | `on_ready` como inicializador único | Inicializar tareas una vez; callback idempotente |
| A13 | P1 | Router LAB3 contiene ruta absoluta y políticas predefinidas | Inyección de catálogo, presupuesto y capacidades |
| A14 | P2 | “Un gateway por token; dos procesos se caen” es excesivo | Documentar singleton operacional y futuro sharding |

### 4.1 Hallazgos concretos del scaffold

- `install/linux/install.sh` crea `PREFIX/logs` y `PREFIX/jobs`, pero el TOML mantiene `/var/lib/universal-bot/logs` y `/var/lib/universal-bot/jobs`. Además, `UB_PREFIX` no actualiza `install_dir`.
- `install/windows/install.ps1` cambia host y Python, pero conserva las rutas Linux de jobs/logs y fija el install_dir sin derivarlo de `-Prefix`.
- La interpolación de backslashes con reemplazos de texto no es una estrategia de serialización confiable. Hay que parsear y comprobar el resultado en Windows, incluyendo espacios, Unicode y prefijos personalizados.
- `Set-Content -Encoding UTF8` tiene diferencias entre Windows PowerShell 5.1 y PowerShell moderno, en particular BOM. Definir UTF-8 sin BOM en los generadores, o aceptar BOM explícitamente en el lector.
- La ACL del .env no demuestra que el directorio padre esté protegido; tampoco comprueba el código de salida de `icacls`. Debe validarse el permiso efectivo bajo la identidad que ejecutará el servicio.
- El default `agy` está deshabilitado junto con todos los CLIs. Es válido arrancar en diagnóstico, pero debe ser un estado deliberado, no un fallo tardío al recibir el primer pedido.
- `.gitignore` protege varias clases de secretos, pero no cubre de forma explícita todos los jobs, resultados, bases SQLite y archivos WAL/SHM posibles. Guardar runtime fuera del checkout y agregar exclusiones defensivas.

Estos son hallazgos de lectura; no se ejecutaron los instaladores.

## 5. Discord: límites reales y contrato de interacción

### 5.1 Gateway, sesiones e intents

El alcance inicial recomendado es **una instalación, una aplicación y un guild autorizado**. Para ese caso no hace falta sharding. Discord exige sharding a partir de 2500 guilds y publica recomendaciones y límites de inicio mediante Get Gateway Bot. IDENTIFY tiene límites propios, incluida concurrencia de inicio; RESUME no debe reemplazarse por reinicios agresivos. Múltiples conexiones no implican automáticamente que ambas caigan: sharding utiliza varias legítimamente. El singleton evita consumidores duplicados en este diseño. [Discord Gateway](https://docs.discord.com/developers/events/gateway)

Message Content se requiere para observar contenido general y prefijos en canales auto; no es indispensable para toda interacción posible. Hay excepciones para mensajes que mencionan al bot y otros contextos documentados; slash commands ofrecen otro modelo. Configurar intents tanto en código como en Portal, manejar el rechazo de intents y no habilitar Members/Presence sin necesidad. El TOML no activa por sí solo permisos del Portal. [Intents de discord.py](https://discordpy.readthedocs.io/en/stable/intents.html)

Permisos mínimos por función: View Channel, Send Messages y Read Message History cuando se recupera contexto; Send Messages in Threads para hilos; Attach Files y permisos de creación de hilos solo cuando se usan. Resolver overwrites efectivos y estados de hilo archivado/bloqueado. No solicitar Administrator como atajo.

`on_message` debe descartar bots/webhooks, guilds no autorizados, DMs no habilitados y autores no autorizados antes de leer historial o preparar contexto. Ignorar ediciones como nuevos pedidos por defecto. Un thread puede heredar activación del padre, pero jamás ampliar permisos por esa herencia.

### 5.2 REST y rate limits

**No usar “5 req/s por canal” como contrato.** Discord indica que los límites varían por ruta/bucket y pueden cambiar; usar headers y Retry-After. El límite global estándar documentado es 50 solicitudes/s por bot, independiente del bucket. Usar el cliente HTTP de discord.py y una cola de salida central; no lanzar procesos que envíen en paralelo con limitadores independientes. Ante 403/404 permanentes, detener el reintento; ante 429, respetar espera; ante fallos transitorios, backoff con jitter. [Rate limits oficiales](https://docs.discord.com/developers/topics/rate-limits)

La cola debe reservar capacidad para finales y errores. Coalescer progreso reemplazable y eliminar typing obsoleto antes de retrasar una respuesta final. Implementar límites globales de backlog y por conversación.

### 5.3 UX segura

El contenido de un mensaje normal admite hasta 2000 caracteres. Dividir con margen para prefijos, numeración y fences, preservando bloques de código; para respuestas extensas, resumen y adjunto. Deshabilitar menciones automáticas mediante `AllowedMentions.none()`, incluida la mención al autor del reply. El resultado de un modelo es texto no confiable. [Message Resource](https://docs.discord.com/developers/resources/message)

Reglas recomendadas:

- Rutas y nombres locales en código inline; no convertirlos en enlaces locales. Evitar exponer rutas sensibles innecesariamente.
- ACK breve tras aceptación durable, indicando job y si está en cola.
- Typing corto y cancelable; no mantenerlo durante treinta minutos.
- Progreso aproximadamente cada cuatro minutos, con tiempo consumido, límite y última actividad conocida. No inventar porcentajes.
- Final explícito: completado, fallido, cancelado, expirado o recuperación pendiente.
- Diagnóstico técnico detallado restringido a operadores; usuarios reciben motivo accionable sin entorno, secretos ni stack traces.
- Adjuntos con límites de tamaño, tipos y rutas permitidas; si se descargan URLs, aplicar control SSRF y redirecciones.
- Un fallo al publicar no debe borrar el resultado ni provocar una nueva ejecución del CLI.

Si se agregan slash commands, los jobs de 30 minutos necesitan una estrategia de entrega que no dependa exclusivamente de la vigencia del token de interacción. El bot puede persistir el destino y usar su autenticación normal para entregar, con permisos apropiados.

## 6. Core portable y dependencias

### 6.1 Arquitectura propuesta

Preferir un paquete `src/universal_bot/`, instalado en un virtualenv, sobre módulos globales llamados `config` o `listener`. Mantener los nombres funcionales solicitados dentro del paquete.

| Módulo | Responsabilidad | No debe hacer |
|---|---|---|
| `config.py` | Parsear TOML, validar dataclasses, resolver paths y secretos | Ejecutar shell o descubrir proveedores |
| `listener.py` | Gateway, normalización, autorización de entrada, encolado | Esperar CLIs o ejecutar router pesado |
| `dispatcher.py` | Admisión, dedup, límites, leases, serialización | Construir comandos específicos de cada CLI |
| `worker.py` | Reclamar jobs, ejecutar adaptador, persistir eventos/resultados | Abrir otro Gateway |
| `redact.py` | Redacción central y logging seguro | Prometer aislamiento |
| `store.py` | SQLite, migraciones, inbox, jobs y outbox | Guardar tokens |
| `platform/locks.py` | Lock POSIX/Windows detrás de una interfaz | Decidir autorización |
| `platform/processes.py` | Lanzamiento/cancelación por OS | Interpretar prompts |
| `adapters/*.py` | Probe, argv, parsing y capacidades por CLI | Elegir canales de Discord |
| `discord_output.py` | Chunks, menciones, progreso, entrega | Reejecutar tareas |
| `doctor.py` | Diagnóstico local sin revelar secretos | Auto-instalar al iniciar Gateway |

Flujo lógico: evento Discord → autorización → transacción de admisión → cola durable → worker → adaptador CLI → resultado durable → outbox → Discord. El Gateway y el worker son procesos supervisados por separado.

Los contratos pueden implementarse con `dataclasses`, `Enum` y `typing.Protocol`. Los módulos de negocio no importan `fcntl`, `msvcrt` ni conocen flags Windows. “Agnóstico al OS” significa una API común con implementaciones de plataforma pequeñas y probadas; no eliminar todas las diferencias reales.

### 6.2 Restricción de dependencias

Recomiendo Python 3.11+ para `tomllib`; `tomli` solo si se decide soportar Python anterior. `discord.py` instala dependencias transitivas, incluida su capa HTTP. Por lo tanto, la promesa correcta es **dependencias directas mínimas**, no árbol de dependencias vacío.

Usar stdlib para SQLite, JSON, logging rotativo, paths, subprocess, concurrencia y validación. No agregar `filelock`, `python-dotenv`, Pydantic o un SDK MCP al core sin revisar la restricción. MCP es opcional: un puente futuro puede vivir en un extra separado; stdin/stdout y eventos propios bastan para Fase 1.

`zoneinfo` no trae por sí solo la base IANA y Windows normalmente no la proporciona. Para mantener estrictamente el requisito: trabajar en UTC y declarar indisponible una zona IANA ausente, con diagnóstico explícito. Si se requiere conversión IANA portable, aprobar `tzdata` como dependencia adicional o distribuir datos con mantenimiento propio. No reemplazar una zona arbitraria por UTC-3 fijo. [zoneinfo](https://docs.python.org/3/library/zoneinfo.html)

### 6.3 Asyncio, memoria y backpressure

No ejecutar `subprocess.run`, HTTP síncrono, escaneo recursivo ni lecturas grandes dentro del callback. Usar APIs async o trabajo bloqueante en un executor acotado. Discord.py advierte que bloquear el loop afecta los heartbeats. [FAQ de discord.py](https://discordpy.readthedocs.io/en/stable/faq.html)

En el worker, drenar stdout y stderr concurrentemente y por bloques acotados. `communicate()` evita ciertos deadlocks, pero acumula la salida; no es apropiado para volumen ilimitado. Un timeout async no reemplaza la terminación explícita y la espera del proceso. Windows necesita un event loop con soporte de subprocess, normalmente Proactor. [Subprocesses de asyncio](https://docs.python.org/3/library/asyncio-subprocess.html)

Límites iniciales sugeridos, configurables: dos ejecuciones globales, una por conversación, una por workspace mutable, veinte pedidos pendientes por instancia, un MiB de prompt y diez MiB de salida capturada por job. Son decisiones del producto, no límites oficiales. Al alcanzar el límite de salida, marcar truncamiento y continuar drenando/descartando o cancelar según política; no bloquear la tubería.

Acotar caché de mensajes, historial, tareas asyncio y buffers. Retirar tareas terminadas y consumir excepciones. SQLite debe operar con transacciones breves, busy_timeout y conexiones bajo un propietario/thread claro; no compartir una conexión arbitrariamente entre threads.

## 7. Jobs durables, subprocess y locks

### 7.1 Propietario de la ejecución

Recomiendo **Gateway y worker separados desde la primera versión que prometa supervivencia al reinicio**. El worker posee el proceso CLI, sus pipes, timeout, cancelación y resultado. Un restart del Gateway no toca el worker. Esto evita convertir al Gateway en supervisor de procesos huérfanos.

Alternativa reducida: un solo proceso que cancela jobs al caer y los marca interrumpidos al volver. Es una opción honesta para un prototipo, pero no cumple la promesa de preservar trabajos durante un bounce.

Un estado mínimo:

`queued → claimed → running → succeeded | failed | cancelled | timed_out | interrupted`

La entrega tiene estado independiente: `pending → sending → delivered | retry_wait | delivery_failed | uncertain`. Guardar job_id, instance_id, guild/channel/thread/message, usuario, adaptador y versión, workspace, timestamps UTC, deadline, intento, lease y resultado. No guardar tokens en estos registros.

Usar unicidad sobre identidad de instalación + message_id y una transacción para admisión. Los mensajes repetidos no deben crear otro job. Las colas FIFO y el mutex lógico por conversación/workspace deben sobrevivir al restart; un `asyncio.Lock` aislado no lo logra.

El JSON inflight de LaPosta inspeccionado usa read-modify-write y `os.replace`: el reemplazo evita lecturas parciales en el caso normal, pero no evita actualizaciones perdidas entre escritores. Además, errores de lectura devuelven estado vacío. **Corrupción no puede significar “no hay jobs”.** SQLite ofrece una base estándar más adecuada.

### 7.2 Recuperación y entrega

Un worker reclama mediante lease con propietario y generación. No ejecutar dos veces por expirar un heartbeat: primero reconciliar si el proceso anterior sigue vivo y si es seguro recuperar. Un PID solo no identifica de forma suficiente una ejecución; puede reutilizarse. Después de crash del worker, la política inicial segura es marcar interrupción, contener descendientes y solicitar reintento explícito cuando pueda haber efectos parciales.

El intervalo entre ejecutar un efecto y persistir el éxito impide garantizar exactly-once para CLIs arbitrarios. No reintentar automáticamente commits, envíos o cambios remotos desconocidos. Igual ocurre si Discord aceptó el mensaje y se perdió la respuesta HTTP: outbox reduce pérdidas, pero requiere reconciliación/identificadores y un estado de entrega incierta. No anunciar exactly-once end-to-end.

A falta de RESUME válido, el Gateway tampoco es una cola histórica durable. Garantizar durabilidad **desde la admisión persistida**. Si se desea recuperar pedidos durante una desconexión prolongada, agregar backfill limitado por cursor, permisos y dedup; no leer todo el historial indiscriminadamente.

### 7.3 POSIX

`start_new_session=True` crea una sesión nueva; no cambia por sí solo la relación padre-hijo ni saca al proceso del cgroup de systemd. `Popen` mantiene al lanzador como padre. Usar argv, `shell=False`, cwd explícito, handles no heredables y entorno filtrado. `stdin=DEVNULL` cuando el protocolo no usa stdin; si lo usa para el prompt, escribir y cerrar. [Python subprocess](https://docs.python.org/3/library/subprocess.html)

El worker puede crear un grupo por job, enviar TERM al grupo al cancelar, esperar una gracia y escalar a KILL. Siempre recolectar el hijo con wait. Un zombie es un proceso terminado no recolectado; un huérfano puede seguir trabajando. Hijos que abandonan el grupo necesitan contención adicional, por ejemplo unidades/cgroups por job. La separación de sesión no es una frontera de seguridad.

### 7.4 Windows

`CREATE_NEW_PROCESS_GROUP` no equivale a una sesión POSIX; permite ciertos eventos de consola, sujetos a contexto y soporte del hijo. `terminate()` no ofrece un SIGTERM cooperativo portable. `CREATE_BREAKAWAY_FROM_JOB` depende de que el Job Object padre permita escapar: no debe aplicarse incondicionalmente ni asumirse exitoso. [Python subprocess](https://docs.python.org/3/library/subprocess.html)

Para contención real del árbol, usar Job Objects con política de cierre definida. Puede implementarse mediante `ctypes` estándar, pero requiere manejo correcto de handles, errores y pruebas, idealmente creación suspendida/asignación/reanudación para evitar carreras. El cierre del Job Object puede terminar sus procesos con KILL_ON_JOB_CLOSE. [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

No usar breakaway dentro del worker por defecto si rompe su contención. `taskkill /T /F` puede ser un mecanismo operacional de emergencia, no un equivalente exacto a cancelación cooperativa ni garantía frente a todos los escapes. Para el MVP se puede admitir cancelación dura documentada, pero no prometer graceful shutdown de cualquier CLI.

Los launchers `.cmd/.bat` necesitan atención adicional al quoting y metacaracteres. Preferir ejecutable real y transportar el prompt por stdin/archivo soportado. No pasar texto de Discord a PowerShell, cmd o bash como código.

### 7.5 Singleton seguro

Distinguir tres elementos: lock de Gateway, lock de worker y coordinación transaccional de jobs. No reutilizar un lock temporal de watchdog como lock de vida del servicio.

- POSIX: abrir archivo estable en directorio protegido, adquirir `flock(LOCK_EX | LOCK_NB)` y mantener descriptor hasta salir.
- Windows: abrir archivo binario sin truncar, fijar offset cero y bloquear un byte con `msvcrt.locking(..., LK_NBLCK, 1)`; liberar exactamente la misma región. [msvcrt](https://docs.python.org/3/library/msvcrt.html)
- Todos los procesos competidores usan la misma ruta canónica y algoritmo. No borrar/recrear el archivo al detectar un PID antiguo: puede crear dos inodos y dos locks válidos.
- Crash libera el lock de kernel al cerrarse los handles, salvo handles heredados que sigan vivos. Forzar no herencia y comprobarlo con pruebas de hijos de larga vida.
- PID y fecha son metadatos de diagnóstico, no prueba de exclusión. Un archivo existente no significa lock activo.
- Acotar soporte a almacenamiento local; no prometer equivalencia en NFS/SMB.
- Usar identidad estable de aplicación/bot en un lock_root compartido entre instalaciones del host, y verificar identidad al autenticar. Si dos usuarios usan directorios distintos, el lock local no coordina entre ellos; el instalador debe resolverlo mediante directorio administrado/ACL.
- Un lock local no evita otro host con el mismo token. Prohibir esa topología en el soporte inicial o implementar coordinación distribuida más adelante.

El lock FE inspeccionado tiene ruta fija de instalación; no demuestra por sí solo una exclusión global por token. Se conserva la lección de no heredar handles, pero hay que generalizar la identidad y el alcance.

## 8. Supervisión nativa

### 8.1 Linux

Dos unidades: Gateway y worker, ejecutados en foreground con Python absoluto del virtualenv y usuario dedicado. No copiar el `User=root` de un despliegue existente como default público.

Recomiendo `Restart=on-failure`; `always` es posible si se documenta que una salida limpia inesperada también debe revivir. Configurar RestartSec, límites de ráfaga, directorios escribibles y entorno explícito. Un token inválido o configuración rota debe producir diagnóstico y evitar una tormenta de reinicios.

La unidad de LaPosta inspeccionada usa `KillMode=process` para preservar hijos. No trasladarlo automáticamente: puede dejar procesos sin propietario. La arquitectura con worker separado permite conservar el control del árbol al reiniciar Gateway. El comportamiento se debe probar con cgroups reales; la documentación web systemd no pudo recuperarse en esta sesión.

Graceful restart: dejar de admitir trabajo en el componente afectado, drenar con plazo acotado y mantener el Gateway vivo si todavía debe informar estados. Apagar el host, matar el worker y reiniciar solo Gateway son operaciones distintas y necesitan políticas distintas.

### 8.2 Windows

Task Scheduler es razonable como primera opción nativa: inicio al boot, identidad dedicada, working directory y ejecutable absolutos, IgnoreNew, reintentos y límite de ejecución deshabilitado para el daemon. Probar sin usuario logueado y bajo la misma identidad que posee las credenciales.

No heredar automáticamente Highest/Administrador ni suponer que S4U accede al mismo keyring o recursos que una sesión interactiva. Configurar condiciones de batería, suspensión, red y recuperación. “Crear un Service” no consiste en ejecutar `sc create python.exe`: hace falta implementar el protocolo del Service Control Manager o usar un host de servicio compatible, aumentando alcance/dependencias.

### 8.3 Watchdog y health

Un supervisor nativo detecta salidas; no necesariamente detecta un loop congelado. Si se agrega watchdog, debe ser externo, único y evaluar heartbeat reciente del loop, no solo existencia de PID o archivo.

Separar liveness, Gateway conectado, worker disponible y aceptación de jobs. Registrar última actividad del loop, último éxito de entrega, tamaño de cola, jobs activos y versión. El timestamp de `on_ready` solo no es health.

Usar varios fallos consecutivos, gracia al boot y backoff. Una caída de internet no debe disparar reinicios infinitos de IDENTIFY. Escribir status atómicamente en archivo distinto del lock. Evitar systemd + cron + watchdog + scripts de auto-revive compitiendo por levantar el mismo daemon.

## 9. Configuración y secretos

### 9.1 Esquema recomendado

Ejemplo de diseño, **no archivo implementado**. Rutas relativas resueltas contra el directorio del TOML; templates diferenciados por OS.

```toml
schema_version = 1

[meta]
instance_name = "example-site"
host_os = "auto"
host_role = "vps"
timezone = "UTC"

[discord]
guild_id = "REPLACE_GUILD_ID"
bot_id = "REPLACE_BOT_ID"
allowlist_ids = []
allowed_channel_ids = []
auto_channels = []
allow_dm = false
message_content_intent = true

[paths]
state_dir = "./state"
jobs_dir = "./state/jobs"
logs_dir = "./state/logs"
workspace_dir = "./workspaces"
secrets_file = "./secrets.env"
# El instalador sustituye esta ruta por una compartida y protegida.
lock_root = "./locks"

[runtime]
default_brain = ""
timeout_long_s = 1800
shutdown_grace_s = 60
max_concurrent_jobs = 2
max_pending_jobs = 20
progress_interval_s = 240
watch_interval_s = 60

[cli.codex]
enabled = false
command = ["codex"]
auth_mode = "existing"
probe_timeout_s = 5

[features]
context7_native = false
```

Listas vacías deniegan ejecución. Un default vacío significa diagnóstico sin proveedor; no seleccionar silenciosamente uno que cobre o envíe datos a otro destino. Probes no deben habilitar adaptadores desactivados.

Usar `sys.executable` para procesos Python internos. Si hace falta un launcher configurable, representarlo como array: `["py", "-3"]`, nunca aplicar split por espacios. Para rutas Windows, TOML literal como `'C:\universal-bot'` evita escapes; también se pueden generar rutas con barras compatibles.

Validar IDs, enums, límites positivos, campos desconocidos, paths y permisos. Detectar host_os real y rechazar contradicciones explícitas. Asegurar separación de estado por instancia. La validación de plantillas puede aceptar placeholders; runtime con token real no.

El `inflight_wait_s = timeout_long_s + 60` actual deja de representar el sistema si hay cola, extensiones o demora de entrega. Separar plazo de ejecución desde inicio, espera en cola, cancelación y entrega. Extensiones actualizan deadline durable y presupuesto máximo; no mantener un valor derivado estático.

### 9.2 Lectura de secretos

Preferir entorno del servicio; si se admite .env, definir un subconjunto simple KEY=VALUE, UTF-8, sin interpolación, sin command substitution, sin source/eval y con manejo documentado de comillas y duplicados. Precedencia explícita: entorno sobre archivo o error ante conflicto, elegida una vez.

POSIX: directorio 0700, archivo 0600 y propietario correcto desde creación. Windows: ACL de archivo **y directorio**, sin herencias amplias y con acceso a la cuenta ejecutora; chmod no equivale a ACL NTFS. Verificar errores del instalador y no anunciar éxito si falló la protección.

No heredar todo `os.environ` hacia CLIs. Construir un entorno mínimo con PATH/HOME/TEMP/SystemRoot y solo credenciales autorizadas para ese adaptador. El worker no necesita el token Discord si la salida la publica Gateway. No poner tokens ni prompts sensibles en argv o en reportes de doctor.

### 9.3 Logging y RedactFilter

El filtro observado en TyR modifica `record.getMessage()`; no sanitiza necesariamente el traceback que se formatea después. Además, un filtro del logger raíz no se aplica automáticamente a todos los registros propagados de descendientes. [Python logging](https://docs.python.org/3/library/logging.html)

Instalar protección en cada handler de consola/archivo y sanitizar la cadena final del formatter, incluyendo exception/stack y campos extra que se impriman. Redactar valores conocidos y campos sensibles; regex de tokens solo como defensa secundaria. Si se procesa stdout por chunks, contemplar secretos cortados entre chunks mediante buffer de solapamiento.

No guardar una copia cruda en otro archivo “para debugging”. Logs de subprocess, crash dumps y capturas necesitan sus propias políticas. Limitar retención y tamaño. La redacción mitiga filtraciones accidentales; no garantiza que un agente con acceso al archivo secreto no lo exfiltre transformado.

### 9.4 Frontera de confianza

Allowlist Discord no es aislamiento del OS. Inicialmente soportar operadores de confianza con cuenta dedicada y workspaces limitados. Para usuarios no confiables, requerir aislamiento adicional por identidad/VM/contenedor o rechazar ese modo.

Autorizar herramientas, paths, red y acciones con efectos fuera del prompt. Historial, adjuntos y respuestas de modelos son entradas no confiables. Mantener contexto separado por instancia/guild/canal y dominio de permisos; no reutilizar una sesión privada en un canal público. Revalidar permisos cuando el job sale de la cola.

Una key presente no autoriza instalar software ni comprar cuota. Publicar requiere revisar también licencias del código heredado, notices y secretos en historial Git; la licencia MIT del destino no cambia la de los módulos importados.

## 10. Detección y setup de CLIs

### 10.1 Modelo de salud

`ready`, `unauthenticated` y `missing` son insuficientes. Representar al menos:

| Dimensión | Estados útiles |
|---|---|
| Habilitación | disabled / enabled |
| Instalación | missing / installed / unsupported_version / broken |
| Autenticación | unknown / authenticated / unauthenticated |
| Capacidad | headless / structured_output / resume / steering / images |
| Disponibilidad | unknown / available / rate_limited / quota_exhausted / network_error |
| Evidencia | checked_at, versión, probe usado, TTL y motivo saneado |

`ready` puede ser una vista derivada con antigüedad visible; jamás garantía de que el próximo pedido funcione. Un directorio de credenciales existente es solo una pista. Un error de red no significa falta de autenticación y una API key no demuestra entitlement del modelo.

Usar `shutil.which` y ruta configurada. Ejecutar probes con timeout y salida limitada bajo la cuenta de servicio, desde cwd controlado; no cargar automáticamente plugins del repositorio del usuario. Registrar ruta/version, sin enumerar tokens ni contenido de caches. Probes pasivos no deben invocar inferencia paga.

### 10.2 Correcciones por proveedor

| CLI | Verificación documental | Decisión para el adaptador |
|---|---|---|
| Codex | Instalación oficial y autenticación propia; cache en CODEX_HOME, por defecto ~/.codex, o almacén del OS | No buscar únicamente ~/.config/codex; comprobar versión y mecanismo soportado |
| OpenCode | Tiene CLI, auth y ejecución no interactiva documentadas | No asumir una key universal ni que todos los providers/planes estén disponibles |
| AGY | Existe documentación oficial de instalación y modo headless | No equiparar carpeta ~/.gemini con sesión válida ni prometer un paquete pip genérico |
| Cursor | Documentación actual usa agent y contempla Windows PowerShell; páginas antiguas usan cursor-agent/WSL | Diferenciar CLI agente de launcher del editor y validar versión instalada |

Codex permite varios mecanismos de autenticación y caches en archivo o keyring. La instalación debe seguir su guía oficial; no prometer paquetes apt/winget genéricos como interfaz estable. [Codex CLI](https://developers.openai.com/codex/cli/), [Autenticación](https://developers.openai.com/codex/auth/)

OpenCode documenta comandos auth y run; el contrato debe extraer capacidades reales del ejecutable instalado y tratar credenciales de proveedor por separado. No fijar IDs de planes/modelos desde otro host. [OpenCode CLI](https://opencode.ai/docs/cli/)

AGY documenta instalación oficial y ejecución headless con credenciales previamente configuradas. El adaptador debe capturar errores de autenticación explícitos y separar stdout de diagnósticos; compatibilidad exacta queda pendiente de prueba. [Instalación AGY](https://antigravity.google/docs/cli/install), [Headless AGY](https://antigravity.google/docs/cli/headless/)

Cursor actualmente documenta `agent` e instalación PowerShell. El material anterior con `cursor-agent` no debe usarse para declarar que Windows nativo no existe; tampoco basta la documentación para certificar el adaptador. [Cursor CLI](https://cursor.com/docs/cli/overview)

### 10.3 Setup asistido

Procedimiento recomendado cuando no hay CLI:

1. Gateway inicia en diagnóstico y responde una vez por ventana a usuarios autorizados: “No hay un proveedor habilitado; completá el setup local”.
2. Operador ejecuta doctor local con la cuenta que usará el servicio.
3. Selecciona proveedor, versión compatible y método de instalación oficial.
4. El instalador muestra qué descargará/modificará, valida origen/integridad cuando el proveedor la publica y requiere acción explícita para instalar.
5. Operador autentica localmente; nunca pega keys o códigos de login en Discord.
6. Doctor verifica instalación y autenticación sin inferencia; un smoke opcional y explícito prueba el modelo con presupuesto limitado.
7. Habilitar adaptador y default; ejecutar un pedido inocuo, comprobar entrega y cancelar otro.
8. Activar supervisión al boot y repetir prueba sin sesión interactiva.

No instalar desde el listener, no actualizar un CLI durante un job y no resolver falta de binario descargando automáticamente un paquete con nombre parecido. Mantener matriz de versiones compatibles y rollback. Los instaladores pueden tener dependencias distintas de las del core, declaradas claramente.

## 11. Migración limpia de LAB3

El `smart_router.py` inspeccionado fija un catálogo bajo `/workspace/universal-driver-lab/data/models_catalog.json`; `access_policy.py` contiene reservas y preferencias concretas de proveedores/modelos. Por eso la migración requiere extracción.

Contratos recomendados:

- `JobRequest`: identidad, prompt, workspace, capabilities, plazo y política.
- `AdapterCapabilities`: operaciones soportadas y versión del protocolo.
- `HealthSnapshot` y `QuotaSnapshot`: estado, fuente, timestamp, TTL y valores desconocidos explícitos.
- `RoutingDecision`: adaptador/modelo efectivos, motivo, restricciones y fallback permitido.
- `JobEvent`: secuencia, tipo, timestamp y payload limitado.
- `JobResult`: estado terminal, salida, artefactos, usage observado y causa de fallo.

El core no importa catálogo ni configuración global de LAB3. El router recibe snapshots y devuelve una decisión; no envía Discord, no ejecuta comandos y no accede a credenciales. Catálogo configurable/cacheado, refresco fuera del hot path y fallos aislados del Gateway.

### Hoja de ruta corregida

| Fase | Entrega | Criterio de salida |
|---|---|---|
| 0 | Esquema, amenaza, contratos y matriz OS | Templates válidos y políticas inequívocas |
| 1 | Gateway + worker + store + ACL + mutex + un adaptador | Crash/restart/cancel/dedup/entrega probados en Linux y Windows |
| 2 | Más adaptadores, capacidades y catálogo | Pruebas de contrato por versión; doctor confiable |
| 3 | Cuotas normalizadas y router determinista | Unknown no equivale a saldo; respeta políticas y presupuesto |
| 4 | Smart-router avanzado | No elige proveedores ausentes ni escala costos sin permiso |
| 5 | Sesión viva y steering | Sesiones aisladas, ordenadas y recuperables según capacidad |

La continuidad básica por hilo puede empezar antes, pero steering vivo solo se anuncia cuando el adaptador lo soporte. No fingir stdin interactivo en un CLI one-shot.

El fallback debe ser visible y configurable. Si cambia proveedor, costo o frontera de datos, aplicar política previa. Reintento automático solo antes de ejecución confirmada o cuando existe una semántica segura; un fallo ambiguo después de herramientas no debe provocar cascadas entre CLIs. Añadir cooldown y circuit breaker por adaptador/modelo.

Las cuotas dependen de credenciales y contratos de cada proveedor. No asumir APIs públicas para todas las suscripciones ni copiar mecanismos privados del entorno original.

## 12. Pruebas de aceptación para declarar Fase 1 lista

Usar `unittest` y CLIs falsos basados en Python para que CI no requiera cuentas ni consuma cuota. Son pruebas propuestas, no ejecutadas en esta revisión.

| Prueba | Resultado exigido |
|---|---|
| Allowlist vacía, autor/guild/canal no autorizado | Cero spawn y cero lectura de contexto adicional |
| Veinte eventos duplicados | Una admisión y una ejecución |
| Dos mensajes mismo hilo/workspace | Orden FIFO, sin escritura concurrente |
| Saturación de cola | Rechazo claro y memoria acotada |
| Segundo Gateway simultáneo | No conecta; diagnóstico singleton |
| Crash del dueño del lock con hijo vivo | Lock vuelve a estar disponible; hijo no lo heredó |
| Restart de Gateway durante job | Worker continúa y resultado se publica al regresar |
| Crash del worker después de efecto parcial | Interrumpido/incierto, sin reejecución automática |
| Timeout y cancelación | Árbol contenido, procesos recolectados y estado terminal |
| CLI que inunda stdout/stderr | Loop sano, disco/memoria acotados |
| CLI esperando input | Termina o falla controladamente; no cuelga treinta minutos |
| SQLite corrupto o disco lleno | No asumir vacío; dejar de admitir y diagnosticar |
| 429 / 403 / 404 / desconexión | Esperas correctas, no tormenta, resultado conservado |
| Caída tras POST aceptado y antes de guardar ID | Entrega incierta reconciliable, no nueva inferencia |
| Tokens en logger hijo, excepción y chunks | No aparecen en consola/archivo saneados |
| Windows: Unicode, espacios, TOML y BOM | Configuración equivalente y argv intacto |
| Windows: Task Scheduler sin login | Credenciales/rutas reales accesibles según política |
| Linux: systemd stop/restart | Respeta separación Gateway-worker y limpia procesos |
| Zona IANA no disponible | Diagnóstico o UTC explícito, nunca hora inventada |
| Reconexión repetida | No duplica tareas de progreso ni workers |
| Reinicio del host | Jobs anteriores reconciliados, no asumidos exitosos |

CI debe ejecutar al menos Linux y Windows nativos, versión mínima de Python y una versión adicional soportada. Pruebas reales de Discord y proveedores en aplicación/guild de staging separados; no probar fallos destructivos en bots de producción.

## 13. Primeras tres acciones recomendadas

1. **Cerrar los ADR fundamentales y corregir la configuración:** deny-by-default, alcance de una instancia/guild, identidad del servicio, rutas por OS, timeout/cancelación y límite de confianza. Corregir ambos instaladores y verificar el TOML generado.
2. **Construir una rebanada vertical con CLI falso:** Gateway → SQLite → worker → resultado → outbox. Incluir desde el inicio deduplicación, mutex por conversación/workspace, límites y recuperación; después sustituir el fake por un único adaptador real.
3. **Probar supervivencia y contención en ambos OS:** lock/crash, restart del Gateway con job activo, kill del worker, salida masiva, permisos de secretos y arranque sin sesión interactiva. Integrar más CLIs y LAB3 solamente después de pasar esa matriz.

**Conclusión:** la base correcta es un bot pequeño con contratos y garantías verificables. La universalidad depende de configuración coherente, permisos cerrados, ejecución supervisada y recuperación explícita; el smart-router se incorpora sobre esa base.

