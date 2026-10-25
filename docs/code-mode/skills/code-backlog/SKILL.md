---
name: code-backlog
description: >-
  Use when starting product work: turn a vague ask into a short backlog of
  stories (no Spec Driven / no architecture layers).
---
# code-backlog

Augmented Coding (Kent Beck style). **Not** Spec Driven Development: no huge specs, no horizontal layers, no SpecKit/OpenSpec.

## When
A feature, bug cluster, or product area needs to be broken into work before coding.

## Do
1. Write a **short backlog** of user-facing stories or tickets (bullets). Prefer outcomes over file trees.
2. Keep each item one sentence: who/what changes and why it matters.
3. Order by risk or dependency; mark the **next** story to refine.
4. Explicitly list what is **out of this backlog** (parked ideas).

## Do not
- Write multi-layer architecture docs.
- Invent a full module design before a story is refined.
- Expand scope while listing.

## Output shape
```
Backlog:
- …
- …
Next: <one story title>
Out of backlog: …
```

Next step: run [code-story](sand-workflow:code-story) on **one** story.
