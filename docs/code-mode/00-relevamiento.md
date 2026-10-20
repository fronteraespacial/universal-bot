# Modo código: relevamiento (2026-10-20, solo lectura)

Lo único que se escribió es este archivo. No hay commit, no se mandaron mensajes y no se tocó ningún repo. Para leer orquestador-sx hice un clon superficial de solo lectura en `<tmp>/orq-sx-ro` (commit `36d0ff7`, v1.5.0, 2026-08-26).

## 1. Repo universal-bot

- Path: `<repo>`. Remote: `origin https://github.com/fronteraespacial/universal-bot.git`.
- Branch actual: `docs/roadmap-steer`. Locales: `main`, `feat/opencode-serve`, `feat/unified-progress`, `docs/lecciones-koda`.
- Historia de la rama actual (5 commits en total):
  - `355e013` 2026-10-20 docs: roadmap de steer a mitad de ejecución (Reason Network evaluado)
  - `71e4296` 2026-09-30 feat(progress): tighten freshness to 180s + ProgressScheduler
  - `b06b24d` 2026-09-10 22:59 ART feat(core): Phase 0/1, deny-by-default, SQLite store, tests
  - `1470cda` 2026-09-10 feat(activity): multi-signal real activity detection
  - `b0f3f64` 2026-09-10 Initial public scaffold
- PRs abiertos:
  - #1 `docs/lecciones-koda`: docs.
  - #2 `feat/unified-progress`: un mensaje de progreso editable por job, trail AGY/Codex/Cursor/Grok, `cli_streams`, `stop_control` y `stop_interaction` (botón "Detener"), quota pin. Son unas 4,4k líneas.
  - #3 `feat/opencode-serve`: `opencode serve` compartido, spawn PTY, remap Free, plantillas MCP y skills por bot, unit systemd y tarea de Windows.

Árbol en `main` + rama actual:
```
AGENTS.md README.md SECURITY.md LICENSE pyproject.toml (discord.py>=2.3, pytest)
config/instance.example.toml   # [discord] allowlist deny-by-default, [runtime] timeout_long_s=1800, max_concurrent_jobs=2, default_brain="", [cli] agy/codex/opencode/cursor
docs/  architecture-review-codex-astra.md install-*.md instance-config.md real-activity-detection.md roadmap-steer.md
install/linux/install.sh  install/windows/install.ps1
instances/README.md
src/universal_bot/  activity.py config.py contracts.py dispatcher.py locks.py progress.py redact.py store.py  (opencode/ solo con __pycache__; el código está en PR #3)
tests/  test_activity/config/dispatcher/locks/progress_contract/redact/store.py
```
Qué hay hoy:
- **Listener de Discord:** no existe en el repo. El README dice: "El listener portable (gateway, MCP, watchdog) se suma por PR".
- **Routing:** solo `Dispatcher.admit_request` (`src/universal_bot/dispatcher.py`). Cubre allowlist, dedupe, capacidad, la elección de `brain` (o `default_brain`) y el workspace. No hay clasificador.
- **Contratos:** `contracts.py` tiene `JobStatus`, `DeliveryStatus`, `JobRequest`, `JobResult`, `JobEvent`, `AdapterCapabilities` y `RoutingDecision`.
- **Store:** `store.py` usa SQLite con jobs, lease, `recover_abandoned_jobs` y un outbox con reintento. Es la base natural para guardar el estado de las preguntas pendientes.
- **Invocación de CLIs:** no hay en `main`. En el PR #3 está la de OpenCode (`run.py`, `serve.py`, `pty_spawn.py`) y en el PR #2 los parsers de streams.
- **Ledger:** no está en el repo. Vive en `<repo>/` (`ledger.py`, `universal-bot.md` rev 7, `universal-bot.log.md` y `universal-bot.bots/{fe,lp,xp,tyr,koda,infra,cj,box-admin}.md`). El adaptador del pack es `<fe-bot>/project_ledger.py` (tool MCP/Zen `ledger`).
- **Steer:** `docs/roadmap-steer.md` propone `steer(task_id,msg)` / `cancel(task_id)` por adaptador. Opciones: opencode v2 inbox, Codex App Server `turn/steer` / `turn/interrupt`, y abortar+relanzar como fallback. Está marcado "No implementar todavía".

