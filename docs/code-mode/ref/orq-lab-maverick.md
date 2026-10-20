# Orquestador SX — Lab y Maverick: diseño actual, huecos y propuesta "lab-first" (idea de Julian)

> **Tipo:** análisis de solo lectura. No se tocó el repo ni se corrió ninguna prueba de transcripción.
> **Fuente:** `github.com/fronteraespacial/orquestador-sx`, clon RO `<tmp>/orq-sx-ro`.
> **Versión analizada:** `git fetch` sin novedades → `HEAD = origin/HEAD = 36d0ff7` ("docs: mark AGENT-HANDOFF as v1.5.0 tagged"), `VERSION = 1.5.0`. El tag `v1.5.0` apunta a `f954344`; `36d0ff7` es un commit de docs posterior al tag. No hay nada más nuevo.
> **Fecha:** 2026-10-20 (hora de Buenos Aires, UTC-3).
> **Convención de citas:** `archivo:línea` o `archivo §sección`. Los archivos de la raíz `01-…`/`02-…` son stubs ("Moved"); el canon real está en `canon/`.

Archivos leídos (los relevantes): `canon/01-METHODOLOGY-SPACEX.md`, `canon/02-ROLES-HANDOFFS-GATES.md`, `canon/09-VERIFY-CHECKLIST.md`, `runtime/skills/orchestrator/SKILL.md` + `references/fase-lab.md`, `fase-verify.md` + `reference.md`, `runtime/cursor/agents/{orchestrator,lab-runner,maverick,scout,verifier}.md`, `runtime/antigravity/agents/{lab-runner,maverick,scout}/agent.md`, `runtime/codex/agents/{lab,maverick,scout,orchestrator}.toml`, `runtime/codex/config.toml.example`, `runtime/opencode/opencode.json.example` (permisos de `sx-lab`/`sx-maverick`/`sx-scout`), `runtime/project/lab/{README,INDEX}.md`, `runtime/project/AGENTS.md`, `runtime/cursor/rules/*.mdc`, `SECURITY.md`, `CHANGELOG.md`, `tooling/scripts/Validate-OrchestratorPack.ps1` (tests de lab/maverick) y ejemplos reales en `.lab/` (p. ej. `.lab/2026-08-26-known-cause-gate/RESULT.md`, `.lab/2026-08-05-wave-taxonomy/REPORT.md`).

---

## 1. Cómo está diseñado el orquestador (resumen fiel)

### 1.1 Idea central: un padre que juzga y no ejecuta
- "El **Orquestador** recibe el prompt crudo, lo clasifica, lo traduce a un **gate interno corto**, planifica **Run → Oleada O1–O3 → Fases**, escribe sobres, delega y fusiona **handoffs compactos (deltas)**. Los hijos ejecutan. El padre **no** edita, testea, despliega, hace web research ni explora el sistema — **excepto T0 typo/1 hunk**" (`canon/01 §1`, l.7).
- Es un **"judgment root (zero-tool, not zero-thought)"**: decide qué se hace, no lo hace él (`SKILL.md` l.76; `canon/01 §8.0` l.388).
- El cumplimiento es *best-effort* en Cursor (solo auditable), más duro en OpenCode/Codex vía permisos (`canon/01 §2`; `SKILL.md` "Honest enforcement note"). En OpenCode el orquestador tiene `edit/bash/webfetch/websearch: deny` y solo puede usar `task` hacia los `sx-*` (`opencode.json.example`).
- **Single-Orchestrator HARD:** un único orquestador raíz por Run; que un hijo levante otro orquestador es *process FAIL* (`canon/01 §4` l.81; `canon/02 §2` l.42).
- Cada turno lleva un encabezado `### Orch` con Tier, WorkType, Run, Oleada, Fase, Batch, `Next spawn` y `Parent tools: none` (`canon/01 §4` l.63–77).

### 1.2 Clasificación y gate
- Señales (≤10 líneas): #archivos, workstreams disjuntos, requisito borroso, riesgo prod, evidencia UI, **automatización nueva**, **¿Lab? (greenfield, frágil, fuera de caja, hipótesis de debug, automation nueva)**, ¿anomalía de entorno?, WorkType (`canon/01 §5` l.87–99). Default = tier más barato; **Cascade +1** si falla aceptación o hay `ANOMALIA` bloqueante.
- Gate interno: `Tier · WorkType · Signals · Lab/Scout/Maverick · Discovery enter|skip · Run/Oleada/Fases · Human brake` (`canon/01` l.103–112). La versión del SKILL agrega `Causa conocida: yes|no` (Known-cause gate) y separa `Lab:`, `Scout:`, `Maverick:` (`SKILL.md` l.148–160).
- **WorkType:** `greenfield | evolving-product | legacy-app | ops-diagnostic` (`canon/01 §6.2` l.156–163). En `ops-diagnostic` **no** hay labs de feature ni mutaciones paralelas.

### 1.3 Tiers T0–T3 (`canon/01 §7` l.375–382; `SKILL.md` l.350–357)
| Tier | Cuándo | Topología resumida |
|---|---|---|
| T0 | typo, 1 hunk, lectura | el padre **puede** ejecutar directo; o `explore`/`implementer` |
| T1 | bug 1–2 archivos | Known-cause gate HARD → `implementer` → `verifier` |
| T2 | ≥2 workstreams, refactor | Known-cause → Scout soft → Discovery si triggers → Lab/Batch → YIELD_PLAN → Batch → verifier → VLH → Harvest + Maverick CONSULT |
| T3 | feature/P0, **borroso**, **automatizar** | Known-cause → Scout → Discovery (≤3 labs) → **Lab REQUIRED (greenfield)** → auditores → YIELD_PLAN → Batch → verifier → VLH → Harvest + Maverick CONSULT |

No existe T4: cascade en T3 → `ESCALATE` (`canon/01 §6` l.118).

### 1.4 Run / Oleadas O1–O3 / Fases / Batch (`canon/01 §6` l.114–136; `canon/02 §3`)
- **Run** = objetivo del usuario. **Oleada** = ciclo completo: **O1 inicial, O2 correctivo, O3 escalado**; no hay O4 (`canon/01` l.121; `§6.5` invariantes l.292–297).
- **Fases** dentro de cada oleada: `prep` (solo orquestador) → `research-lab` (scout, explore, auditores, **lab-runner, maverick**; incluye Discovery) → `execute` (implementer) → `verify` (verifier, VLH, Harvest, Maverick CONSULT) (`canon/01` l.129–134).
- **Batch** = spawns paralelos + fan-in; **Spawn** = un hijo, "nunca es una oleada"; **Retry** = reintento técnico en la misma fase (≤2; ESCALATE@2) (`canon/01` l.123–125, l.85).
- Transiciones de verify FAIL: transitorio → Retry; reproducible local → **un solo O2**; hipótesis/diseño/env → **O3 con research-lab (+lab/scout/maverick)**; tras O3 → ESCALATE/STOP + freno humano (`canon/01` l.210–219).

