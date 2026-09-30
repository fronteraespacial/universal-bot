# Universal Driver / Universal Bot — shared pack index

Same pack as every installed CLI (AGY, Codex, Cursor, OpenCode, Grok Build CLI).

- Canonical rules: `/home/box/agent-data/agents/5aa31e9c-2a23-4836-b43b-8a621224c974/docs/cli-shared-rules.md`
- Pack live: `/workspace/fe-bot-discord/`
- This tree (LAB3 / Universal Driver): `/workspace/universal-driver-lab/`
- Universal Bot (future): `/workspace/universal-bot/`
- Skills: `/home/box/agent-data/workflows/`
- MCP: `fe-bot-pack` → `/workspace/fe-bot-discord/mcp_server.py`
- Transcribe media (all ranks/CLIs): MCP `media_transcribe` → srt/md/txt/json/pdf; CLI `transcript_cli.py`; memo `docs/media-transcribe-tool-2026-09-19.md`

Do not invent a second rules or tools tree. Sync: `python3 /workspace/fe-bot-discord/sync_cli_shared_rules.py`
