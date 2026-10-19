---
name: get-time
description: Obtain exact time via MCP get_current_time (never invent the clock).
compatibility: opencode
---

# get-time

When asked for the time, date, or "what time is it":

1. Call MCP tool `get_current_time` on server `{{BOT_SLUG}}`.
2. Answer with that result in the bot timezone.
3. Do not invent or use the model clock.
