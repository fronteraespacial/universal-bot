# Security

This repository is **public**. Treat everything here as world-readable.

## Never commit

- Discord bot tokens, webhook URLs, OAuth refresh tokens
- SSH private keys, cloud API tokens, Tailscale auth keys
- Per-site `instance.toml` with live IDs if the guild is private
- Client sqlite dumps, message history, member lists

Tokens live **outside** the repo:

- Linux: `~/.config/universal-bot/<instance>.env` (mode `600`)
- Windows: `%USERPROFILE%\.config\universal-bot\<instance>.env` (icacls owner-only)

## One gateway per token

Two live Discord gateways with the same bot token will both disconnect. Each installation uses **one** host (VM, VPS, or server PC).

## Report a leak

If a secret lands in a public commit, rotate it first, then open an issue on this repo (no secret in the issue body).
