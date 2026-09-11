#!/usr/bin/env bash
# Scaffold a Universal Bot instance on Linux (VM / VPS / PC server).
# Does not download secrets. Does not start a Discord gateway.
set -euo pipefail

INSTANCE="${1:-}"
PREFIX="${UB_PREFIX:-/opt/universal-bot}"

if [[ -z "$INSTANCE" ]]; then
  echo "uso: $0 <instance-name>"
  echo "ejemplo: $0 sitio-acme"
  exit 2
fi

if [[ "$INSTANCE" =~ [^a-z0-9_-] ]]; then
  echo "nombre inválido: solo a-z 0-9 _ -"
  exit 2
fi

SRC="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${PREFIX}/instances/${INSTANCE}"
CFG_DIR="${HOME}/.config/universal-bot"
ENV_FILE="${CFG_DIR}/${INSTANCE}.env"

mkdir -p "$DEST" "$CFG_DIR" "${DEST}/state/logs" "${DEST}/state/jobs" "${DEST}/state/locks" "${DEST}/workspaces"
chmod 700 "$CFG_DIR"

if [[ ! -f "${DEST}/instance.toml" ]]; then
  sed "s/example-site/${INSTANCE}/g" "${SRC}/config/instance.example.toml" > "${DEST}/instance.toml"
  sed -i "s|\./secrets\.env|${ENV_FILE}|g" "${DEST}/instance.toml"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  umask 077
  cat > "$ENV_FILE" << 'INNER_EOF'
# chmod 600. Never commit. Never paste in Discord.
DISCORD_BOT_TOKEN=
CONTEXT7_API_KEY=
INNER_EOF
  chmod 600 "$ENV_FILE"
fi

echo "instancia: ${DEST}"
echo "secrets:   ${ENV_FILE}  (completar a mano)"
echo "siguiente: editar instance.toml y pegar token en el .env"
echo "luego:     un solo gateway vivo en este host"
