# Gentle AI + Engram: qué copiar para el verificador del modo código

> Research de solo lectura, 2026-10-20 (hora ART). Clones de lectura en `<tmp>/gentle-lab/` con `--depth`:
> `gentle-ai` @ `bc27d9e` (2026-10-20, tag más reciente v4.2.0) y `engram` @ `41f1254` (release v3.5.1).
> orquestador-sx: clon RO `<tmp>/orq-sx-ro` (VERSION 1.5.0). No se instaló nada global ni se tocó `~/.config`.
> Lo marcado **[verificado en lab]** se corrió en `<tmp>/gentle-lab` con `HOME`/`ENGRAM_DATA_DIR` aislados.

## TL;DR

- **Confirmado:** Gentle AI es del ecosistema **Gentleman Programming** (Alan Buscaglia, argentino). Repo `Gentleman-Programming/gentle-ai`, Go, MIT, ~7.9k★, muy activo (commits diarios, v4.2.0 el 2026-10-15). Engram es un repo hermano (`Gentleman-Programming/engram`, MIT, ~7.5k★) y es "la capa de memoria de Gentle-AI", usable standalone.
- **Ojo, cambió:** el famoso flujo **SDD (spec-driven) quedó retirado en v4.0.0**. Hoy es **ODD** (Organic Driven Development) + **RDD** (Receipt-Driven Development, la revisión) + **Judgment Day** (doble juez ciego, opcional).
- **La pieza que vale oro para nosotros no es RDD** (≈76k líneas de Go para una máquina de estados de revisión que su propia auditoría llama sobrediseñada). Es el **prompt del verificador independiente** (`gentle-ai-verify`) y sus reglas: probes derivadas del spec verbatim (no de los tests del writer), comparación contra baseline, invariantes de datos por hash, copia scratch aislada, veredicto por cada `S#`, severidad reproducible a baseline, corrección acotada y probes devueltas como tests de regresión.
- **Recomendación:** opción **(b)+(c)**: mantener orquestador-sx como esqueleto (tiers/oleadas/gates), **reemplazar el verifier por uno estilo Gentle** + gate de riesgo de 6 ítems + 4R con refuter solo en riesgo alto; Engram como memoria **opcional** detrás de un adaptador con timeout. No adoptar Gentle AI entero (no soporta Grok CLI, toca configs globales de los CLIs, telemetría opt-out, RDD solo en Claude Code/Codex/OpenCode/Pi).

---

## 1. Qué es Gentle AI

