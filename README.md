# Universal Bot

Molde **público** para instalar y adaptar un bot Discord + CLIs (AGY / OpenCode / Codex / Cursor) en **una** máquina Linux o Windows: VM, VPS o PC servidora.

Org: [fronteraespacial](https://github.com/fronteraespacial) · repo: **https://github.com/fronteraespacial/universal-bot**

No es el pack de operación de Frontera Espacial. Cada instalación usa **su propia** app Discord y sus propios tokens.

## Qué hay hoy (2026-09-10)

- Scaffold de instancia (`config/instance.example.toml`)
- Installer Linux: `install/linux/install.sh`
- Installer Windows: `install/windows/install.ps1`
- Docs de adaptado por host
- Reglas de secretos (`SECURITY.md`)

El listener portable (gateway, MCP, watchdog) se suma por PR. Este repo arranca vacío de tokens a propósito.

## Quick start

Linux:

```bash
bash install/linux/install.sh mi-sitio
```

Windows (PowerShell):

```powershell
.\install\windows\install.ps1 -Instance mi-sitio
```

Luego completar `instance.toml` + `.env` en el host. Ver `docs/install-linux.md` / `docs/install-windows.md`.

## Reglas duras

- **Un gateway** por token. Dos procesos = ambos se caen.
- Token **fuera** de git. Nunca en Discord ni en issues.
- No reutilizar tokens ni sqlite de otra organización.
- Restart espera jobs inflight; timeout largo default 1800 s.

## Crédito

Pedido de **Julian Cohen** (@cejotastarship) — hilo LAB3 driver universal, **2026-09-10**.