## 2. Metodología Orquestador SX (canon/)

Archivos: `canon/00-README-INSTALL-AGENT.md`, `01-METHODOLOGY-SPACEX.md` (537 líneas), `02-ROLES-HANDOFFS-GATES.md`, `07-MODELS-MATRIX.md` y `09-VERIFY-CHECKLIST.md`. Hay runtime para cursor, antigravity, opencode y codex (`runtime/*`). **No hay runtime de Grok CLI.**

### Tiers (§7 Router T0–T3; señales §5)
Señales que mira el gate (≤10 líneas): número de archivos y boundaries, workstreams disjuntos, requisito borroso, riesgo prod/irreversible, evidencia UI, automatización nueva, si hace falta lab, anomalía de entorno y WorkType (`greenfield|evolving-product|legacy-app|ops-diagnostic`). Por defecto se elige el **tier más barato**. **Cascade +1** si falla la aceptación o hay una `ANOMALIA` bloqueante. El techo es T3: si T3 falla, va a ESCALATE (no hay T4).

| Tier | Cuándo | Topología |
|---|---|---|
| T0 | Typo, 1 hunk, lectura | El padre **MAY** ejecutar directo (typo/1 hunk) **o** `explore`/`implementer`. Se salta Discovery si está claro. Escape Known-cause (causa ≡ cambio). |
| T1 | Bug de 1–2 archivos | **Known-cause gate HARD**: si la causa es desconocida, primero `explore`/`scout`/Mode diagnostic; con causa conocida, `implementer` → **verifier**. `repro ≠ causa`. |
| T2 | ≥2 workstreams, refactor | Known-cause → Scout soft → Discovery si hay triggers → Lab/Batch → YIELD_PLAN si aplica → Batch fan-out → verifier → VLH si es user-facing → Harvest + Maverick CONSULT |
| T3 | Feature/P0, borroso, automatizar | Known-cause → Scout → Discovery (≤3 labs) → **Lab REQUIRED** (greenfield) → auditors → YIELD_PLAN → Batch → verifier → VLH si es user-facing → Harvest + Maverick CONSULT |

### Oleadas y fases (§6)
- Jerarquía: `Run R-…` ⊃ `Oleada O1–O3` ⊃ `Fase prep|research-lab|execute|verify` ⊃ `Batch|Spawn`.
- **O1** es la inicial, **O2** la correctiva y **O3** la escalada. No hay O4/O5 (si aparecen, es process FAIL). Una oleada es un ciclo completo: **un spawn nunca es una oleada**. Los retries técnicos son ≤2 por fase y en el 2 hay ESCALATE.
- Qué hacer cuando el verify da FAIL:
  - Transient → retry en verify.
  - Reproducible local → **un solo O2** que consolida todo el gap inventory en un Batch execute.
  - Hipótesis, diseño o entorno → **O3** con research-lab (+ cascade).
  - Después de O3 → ESCALATE/STOP con freno humano.
- Discovery/Pre-Plan está dentro de research-lab: `DISCOVERY → DECIDE → YIELD_PLAN → Plan nativo → aprobación humana → Build`. Presupuesto: 1 research Batch, ≤2 labs (≤3 en T3) y 1 REVISE.
- Diagnosis adjudication (§6.5) es un circuit breaker dentro de verify. Cadena: Verifier-B en clean-room → O2 mejorado → diagnostic-adjudicator → ≤2 FINAL_PASS (H-F1 ≠ H-F2) → STOP con Human decision packet (`RESET_RUN|ESCALATE|ACCEPT_PARTIAL|ABORT`).