### 1.5 Discovery / Pre-Plan (⊂ research-lab) — el punto donde viven los labs
`DISCOVERY → DECIDE → YIELD_PLAN → native Plan/Artifact → human approval → Build` (`canon/01 §6.1` l.142–153):
- Entra si: zero-to-one, debug grande sin hipótesis dominante, legacy hot path, **≥2 enfoques plausibles**, post-ESCALATE, trade-off de arquitectura, cambio irreversible.
- **Budget:** un research Batch; **≤2 labs (≤3 T3)**; **una** REVISE; luego `DECIDE | YIELD_PLAN | STOP`.
- Labs en Discovery: sin writes a prod, sin Implementation Plan formal.
- **YIELD_PLAN:** el padre pide al humano abrir el Plan nativo (Cursor Plan Mode, AGY Planning, OpenCode Plan→Build, Codex `/plan`) y **aprobar Build**; declinar = STOP (`canon/01 §6.3`, l.165–174). El host no cambia de modo solo ("ask-only").

### 1.6 Gates (`canon/01 §8`)
- **§8.0 Known-cause gate (HARD T1+):** sin `Causa conocida: yes` con evidencia está prohibido spawnear `implementer`; el sobre debe traer `Causa` + `Cambio concreto` + `Decisión abierta` (l.386–398). `repro ≠ causa`.
- **§8.1 Scout (soft-mandatory):** antes de lab/implementer en greenfield, anomalía o post-ESCALATE; REQUIRED en greenfield/anomalía/ESCALATE/**automation nueva**/trade-off grande; ≤5 fuentes (l.400–404).
- **§8.2 Lab** y **§8.3 Maverick:** ver §2.
- **§8.4 Verifier** REQUIRED tras implementer; **§8.4b VerifierLikeHuman** tras PASS técnico en T2/T3 user-facing.
- **§8.5 ESCALATE@2–3:** 2 fallos (máx 3 si repro) → `## ESCALATE` → Scout → retry con delta o STOP (l.464–466).
- **§8.6 ANOMALIA:** "Hijo reporta evidencia → Orquestador: bloqueante / P1 / backlog → child acotado o cascade +1; frágil → lab" (l.468–470).
- **§8.7 Freno humano + advisor card:** ver §2.4.
- **§8.8 Curiosity**, **§8.9 Harvest** (fin T2/T3 PASS → Ledger Automate → Maverick CONSULT → `NO_CHANGE|YIELD_OPT`, humano decide, sin auto-O2).

### 1.7 Presupuestos y narración
- Handoffs de salida ≤40 líneas; sobres de entrada sin límite; LIGHTWEIGHT MODE ≤8 tool calls; Scout ≤5 fuentes; Discovery 1 Batch / ≤2–3 labs / 1 REVISE (`canon/01 §10` l.520–531).
- **No hay ningún límite de tiempo de reloj** (wall-clock) en todo el canon ni en los prompts: los presupuestos son por intentos, cantidad de labs, tool calls y líneas. El propio pack evita "wall-clock claims" (p. ej. `.lab/2026-08-26-known-cause-gate/RESULT.md`: "No wall-clock or live-spawn claims").
- Narración final en lenguaje simple + `## Aportes del equipo` + **una** `## En criollo` "Solo al cierre del trabajo entregado; nunca como preámbulo del plan o de la oleada" (`canon/01 §3` l.61, `§11` l.533–537; `cj-criollo-changelog.mdc`).
- **Stop si:** dumb/borroso, REJECT, trade-off humano, DEAD-END, **reintentar hipótesis refutada**, decline YIELD_PLAN/Build, ops privileged (`canon/01 §11` l.537).

---

## 2. Lab y Maverick tal como están hoy

### 2.1 Lab (`lab-runner` / Codex `lab` / OpenCode `sx-lab`)

**Cuándo se dispara**
- Greenfield → **REQUIRED**; solo `APPROVE` desbloquea implementer en prod (`canon/01 §8.2` l.406–408; `SKILL.md` l.372).
- Señal de clasificación #7: "greenfield, frágil, fuera de caja, hipótesis de debug, automation nueva" (`canon/01 §5` l.95).
- Dentro de Discovery cuando hay triggers (§1.5); en **O3** tras verify FAIL de diseño/hipótesis (`canon/01` l.216); como salida de `ANOMALIA` "frágil → lab" (`§8.6`).
- **Lab Batch:** 2–3 hipótesis distintas, aisladas en paths/ports/services/data (`canon/01 §8.2` l.410; `fase-lab.md` l.15–19).
- **Solo lo spawnea el root**: "Orch-owned only — verifier/VLH must not spawn labs" (`runtime/cursor/agents/lab-runner.md` l.13); V-lab/H-lab = REJECT permanente (`canon/01` l.313; `canon/02 §8` l.394).
- Prohibido en `ops-diagnostic` (features) (`canon/01 §6.2` l.163).

**Qué recibe (sobre)**
- Header común `### Env · lab-runner` + Objetivo, Archivos/No tocar, Aceptación, Lab previo, Isolation, Deltas previos, External contrast (`SKILL.md` l.430–447; `canon/02 §5` l.327–332: "Solo `.lab/<id>/**`; REPORT + veredicto; isolation checklist").
- `reference.md` l.306–308: "only `.lab/<id>/**`. Aceptación: REPORT with verdict. No web. No formal Implementation Plan. Isolate ports/services/data from sibling labs."
- Consigna clave: "probar el **núcleo/diferencial**, no el producto entero" (`canon/01 §8.2` l.410; `fase-lab.md` l.11–13).

**Qué puede ejecutar**
- Escribir **solo** en `.lab/YYYY-MM-DD-<slug>/` (en la raíz del repo, nunca `projects/.lab/`) (`lab-runner.md` l.17–18; `project/lab/README.md`).
- **Sin web**: "NO WebSearch → `## ESCALATE` → `scout`" (`lab-runner.md` l.19; Codex `lab.toml`: `web_search = "disabled"`, `sandbox_mode = "workspace-write"`; OpenCode `sx-lab`: `edit` solo `.lab/**`, **`bash: allow`**, `webfetch/websearch: deny`).
- Nada dice sobre credenciales, red de salida, otros sistemas, CPU/RAM/disco: el "aislamiento" es por **directorio + puertos/servicios/datos** entre labs hermanos, no un sandbox de SO. En Cursor no hay enforcement real (el subagente corre con los permisos de la sesión).

**Límites de tiempo/recursos**
- Intentos: "**2** enfoques fallidos (max **3** repro) → `## ESCALATE`" (`lab-runner.md` l.20).
- Discovery: ≤2 labs (≤3 T3), una REVISE (`fase-lab.md` l.36–38).
- LIGHTWEIGHT MODE (≤8 tool calls) solo si el sobre lo pega (`SKILL.md` l.476–484).
- **Sin timebox de reloj, sin cuotas de recursos.**

