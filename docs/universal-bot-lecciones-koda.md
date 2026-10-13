# Universal-Bot — Lecciones del despliegue de Koda Bot (BGH)

Koda es el bot familiar de Discord que corre en `bgh-server` (código en `/home/patri-bot/patri-bot-discord`, servicios `patri-bot-discord` y `koda-hostd`). Durante el 12–13/10/2026 hubo que corregir varias cosas a mano (backups `*.bak-authv2`, `*.bak-grants2`, `*.bak-vision`, `*.bak-sshctx`, `*.bak-roottools`, `*.bak-viewfile`, `*.bak-tools1`, etc.). Este documento busca que los próximos despliegues de Universal-Bot ya traigan esos arreglos.

> Sin tokens ni secretos: los valores sensibles siempre van en `config.env` local y nunca al repo.

## 1. Comandos largos fallaban aunque estuvieran autorizados
- **Síntoma:** el speedtest fallaba aun con ✅.
- **Causas:** (a) el timeout de `host_exec` era de 30 s; (b) el presupuesto del run de AGY cortaba antes; (c) cada comando alternativo que probaba el agente generaba una **clave de grant nueva**, así que volvía a pedir aprobación.
- **Arreglo:** timeout por defecto de 120 s (máximo 300 s) para `host_exec`, 600 s para el run del CLI, y grants con alcance `request` (toda la petición) y `user_day` (usuario, por 24 h). La tarjeta de autorización tiene 5 botones y se publica en `#autorizaciones`.

## 2. Koda no veía las imágenes
- **Causa:** `build_prompt` ignoraba los adjuntos del mensaje.
- **Arreglo:** `collect_images` guarda los adjuntos en `work/attachments/` y los referencia en el prompt, y se permite `read_file`/`view_file` sobre esa ruta.

## 3. Koda creía no tener SSH a las laptops
- **Causa:** ni su prompt ni `GEMINI.md` mencionaban los dispositivos.
- **Arreglo:** herramienta `device_ssh` y la documentación de dispositivos (alias, SO, usuario) incluida en el prompt y en `GEMINI.md`.

## 4. La tarea programada de la netbook quedaba en "Queued"
- **Causa:** la laptop estaba a batería y Windows no arranca tareas así por defecto.
- **Arreglo:** registrar la tarea con `New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`.

## 5. Sin scp/sftp a las laptops Windows y sin token elevado
- No hay subsistema sftp/scp que funcione hacia las laptops Windows, y el token del usuario `may` no está elevado (UAC).
- **Default:** transferir por `share_file` (LAN/Cloudflare) o por PowerShell sobre ssh, habilitar el subsistema sftp de OpenSSH en el instalador Windows y documentar qué acciones necesitan un usuario admin o una tarea programada con `RunLevel Highest`.

## 6. AGY en la BGH estaba limitado
- Solo tenía herramientas de Discord y web, y `ViewFile` se denegaba sobre los propios archivos del bot.
- **Arreglo:** servicio root (`koda-hostd`) con herramientas de host solo para admins (allowlist de `host_service`, salida ≤ 8 KB, env limpio).

## 7. No se podían pasar adjuntos a las laptops (fondo de pantalla de Maylen)
- **Síntoma:** fallaron `ViewFile` y `share_file` al intentar poner el fondo de pantalla.
- **Evidencia:** el journal de `patri-bot-discord` muestra `acción denegada (ViewFile)` el 13/10 a las 11:38, 12:28 y 12:31 (ART). No hay backups `.bak-wallpaper-2026-10-13` (todavía) ni logs en `logs/`. Causa probable: la ruta del adjunto no entraba en la allowlist de ViewFile/`share_file`, así que el archivo nunca llegó a la laptop. Otro worker lo está arreglando; actualizar esta sección con su fix.
- **Default:** el adjunto recibido debe poder publicarse con `share_file` y entregarse con `device_ssh` sin pasar por ViewFile.

## 8. Herramientas que hubo que portar
- Recordatorios (`koda_reminders.py`).
- `media_download` con yt-dlp (`koda_media.py`).
- Transcripción (`koda_stt.py`) con fallback a Whisper (`koda_whisper_fallback.py`) que se cierra después de usarse para liberar RAM.
- `share_file` por LAN o Cloudflare (`koda_share.py`).
- Navegador CDP con un MCP (`koda_browser_mcp.py`).
- Overlay del agente en las laptops.

## 9. `ssh` no está en la lista de comandos seguros
- Cada conexión pedía aprobación. **Default:** incluir `ssh` a dispositivos registrados (vía `device_ssh`) en los safe-commands, o cubrirlo con un grant `user_day`.

## Checklist de defaults para el instalador
- [ ] `host_exec`: timeout por defecto de 120 s, máximo 300 s; run del CLI de 600 s.
- [ ] Grants `request` y `user_day`, con la clave normalizada para que las variantes de un mismo comando no generen grants nuevos.
- [ ] Canal `#autorizaciones` creado, con la tarjeta de 5 botones.
- [ ] `collect_images` en `build_prompt` y `read_file`/`view_file` permitidos en `work/attachments/`.
- [ ] `device_ssh` y un inventario de dispositivos inyectado en el prompt y en `GEMINI.md`.
- [ ] `ssh`/`device_ssh` en los safe-commands.
- [ ] Tareas programadas de Windows con `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`.
- [ ] Subsistema sftp de OpenSSH en Windows y documentación de las limitaciones del token no elevado.
- [ ] Servicio root de herramientas de host solo para admins y ViewFile permitido sobre el directorio del bot.
- [ ] Pipeline de adjuntos → `share_file` → laptop (fondo de pantalla, etc.).
- [ ] Módulos incluidos: reminders, media_download (yt-dlp), STT + fallback a Whisper efímero, share_file (LAN/Cloudflare), MCP del navegador CDP y overlay en laptops.
- [ ] Backup `*.bak-<cambio>-<fecha>` automático antes de cada parche.
- [ ] Nada de secretos en el repo: solo `config.env` local con permisos 600.
