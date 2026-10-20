#!/usr/bin/env bash
# Smoke real mínimo: una respuesta "OK" y un steer corto. Gasta muy poca cuota de Cursor (composer-2.5).
# La key se lee del archivo por defecto (~/.secrets/cursor_api_key_frontera) o de --key-file / CURSOR_SDK_KEY_FILE.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
NODE="${CURSOR_SDK_NODE:-node}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ms() { date +%s%3N; }
t0=$(ms)
echo "{\"prompt\":\"Respondé solo OK. No uses herramientas.\",\"cwd\":\"$TMP\",\"timeout_s\":60}" | "$NODE" "$HERE/runner.mjs" "$@" > "$TMP/ok.jsonl"; rc=$?
t1=$(ms)
echo "ok: exit=$rc wall_ms=$((t1-t0))"; tail -1 "$TMP/ok.jsonl"
( sleep 4; echo '{"text":"Cambio: en vez de contar, respondé solo la palabra STEERED."}' >> "$TMP/steer.jsonl" ) &
t0=$(ms)
echo "{\"prompt\":\"Escribí los números del 1 al 40 en el archivo n.txt de a uno, con un comando de shell por número (echo N >> n.txt; sleep 1). Al final respondé FIN.\",\"cwd\":\"$TMP\",\"timeout_s\":120,\"stream\":true,\"steer_file\":\"steer.jsonl\"}" | "$NODE" "$HERE/runner.mjs" "$@" > "$TMP/steer-out.jsonl"; rc=$?
t1=$(ms)
echo "steer: exit=$rc wall_ms=$((t1-t0))"
grep '"type":"steer"' "$TMP/steer-out.jsonl"; tail -1 "$TMP/steer-out.jsonl" | cut -c1-600
echo "lineas en n.txt: $(wc -l < "$TMP/n.txt" 2>/dev/null || echo 0)"
