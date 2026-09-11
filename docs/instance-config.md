# Adaptar una instalación

Cada VM / VPS / PC servidora es **una instancia**. El repo público es el molde; los IDs y tokens viven en el host.

## Checklist

1. App + Bot **nuevos** en el Discord Developer Portal del cliente.
2. Privileged intent **Message Content** ON.
3. Invite al guild del cliente con permisos de escritura en los canales acordados.
4. Allowlist de user IDs (`allowlist_ids`): **deny-by-default**. Si la lista está vacía, nadie puede ejecutar comandos CLI.
5. Canales permitidos (`allowed_channel_ids`): opcional, restringe a canales o categorías específicas.
6. `instance.toml` en el host (no en git, resuelve rutas relativas al directorio de la instancia).
7. Token en `.env` fuera del árbol git (permisos 0600 en Linux, ACL owner-only en Windows).
8. Listener + Worker separados con persistencia transaccional SQLite (`jobs.sqlite`).
9. Mutex FIFO por conversación/canal/workspace: no hay colisiones de escritura concurrentes.
10. Detección de actividad real multi-señal (`activity.py`): no corta por stderr quieto mientras haya progreso, stdout o procesos activos.

## Qué no copiar de otra instalación

- Token, webhook, OAuth, sqlite de miembros, historial de mensajes
- Guild IDs / channel IDs de otro cliente
- Claves SSH de orquestación