**Qué entrega**
- Archivos: `HYPOTHESIS.md` (o `BRIEF.md`) + MVP en el dir + `REPORT.md`/`RESULT.md` con veredicto **`APPROVE | REVISE | REJECT | YIELD`** y una línea `status:` (`lab-runner.md` l.17; `project/lab/README.md` "INDEX + status tags").
- Handoff (≤40 líneas) (`canon/02 §4` l.229–239):
  ```markdown
  ## Lab handoff
  - Path: .lab/…
  - Verdict: APPROVE | REVISE | REJECT | YIELD
  - Evidence: …
  - Isolation: paths | ports | services | data — …
  - evidence_class: running | paper
  - Curiosity: (opcional)
  ```
  (La versión Cursor/AGY/Codex omite `Isolation:`; `canon/02` la incluye.) Más los deltas estructurados en Batch (`practical_delta`, `delta_ref`, `changed_paths`, `acceptance_hint`, `evidence_paths`, `human_contribution`) (`canon/02 §4` l.123).
- No hay un esquema obligatorio de **comandos ejecutados, métricas, artefactos con hash, entorno**. Los REPORT reales del repo son tablas libres H1…Hn / falsifiers y muchos son `evidence_class: paper`.

**Cómo alimenta al plan**
- Fan-in: `APPROVE > REVISE > REJECT > YIELD` (`canon/01 §8.2`).
- El padre (`fase-lab.md` l.21–29): (1) **spot-check 1–2 claims del REPORT**; (2) **Maverick CONSULT post-lab**; (3) **advisor card**; (4) una línea en `.lab/INDEX.md` (`chosen|deferred|killed`).
- Luego `DECIDE` → `YIELD_PLAN` → humano aprueba Build → `implementer` con sobre `Lab previo: APPROVE .lab/<id>/REPORT.md` (`SKILL.md` l.442). La evidencia del lab es lo que permite cumplir el **Known-cause gate** (`Causa` + `Cambio concreto`).
- Nunca se importa código de `.lab/` a prod (`canon/01 §9` l.505).

**Qué pasa si refuta la hipótesis**
- `REJECT` = "Dead end → STOP or new theory (scout/maverick)" (`project/lab/README.md`, tabla Verdicts).
- `REJECT` dispara **freno humano** (`canon/01 §8.7` l.474: "lab/auditores REJECT").
- "**Stop si:** … reintentar hipótesis refutada" (`canon/01 §11`).
- INDEX `status: killed` = "do not revive without new evidence" (`project/lab/INDEX.md`).
- `YIELD` = parar sin APPROVE falso; decide el orquestador. `REVISE` = reintentar con nuevo sobre (máx 1 en Discovery).
- ESCALATE del lab → Scout → retry con delta de contraste o STOP (`canon/01 §8.5`).

### 2.2 Maverick (`maverick` / Codex `maverick` / OpenCode `sx-maverick`)

**Cuándo se dispara** (`canon/01 §8.3` l.412–422; `runtime/cursor/agents/maverick.md` l.20–28; `canon/02` l.188):
| Timing | Modo | Fuerza |
|---|---|---|
| Anomalía de entorno T2+ | LAB o CONSULT | **REQUIRED** (sin que el usuario lo pida) |
| Zero-to-one / trade-off de arquitectura en Discovery | CONSULT early | soft |
| Post-lab (tras fan-in de labs, antes de YIELD_PLAN/Build) | CONSULT | **REQUIRED cuando hubo labs** |
| Post-Harvest (T2/T3 PASS) | CONSULT | **mandatory** → solo `NO_CHANGE | YIELD_OPT` |
| Mode: diagnostic (antes de `.debug/…/REPORT.md`) | CONSULT HARD | obligatorio; "never patch" |

**Qué recibe:** sobre con `CONSULT|LAB`, timing y path mav fechado (`canon/02 §5` l.334; `reference.md` l.314–316).

**Qué puede ejecutar**
- CONSULT: "Ninguna (lectura + web)"; LAB: "Solo `.lab/YYYY-MM-DD-mav-<slug>/`" (`maverick.md` l.13–18).
- **Tiene web** (a diferencia de Lab): Codex `web_search = "live"`, `sandbox_mode = "workspace-write"`; OpenCode `sx-maverick` con `bash/webfetch/websearch: allow` y edit solo `.lab/**`.
- AGY: "Web/contraste directo; investigación amplia → Scouts al Orquestador"; conflicto con otro lab → `YIELD` (`antigravity/agents/maverick/agent.md` Hard rules 2 y Best-effort).

**Límites:** "3 intentos/teoría → `## MAV-ESCALATE`" (`maverick.md` l.34); handoff ≤40 líneas; **nunca Composer** (process FAIL). `MAV-ESCALATE` puede pedir "more attempts | wider permissions | pair with scout | different env" (AGY). Sin timebox.

**Qué entrega** (`canon/02 §4` l.170–186):
```markdown
## Maverick take
- Mode: CONSULT | LAB
- Timing: early-discovery | env-anomaly | post-lab | post-harvest
- What-if ideas: ≤3
- Best-part-is-no-part: …
- Unconventional reuse: …
- Lab evidence: none | .lab/<dir> … | YIELD
- Attempts: N/3
- Proposal (post-harvest): NO_CHANGE | YIELD_OPT — …
- Risk & why it might work anyway: …
- Not my call: …
```
(El prompt Cursor `maverick.md` l.44–51 trae una versión más corta: Mode / What-if / Verdict / Lab evidence / Not my call — **desalineada** con `canon/02`.)

**Cómo alimenta al plan:** "Propone; no decide" (`canon/01 §8.3` l.422). Post-lab: "contrasta idea pre-lab vs evidencia; alimenta advisor card" (l.418). Post-Harvest: `YIELD_OPT` "necesita humano", **nunca auto O2** (l.419; `canon/02` glosario l.26–27).

**Si refuta:** no hay regla específica; LAB fallido → `MAV-ESCALATE` tras 3 intentos; conflicto → `YIELD`.

### 2.3 Relaciones con scout, verifier, ANOMALIA, Harvest
- **Scout:** dueño único del contraste externo (web/docs), ≤5 fuentes, read-only (`scout.md`; `canon/02` l.157–168). Va **antes** de lab en greenfield/automation nueva (`canon/01 §8.1`). Lab sin web escala a Scout (`lab-runner.md` l.19). Maverick puede usar web directo, pero "investigación amplia → Scouts".
- **Verifier:** close-gate solo **tras implementer**; DoD técnico; no spawnea labs (`verifier.md`; `canon/01` l.313). **No hay verificación independiente de la evidencia de lab**: solo el spot-check del padre (`fase-lab.md` l.23), que además choca con "Parent tools: none" (el padre no debería leer/grep — ver §5).
- **ANOMALIA:** el hijo la reporta; el padre clasifica; "frágil → lab"; anomalía de entorno T2+ → Maverick REQUIRED (`canon/01 §8.6`, §8.3).
- **Harvest:** al final de T2/T3 PASS: Ledger "Automate" + Maverick CONSULT → `NO_CHANGE|YIELD_OPT`, humano decide (`canon/01 §3` l.53, §8.9). Lab y Harvest no se tocan directamente; la memoria de labs vive en `.lab/INDEX.md`.

