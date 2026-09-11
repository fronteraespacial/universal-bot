# Adaptar una instalación

Cada VM / VPS / PC servidora es **una instancia**. El repo público es el molde; los IDs y tokens viven en el host.

## Checklist

1. App + Bot **nuevos** en el Discord Developer Portal del cliente.
2. Privileged intent **Message Content** ON.
3. Invite al guild del cliente con permisos de escritura en los canales acordados.
4. Allowlist de user IDs (admins que pueden disparar CLIs).
5. `instance.toml` en el host (no en git).
6. Token en `.env` fuera del árbol git.
7. Listener + MCP + CLIs en **la misma** máquina.
8. MCP stdio local (no puente HTTP remoto como único cable).
9. Restart espera `inflight` vacío (`inflight_wait_s` ≥ `timeout_long_s` + 60).

## Qué no copiar de otra instalación

- Token, webhook, OAuth, sqlite de miembros, historial de mensajes
- Guild IDs / channel IDs de otro cliente
- Claves SSH de orquestación

## Próximo código (este repo)

El pack listener portable (gateway, routing, MCP, watchdog) entra por PRs **sin** secrets. Hasta entonces este repo solo deja el molde de install + config.
