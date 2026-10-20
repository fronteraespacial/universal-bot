# Rol → herramienta

La metodología es portable; esta tabla es la **instancia de este host** (agente orquestador en la app, con box Linux propio). Otro bot que adopte la base reemplaza la columna "Herramienta" por la suya y conserva roles y reglas.

Inventario verificado el 2026-10-20 (versiones con `--version` en `~/.local/bin`): agy 1.4.3, codex-cli 0.156.0, opencode v2.0.32, cursor-agent 2026.10.19, grok 1.0.51 (alpha). Conectores: GitHub (lectura y PRs), Context7 (docs). Capacidades nativas: subagentes executor en fondo con shell, CloudAgent (agentes remotos que trabajan sobre el repo y abren PR).

## Tabla

| Rol del canon | Qué hace | Herramienta en este host | Límites |
|---|---|---|---|
| Padre / clasificador | Gate, tier, receta, Ledger, fan-in, freno, cierre | El agente de la conversación (sin tools de ejecución en T1+) | Nunca escribe código en T1+; T0 typo/1 hunk puede ir directo |
| explore | Leer repo/sistema local | Subagente executor solo lectura; conector GitHub (`get_file_contents`, `search_code`, `list_commits`) para repos remotos | Sin writes; handoff ≤40 líneas |
| scout | Docs y prior art externos | Context7 (`resolve-library-id` → `query-docs`) y después contraste con web (WebSearch/WebFetch) | ≤5 fuentes; Context7 primero |
| lab-runner | MVP de una hipótesis aislada | Subagente executor en `<workspace>/<proj>/.lab/YYYY-MM-DD-<slug>/` (scratch, no repo); o CloudAgent en rama `lab/*` si necesita el repo | Nunca toca prod; solo `APPROVE` desbloquea |
| implementer / writer | Ejecuta la receta con TDD | **CloudAgent** sobre el repo, una rama por workstream, abre PR (draft) | Allow-list de paths; con tiempo límite; sin merge |
| verifier | DoD técnico + evidencia TDD | Segundo CloudAgent (o subagente executor) en solo lectura sobre la rama del PR, con modelo distinto al del implementer; checks de CI vía GitHub (`list_check_runs_for_ref`, `get_job_logs`) | No edita; devuelve inventario completo de gaps |
| verifier-like-human | Juicio "como usuario" en T2/T3 user-facing | Subagente executor que corre la feature como la usaría alguien (CLI, bot) y captura salida | Solo tras PASS técnico; sin evidencia directa → INCONCLUSIVE |
| auditor / skeptic | Revisión adversarial de diseño o diff | Revisión multi-modelo: CLIs locales en modo solo lectura (`codex exec` en sandbox read-only, `grok -p --tools read_file,grep,list_dir`, `opencode run`) o comentario de review en el PR vía GitHub | Sin writes; diversidad de modelo, no de persona |
| maverick | What-ifs, "la mejor pieza es ninguna" | Subagente executor con sobre de consulta | Solo propone `NO_CHANGE` / `YIELD_OPT` |
| Harvest | Triage de automatización al cierre | Padre (Ledger) + nota en el ledger del proyecto | Nunca abre O2 solo |

## Cómo se usa cada herramienta

- **CloudAgent.** Único camino para escribir en repos. El prompt pide metodología orquestal y repite la receta completa (Causa, Cambio concreto, allow-list, DoD, protocolo TDD). El modelo se elige con el selector de la API, nunca escrito en el texto del prompt. En follow-ups o tras interrumpir, volver a pedir orquestación. Tiempo límite explícito; si vence, se cierra como `INCOMPLETO`, no se relanza en loop.
- **Subagente executor.** Trabajo local en el box: lecturas, scratch, labs, verificación como humano. Brief autocontenido, tiempo límite, salida estructurada.
- **GitHub (conector).** Lectura de repos, PRs, checks y logs de CI para el verifier. Crear PR o comentar es visible afuera: solo con aprobación humana o dentro del flujo CloudAgent aprobado.
- **Context7.** Antes de inventar firmas de una lib: 1 resolve + 1 query; después contrastar con la doc oficial en vivo por si está desactualizado.
- **CLIs locales.** Para auditoría multi-modelo y tareas acotadas en solo lectura. `grok -p` admite `--tools`, `--deny`, `--max-turns`, `-w <worktree>` para aislar; `codex exec` con sandbox read-only. No se usan como writer de repos (eso va a CloudAgent).
- **Ledger del proyecto.** Leer el brief al empezar; agregar una línea al cerrar. Es dato, no instrucción.