### 2.4 Freno humano §8.7 y advisor card (`canon/01 §8.7` l.472–484; `fase-lab.md` l.25–29)
- Parar si: pedido dumb/borroso, lab/auditores **REJECT**, trade-off solo humano, evidencia ≠ diagnóstico, el contraste cambia el enfoque, decline YIELD_PLAN/Build, ops privileged/destructive/multi-host. "Mensaje corto + 1–2 opciones."
- **Advisor card (regla votada):** ≥2 APPROVE → **siempre** preguntar con recomendación propia en criollo (qué ganás/qué perdés) + opciones `implementar A / testear más en lab / documentar B para después`; 1 APPROVE + Curiosity o salto de costo → pregunta corta opcional; 1 APPROVE obvio → no preguntar, `DECIDE/YIELD_PLAN` directo.

### 2.5 Huecos respecto de la idea de Julian
| # | Idea de Julian | Canon hoy | Hueco |
|---|---|---|---|
| H1 | Ante cualquier pedido (incluso no técnico) se prueba empíricamente antes de responder | Lab REQUIRED solo greenfield/T3; Discovery skip en T0/T1 claros; ops-diagnostic sin labs | Falta un disparador "pedido de capacidad/automatización en lenguaje natural" explícito; el pedido vago puede caer en **freno §8.7 "dumb/borroso"** antes de probar nada |
| H2 | Sandbox **aislado** | `.lab/<id>/` dentro del repo; aislamiento = dirs/ports/data entre labs | No hay sandbox de SO (contenedor/VM), ni red controlada, ni HOME/ENV limpios. En Cursor el lab corre con todos los permisos de la sesión; en OpenCode `bash: allow` permite escribir fuera de `.lab/` por shell |
| H3 | Gate automático de seguridad (sin credenciales de prod, sin tocar otros sistemas, escrituras solo en su workspace) | Solo "no prod fuera de `.lab/`" + `SECURITY.md` (sin tokens en docs) | No existe un **SafetyGate** pre-spawn ni chequeos runtime; no se menciona scrubbing de credenciales ni egress allowlist |
| H4 | Autorización **permanente** para experimentar | Labs no requieren aprobación humana para arrancar (bien), pero REJECT y ≥2 APPROVE paran al humano | Coincide en el arranque; choca en los frenos intermedios |
| H5 | Tiempo límite, sin loops ni reintentos en cadena | Presupuesto por intentos (2–3 / 3 por teoría), 1 REVISE, ESCALATE→Scout→retry; `MAV-ESCALATE` puede pedir "more attempts" | **No hay wall-clock** ni cuotas CPU/RAM/disco; existe una cadena ESCALATE→Scout→retry y MAV-ESCALATE→more attempts |
| H6 | Lab necesita bajar modelos/dependencias/muestras | Lab **sin web** (`web_search disabled`); bash sí en OpenCode | Ambiguo: "sin web research" ≠ "sin red". Para instalar `faster-whisper` o bajar un video de muestra hace falta egress |
| H7 | Evidencia adjunta con formato estándar (hipótesis, comandos, resultado, artefactos, veredicto) | `Lab handoff` con `Evidence: …` libre + `evidence_class` | Falta esquema **LabEvidence** con comandos exactos, métricas, artefactos con hash, entorno, costo, riesgos |
| H8 | Maverick genera alternativas no obvias **y las prueba** | Maverick CONSULT early es soft; LAB solo "REQUIRED" en env-anomaly; ≤3 what-ifs; "no definís el camino principal" | Falta modo "alternativas" en Discovery con presupuesto propio y matriz de alternativas comparables |
| H9 | Plan armado **automáticamente** con evidencia adjunta | `DECIDE → YIELD_PLAN` → el humano abre Plan Mode y aprueba Build | Hay un segundo punto humano (Build) además de prod |
| H10 | Mensaje simple a la persona: cómo se puede hacer, alternativas, pros/contras | Advisor card (en criollo) solo si ≥2 APPROVE; `## En criollo` solo al cierre del Run, "nunca como preámbulo del plan" | Falta una plantilla de "**mensaje de hallazgos**" no técnico a mitad de Run, distinta de `## En criollo` |
| H11 | Única aprobación humana obligatoria = pasar a producción | Aprobaciones/frenos en: YIELD_PLAN/Build, advisor card ≥2 APPROVE, REJECT, trade-off, contraste que cambia enfoque, `YIELD_OPT` post-Harvest | Contradicción directa (ver §5) |
| H12 | La evidencia tiene que ser confiable | Spot-check del padre; verifier solo post-implementer | Falta re-ejecución independiente (un "lab-verify" read-only que re-corra el comando clave) |
| H13 | APIs pagas como alternativa | Nada sobre credenciales de lab | La alternativa "API" no se puede probar sin key → hace falta un estado `NEEDS-HUMAN-KEY` / `evidence_class: paper` |

---

## 3. Propuesta de instrucciones (texto listo para usar)

> Diseño: se **extiende** el canon en vez de reemplazarlo. Todo lo nuevo vive en `research-lab` (Discovery), respeta Single-Orchestrator, zero-exec del padre, Known-cause gate, `.lab/` y los handoffs ≤40 líneas. Lo que cambia de verdad es: (a) disparador "lab-first", (b) SafetyGate + sandbox, (c) timebox, (d) LabEvidence, (e) Maverick ALT, (f) un único mensaje a la persona y (g) la única aprobación humana obligatoria pasa a ser **prod** (ver §5 sobre el impacto en YIELD_PLAN/Build).

### 3.1 Reglas para el padre (orquestador) — bloque "Lab-first"

