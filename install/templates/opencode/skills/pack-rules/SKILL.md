---
name: "{{BOT_SLUG}}-pack-rules"
description: Canonical shared rules for this bot pack. Load at the start of any Discord/OpenCode request.
compatibility: opencode
---

# {{BOT_SLUG}}-pack-rules

Read and follow `{{AGENTS_MD}}`.

Timezone: {{TIMEZONE}}. Clock: MCP tool `get_current_time` on server `{{BOT_SLUG}}`.

Pack workflow skills live under the host workflows directory — open them with read when a request names them.

Discord/pack tools: use MCP `{{BOT_SLUG}}` (do not invent channels or times).
