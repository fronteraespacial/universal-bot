#!/usr/bin/env bash
# Watchdog hook: ensure shared opencode serve is healthy on loopback.
# Safe to call from a host supervisor every N seconds. No secrets printed.
set -euo pipefail

HOST="${UB_OPENCODE_HOST:-127.0.0.1}"
PORT="${UB_OPENCODE_PORT:-49374}"
UNIT="${UB_OPENCODE_SYSTEMD_UNIT:-ub-opencode-serve.service}"
URL="http://${HOST}:${PORT}/global/health"
BIN="${UB_OPENCODE_BIN:-opencode}"

if [[ "$HOST" != "127.0.0.1" && "$HOST" != "localhost" ]]; then
  echo "refuse non-loopback host: $HOST" >&2
  exit 2
fi

if curl -fsS --max-time 3 "$URL" >/dev/null 2>&1; then
  echo "ok $URL"
  exit 0
fi

if command -v systemctl >/dev/null 2>&1 && systemctl --user status "$UNIT" >/dev/null 2>&1; then
  systemctl --user restart "$UNIT" || true
elif command -v "$BIN" >/dev/null 2>&1; then
  "$BIN" service restart >/dev/null 2>&1 || \
    "$BIN" serve --hostname "$HOST" --port "$PORT" >/dev/null 2>&1 &
fi

sleep 1
if curl -fsS --max-time 3 "$URL" >/dev/null 2>&1; then
  echo "restarted ok $URL"
  exit 0
fi
echo "unhealthy $URL" >&2
exit 1