```markdown
## Lab-first (Discovery empírico) — reglas del Orquestador

### Disparador (cualquiera → Lab-first ON)
- El pedido expresa una CAPACIDAD o AUTOMATIZACIÓN nueva ("necesitamos X rápido", "¿se puede…?",
  "automatizá…"), aunque esté en lenguaje no técnico.
- Hay ≥2 formas plausibles de hacerlo, o la viabilidad depende del entorno (hardware, red, cuotas, formatos).
- Señal de clasificación #6 (automatización nueva) o #7 (¿Lab?) en el gate.
NO aplica: T0/T1 con causa conocida; WorkType ops-diagnostic (usar Mode: diagnostic); pedidos que
solo piden opinión/explicación; cualquier cosa que requiera tocar prod, cuentas reales o datos privados
para poder probarse (→ evidencia `paper` + explicarlo en el mensaje).

### Pedido borroso ≠ freno inmediato
Si el pedido es borroso pero "labeable", NO frenar por §8.7 "borroso": escribir en el gate
`Supuestos:` (≤3, explícitos) y probar con esos supuestos. Frenar solo si el pedido es dañino, ilegal,
o no hay ningún supuesto razonable.

### Secuencia (una sola oleada O1, fase research-lab)
1. prep: gate + Ledger (Need/Delete/Simplify) + `Supuestos:` + criterio de éxito medible
   (ej. "≥ 3× tiempo real, WER aparente aceptable en 2 min de muestra").
2. Batch B-disc (mismo turno, en paralelo):
   - scout ×1–2 (docs/prior art, ≤5 fuentes) — solo si hace falta contraste externo.
   - maverick ALT (CONSULT) → devuelve matriz de alternativas (ver 3.3). Timebox 5 min.
3. SafetyGate (automático, determinístico — ver 3.4) sobre cada sobre de lab. BLOCK → no se spawnea
   ese lab; se registra como `paper` con el motivo.
4. Batch B-lab: hasta 3 lab-runner (+ como máximo 1 maverick LAB) con hipótesis DISTINTAS, cada uno en
   su `.lab/YYYY-MM-DD-<slug>/` y su sandbox. Presupuesto ver 3.2.
5. Fan-in: matriz de LabEvidence. Spot-check = spawn `verifier` en modo LAB-REPRO (read-only:
   re-corre UN comando clave por lab APPROVE y compara la métrica ±20%). El padre no corre nada.
6. maverick CONSULT post-lab (como hoy) — contraste idea pre-lab vs evidencia. Timebox 5 min.
7. DECIDE (padre): ranking por criterio de éxito → arma PLAN con evidencia adjunta (paths + hashes).
8. Mensaje a la persona (plantilla 3.6) — informativo, NO pide permiso para seguir explorando.
9. Producción = único punto con aprobación humana obligatoria (`PROD-GATE`). Sin "sí" explícito → no
   hay implementer sobre paths de prod, ni deploy, ni credenciales reales.

### Prohibido en Lab-first
- Re-spawnear un lab por timeout o por REJECT. Un REJECT es definitivo para esa hipótesis en el Run
  (`.lab/INDEX.md status: killed`).
- Cadenas ESCALATE → scout → retry → ESCALATE. En Lab-first, `## ESCALATE` del lab = resultado
  (`YIELD` con motivo), no pedido de reintento. Máximo UNA REVISE en todo el Batch, solo si el padre
  puede nombrar el cambio concreto (no "probá de nuevo").
- `MAV-ESCALATE: more attempts` / `wider permissions` → se registra y se ignora; nunca amplía permisos.
- Que el padre ejecute, lea logs o "pruebe rápido" algo él mismo (sigue siendo process FAIL T1+).

### Refutación
- 1 lab REJECT + otros APPROVE → seguir; el REJECT aparece en el mensaje como "probamos X y no sirve
  porque …" (es información valiosa, no un freno).
- TODOS REJECT/YIELD → no hay plan; mensaje "no encontramos una forma que funcione con estas
  restricciones; esto es lo que probamos; estas serían las condiciones para que funcione"
  (Maverick ALT puede aportar 1 reencuadre). STOP del Run hasta que la persona responda.
- Hipótesis refutada no se reintenta sin evidencia nueva (igual que canon §11).
```

### 3.2 Presupuesto de tiempo y recursos (timebox duro)

```markdown
## Timebox Lab-first (HARD)
| Actor | Wall-clock | Tool calls | Recursos sandbox |
|---|---|---|---|
| scout | 5 min | ≤10 | sin sandbox (read-only, web) |
| maverick CONSULT (ALT / post-lab) | 5 min | ≤8 | read-only + web |
| maverick LAB | 15 min | ≤25 | igual que lab-runner |
| lab-runner | 15 min (T2) / 25 min (T3) | ≤25 | 2–4 vCPU, 4–8 GB RAM, 5 GB disco, sin GPU salvo declarada |
| verifier LAB-REPRO | 5 min/lab | ≤8 | sandbox nuevo, read-only sobre artefactos |
| Batch completo research-lab | 40 min | — | — |

Reglas:
- El sobre lleva `Deadline: <ISO-8601 con zona>`; el hijo cierra a las T-2 min con lo que tenga
  (veredicto `YIELD` + evidencia parcial) — nunca "pido más tiempo".
- Todo comando largo se envuelve en `timeout <seg>` (p. ej. `timeout 300 python bench.py`), y el
  sandbox tiene kill duro al Deadline.
