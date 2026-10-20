#!/usr/bin/env bash
# Smoke offline: sin red (unshare -rn), valida schema y códigos de error. No gasta cuota.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SIDECAR="$HERE/bin/cursor-sdk-sidecar"
NODE="${CURSOR_SDK_NODE:-$("$SIDECAR" --exec-node -e "process.stdout.write(process.execPath)")}"
OLD_NODE="${OLD_NODE:-}"
FAKE_KEY="crsr_offline_FAKE_0123456789abcdefghijklmnop"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
printf '%s\n' "$FAKE_KEY" > "$TMP/key"
fails=0
check() { # nombre, código esperado, salida
  local name="$1" want="$2" out="$3"
  local got; got="$(printf '%s' "$out" | tail -1 | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print(d.get("code") or ("OK" if d.get("ok") else "?"))' 2>/dev/null)"
  if printf '%s' "$out" | grep -q "FAKE_0123"; then echo "FAIL $name: filtró la key"; fails=$((fails+1)); return; fi
  if [ "$got" = "$want" ]; then echo "ok   $name → $got"; else echo "FAIL $name: esperaba $want, dio $got"; fails=$((fails+1)); fi
}
run() { unshare -rn "$NODE" "$HERE/runner.mjs" "$@" 2>&1; }
check "bad_request" BAD_REQUEST "$(echo '{nope' | run --key-file "$TMP/key")"
check "no_key" NO_KEY "$(echo '{"prompt":"OK"}' | env -u CURSOR_API_KEY unshare -rn "$NODE" "$HERE/runner.mjs" --key-file "$TMP/missing" 2>&1)"
out="$(echo "{\"prompt\":\"respondé OK\",\"cwd\":\"$TMP\",\"timeout_s\":20}" | run --key-file "$TMP/key")"
code="$(printf '%s' "$out" | tail -1 | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print(d["code"], d["fallback"])')"
if printf '%s' "$out" | grep -q "FAKE_0123"; then echo "FAIL sin_red: filtró la key"; fails=$((fails+1)); else echo "ok   sin_red → $code (fallback esperado True)"; fi
case "$code" in *True) ;; *) fails=$((fails+1)); echo "FAIL sin_red: no pide fallback";; esac
if [ -n "$OLD_NODE" ]; then check "node_viejo" NODE_TOO_OLD "$(echo '{"prompt":"OK"}' | "$OLD_NODE" "$HERE/runner.mjs" --key-file "$TMP/key" 2>&1)"; fi
echo "fallas: $fails"; exit "$fails"