### Gates (§8)
- **8.0 Known-cause (HARD T1+):** el envelope del writer exige `Causa:`, `Cambio concreto:` y `Decisión abierta:`. Si falta, el hijo responde `## NEEDS-DIAGNOSIS`. Spawnear un writer sin causa es process FAIL.
- **8.1 Scout (soft-mandatory):** en greenfield, anomalía o post-ESCALATE. Fuentes ≤5.
- **8.2 Lab:** obligatorio en greenfield, en `.lab/YYYY-MM-DD-slug/`. Solo **APPROVE** desbloquea prod. Lab Batch de 2–3 hipótesis aisladas.
- **8.3 Maverick:** CONSULT early, post-lab, post-Harvest (obligatorio en T2/T3) y HARD en diagnostic. Solo propone `NO_CHANGE|YIELD_OPT`, nunca auto O2.
- **8.4 Verifier:** obligatorio después de cualquier implementer, antes de decir "done".
- **8.4b VerifierLikeHuman:** T2/T3 user-facing, después de un PASS técnico. Readonly, contrato B4.
- **8.5 ESCALATE@2–3.**
- **8.6 ANOMALIA.**
- **8.7 Freno humano + advisor card:** mensaje corto con 1–2 opciones. Con ≥2 APPROVE siempre pregunta con recomendación: `implementar A` / `testear más en lab` / `documentar B`. **Este es el punto exacto donde entra el puente a Discord.**
- **8.9 Harvest:** Ledger Automate + Maverick.

### Verifier (02 §4 verifier)
- Handoff: `Verdict: PASS|FAIL|INCONCLUSIVE`, `Commands run`, `Evidence` y `Gap inventory` (con **todos** los gaps bloqueantes).
- No escribe. Si el mismo DoD falla 2 veces sin un envelope nuevo, hace ESCALATE.
- V-direct (el verifier spawnea un implementer una sola vez) es opcional, solo Cursor y solo T0/T1 single-gap. Por defecto, el O2 lo maneja el padre.
- En Cursor el modelo es `cursor-grok-4.5-high-fast` (o 4.6-high-fast). En otros hosts, "Host remap" a high-reasoning.

### Reglas del padre
- Judgment root, "zero-tool, not zero-thought": clasifica, gatea, escribe sobres, espera el fan-in, consolida el O2, lleva Ledger y Harvest, aplica frenos y narra.
- **No** edita, no testea, no despliega, no busca en la web ni explora, salvo en T0 typo/1 hunk.
- Header `### Orch` en cada turno: `Tier | WorkType | Run | O | Fase | Batch` + `Next spawn` + `Parent tools: none`.
- **Single-Orchestrator HARD:** si un hijo spawnea al orquestador es process FAIL. Nested orch es opcional, de profundidad 1.
- Reenvía solo deltas. Los handoffs de salida tienen ≤40 líneas; los sobres de entrada no tienen límite.
- Algorithm Ledger ≤10 líneas, solo del padre (Need/Delete/Simplify/Accelerate/Automate).
- Cierre: `## Aportes del equipo` + exactamente una `## En criollo`.
- Batch obligatorio cuando los workstreams son independientes; el padre rechaza path sets que se crucen. Implementer N=1 por defecto. Composer nunca hace de verifier, maverick, VLH ni adjudicator.

## 3. Cómo FE-BOT y LP-BOT invocan CLIs

### FE-BOT: `<fe-bot>/`
- **Listener:** `listener.py` (2993 líneas, discord.py). Hace el routing por prefijo/sticky/grant y llama a `cli_brains.run_*`.
- **Wrappers** en `cli_brains.py`:
  - Binarios en L32-36: `<home>/.local/bin/{agy,codex,cursor-agent,grok}`. `cursor-agent` va con ese nombre y no como `agent`, porque Grok CLI también instala `agent`.
  - `run_agy` (L1681): `agy --dangerously-skip-permissions --model M [effort] --output-format stream-json --print-timeout <wall+90+8*1800>s --print=<prompt>`.
  - `run_codex` (L1749): `codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -m <slug> -C <wd> -c model_reasoning_effort=… [-c service_tier="fast"] [--image=…] --json -`. El prompt va por stdin y el canal se inyecta por `-c mcp_servers.fe-bot-pack.env.FE_UNIFIED_TRAIL_CHANNEL=…`.
  - `run_cursor` (L1837): `cursor-agent -p --trust --approve-mcps --force --output-format stream-json [--model slug] <prompt>`. Fuerza HTTP/1 (`cursor_http1.ensure`) y usa live trail.
  - `run_grok_cli` (L2101): `grok --prompt-file <tmp> --output-format streaming-json --always-approve --cwd <wd> --model grok-4.7 --effort <medium>`.