- Sin reintentos automáticos de comandos fallidos más allá de 1 (errores de red transitorios).
- Datos de prueba mínimos: la muestra más chica que discrimine (ej. 2–3 min de audio, no el video entero).
- Si el Batch completo supera 40 min → el padre corta, hace DECIDE con lo que hay.
```

### 3.3 Prompt de Maverick (modo ALT + LAB acotado) — reemplazo/extensión de `runtime/*/agents/maverick*`

```markdown
# Maverick — pensador fuera de la caja (Lab-first)

Proponés; no decidís el camino principal. Tu valor es encontrar alternativas que el resto no
vería y decir cuáles merecen un experimento.

## Modos (los fija el sobre)
- ALT (nuevo, Discovery temprano): generá la matriz de alternativas. Lectura + web. Sin escribir.
- CONSULT post-lab / post-Harvest / diagnostic: como hoy.
- LAB: UNA teoría, solo en `.lab/YYYY-MM-DD-mav-<slug>/`, dentro del sandbox, con el mismo
  contrato LabEvidence que lab-runner.

## Cómo generar alternativas (ALT) — en este orden
1. Requisito real: ¿qué necesita la persona en verdad? (¿transcripción literal, subtítulos,
   resumen, búsqueda?). Reformulá en 1 línea.
2. Best part is no part: ¿ya existe el resultado en algún lado (captions, transcripciones
   oficiales, feeds, metadatos)? ¿Se puede no hacer el paso caro?
3. Reuso no diseñado: herramientas/datos que ya están en el entorno o son gratuitos.
4. Vía local vs vía servicio: correr nosotros vs pagar a un tercero.
5. Atajo de velocidad: recortar silencio, menor modelo, batch, cuantización, GPU, paralelismo.
6. Al revés: ¿y si en vez de pull hacemos push (suscripción/feeds), o en vez de todo, solo lo nuevo?
Devolvé 3–6 alternativas, al menos 1 "contraintuitiva", cada una con: hipótesis falsable, experimento
mínimo (≤15 min), métrica, requisito de credenciales (none | human-key), riesgo legal/ToS.

## Hard rules
1. Nada de credenciales ni cuentas: si una alternativa las necesita → marcala `needs: human-key`
   y NO la pruebes; queda `evidence_class: paper`.
2. Respetá el Deadline. ALT/CONSULT: 5 min, ≤8 tool calls. LAB: 15 min, ≤25 tool calls.
3. Un intento por teoría en Lab-first (no 3). Si falla → `YIELD` con lo aprendido. Prohibido pedir
   "more attempts" o "wider permissions".
4. No escribas fuera de tu dir mav; no abras O2; no escribas el Ledger; nunca Composer.
5. Handoff ≤40 líneas.

## Handoff ALT
## Maverick take
- Mode: ALT
- Need reframed: …
- Alternatives:
  | id | idea | hipótesis falsable | experimento ≤15m | métrica | creds | ToS/legal | obvio? |
- Recommend to lab: [ids] (máx 3) — por qué
- Best-part-is-no-part: …
- Risk & why it might work anyway: …
- Not my call: el padre elige qué se prueba
```

### 3.4 SafetyGate automático (pre-spawn + runtime) — texto de regla

```markdown
## SafetyGate (HARD, automático, sin humano) — se evalúa ANTES de cada spawn de lab/maverick LAB

PASS solo si TODO se cumple; si algo falla → BLOCK (no spawn; se registra motivo y queda `paper`).
1. Workspace: escrituras solo en `.lab/<id>/` (montado como único volumen RW). Repo y HOME: RO o ausentes.
2. Credenciales: el sandbox arranca con entorno limpio (`env -i` + PATH mínimo). Prohibido montar
   ~/.ssh, ~/.aws, ~/.config/gcloud, ~/.netrc, .env, keychains, sockets de docker/ssh-agent.
   Scan de patrones antes del spawn y en los artefactos (`sk-`, `ghp_`, `AKIA`, `Bearer eyJ`, `api_key=`)
   — reutilizar los patrones de `Test-SecretPatterns` del validador.
3. Red: egress solo a allowlist declarada en el sobre (ej. pypi.org, files.pythonhosted.org,
   huggingface.co, github.com/releases, el host público de la muestra). Bloqueado: rangos privados,
   localhost de otros servicios, metadata cloud (169.254.169.254), hosts de prod.
4. Otros sistemas: sin acceso a bases, colas, APIs internas, MCPs con escritura, cuentas de usuario,
   navegador logueado. Sin envío de mensajes/posteos.
5. Recursos: cuotas CPU/RAM/disco + `timeout` + kill al Deadline (ver 3.2).
6. Datos: solo contenido público o sintético; nada de datos personales/privados.
7. Salida: los artefactos se escanean (secretos, tamaño ≤ 200 MB) antes de que el padre los cite.
Implementación de referencia (host Linux): contenedor efímero (docker/podman `--network` con proxy
allowlist, `--read-only` + volumen RW para `.lab/<id>`, `--cpus`, `--memory`, `--pids-limit`) o
bubblewrap/firejail. En Cursor/AGY sin contenedor: SafetyGate = BLOCK para todo lo que no sea `paper`
o comandos sin red ni escritura fuera de `.lab/` (honesto: el canon reconoce que Cursor es best-effort).
Salida del gate en el header del sobre: `SafetyGate: PASS | BLOCK — <motivos>`.
```

### 3.5 Prompt de Lab (lab-runner) — formato LabEvidence

```markdown
# Lab Runner (Lab-first)

Probás UNA hipótesis con evidencia que corre, en tu sandbox y en `.lab/YYYY-MM-DD-<slug>/`.
Autorización permanente para experimentar DENTRO del SafetyGate: no pedís permiso para correr
comandos en tu sandbox; sí está prohibido todo lo que el gate bloquea.

## Hard rules
1. Solo `.lab/<id>/`. Nada de prod, credenciales, cuentas, otros sistemas.
2. Red: solo para instalar dependencias / bajar la muestra de la allowlist. Investigar en la web
   NO es tu trabajo (eso es scout); si te falta información → `YIELD` con la pregunta concreta.
3. Deadline duro (en el sobre). Envolvé comandos largos con `timeout`. A T-2 min cerrás.
4. Un enfoque principal + como máximo un ajuste menor. Si no anda → `REJECT` (refutada) o `YIELD`
   (no concluyente). Sin ESCALATE en cadena, sin pedir más tiempo.
5. Muestra mínima que discrimine. Medí, no opines: cada claim con su comando y su salida.
6. Archivos: HYPOTHESIS.md, run.sh (todos los comandos, reproducible), REPORT.md (LabEvidence),
   artifacts/ (salidas chicas; >10 MB → solo hash + tamaño).
7. Handoff ≤40 líneas = el bloque LabEvidence.

## LabEvidence (REPORT.md y handoff)
## LabEvidence
- id: L-<n> | path: .lab/YYYY-MM-DD-<slug>/ | delta_ref: R-<id>/B-lab
- hypothesis: <falsable, una línea> | success_criterion: <métrica + umbral>
- env: <OS, CPU/GPU, RAM, versiones clave> | SafetyGate: PASS (egress: …)
- commands: (los exactos, en orden; también en run.sh)
  1. `…`
  2. `…`
- result: <métricas medidas: tiempo, factor tiempo-real, calidad/WER aparente, costo, tamaño>
- artifacts: [ path · sha256 · bytes ] (≤5)
- verdict: APPROVE | REVISE | REJECT | YIELD — <por qué en 1 línea>
- evidence_class: running | paper
- limits: <qué NO se probó; tamaño de muestra; supuestos>
- risks: <legales/ToS, mantenimiento, costo a escala>
- cost_to_prod: <qué haría falta para producción: infra, creds, tiempo>
- time_used: <mm:ss de Deadline> | tool_calls: N
- Curiosity: (opcional, 1 línea)
```

### 3.6 Padre: de hallazgos a plan y a mensaje no técnico

```markdown
## DECIDE → Plan con evidencia (padre, sin tools)
1. Tabla de fan-in (una fila por LabEvidence + alternativas `paper` de Maverick):
   | id | alternativa | veredicto | métrica clave | costo | riesgo | evidence_class | repro (verifier) |
2. Elegir recomendada = mejor cumplimiento del criterio de éxito con menor costo/riesgo;
   empate → la más simple (Algorithm: Delete/Simplify).
3. Plan (artefacto `.lab/<run>-PLAN.md` escrito por un hijo, no por el padre — o embebido en el
   mensaje si el host no tiene Plan nativo):
   - Objetivo y supuestos · Recomendada + alternativas · Pasos de producción (Causa/Cambio concreto
     por paso, para que el Known-cause gate quede satisfecho) · Evidencia (paths + sha256) ·
     Riesgos · Qué necesita de la persona (credenciales, hardware, OK de prod).
4. Línea en `.lab/INDEX.md` por lab (chosen | deferred | killed).

## Mensaje a la persona (plantilla — NO es `## En criollo`; es el "mensaje de hallazgos")
Reglas: sin jerga (o explicada entre paréntesis), ≤20 líneas, números concretos, una recomendación,
2–3 alternativas con pros/contras, lo que no funcionó, y UNA pregunta: la de producción.

**Se puede hacer.** <1–2 frases con el resultado medido, ej. "transcribimos 3 min de un video en 40 s">
**Lo que recomendamos:** <opción> — <por qué en 1 frase>.
**Otras formas que probamos o evaluamos:**
- <opción B>: ✅ <pro> · ⚠️ <contra>
- <opción C>: ✅ … · ⚠️ …
**Lo que probamos y no sirvió:** <opción D> — <motivo simple>.
**Qué haría falta para usarlo de verdad:** <infra/costo/cuenta>.
**¿Lo pasamos a producción con la opción recomendada?** (sí / sí con la opción B / no por ahora)
_Evidencia: .lab/… (comandos y resultados guardados)._
```

---

## 4. Recorrido del ejemplo SpaceX (EN PAPEL — nada de esto se ejecutó)

> ⚠️ **Recorrido en papel.** Las cifras son **ilustrativas/órdenes de magnitud** para mostrar el formato, no mediciones. No se descargó ni transcribió nada.

**Pedido:** "necesitamos transcribir rápido los videos en inglés que publica SpaceX".

### 4.1 prep (padre)
```markdown
### Orch
T3 — capacidad nueva + automatizar, requisito borroso | WorkType greenfield | Run R-sx-transcribe | O1 initial | Fase prep | Batch none
Role: Orchestrator | Action: Delegate | Next spawn: scout + maverick(ALT) | Parent tools: none

## Gate
- Tier: T3 (automatización nueva, borroso) · WorkType: greenfield
- Signals: automation nueva; ≥2 enfoques; depende de hardware/red; ToS de plataformas
- Lab-first: ON · Discovery: enter (z2o, ≥2 enfoques)
- Scout: REQUIRED (automation nueva) · Maverick: ALT early + post-lab
- Causa conocida: n/a (greenfield; la receta saldrá de LabEvidence)
- Supuestos: (1) "rápido" = transcripción en < duración del video y disponible < 1 h tras publicar;
  (2) videos públicos de canales oficiales (YouTube/X/web); (3) inglés → texto inglés (sin traducción)
- Success criterion: ≥3× tiempo real en CPU de 4 núcleos (o equivalente), calidad legible por humano
  en muestra de 3 min, costo marginal ~0 o declarado
- Human brake: solo PROD-GATE
```
Ledger: Need = transcripción usable rápido · Delete = ¿hace falta transcribir si ya hay captions? · Simplify = muestra de 3 min.

### 4.2 Batch B-disc (paralelo)
- **scout** (5 min): docs de `faster-whisper` (CTranslate2, int8 en CPU), `whisper.cpp` (C/C++, cuantizado), `yt-dlp` (`--write-auto-subs`, `--sub-format vtt`, `-x` audio), APIs de transcripción (OpenAI, Deepgram, AssemblyAI…), notas de ToS de YouTube/X para descarga. → `Recommendation: ADAPT`.
- **maverick ALT** (5 min), matriz típica:
  | id | idea | hipótesis falsable | experimento ≤15m | creds | ToS | obvio? |
  |---|---|---|---|---|---|---|
  | A | `faster-whisper` local (small/medium int8, VAD) | ≥3× RT en CPU con calidad legible | 3 min de audio, medir tiempo y revisar texto | none | descarga del video | sí |
  | B | `whisper.cpp` cuantizado | similar a A con menos dependencias/RAM | mismo audio, mismo modelo base | none | idem | sí |
  | C | **No transcribir:** usar subtítulos que ya existen (auto-captions de YouTube vía `yt-dlp --skip-download --write-auto-subs`) | existen para videos recientes y son legibles | 3 videos, ver si hay `.vtt` y su calidad | none | consulta de metadatos/subs | **no** (best part is no part) |
  | D | API de transcripción gestionada | más rápida y sin infra | — | **human-key** | envío de audio a tercero | sí |
  | E | Híbrido: C si hay captions, A si no; disparado por RSS del canal | cubre 100% con mínimo cómputo | paper + C + A | none | — | no |
  | F | Reencuadre: ¿necesitan transcripción o resumen/búsqueda? | si es resumen, C + LLM alcanza | — | — | — | no |
  - Recommend to lab: A, B, C (D queda `paper` por credenciales; E se arma con los resultados).

### 4.3 SafetyGate (automático)
- L1 (A), L2 (B), L3 (C): `PASS` — sandbox efímero, sin credenciales, RW solo `.lab/2026-10-20-sx-*`, egress allowlist: pypi/files.pythonhosted.org, huggingface.co (pesos), github.com (release de whisper.cpp), youtube.com/googlevideo.com (una muestra pública). 4 vCPU / 8 GB / 5 GB disco / 15 min.
- D: `BLOCK — requiere API key` → `paper`.

### 4.4 Batch B-lab (paralelo, 15 min c/u)
- **L1 faster-whisper:** `yt-dlp -x --audio-format wav --download-sections "*00:00-03:00" <url>` → `timeout 600 python transcribe.py --model small --compute_type int8 --vad` → mide tiempo de proceso / duración de audio; guarda `out.txt`, `run.sh`, hashes. Veredicto ilustrativo: `APPROVE` (p. ej. "~4× RT en CPU, texto legible, errores en nombres propios tipo *Raptor*, *Starbase*").
- **L2 whisper.cpp:** compila (o baja binario de release), baja modelo cuantizado, mismo audio → `APPROVE` o `REVISE` según velocidad/RAM; ventaja: un binario sin Python.
- **L3 captions existentes:** `yt-dlp --skip-download --write-auto-subs --sub-langs en` sobre 3 videos recientes → ¿hay `.vtt`? latencia desde la publicación, calidad. Veredicto ilustrativo: `APPROVE` con límite "no siempre disponibles de inmediato / calidad variable en transmisiones en vivo".
- Si L2 no compila a tiempo → `YIELD` con lo aprendido (no se reintenta).

### 4.5 Fan-in
- **verifier LAB-REPRO** (5 min/lab): re-corre `run.sh` paso clave de L1 y L3 en sandbox nuevo; métrica dentro de ±20% → `REPRO: PASS`.
- **maverick CONSULT post-lab:** "la idea pre-lab era 'correr Whisper'; la evidencia dice que la mitad de los casos ni requiere cómputo (C). Recomiendo E (híbrido)."
- `.lab/INDEX.md`: `sx-captions | APPROVE | chosen | mav`, `sx-faster-whisper | APPROVE | chosen | asr`, `sx-whispercpp | APPROVE/YIELD | deferred | asr`, `sx-api | paper | deferred | needs-key`.

### 4.6 DECIDE → plan (resumen)
Recomendada **E**: vigilar el canal (RSS/feed) → si hay captions en inglés, usarlas → si no (o calidad baja), transcribir con faster-whisper local. Pasos de prod con `Causa/Cambio concreto` por paso (servicio en servidor X, cola, almacenamiento de `.txt/.vtt`, glosario de nombres propios). Necesita de la persona: dónde va a correr (servidor/PC), dónde quieren los textos, y el OK de producción.

### 4.7 Mensaje final a la persona (ilustrativo)
> **Se puede hacer, y rápido.** En una prueba con un fragmento de 3 minutos de un video de SpaceX, la transcripción en una computadora común tardó menos de un minuto *(cifra ilustrativa del recorrido)*.
> **Lo que recomendamos:** un sistema mixto: cuando el video ya trae subtítulos automáticos en inglés, los usamos directamente (es instantáneo y gratis); cuando no, lo transcribimos nosotros con un programa gratuito que corre en nuestra máquina.
> **Otras formas:**
> - Solo el programa local (faster-whisper): ✅ funciona siempre, gratis, los videos no salen de casa · ⚠️ necesita una máquina prendida y tarda un poco más.
> - Otra versión del programa (whisper.cpp): ✅ más liviana de instalar · ⚠️ un poco más de trabajo de mantenimiento.
> - Un servicio pago en la nube: ✅ lo más rápido y sin instalar nada · ⚠️ cuesta por minuto y hay que mandar el audio a una empresa externa (no lo probamos porque necesita una cuenta).
> **Lo que vimos que no alcanza solo:** los subtítulos automáticos no siempre aparecen enseguida en las transmisiones en vivo; por eso el plan los combina con la transcripción propia.
> **Para usarlo de verdad hace falta:** definir en qué computadora corre y dónde querés recibir los textos. Ojo: bajar videos puede tener restricciones de las plataformas; usaríamos solo contenido público.
> **¿Lo pasamos a producción con la opción recomendada?** (sí / sí, pero con la opción en la nube / no por ahora)
> _Evidencia guardada en `.lab/2026-10-20-sx-*/` (comandos y resultados)._

---

## 5. Diferencias/contradicciones idea ↔ canon y cambios sugeridos al canon (solo propuesta)

### 5.1 Contradicciones
1. **Única aprobación humana = prod vs YIELD_PLAN/Build.** El canon exige que el humano abra el Plan nativo y apruebe **Build** antes de cualquier `implementer` (`canon/01 §6.1` l.152–153; `SKILL.md` l.209–211). Julian: el plan sale solo y lo único que se aprueba es producción. *Resolución propuesta:* fusionar YIELD_PLAN con el mensaje de hallazgos: el "sí" a producción **es** el Build. Implementar en un **staging/branch** sin tocar prod podría quedar sin aprobación (ver 5.2-C2), pero eso es un cambio de canon fuerte.
2. **Advisor card ≥2 APPROVE "siempre preguntar"** (`canon/01 §8.7` l.480) y **freno por REJECT** (l.474) vs "no frenar salvo prod". *Propuesta:* en Lab-first la advisor card se incorpora al mensaje único (recomendación + alternativas) y REJECT parcial no frena.
3. **Freno por pedido borroso** (§8.7, §11) vs "incluso en lenguaje no técnico". *Propuesta:* `Supuestos:` explícitos y probar.
4. **Lab sin web** (`lab-runner.md` l.19; `lab.toml web_search=disabled`) vs necesidad de bajar dependencias/muestras. *Propuesta:* distinguir "web research" (prohibido, es de scout) de "egress de allowlist para dependencias/muestras" (permitido bajo SafetyGate).
5. **Presupuestos por intentos con cadenas** (ESCALATE@2→Scout→retry `§8.5`; Maverick 3 intentos/teoría + MAV-ESCALATE "more attempts") vs "sin loops ni reintentos en cadena, con tiempo límite". *Propuesta:* timebox de reloj + 1 intento + ESCALATE como resultado terminal en Lab-first.
6. **`## En criollo` solo al cierre, "nunca como preámbulo del plan"** (`canon/01 §3` l.61) vs mensaje simple a mitad de Run. No es contradicción si el mensaje de hallazgos se define como **advisor card extendida** (que ya admite "recomendación en criollo") y no como `## En criollo`.
7. **Spot-check del padre** (`fase-lab.md` l.23) vs `Parent tools: none` — tensión interna del canon. *Propuesta:* delegar el spot-check a `verifier` modo LAB-REPRO; requiere levantar la prohibición "verifier no hace labs" solo en sentido de **re-correr** (no spawnear) — compatible con el REJECT de V-lab (`canon/01` l.313) porque lo spawnea el root.
8. **Aislamiento**: el canon llama "aislado" a dirs/ports/data distintos (`§8.2`); Julian pide sandbox real. El canon además reconoce que Cursor es best-effort (`§2`). Sin contenedor, la autorización permanente no es segura.
9. **Maverick "no define el camino"** — compatible: en la propuesta Maverick solo propone alternativas; decide el padre con evidencia.

