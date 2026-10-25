---
name: code-pair
description: >-
  Use when implementing a refined story: AI writes, human/orchestrator pilots,
  vertical slice + tests; fail on loops, scope creep, or faking tests.
---
# code-pair

Pair-programming loop for **one** refined story ([code-story](sand-workflow:code-story)).

## Rules
1. Implement **only** the current slice; no scope creep.
2. Prefer TDD-ish: failing test/check → minimal code → green → small refactor.
3. AI writes; orchestrator/human pilots in small steps.
4. **Alarms = FAIL** (stop and report; do not “finish”):
   - **Loops** — same failing approach repeated without new info.
   - **Scope creep** — work outside acceptance / out of scope.
   - **Fake tests** — editing tests only to make them pass (unless the test itself is proven wrong).
5. One CloudAgent/CLI job = one slice. Prompt must include story, acceptance, out of scope, how to prove, and “one slice; do not expand scope”.
6. Evidence = green proof (tests/smoke), not a long design doc.

## Invocation template (CLI / CloudAgent)
```
Story: …
Acceptance: …
Out of scope: …
Prove: …
One slice only; do not expand scope. If blocked, stop and report.
```

## Done when
Acceptance checklist is met and proof command/smoke passes. Then return to backlog for the next story.
