#!/usr/bin/env bash
# Installer smoke: Free prefix → shared serve → MCP get_current_time.
# Does NOT print passwords or API keys. Requires host already logged in
# (`opencode auth login`) and serve healthy on loopback.
set -euo pipefail

HOST="${UB_OPENCODE_HOST:-127.0.0.1}"
PORT="${UB_OPENCODE_PORT:-49374}"
FREE_MODEL="${UB_OPENCODE_FREE_MODEL:-deepseek-v4.1-flash-free}"
BIN="${UB_OPENCODE_BIN:-opencode}"
URL="http://${HOST}:${PORT}"
PROMPT="${1:-Responde exactamente: smoke-serve-ok. Si tenés MCP get_current_time, llamala y mencioná la zona.}"

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "refuse non-loopback host: $HOST" >&2
  exit 2
fi

echo "== health =="
curl -fsS --max-time 5 "${URL}/global/health"
echo

# Password for --server clients (never echo). Prefer env; else service get.
if [[ -z "${OPENCODE_PASSWORD:-}" && -z "${OPENCODE_SERVER_PASSWORD:-}" ]]; then
  if pw="$("$BIN" service get password 2>/dev/null | tr -d '\r')"; then
    if [[ -n "$pw" ]]; then
      export OPENCODE_PASSWORD="$pw"
    fi
  fi
fi

MODEL_ARG="opencode/${FREE_MODEL}#low"
echo "== run free via --server ($MODEL_ARG) =="
# PTY: script(1) when available so --auto does not stall without a TTY.
RUN_CMD=("$BIN" run -m "$MODEL_ARG" --auto --format json --server "$URL" "$PROMPT")
if command -v script >/dev/null 2>&1; then
  script -q -c "${RUN_CMD[*]}" /dev/null | tee /tmp/ub-opencode-smoke.out | tail -n 40
else
  "${RUN_CMD[@]}" | tee /tmp/ub-opencode-smoke.out | tail -n 40
fi

echo
echo "smoke finished (inspect /tmp/ub-opencode-smoke.out). No credentials were written to the pack."