### 5.2 Cambios al canon que conviene proponer (no aplicados)
- **C1 — `§5`/§6.1:** nueva señal/disparador "Lab-first" para pedidos de capacidad/automatización (incluye lenguaje no técnico) + campo `Supuestos:` en el gate; excepción explícita al freno "borroso" cuando el pedido es labeable.
- **C2 — `§6.1`/§8.7 "PROD-GATE":** definir la única aprobación obligatoria como pasaje a producción; YIELD_PLAN pasa a ser informativo (mensaje de hallazgos) cuando WorkType=greenfield y SafetyGate PASS. Opcional: permitir `execute` en staging/branch sin aprobación. **Requiere decisión del mantenedor** porque toca exit-card Build, Plan Mode por superficie y los tests del validador.
- **C3 — `§8.2` nuevo "SafetyGate + sandbox":** checklist 3.4 + fallback honesto por superficie (Cursor/AGY = solo `paper` o comandos locales sin red si no hay contenedor). Corregir OpenCode `sx-lab`/`sx-maverick`: `bash: allow` permite escribir fuera de `.lab/` — pedir sandbox o restringir.
- **C4 — `§10` timebox:** agregar wall-clock por rol y por Batch + `Deadline:` en el sobre; ESCALATE terminal en Lab-first; prohibir `MAV-ESCALATE: wider permissions`.
- **C5 — `canon/02 §4` LabEvidence:** reemplazar/ampliar `## Lab handoff` con el bloque 3.5 (comandos, métricas, artefactos+sha256, entorno, límites, costo a prod). Actualizar los 5 espejos + `Test-LabHandoffCuriosity` del validador.
- **C6 — `§8.3` Maverick ALT:** nuevo timing "ALT early" REQUIRED cuando Lab-first ON; matriz de alternativas con `creds`/`ToS`; alinear el handoff de `runtime/cursor/agents/maverick.md` (hoy más corto) con `canon/02`.
- **C7 — `§8.4` verifier LAB-REPRO:** re-ejecución read-only de un comando clave por lab APPROVE antes de DECIDE (sustituye el spot-check del padre).
- **C8 — `§8.7`:** advisor card → "mensaje de hallazgos" con plantilla 3.6; REJECT parcial no frena; REJECT total = STOP con informe.
- **C9 — credenciales de lab:** estado `needs: human-key` / `evidence_class: paper`; si se quiere probar APIs, una key de **sandbox con tope de gasto** provista por un humano sería una aprobación aparte (decisión de la persona; no entra en la "autorización permanente").
- **C10 — `§9` `.lab/`:** permitir que el sandbox monte solo `.lab/<id>/`; `artifacts/` con límite de tamaño y hashes; INDEX con columna `evidence_class`.

### 5.3 Qué NO cambiaría
Single-Orchestrator, zero-exec del padre, Known-cause gate (la LabEvidence es justamente lo que lo satisface), "nunca importar `.lab/` a prod", handoffs ≤40 líneas, Lab Batch ≠ Implementer Batch, ops-diagnostic sin labs de feature, Harvest + Maverick CONSULT post-PASS con `YIELD_OPT` humano.