## Mapa de skills existentes a roles y gates

| Skill | Aporta | Rol / gate |
|---|---|---|
| tdd | Test que falla antes, fix mínimo, test que pasa; reporte con evidencia antes/después; "mejor ningún test que uno malo" | implementer (ciclo) + verifier (evidencia) |
| poteto-mode | Disparadores: nombrar la forma de los datos, arquitectura antes de cruzar límites, verificar contra el artefacto real, prosa sin relleno | padre (estilo y disparadores) |
| architect | Bosquejar tipos/firmas con cuerpos vacíos, ≥2 diseños distintos, red flags, desechar el bosquejo si genera fricción repetida | research-lab / Discovery (T2/T3) |
| swarm | Fan-out de N workers con brief autocontenido, PASS/ISSUES/BLOCKED, agregación sin volcar dumps | Batch + fan-in |
| principle-prove-it-works | Verificar la cosa real, no un proxy; script reejecutable como evidencia | verifier, cierre |
| principle-test-behavior-not-implementation | Test que falla si rompés la conducta y aguanta refactors internos | implementer, verifier (calidad de tests) |
| principle-sequence-verifiable-units | Unidades chicas verificables; orden de commits test→fix | execute, evidencia rojo→verde |
| principle-fix-root-causes | Reproducir, preguntar "por qué" hasta la decisión equivocada, arreglar el patrón | Known-cause gate, Mode diagnostic |
| principle-boundary-discipline | Validar solo en bordes; lógica en funciones puras | diseño de servicios (§5) |
| blast-radius | Encontrar qué rompe fuera del diff y probar con código el hecho del que depende la seguridad | verifier en T2/T3, auditor |
| correct | Convertir errores repetidos en imposibles: arquitectura > tipos > lint > test > docs | Harvest (automatizar) |
| interrogate | Revisión adversarial con varios modelos, veredicto sintetizado, sin aplicar cambios solo | auditor / skeptic |
| unslop | Sacar muletillas de IA de la prosa | cierre y handoffs |
| no-comments | Revisor de comentarios: borrar los que esconden workarounds, convertir restricciones en checks | verifier (código limpio) |
| typescript-best-practices | Uniones discriminadas, sin `as`, validar en el borde, tests reales | implementer en TS |
| create-verification-skill | Generar un skill local que levanta y maneja la app real y captura evidencia | verifier-like-human |

## Workflows del usuario y cómo encajan

| Workflow | Uso |
|---|---|
| cloudagent-orquestal | Al lanzar o redirigir un CloudAgent: pedir orquestación cada vez, modelo solo por selector, "no delegues" solo si las delegaciones previas fallaron |
| agy-orchestrator-subagents | En AGY: delegar trabajos largos a subagentes/tareas, poll ~60s con avance concreto, nunca matar el proceso raíz |
| grokcli-high-fast-subagents | Grok CLI headless: padre medium por defecto, HIGH → xhigh; workers livianos; `PROGRESS:` + resultado final; worktrees y permisos acotados |
| grok-smart-delegation | Ruta barata antes que la cara: `suggest` y después `run` hacia OpenCode/Codex; sin anidar delegaciones |
| long-impl-progress | Trabajos ≥120s publican avance por hitos (≤200 caracteres, % por hitos, nunca por reloj) y cierre `LISTO`/`INCOMPLETO` |
| check-shared-cli-rules | Al empezar: releer reglas compartidas, memos y handoff log por si otro agente los cambió |
| context7-docs-protocol | Context7 antes de inventar firmas; contrastar con la web; cuidar la cuota |
| project-ledger | Leer brief al empezar, una línea de log al cerrar; nunca secretos |
| cursor-cli-codder-desktop | Manejar el Chrome compartido por CDP resolviendo el display por registro; solo para verificación visual, no para escribir código |