- **Ejecución común:** `_run` (L1483). Usa `Popen(start_new_session=True)` y escribe stdout/stderr a archivos temporales. Hay un tail thread que parsea los streams (`agy_cli_trail.AgyStream`, `ub_cli_streams.{CodexStream,GrokCliStream}`) y escribe `pid.json` en `DISCORD_JOB_DIR`. `_wait_job` controla la pared, el stall real (>3 min sin actividad), un silence heartbeat de 120 s y fail-fast ante un 400. La salida pasa por `unibot_access.redact` y hay un ssh jail (`sandbox_wrap`) para quien no tiene acceso.
- **Timeouts:** `LONG_TIMEOUT=1800` (L47). `_job_timeouts` siempre devuelve 30 min (regla de Julian del 2026-09-02). `job_deadline.py` maneja `WALL_S=1800`, `ADD_S=1800`, `MAX_RENEWS=8` y `WARN_S=360`.
- **Sesión/estado:** cada job es un **proceso nuevo, sin `--resume`**. La continuidad sale de:
  - el historial del hilo inyectado en el prompt (`_history_block`);
  - `thread_brain.py`, con brain sticky por hilo, grants y pin de modelo en `logs/thread_brain.json`;
  - `inflight.py`, con jobs vivos por canal;
  - los handoffs (`handoff.py`, `handoff_store.py`);
  - el brief del ledger (`project_ledger.project_brief_block`).
- **Respuesta en hilos:** el stdout final lo postea el wrapper como reply al mensaje (`discord_reply`). El progreso va por la tool `discord_progress`: contrato v1 de ~2 min y ≤200 caracteres, en un único embed editable (`unified_progress.py`), con botón "Detener pedido" (`ub_stop_control.py`, `ub_stop_interaction.py`). Las tools están en `zen_client.py`: `ledger` L225, `discord_send_message` L945, `discord_progress` L1152 y `job_extend` L1195. Las sirve el MCP `fe-bot-pack` (`mcp_server.py`).
- **Elección de modelo vigente** (de `cli-shared-rules.md` L35 y L320, en `<home>/agent-data/agents/5aa31e9c-…/docs/`, y de `cli_brains.py`):
  - AUTH sin prefijo → **Composer Fast `composer-2.5-fast`** en todo el guild salvo #orbital-viz (regla de Julian del 2026-10-10/11).
  - Cambiar de CLI solo se hace con un prefijo explícito: AGY / Codex|GPT / OpenCode / Grok|FE-BOT / Cursor.
  - AGY: por defecto `gemini-3.8-flash-low`; `AGY 3.8` → flash-high; `AGY 4/argon` → gemini-4-argon (low por defecto); Sonnet `claude-sonnet-5-5-high`; Opus `claude-opus-5-5-medium`.
  - Codex: por defecto `luna` = `gpt-6-luna` high fast; `terra` = `gpt-5.6-terra`; `sol` = `gpt-6-sol` xhigh; `astra` = `gpt-6-astra`.
  - Grok CLI: `grok-4.7` medium.
- **Pack edit:** solo se permite en #admin-febot y #uni-bot, y solo para Julian o Emanuel (`_pack_edit_note`).

