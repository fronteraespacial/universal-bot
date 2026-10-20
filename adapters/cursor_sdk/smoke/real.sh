#!/usr/bin/env bash
# Smoke real mínimo: una respuesta "OK" y un steer corto. Gasta muy poca cuota de Cursor (composer-2.5 fast).
# Usa el lanzador (elige Node >= 22.13 solo). La key: --key-file, CURSOR_SDK_KEY_FILE o el archivo por defecto.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR="$HERE/bin/cursor-sdk-sidecar"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ms() { date +%s%3N; }
t0=$(ms)
echo "{\"prompt\":\"Respondé solo OK. No uses herramientas.\",\"cwd\":\"$TMP\",\"timeout_s\":60}" | "$SIDECAR" "$@" > "$TMP/ok.jsonl"; rc=$?
t1=$(ms)
echo "ok: exit=$rc wall_ms=$((t1-t0))"; tail -1 "$TMP/ok.jsonl"
( sleep 4; echo '{"text":"Cambio: en vez de contar, respondé solo la palabra STEERED."}' >> "$TMP/steer.jsonl" ) &
t0=$(ms)
echo "{\"prompt\":\"Escribí los números del 1 al 40 en el archivo n.txt de a uno, con un comando de shell por número (echo N >> n.txt; sleep 1). Al final respondé FIN.\",\"cwd\":\"$TMP\",\"timeout_s\":120,\"stream\":true,\"steer_file\":\"steer.jsonl\"}" | "$SIDECAR" "$@" > "$TMP/steer-out.jsonl"; rc=$?
t1=$(ms)
echo "steer: exit=$rc wall_ms=$((t1-t0))"
grep '"type":"steer"' "$TMP/steer-out.jsonl"; tail -1 "$TMP/steer-out.jsonl" | cut -c1-600
# Si el steer corta antes del primer echo, n.txt no existe: 0 líneas, sin error de redirección.
if [ -f "$TMP/n.txt" ]; then lines=$(wc -l < "$TMP/n.txt"); else lines=0; fi
echo "lineas en n.txt: $lines"
