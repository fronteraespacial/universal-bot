---
name: code-story
description: >-
  Use when one backlog item is picked: refine it into acceptance criteria, out
  of scope, and a small vertical slice before coding.
---
# code-story

Refine **one** story before any implementer/CLI/CloudAgent codes.

## Inputs
- One backlog item (from [code-backlog](sand-workflow:code-backlog) or the user).
- Optional: constraints (repo, env, deadline).

## Produce (required)
1. **Story** — 1–3 sentences.
2. **Acceptance** — checklist of observable outcomes (what “done” looks like).
3. **Out of scope** — explicit non-goals for this slice.
4. **How to prove** — command, smoke, or manual check.
5. **Slice** — the smallest vertical path that delivers acceptance (not a horizontal layer).

## Do not
- Design the whole file tree.
- Add “nice to haves” into acceptance.
- Start coding in this skill — hand off to [code-pair](sand-workflow:code-pair).

## Output shape
```
Story: …
Acceptance:
- [ ] …
Out of scope:
- …
Prove: …
Slice: …
```

Stronger model for this refine step when available; faster model later for iteration.
