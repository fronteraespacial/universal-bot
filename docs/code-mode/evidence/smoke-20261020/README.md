# Humo local 2026-10-20 (UTC-3 17:15:43 → 17:19:17, 3 min 34 s)

- Spool temporal: <codemode-base>/jobs/20261020-171543-smoke/spool (nunca el real). Job generado con `labcode_bridge.write_job()` de FE-BOT contra ese spool temporal.
- Comando: `timeout 900 .venv/bin/python -m universal_bot.labcode_runtime --spool <tmp>/spool --once --db <tmp>/smoke.sqlite --lab-root <tmp>/labs --routing-policy <codemode-base>/catalog/routing-policy.yaml --lab-timeout 540 --maverick-timeout 300 --max-labs 1` → exit 0.
- CLI real: grok-4.7 effort medium (ruta `lab` del routing-policy), `--sandbox workspace`, `--deny mcp__*`. Lab: 2 min 57 s, APPROVE/running. Maverick ALT: 37 s, 4 alternativas.
- Sin bridge corriendo: no hay `*.result.json`; los hilos de etapa caen al canal con prefijo.
- No se guardaron los .vtt/.m4a del lab (solo stdout, transcript de texto y meta sin env).