### LP-BOT: `<repo>/LaPostaHH/listener/`
- Archivos: `listener.py` (934), `routing.py` (811), `brains.py` (629), `run_job.sh`, `job_deadline.py`, `job_stop.py`, `inflight.py`, `ub_cli_streams.py`, `unified_card.py` y `mcp_server.py`.
- **Modelo job-dir:** `brains._write_job_files` escribe `job.json` y `prompt.txt` en el directorio del job. Después `run_job.sh <job-dir>` arma el comando por brain (codex por defecto `gpt-6-luna`; opencode, agy, cursor y grokcli) y escribe `stdout.txt`, `stderr.txt` y `meta.json`. `_run_job_proc` usa `Popen` + `communicate(timeout)` + `killpg`, y `job_stop.register` lo deja cancelable.
- Este modelo desacopla mejor que FE-BOT y es el que conviene copiar.
- **Modelo:**
  - `routing.py`: `DEFAULT_BRAIN="agy"`, aunque el ledger dice que el brain activo es codex.
  - Grok CLI: `GROKCLI_DEFAULT_SLUG="grok-4.7"`, effort medium, FAST=True.
  - Cursor: `CURSOR_DEFAULT_SLUG="auto"`.
- **Snippet de orquestador** (`brains.py` ~L97): "Metodología GROKCLI XHIGH FAST: sos el orquestador padre (grok-4.7, reasoning effort xhigh, subagents ON)…workers grok-4.5…". Es lo más parecido a un "CLI de código con padre + subagentes" que ya está en producción. En la box, `~/.grok/config.toml` tiene `[subagents] enabled=true`, `[subagents.models] explore="grok-4.5"` y `fork_secondary_model="grok-4.6"`.
- **Timeouts:** `job_timeouts` → `TIMEOUT_LONG`, 1800 s para todo.

## 4. Detector por tiers y preguntas interactivas: qué existe

- **Clasificación por tiers T0–T3 en código:** **no existe.** Lo más cercano:
  - `fe-bot-discord/banter_triage.py`: clasificador OpenCode sin tools, banter vs request.
  - `is_simple_question` en `listener.py`: deriva preguntas simples a OpenCode.
  - `universal-driver-lab/routing/{classifier.py,smart_router.py,fast_path.py,engine.py}`: el classifier de LAB3 hace scope/inception con un agente económico (OpenCode Free). Las listas de keywords son solo un fallback. El "tier" de `smart_router` es de **costo** (free/go/pro/plus), no de complejidad.
  - `opencode_tiers.py`: también es de costo.
- **Preguntar a Discord y esperar respuesta en mitad de un job:** existe **un solo precedente**, y está acotado a renovar la pared:
  1. El CLI pregunta «¿Renuevo 30 min más? Respondé renovar o +30» (`job_deadline.prompt_rules`).
  2. El listener intercepta la respuesta de AUTH en el canal que tiene un job inflight (`listener.py` L2078-2114: `job_deadline.is_renew_text` → `apply_extend_for_channel`) y ese mensaje no dispara un CLI nuevo.
  3. El job también puede llamar a la tool `job_extend`.
- El patrón sirve: el mensaje dirigido a un job vivo se intercepta, se escribe en el job_dir y el proceso sigue vivo. Le falta generalizarse a preguntas con opciones.
- También existen botones de Discord Components V2 (stop) y el parser de interacciones (`ub_stop_interaction.py`), que se pueden reusar para botones de opción.
- **No hay** una tool `discord_ask` ni un estado de "pregunta pendiente" persistido.
- La metodología ya define dónde preguntar: §8.7 (freno humano + advisor card), YIELD_PLAN → Build y el Human decision packet.

## 5. CLIs en la box

| CLI | Path | Versión |
|---|---|---|
| agy | `<home>/.local/bin/agy` | 1.4.3 |
| codex | `<home>/.local/bin/codex` | codex-cli 0.156.0 |
| opencode | `<home>/.local/bin/opencode` | v2.0.32 |
| cursor-agent | `<home>/.local/bin/cursor-agent` | 2026.10.19-6bbf2c4 |
| grok | `<home>/.local/bin/grok` | 1.0.51 (alpha) |
| claude | **no instalado** | — |

## Huecos

