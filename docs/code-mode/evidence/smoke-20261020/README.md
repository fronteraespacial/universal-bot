# Humo local 2026-10-20 (UTC-3 17:15:43 → 17:19:17, 3 min 34 s)

- Spool temporal: <codemode-base>/jobs/20261020-171543-smoke/spool (nunca el real). Job generado con `labcode_bridge.write_job()` de FE-BOT contra ese spool temporal.
- Comando: `timeout 900 .venv/bin/python -m universal_bot.labcode_runtime --spool <tmp>/spool --once --db <tmp>/smoke.sqlite --lab-root <tmp>/labs --routing-policy <codemode-base>/catalog/routing-policy.yaml --lab-timeout 540 --maverick-timeout 300 --max-labs 1` → exit 0.
- CLI real: grok-4.7 effort medium (ruta `lab` del routing-policy), `--sandbox workspace`, `--deny mcp__*`. Lab: 2 min 57 s, APPROVE/running. Maverick ALT: 37 s, 4 alternativas.
- Sin bridge corriendo: no hay `*.result.json`; los hilos de etapa caen al canal con prefijo.
- No se guardaron los .vtt/.m4a del lab (solo stdout, transcript de texto y meta sin env).

## Humo MAIN (conversar mientras delega)

Runtime real (`run_once` + FileOutbox) contra un spool temporal, con el puente simulado, el MAIN warm real (grok-4.7, effort low, ACP) y un worker largo simulado (6 s por video). Nunca se usó el spool real ni Discord.

- `main-run1.txt`: arranque, estado, cambio ("solo 3"), estado y resultado final. El MAIN pidió "relanzar": el worker 1 se cortó en 7/10 y el worker 2 terminó 3/3. Hubo 0 duplicados y el outbox quedó vacío.
- `main-run2.txt`: arranque, estado, cambio ("solo 8") y botón Frenar. "Frené el trabajo." salió 0.1 s después del click, el worker 2 quedó cortado en 1/8, el job quedó en `stopped` y hubo 0 duplicados.
- Latencia de respuesta del MAIN: 2 a 10 s según el turno (el más lento fue el de cambio de orden).
