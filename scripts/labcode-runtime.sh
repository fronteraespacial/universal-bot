#!/bin/sh
# Arranca, frena o consulta el runtime. El spool se pasa por argumento; no usa el spool real salvo que se lo indiques.
cd "$(dirname "$0")/.." || exit 1
exec .venv/bin/python -m universal_bot.labcode_service "$@"