1. Universal-bot no tiene listener ni adaptadores de CLI en `main`. Todo está en los PRs #2 y #3, sin merge.
2. No hay clasificador T0–T3, ni uno de "es programación sí/no".
3. No hay `ask`/espera genérico. Solo el intercept de `renovar`. Tampoco se persiste estado de pregunta.
4. Ningún CLI corre con sesión reanudable. Esperar a Discord obliga a mantener el proceso vivo (cuenta para la pared de 30 min y el stall detector lo puede matar) o a reanudar la sesión.
5. Orquestador-sx no tiene runtime de Grok CLI, y las IDs de modelos de `canon/07` (composer-2.5-fast, cursor-grok-4.5/4.6) hay que reconciliarlas con la regla actual del pack (Composer Fast por defecto, grok-4.7).
6. Inconsistencia: `cli-shared-rules.md` L237 estampa `Codex / gpt-5.6-luna`, pero el código usa `gpt-6-luna`.
7. LP `routing.py` dice `DEFAULT_BRAIN="agy"` y el ledger dice que el brain activo es codex. Hay que confirmar cuál vale.
8. No encontré una "regla vigente de modelos para bots de código" con ese nombre. Lo más cercano es la regla Composer Fast server-wide y la de GrokCLI XHIGH FAST en LP.

## Propuesta breve de arquitectura (modo código)

Servicios chicos, cada uno con su contrato en `contracts.py` y TDD:

1. **gateway** (proceso único por token): listener de Discord. Solo admite y encola (`Dispatcher` + `JobStore`) y entrega el outbox. Intercepta las respuestas a preguntas pendientes, igual que hoy con `renovar`, para que no abran jobs nuevos.
2. **triage** (`universal_bot/triage/`): una función pura `classify(text, ctx) -> TriageDecision{tier, worktype, is_code, signals, confidence}`.
   - Primero reglas baratas: señales §5 del canon, menciones de archivos/repos, verbos de implementación.
   - Después un LLM barato sin tools (como `banter_triage`) con salida JSON.
   - Si es dudoso, elegir el tier más barato (lo que dice el canon) y dejar que el CLI de código haga cascade +1.
   - T0/T1 → `basic_worker`. T2/T3 + `is_code` → `code_worker`.
   - Tests con una tabla de casos.
3. **worker runner** (al estilo LP): `job_dir/{job.json,prompt.txt,stdout,stderr,meta.json,state.json}` + adaptadores por CLI (`agy`, `codex`, `cursor`, `grok`, `opencode`). Cada adaptador expone `AdapterCapabilities{stream, resume, steer, subagents}`. Hay que reusar los parsers del PR #2 y el serve del PR #3.
4. **code worker**: corre el CLI con el pack orquestador-sx instalado (rules, skills, agents por superficie) y un prompt de padre "judgment root". Necesita header `### Orch`, Known-cause, oleadas O1–O3 y verifier obligatorio, más TDD estricto (rojo→verde→refactor como DoD del verifier), Clean Coder y servicios desacoplados (como reglas del implementer).
5. **ask bridge**:
   - Una tool MCP `discord_ask(question, options[], timeout_s)`. Postea en el hilo un embed con botones (Components V2, reusando `stop_interaction`).
   - Persiste `pending_question{job_id, qid, options, status}` en SQLite.
   - Bloquea con un long-poll sobre el store. La espera cuenta como actividad, para que el stall detector no mate el job, y pausa la pared.
   - El gateway resuelve el clic o el texto y escribe `answer` en el store y en `job_dir/answers/<qid>.json`.
   - Si el CLI tiene `resume` (codex `exec resume`, cursor `--resume`, opencode serve session), se puede cortar el proceso y reanudar con la respuesta. Si no, se mantiene vivo.
   - Mapeo directo a §8.7, YIELD_PLAN y Human decision packet.
6. **ledger/state**: `state.json` del Run (Run/Oleada/Fase/Algorithm Ledger ≤10 líneas) en el job_dir, más un puente al `project-ledger` existente.
7. **package**: `install/templates/<cli>/` (rules, skills, MCP `ub-pack`, agents) generados desde una sola fuente, más un `sync` como `sync_cli_shared_rules.py`. Superficies: Cursor CLI, Antigravity, OpenCode, Codex y Grok CLI (este último es nuevo respecto del canon: hay que mapear subagents de `~/.grok/config.toml`).