| Ítem | Dato | Fuente |
|---|---|---|
| Qué es | "The deterministic engineering environment for the AI agent you already use": instalador/configurador en Go que inyecta memoria (Engram), workflow (ODD), revisión (RDD), skills, MCP (Context7), CodeGraph, deny-list de seguridad, personas, en el agente que ya usás. **No instala el agente.** | [README](https://github.com/Gentleman-Programming/gentle-ai) |
| Autor | Alan Buscaglia (Gentleman Programming). Marcas "Gentle AI™" y "Engram™" registradas por él: MIT cubre el código, **no** el uso del nombre. | README, `TRADEMARKS.md` |
| Licencia | MIT (repo). Ojo: algunas skills declaran `license: Apache-2.0` en frontmatter (p. ej. `judgment-day`). Si copiamos texto, mantener aviso de copyright/licencia. | `LICENSE`, [judgment-day/SKILL.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/skills/judgment-day/SKILL.md) |
| Actividad | 7874★, 849 forks, 1011 issues+PR abiertos, push 2026-10-20; releases v4.1.0/v4.1.1 (12-oct) y v4.2.0 (15-oct). | GitHub API `repos/Gentleman-Programming/gentle-ai` (consultado hoy) |
| Agentes (17) | Pi, OpenCode, Claude Code, Codex, Cursor, VS Code Copilot, Gemini CLI, Kilo Code, Kimi Code, Kiro IDE, Qwen Code, Hermes, Antigravity, Windsurf, OpenClaw, Trae, Conductor. **Grok CLI: no** (solo aparece "grok" como patrón de ID de modelo en telemetría). | [docs/agents.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/agents.md), `internal/telemetry/runtime.go:201` |
| Capacidades desiguales | RDD (revisión nativa) solo en **Claude Code, Codex, OpenCode y Pi**. Cursor recibe solo Judgment Day (`jd-judge-a/b`, `jd-fix-agent`), no los `review-*`. Gemini "experimental". | [docs/review-integration.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/review-integration.md) §Cross-repository, docs/agents.md |
| Instalación | `brew install gentleman-programming/tap/gentle-ai` · `curl …/scripts/install.sh \| bash` · `go install github.com/gentleman-programming/gentle-ai/v4/cmd/gentle-ai@v4.1.1`; luego `gentle-ai` (TUI), `gentle-ai doctor` (RO), `sync --dry-run`, `install --scope=workspace`. Snapshotea configs antes de cada escritura. | README §Get started, [docs/usage.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/usage.md) |
| Telemetría | Anónima, **opt-out** (`DO_NOT_TRACK`, `GENTLE_AI_TELEMETRY`; en `CI` se deshabilita). | [docs/telemetry.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/telemetry.md) |
| Hermano | **Gentle Shell** (`gentle-shell`, TypeScript, Pi-native, 1.4k★): el runtime "completo" con subagentes y revisión. | GitHub API `repos/Gentleman-Programming/gentle-shell` |

## 2. Engram

**Qué es:** memoria persistente para agentes. Un binario Go, SQLite + FTS5 (`~/.engram/engram.db`, configurable con `ENGRAM_DATA_DIR`), expuesto por **MCP stdio**, **HTTP** (`engram serve`, puerto 7437), **CLI** y **TUI**. Sin Node/Python/Docker. MIT. ([README](https://github.com/Gentleman-Programming/engram), [DOCS.md](https://github.com/Gentleman-Programming/engram/blob/main/DOCS.md))

**Cómo funciona:**
- El **agente decide** qué guardar (`mem_save` con título/tipo/contenido What/Why/Where/Learned), no un firehose de tool calls. Recuperación progresiva en 3 capas: `mem_search` (compacto) → `mem_timeline` → `mem_get_observation`. ([docs/ARCHITECTURE.md](https://github.com/Gentleman-Programming/engram/blob/main/docs/ARCHITECTURE.md))
- Sesiones con resumen de cierre (`mem_session_summary`: Goal/Discoveries/Accomplished/Next Steps/Files). `topic_key` permite upserts de un mismo tema (Gentle lo usa para `odd/<feature>/tasks` y `review/<slug>/ledger`).
- Proyecto = remote de git normalizado (fallback: nombre de dir). Conflictos entre memorias: `mem_judge`/`memory_relations`.
- SQLite en WAL, busy timeout 5000 ms. ([DOCS.md §SQLite Configuration](https://github.com/Gentleman-Programming/engram/blob/main/DOCS.md))
- Compartir: `engram sync` exporta chunks a `.engram/` para commitear en git (excluye prompts por defecto); **cloud opcional** self-hosted (Postgres, token/JWT, allowlist de proyectos).
- Integración: `engram setup <agent>` para Claude Code, OpenCode, Gemini CLI, Codex, Antigravity CLI, Cursor, Windsurf, Qwen, Kiro, Kimi, VS Code… o `engram mcp` para "cualquier agente MCP". ([docs/AGENT-SETUP.md](https://github.com/Gentleman-Programming/engram/blob/main/docs/AGENT-SETUP.md))

**[verificado en lab]** Compilé `engram` 3.5.1 desde fuente (`go build`, ~26 s) en `<tmp>/gentle-lab/bin/engram`, con `HOME` y `ENGRAM_DATA_DIR` en `<tmp>/gentle-lab`:
`engram save … --project codemode-lab` → `Memory saved: #1`; `engram search "verifier probes"` lo encuentra; `engram mcp` responde `tools/list` con **26 tools** (`mem_save`, `mem_search`, `mem_context`, `mem_session_summary`, `mem_judge`, …). La DB quedó solo en `<tmp>/gentle-lab/engram-data/`.

## 3. Flujo y sistema de verificación de Gentle AI

### 3.1 ODD (workflow, prompt-level)
Protocolo en 7 pasos: Authorize → Explore → Resolve uncertainty → Classify (small/large por **"¿se puede retomar con el pedido + `git diff`?"**, nunca por cantidad de archivos) → Track (feature doc `odd/tasks/<f>.md` + espejo Engram) → Implement task by task → Close. ([docs/usage.md §ODD](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/usage.md))
- **Feature doc** con `## Specs` numeradas `S#` que **citan textual** strings, errores y ejemplos del usuario; `## Tasks` (ID, `S#`, ruta, commit); `## Log` con `L1` = pedido verbatim. Los workers reciben **referencia** al doc, nunca una paráfrasis. Su bench: spec de 73 líneas con 26 checks ocultos, con handoffs parafraseados quedaban 13 fallando (23/26 tras 2 rondas); pasándolo por referencia pasó (README §Measured, cita gentle-shell#1718; n=1, no lo verifiqué).
- **Delegar solo con razón nombrada** (exploración que excede ~3 calls/10k tokens, writers paralelos con superficies disjuntas, backstop de contexto, **verificador independiente para riesgo alto**). Por defecto, inline. ([docs/trigger-rules.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/trigger-rules.md))

### 3.2 TDD
Test-first **por defecto** cuando hay test runnable determinístico y resultado esperado claro: RED observado → GREEN → REFACTOR; si no, explicar la excepción y correr checks funcionales igual. Regla de cobertura mínima y precisa: **un RED por regla pedida**, **un test por cada comando/opción existente tocado** que pruebe que su conducta previa sigue igual, y nada más. Antes de cerrar: correr los comandos existentes que comparten código contra baseline (`git stash`/copia de HEAD) y contra el cambio comparando **stdout, stderr y exit code**. "Strict TDD" es un modo configurable aparte. ([docs/intended-usage.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/intended-usage.md), docs/usage.md §Tests, docs/agents.md)

### 3.3 Verificación proporcional al riesgo (quién y cuándo)
`internal/assets/skills/_shared/odd-orchestrator-sections.md` ("Delegated Verification Gate"):
- **passive** (docs/comentarios): readback estructural.
- **medium** (cambio de conducta con tests focalizados): **auto-verificación del writer** corriendo los comandos `## Verification` que autorizó el padre y reportando `<comando>: <resultado observado>`.
- **high**, **solo si el padre nombra uno de 6 ítems**: (1) datos almacenados/efectos irreversibles, (2) seguridad, (3) contratos que otros consumen, (4) concurrencia, (5) delivery/entorno, (6) **no hay test que atrape una regresión** → + **verificador independiente** fresco, read-only, sin el contexto del writer.
- Siempre: **spot-check del padre** (re-correr un comando reportado).
- **Corrección acotada:** 1 batch que arregla todos los blockers + 1 recheck limitado a esos blockers; 2ª corrección solo si el mismo blocker sigue; hallazgos nuevos nunca abren ronda → "Needs your decision".
- `gentle-ai review assess --json` da `risk` determinístico (passive/medium/high) a partir del diff; el agente solo puede **subir** el tier con `--escalate-item <1-6> --escalate-reason`. Falla de assess ⇒ tratar como high. ([docs/review-integration.md §assess](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/review-integration.md))

### 3.4 El verificador (`gentle-ai-verify`), lo más copiable
Fuente: [`internal/assets/opencode/agents/gentle-ai-verify.md`](https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/opencode/agents/gentle-ai-verify.md). Resumen fiel:
1. **"Verify the request, not the writer's work."** Los tests y ejemplos del writer **no son evidencia**: "a writer's test can lock a bug in".
2. **Probes propias** desde el pedido verbatim y cada `S#/AC#`: positivos, negativos, bordes (vacío, cero, duplicado, malformado, fuera de rango), mensajes de error y exit codes exactos.
3. **Invariantes:** hash del archivo de datos antes/después de cada comando rechazado (debe quedar idéntico); comandos preexistentes producen la **misma salida que en el baseline** salvo que el pedido los cambie.
4. **Interacciones:** datos nuevos fluyendo por reportes/totales/exports/imports existentes.
5. **Build y scope:** typecheck/build; marcar todo archivo o conducta fuera de alcance.
6. **Veredicto por CADA spec:** met / unmet / not implemented, con evidencia; "unverified" cuenta como unmet. Pasar tests nunca prueba un `S#` cuyo ejemplo no se ejecutó.
7. **Probes durables:** devuelve las probes como **tests de regresión listos para commitear** (path, contenido, `S#`), que el padre le da al writer; el verificador nunca escribe.
8. **Severidad:** blocker = defecto causado por el cambio o spec incumplida, **reproducido con input realista**; antes de llamarlo blocker se **reproduce en baseline** (si ya estaba → advisory preexistente). Ignorar en silencio una opción pasada explícitamente con exit 0 = siempre blocker. Cambio no pedido en salida/errores de un comando existente = blocker.
9. **Aislamiento:** copia scratch con `mktemp -d` fuera del workspace (sin `.git`, sin worktree/stash/symlink), `HOME` y `TMPDIR` dentro del scratch, **sin red ni instalaciones**, `git status` antes/después; toda mutación inesperada = blocker.
10. Handoff ≤~2k tokens: comandos exactos, resultados observados, `path:line`, veredicto por spec, blockers, no verificado. "Never claim a command ran … without observed output."
11. TDD: no inferir RED porque existe el archivo de test; no declarar GREEN sin ejecución observada.

### 3.5 RDD (revisión con "recibo") y 4R
- Se **congela el candidato** (lineage/revision/target, árboles inmutables desde objetos git, hashes); los revisores solo ven árboles congelados, nunca el worktree vivo. El tier decide las lentes: passive = 0, medium = 1 (`review-reliability`), high = **4R** (Risk, Resilience, Readability, Reliability). ([docs/review-integration.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/review-integration.md))
- Lentes read-only, `tools: []`, con **precision gate** ("reportá solo lo que defenderías con evidencia concreta; ante la duda, callate") y ledger con `id/lens/location/severity/status/evidence`. ([review-reliability.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/claude/agents/review-reliability.md))
- Solo BLOCKER/CRITICAL pasan por un **refuter** (`corroborated | refuted | inconclusive`; malformado ⇒ inconclusive). Revisión estándar: 1 refuter para toda la lista; full-4R: 3 refuters (correctness, exploitability, reproducibility) con **voto 2 de 3**. En Codex el refuter puede correr **un** comando reproductor en scratch sin red. ([review-refuter.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/claude/agents/review-refuter.md))
- Máximo **una** corrección acotada; la aprobación **no autoriza delivery** (commit/push/PR siguen siendo humanos). Presupuestos operativos históricos: 25/120/180 s.
- **Su propia auditoría** (2026-07-21): el núcleo de confianza es coherente, pero el sistema completo es "a distributed state machine whose correct recovery depends on knowledge that ordinary users and agents cannot reasonably possess"; "Overengineered: Selectively". ([docs/audits/2026-07-21-rdd-system-audit.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/audits/2026-07-21-rdd-system-audit.md))
- **Judgment Day** (a pedido): 2 jueces ciegos en paralelo sobre un target inmutable; solo se arreglan severos **confirmados por ambos**; 1 solo juez ⇒ "suspect", contradicción ⇒ humano; ≤2 rondas de fix + re-juicio sobre ledger congelado + delta; veredicto `APPROVED | ESCALATED`. ([judgment-day/SKILL.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/skills/judgment-day/SKILL.md))

### 3.6 Cómo testean a los agentes
"A model asserting 'I verified it, it passes' is prose, not proof": la ceremonia (congelar, hashear, emitir recibo) se mudó del prompt al CLI. E2E con **agente real (OpenCode pineado) + CLI real + repo git real, pero con el razonamiento del modelo guionado**: sin API keys ni costo por token en CI. ([docs/testing-agents-deterministically.md](https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/testing-agents-deterministically.md))

## 4. Comparación con orquestador-sx y con nuestra base

### 4.1 Qué hace el verifier de orquestador-sx hoy
- `runtime/cursor/agents/verifier.md`: "DoD técnico only"; regla 3 **"Run DoD commands from envelope"**; read-only; 2 fallos ⇒ `ESCALATE`; handoff `Verdict / Commands run / Evidence / Gap inventory`.
- `canon/02-ROLES-HANDOFFS-GATES.md:241-256`: en FAIL, **inventario completo** de gaps → el root abre **una** O2; V-direct opt-in; Verifier-B clean-room con paquete ciego (sin la conclusión de Verifier-A).
- `runtime/skills/orchestrator/references/fase-verify.md`: verifier **REQUIRED** tras cualquier implementer T2/T3; spot-check HARD del padre; VLH después de PASS técnico si es user-facing (contrato B4).
- `canon/09-VERIFY-CHECKLIST.md` §F/§G: VLH B4 (`verdict/evidence_class/serves_ask`, nunca FAIL+yes), circuit breaker de diagnóstico (≥2 FAIL mismo Failure-ID → Verifier-B → adjudicator → ≤2 pasadas finales → paquete humano).
- `canon/01-METHODOLOGY-SPACEX.md` §8.7 (freno humano + advisor card post-lab) y §8.9 (Harvest + Maverick CONSULT obligatorio en T2/T3).
- Mucho del canon es **ruteo de modelos/hosts** (`cursor-grok-4.5-high-fast`, "Never Composer", remaps AGY) más que criterio de verificación.

### 4.2 Tabla

| Dimensión | orquestador-sx | Nuestra base (`SKILL.md` + `references/tdd-evidence.md`) | Gentle AI | Mejor |
|---|---|---|---|---|
| Origen de los checks | Comandos DoD del sobre (los arma padre/implementer) | Re-corre red/green del implementer + mutación manual | **Probes propias derivadas del spec verbatim**; tests del writer no cuentan | Gentle |
| Spec como contrato | Sobre parafraseado (Causa/Cambio/aceptación) | DoD en el sobre | `S#` verbatim en feature doc, pasado **por referencia** | Gentle |
| Veredicto | PASS/FAIL/INCONCLUSIVE global + gap inventory | Igual + gaps tipados (`red-invalid`, `test-weakened`, `test-hollow`, `scope-escape`) | **Por cada S#** (met/unmet/not implemented); unverified = unmet | Gentle + nuestros gaps tipados |
| Evidencia TDD | No exige RED | **Exige** commit rojo antes que verde, falla por aserción, test no aflojado, mutación | Exige RED/GREEN **observados**; 1 RED por regla + 1 test de no-regresión por comando tocado | Nuestra base (más dura) + regla de cobertura mínima de Gentle |
| Regresión de lo existente | No explícito | Suite completa en `main` (Harvest R-classify-01 #5) | **Diff de stdout/stderr/exit vs baseline** + hash de datos tras rechazo | Gentle |
| Severidad / falsos positivos | No definida | No definida | Blocker = reproducible con input realista **y no presente en baseline**; precision gate; refuter | Gentle |
| Aislamiento del verificador | read-only "por política" | "copia descartable" para la mutación | `mktemp -d` fuera del repo, `HOME`/`TMPDIR` aislados, sin red, `git status` antes/después | Gentle |
| Cuándo hay verificador independiente | **Siempre** tras implementer T2/T3, + VLH + Maverick | Siempre ("no hay listo sin verifier PASS") | Solo riesgo alto por **6 ítems nombrados**; medium = auto-verificación + spot-check | Gentle en costo; sx/base en seguridad. Ver §6 |
| Bucle de corrección | 1 O2 con inventario completo; breaker con Verifier-B ciego y ≤2 pasadas finales | Igual | 1 batch + 1 recheck **solo de esos blockers**; hallazgo nuevo no abre ronda | Empate; Gentle evita "barridos nuevos" |
| Juicio humano/UX | **VLH B4** (evidence_class, serves_ask) | Hereda | No tiene equivalente | sx |
| Revisión de calidad de código | Skeptic/Maverick (ideas, no defectos) | Clean Coder checklist | **4R** con precision gate + refuter 2/3; Judgment Day ciego doble | Gentle |
| Durabilidad | Harvest → Ledger | Harvest en `tdd-evidence.md` | Probes devueltas como **tests de regresión** que se commitean | Gentle |
| Determinismo | Prompt-only (Cursor best-effort) | Prompt-only | Parte crítica en binario Go (assess, freeze, refuter admission) | Gentle (pero caro) |
| Portabilidad a nuestros CLIs | Cursor/AGY/OpenCode/Codex, modelos Grok | Agnóstica | 17 agentes, RDD solo en 4, **sin Grok CLI** | Prompts de Gentle portables; binario no |

### 4.3 Qué le falta a cada uno
- **orquestador-sx:** el verifier verifica lo que le dicen que verifique (DoD del sobre) ⇒ si el implementer escribió un test que fija el bug, PASA. No hay baseline, ni invariantes, ni veredicto por requisito, ni definición de severidad, ni aislamiento real. Mucho peso en modelos/roles y poco en *qué* cuenta como evidencia. Esto coincide con lo que dice Julian.
- **Nuestra base:** buena disciplina de RED/GREEN y mutación, pero hereda el mismo punto ciego: verifica la evidencia **del implementer**. Falta spec verbatim con `S#`, probes propias, baseline diff, severidad, scratch aislado y gate de riesgo para no pagar un verificador en cada T1.
- **Gentle AI:** no tiene juez "como humano"/UX (VLH), su TDD es "por defecto" y no exige commit rojo separado; RDD es pesado, git-bound, y su recuperación es frágil (su propia auditoría); medium sin verificador independiente es un riesgo si el writer es un modelo barato.

## 5. Opciones de integración

Restricciones: varios CLIs y servidores, **una sola suscripción**, gratis/local, delegaciones con tiempo límite.

| Opción | Pros | Contras |
|---|---|---|
| **(a) Adoptar Gentle AI y montar tiers/oleadas encima** | Mantenido por terceros, 17 integraciones, assess determinístico, Engram incluido. | Instala/modifica configs globales de cada CLI (prompts, hooks, agentes, persona) en cada servidor: choca con "no tocar los CLIs"; **sin Grok CLI**; RDD solo en 4 runtimes; ODD **contradice** partes de sx (inline por defecto vs zero-exec del padre; sin tiers/oleadas); telemetría opt-out; RDD consume tokens de la suscripción en revisores in-process; churn altísimo (SDD retirado en v4, contratos v1→v2→v9); su auditoría admite recuperación inoperable. |
| **(b) Mantener sx y copiar el verificador y piezas de Gentle** | Ataca justo el punto débil (verificación); son **prompts + reglas**, portables a cualquier CLI; sin binario ni hooks; MIT (con atribución); se testea con TDD y fixtures. | Perdemos el determinismo del binario (assess, freeze); hay que mantener la copia; la severidad y los probes dependen del modelo verificador. |
| **(c) Engram como memoria del modo código** | Go single-binary, local, MIT, MCP + HTTP + CLI (la parte Discord puede usar HTTP/CLI sin MCP); `ENGRAM_DATA_DIR` permite una DB por bot/proyecto; `topic_key` sirve para el feature doc y el ledger; **verificado en lab**. | Otro proceso/estado por servidor; multi-servidor requiere `engram sync` por git o cloud self-hosted (Postgres); `engram setup` toca configs de los CLIs (evitarlo y registrar MCP a mano/por workspace); memoria contaminable: nunca es evidencia de verificación; proyecto atado al git remote. |
| **(d) Híbrido mínimo** (b) + gate de riesgo como **función pura nuestra** + 4R/refuter **solo en riesgo alto** + (c) opcional detrás de adaptador | Lo mejor de ambos con costo controlado; todo con timeout y testeable; no dependemos del binario de Gentle. | Más diseño propio; reimplementar un `assess` simple (por paths/señales), menos fino que el de ellos. |
| (e) Usar el binario `gentle-ai review assess` como oráculo de riesgo, nada más | Clasificación determinística ya hecha. | Requiere instalar el binario en cada servidor y su estado de review en `.git`; acoplamiento a contratos versionados que cambian seguido. Solo para benchmark, no para prod. |

## 6. Recomendación

**Opción (d):** sx sigue siendo el esqueleto (padre único, tiers T0–T3, oleadas O1–O3, Known-cause gate, VLH B4, breaker ciego, §8.7). Cambios concretos en `codemode-base`:

1. **Spec por referencia:** el gate T2/T3 genera un `spec.md` con `S#` que citan el pedido verbatim (+ `L1` = mensaje de Discord original). Los sobres apuntan a `S#`, no parafrasean.
2. **Verifier v2** = nuestro contrato TDD (`tdd-evidence.md`: red antes que green, `test-weakened`, `test-hollow`, `scope-escape`) **+** las reglas 1–11 de §3.4: probes propias desde `S#`, baseline diff stdout/stderr/exit, hash de datos tras rechazo, veredicto por `S#`, severidad con repro en baseline, scratch `mktemp -d` con `HOME`/`TMPDIR` aislados y sin red, probes devueltas como tests de regresión, corrección acotada (1 batch + 1 recheck solo de blockers).
3. **Gate de riesgo de 6 ítems** como función pura (`assess_risk`) que decide la **profundidad**, no si hay verificación: T0/passive = readback; medium = verifier v2 en modo "probes del spec" (seguimos exigiendo verificador independiente porque los writers suelen ser modelos baratos: más estricto que Gentle); high = verifier v2 + 4R reducido (Reliability siempre; Risk si toca seguridad o datos) + **1 refuter** sobre BLOCKER/CRITICAL. Judgment Day solo a pedido.
4. **Maverick post-Harvest y VLH** quedan, pero VLH solo si user-facing (ya es así).
5. **Engram opcional** detrás de `MemoryPort` (save/search/context) con timeout duro y degradación "memoria no disponible ⇒ se reporta, no es éxito". Una DB por bot (`ENGRAM_DATA_DIR`), sin `engram setup` global; MCP registrado por workspace o uso por HTTP/CLI. Nunca se usa como evidencia de PASS.
6. **Todo con tiempo límite:** verifier, refuter y lentes con timeout; timeout ⇒ `INCONCLUSIVE` (nunca PASS), como VLH UNAVAILABLE.

### Primeros pasos verificables (TDD)
1. **Bench del verificador (RED primero).** `codemode-base/bench/verifier/` con 4 fixtures chicos (repo + `spec.md` + diff del writer):
   (F1) el test del writer fija el bug y contradice `S2`; (F2) cambio no pedido en la salida de un comando existente; (F3) comando rechazado que igual muta el archivo de datos; (F4) control sano.
   Esperado: FAIL con `S#` correcto en F1–F3 y PASS en F4. **RED:** correr el verifier actual de sx/base (DoD del sobre) y registrar que da PASS en F1–F3. **GREEN:** verifier v2 los atrapa. Métrica: 4/4 con 2 modelos distintos, ≤N min cada uno.
2. **`assess_risk` como función pura** con tabla de casos exactos (un caso por ítem 1–6, uno passive, uno medium, uno "assess falla ⇒ high", uno "escalate nunca baja tier"). Commit rojo → verde, según `tdd-evidence.md`.
3. **Parser/validador de handoff del verifier v2**: rechaza handoffs sin veredicto para cada `S#`, con "PASS" sin comando observado, o con `unverified` contado como met ⇒ el padre lo trata como `INCONCLUSIVE`. Tests de tabla.
4. **Contrato de `MemoryPort` con Engram**: test de integración con `ENGRAM_DATA_DIR=$(mktemp -d)` y timeout de 5 s: save → search devuelve el título; binario ausente ⇒ `MemoryUnavailable` (no excepción, no éxito). Ya hay evidencia de lab de que el binario 3.5.1 compila y responde (§2).
5. **Wrapper de timeout de delegación**: test donde el verificador "cuelga" (fake) ⇒ `INCONCLUSIVE` + `limitations: ["timeout Ns"]`.
6. Recién después, actualizar `SKILL.md` §3/§8 y `references/tdd-evidence.md` (no lo hice: este research es de solo lectura sobre la base).

## 7. Riesgos y dudas abiertas
- Los benchmarks del README de Gentle son n=1 y apuntan a PRs de `gentle-shell` que no abrí; tomarlos como señal, no como prueba.
- El prompt `gentle-ai-verify.md` está en assets de OpenCode; las otras integraciones lo renderizan desde las secciones compartidas (`odd-orchestrator-sections.md`). Si copiamos, pinear el commit (`bc27d9e`) porque el texto cambia casi a diario.
- Marca: no usar "Gentle AI"/"Engram" en nombres de nuestros componentes (TRADEMARKS.md).
- Pregunta para Julian: ¿medium sin verificador independiente (como Gentle) o lo mantenemos siempre (más caro, más seguro)? Recomiendo mantenerlo y medir con el bench del paso 1.

## Fuentes (leídas)
- Gentle AI repo y README: https://github.com/Gentleman-Programming/gentle-ai
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/intended-usage.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/usage.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/trigger-rules.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/review-integration.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/agents.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/engram.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/telemetry.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/testing-agents-deterministically.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/audits/2026-07-21-rdd-system-audit.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/docs/architecture/the-organic-rdd-story.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/opencode/agents/gentle-ai-verify.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/skills/_shared/odd-orchestrator-sections.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/claude/agents/review-reliability.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/claude/agents/review-refuter.md
- https://github.com/Gentleman-Programming/gentle-ai/blob/main/internal/assets/skills/judgment-day/SKILL.md
- Engram: https://github.com/Gentleman-Programming/engram · https://github.com/Gentleman-Programming/engram/blob/main/DOCS.md · https://github.com/Gentleman-Programming/engram/blob/main/docs/AGENT-SETUP.md · https://github.com/Gentleman-Programming/engram/blob/main/docs/ARCHITECTURE.md · https://www.mintlify.com/Gentleman-Programming/engram/quickstart
- Metadatos: https://api.github.com/repos/Gentleman-Programming/gentle-ai · https://api.github.com/repos/Gentleman-Programming/engram · https://api.github.com/repos/Gentleman-Programming/gentle-shell (+ `/releases`)
- orquestador-sx: https://github.com/fronteraespacial/orquestador-sx, leído en `<tmp>/orq-sx-ro`: `canon/01-METHODOLOGY-SPACEX.md` (§8.7, §8.9), `canon/02-ROLES-HANDOFFS-GATES.md`, `canon/09-VERIFY-CHECKLIST.md`, `runtime/cursor/agents/verifier.md`, `runtime/skills/orchestrator/references/fase-verify.md`, `runtime/skills/orchestrator/SKILL.md`
- Base local: `<codemode-base>/SKILL.md`, `<codemode-base>/references/tdd-evidence.md`
