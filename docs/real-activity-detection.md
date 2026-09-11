# Real activity detection (stall / watchdog)

## Principle
**Lack of activity must be multi-signal.** Never kill a job because a single stream (e.g. stderr) went quiet.

Quiet orchestrators are normal: an AGY/host process may wait on tools, external APIs, or a sibling CLI (Codex, OpenCode, Cursor) that is actively burning tokens and posting progress.

## Required signals (any one = alive)
1. **Process I/O growth** — stdout and/or stderr byte size increased.
2. **External progress** — durable progress marker for the conversation/channel updated recently (Discord `progress_state`, or equivalent outbox row).
3. **Job workspace mtime** — files under the job lease/dir changed recently.
4. **Sibling / child workers** — another live worker PID bound to the same conversation/channel (or a living child in the job’s process group that is still leased).
5. **Explicit renew** — `job_extend` / lease renew resets idle.

Only when **all** applicable signals are idle past the threshold (`stall_threshold_s`, default 180s) may the supervisor abort as “stalled”.

## Freshness & Timing Windows
- `STALL_THRESHOLD_S = 180` (3 min idle limit before abort).
- `PROGRESS_FRESHNESS_S = 360` (6 min): Discord progress remains a live signal across the ~4 min digest throttle.
- `WORKSPACE_FRESHNESS_S = 360` (6 min): File updates in the working directory indicate ongoing processing.

## Implementation in Universal Bot
The core engine is implemented in `src/universal_bot/activity.py`:
- `RealActivityMonitor`: State-tracking monitor holding watermarks (`ActivitySnapshot`) and evaluating incoming signals via `evaluate(...)` and explicit renewals via `renew(...)`.
- `real_activity_seen(...)`: Functional interface drop-in compatible with worker wait loops.
- `ActivitySignal`: Enumeration of detected signal sources (`STDERR`, `STDOUT`, `PROGRESS`, `WORKSPACE_MTIME`, `SIBLING_CLI`, `CHILD_PROCESS`, `LEASE_RENEW`).
- `is_pid_alive(...)`: Cross-platform process verification working reliably on both Linux (POSIX) and Windows.

## Unit Tests
Covered in `tests/test_activity.py`:
- Stream growth tests (stdout and stderr independently).
- Progress freshness window tests (preventing premature timeouts mid-digest).
- Workspace directory mtime change detection.
- Sibling and child PID liveness detection.
- Explicit lease renewal verification.
- Accurate stall triggering when all signals are genuinely idle past the threshold.

Run tests:
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*.py" -v
```

## Anti-patterns
- Kill on stderr-idle alone.
- Treat “no Discord message” as dead if progress_state or sibling CLI is live.
- Reuse gateway heartbeat as job liveness (different concerns).
- Restart loops that confuse network blips with hung inference.

## Pack Reference
- FE-BOT live incident fix: `cli_channel_guard.real_activity_seen` + `cli_brains._wait_job` (2026-09-10).
- Incident Memo: `docs/real-activity-detection-stall-2026-09-10.md` on the FE-BOT agent docs tree.
- Architecture Review: `docs/architecture-review-codex-astra.md`.
