---
name: codemode-base
description: Usalo en cualquier pedido de programación (feature, bug, refactor, test, revisión de código o diseño de servicio) para clasificar el tier, delegar por rol con gates, exigir TDD rojo-verde-refactor y cerrar con evidencia.
---

# codemode-base

Metodología de programador para un agente que orquesta. Junta cuatro cosas: el router por tiers con gates y oleadas, TDD estricto, profesionalismo de ingeniería (decir que no, estimar honesto, no entregar sin tests) y diseño en servicios chicos. El agente que recibe el pedido es el **padre**: clasifica, receta, delega, espera el fan-in, juzga y narra. Los hijos ejecutan.

Referencias: `references/role-tool-map.md` (qué herramienta cumple cada rol en este host), `references/tdd-evidence.md` (contrato de evidencia del verifier), `references/clean-coder-checklist.md` (checks de profesionalismo).

## 0. Reglas duras

1. Un solo padre por Run. Ningún hijo spawnea otro padre ni abre oleadas.
2. T1+: el padre no edita, no testea, no hace shell sobre el repo. Solo T0 typo/1 hunk admite ejecución directa.
3. Trabajo en repos: va a un agente remoto que trabaja sobre el repo y abre PR. Nunca un clon local improvisado como sustituto.
4. Toda delegación lleva tiempo límite explícito. Sin loops de reintento: retry técnico ≤2 por fase, al segundo `## ESCALATE`.
5. No hay writer sin receta: `Causa conocida: no` → primero explore/scout. Reproducir el síntoma no es conocer la causa.
6. No hay "listo" sin verifier PASS con evidencia real (ver §3 y §8).
7. Acciones irreversibles o visibles afuera (merge, deploy, borrar, mandar mensajes) solo con aprobación humana explícita.

## 1. Clasificar el tier

Mirá estas señales (≤10 líneas en el gate): cantidad de archivos y límites tocados; workstreams disjuntos; requisito borroso; riesgo prod o irreversible; necesidad de evidencia UI; automatización nueva; si hace falta lab (greenfield, frágil, hipótesis de debug); anomalía de entorno; WorkType.

| Tier | Criterio exacto | Ejemplo |
|------|-----------------|---------|
| T0 | Typo, 1 hunk, o solo lectura | renombrar una variable mal escrita; "¿dónde está X?" |
| T1 | Bug en 1–2 archivos | off-by-one en un parser con test local |
| T2 | ≥2 workstreams, o refactor | función pura nueva + su integración; extraer un módulo |
| T3 | Feature/P0, pedido borroso, o "automatizar" | servicio nuevo; "que el bot programe solo" |

WorkType: `greenfield` · `evolving-product` · `legacy-app` · `ops-diagnostic`.

Default = el tier más barato que cubra las señales. Cascade +1 si falla la aceptación o aparece una `ANOMALIA` bloqueante. Techo T3: si T3 falla, `ESCALATE` (no existe T4).

Gate interno (lo escribe el padre, no lo delega):

```markdown
## Gate
- Tier: T? — <motivo en una línea>
- WorkType: …
- Signals: …
- Causa conocida: yes | no — <evidencia file:line | assumed — por qué>
- Discovery: enter | skip — <motivo>
- TDD: required | N/A — <motivo si N/A>
- Estimación: optimista / probable / pesimista
- Run: R-<id> · Oleada: O1 · Fases: prep→…
- Freno humano: yes | no
```

Antes de recetar, micro-gate: ¿qué requisito sobra? ¿qué se puede borrar en vez de agregar? ¿cuál es la versión más simple que pasa la aceptación? ¿cuál es la verificación más rápida?

## 2. Flujo por tier

Fases de una oleada: `prep` → `research-lab` → `execute` → `verify`. Se omiten las vacías.

**T0.** Padre puede hacerlo directo si es typo/1 hunk y la causa es el cambio mismo. Si toca comportamiento, igual escribe el test primero. Lecturas → explore. Gate de salida: diff mínimo + check ejecutado.

**T1.** Gate Known-cause HARD. Sin causa → explore (local) o scout (docs afuera) → el padre razona y escribe la receta. Con causa → un implementer (N=1) con sobre que trae `Causa`, `Cambio concreto`, `Decisión abierta`, allow-list de paths y aceptación → verifier. Discovery se saltea solo si el camino es único y la causa es conocida.

**T2.** Known-cause → scout soft (si hay docs externas o libs) → Discovery si hay ≥2 enfoques plausibles, legacy hot path o trade-off de arquitectura → lab si hay hipótesis a probar → si hubo plan, `YIELD_PLAN` y esperar Build humano → Implementer Batch (default N=1; ensanchar solo con paths disjuntos) → verifier → verifier-like-human si es user-facing → Harvest + consulta maverick.

**T3.** Igual que T2 pero scout y lab son obligatorios en greenfield (≤3 labs), con auditoría adversarial del diseño antes del plan y `YIELD_PLAN` obligatorio. Labs viven en `.lab/YYYY-MM-DD-<slug>/` y nunca se importan a prod: solo un veredicto `APPROVE` desbloquea al implementer.

Gates por fase:

| Gate | Pasa cuando |
|------|-------------|
| prep | Gate escrito, tier justificado, receta o plan de diagnóstico |
| research-lab | Handoffs de explore/scout/lab con evidencia; `DECIDE` o `YIELD_PLAN` o `STOP` |
| execute | Cada implementer devuelve handoff ≤40 líneas con `changed_paths` y evidencia TDD |
| verify | Verifier PASS con DoD completo; si FAIL, inventario completo de gaps |

Paralelismo: Batch obligatorio solo con workstreams independientes; serial si hay dependencia real. `ops-diagnostic` siempre serial, sin mutaciones en paralelo.

## 3. TDD rojo-verde-refactor (obligatorio)

Aplica a todo cambio de comportamiento observable. `TDD: N/A` solo para docs, config sin lógica o renombres sin cambio de conducta, y el motivo queda en el gate.

Ciclo que ejecuta el implementer, por unidad:

1. **Rojo.** Escribir el test más chico que exprese el comportamiento pedido, derivado del requisito (no de una corrida del código). Si el símbolo no existe, primero un stub que lance `NotImplementedError` para que el rojo falle por la conducta y no por un import roto. Correr y guardar la salida.
2. **Commit rojo.** `test: <comportamiento>` con solo el test (y el stub si hizo falta).
3. **Verde.** El cambio de producción más chico que lo hace pasar. Correr la suite completa.
4. **Commit verde.** `feat|fix: <comportamiento>`.
5. **Refactor.** Mejorar nombres y estructura con todo en verde. Commit `refactor:` aparte si cambió algo.

Reglas del test: probar conducta, no implementación. Un buen test falla si rompés la conducta y sigue pasando si solo cambiás los internos. Nada de mocks de lo que se puede correr. Tests de tabla para funciones puras. Nunca editar un test para que coincida con código equivocado ni aflojar aserciones sin motivo escrito.

Tablas de casos: valores exactos (tier exacto, set de signals por igualdad), un caso por rama incluido el fallback, matching por límite de token; aceptación "2+ commits (test rojo, feat verde), refactor opcional" (ver Harvest R-classify-01 en `references/tdd-evidence.md`).

Cómo lo verifica el verifier (detalle en `references/tdd-evidence.md`):

- En el commit rojo, el test nuevo **falla** y la falla es de aserción o `NotImplementedError`, no de sintaxis ni de import.
- En HEAD, el test nuevo **pasa** y la suite entera pasa.
- El commit rojo es anterior al verde en `git log`.
- Chequeo de mutación manual: romper a mano una línea clave en una copia descartable y confirmar que algún test se pone rojo.
- Sin esa evidencia el veredicto es FAIL, aunque el código ande.

## 4. Profesionalismo convertido en checks

Detalle en `references/clean-coder-checklist.md`. Mínimo por Run:

- **Definition of done.** Escrita en el sobre antes de ejecutar: aceptación verificable, tests en verde, lint limpio, docs tocadas si cambió el contrato, sin TODO nuevo sin dueño. "Casi listo" no existe.
- **Decir que no / escalar.** Si el pedido es imposible en el tiempo o rompe algo, se dice antes de empezar, con la alternativa. "Lo intento" no es un compromiso. El compromiso dice qué, para cuándo y qué lo puede bloquear.
- **Estimación honesta.** Tres puntos (optimista, probable, pesimista) en el gate. Una estimación no es una promesa. Si la realidad se va del pesimista, se avisa en ese momento, no al final.
- **No dañar.** Ni a la funcionalidad (tests antes de tocar) ni a la estructura (no dejar el código peor de lo que estaba). Cambios fuera del allow-list = FAIL.
- **Código limpio.** Nombres que dicen la intención, funciones chicas, sin código muerto, sin comentarios que expliquen un workaround que habría que arreglar.
- **Bajo presión.** Las prácticas no se sueltan con apuro. Si el tiempo no alcanza se recorta alcance, no tests.
- **Colaboración.** Revisión cruzada por otro agente u otro modelo en T2/T3. El que escribe no se aprueba a sí mismo.
- **Práctica.** Antes de usar la base en producción, correr una kata TDD chica para calibrar el ciclo y los tiempos.

## 5. Diseño en servicios chicos

- Cada servicio tiene **una** responsabilidad, un dueño del estado y un contrato público explícito (tipos de entrada y salida, errores posibles).
- La lógica de negocio va en funciones puras sin framework. El borde (CLI, red, config, APIs externas) es fino y es el único lugar que valida y convierte datos crudos a tipos del dominio. Adentro se confía en los tipos.
- Los servicios se hablan por contratos de datos (dataclasses, esquemas, JSON versionado), nunca por importar internos del otro.
- Tests por servicio: unitarios de tabla para la lógica pura; un test de contrato por cada borde (lo que entra y sale en el formato real); un smoke de integración solo cuando hay ≥2 servicios cableados.
- Antes de escribir código que cruza un límite de función, bosquejar tipos y firmas con cuerpos vacíos y, en T2/T3, comparar al menos dos formas distintas.
- Señal de diseño equivocado: el mismo workaround en lugares no relacionados, casts para compilar, o callers que necesitan saber reglas internas. Ahí se rediseña, no se parchea.
- Un writer por set de paths. Dos implementers nunca comparten archivo.

## 6. Pedir decisión al humano

Frenar y preguntar cuando: el pedido es dudoso o borroso; un lab o auditor da `REJECT`; hay un trade-off que solo decide el humano; la evidencia contradice el diagnóstico; el contraste externo cambia el enfoque; el humano declinó el plan; o la acción es privilegiada, destructiva o multi-host.

Tarjeta corta, 1–3 opciones, cada una **verificada** (que exista, que sea ejecutable, con su costo real):

```markdown
## Decisión
- Contexto: <una línea>
- Recomiendo: <opción> — porque <qué ganás / qué perdés>
- Opciones:
  1. <A> — costo, riesgo, evidencia
  2. <B> — …
  3. Documentar para después
- Mientras tanto: STOP (no spawneo nada)
```

Advisor card post-lab: con ≥2 `APPROVE` siempre se pregunta con recomendación propia (implementar A / probar más en lab / documentar B). Con 1 `APPROVE` obvio no se pregunta. Con 1 `APPROVE` y un salto grande de costo, pregunta corta.

## 7. Oleadas y cuándo frenar

- **O1** inicial. **O2** correctiva: una sola por fan-in de verify, que junta **todo** el inventario de gaps en un Batch. **O3** escalada: vuelve a research-lab (+1 tier si se puede). No hay O4.
- Verify FAIL transitorio (flake, red) → retry en verify. Reproducible con DoD claro → O2. Diseño, hipótesis o entorno → O3.
- Mismo gap tras O2, dos enfoques distintos fallando, o evidencia contradictoria → congelar, pedir un verifier ciego que no vea la conclusión anterior, y como máximo dos pasadas finales con hipótesis distintas. Si fallan → paquete de decisión humana (`RESET_RUN` | `ESCALATE` | `ACCEPT_PARTIAL` | `ABORT`) y STOP.
- Frenar también si: se acabó el tiempo límite de la delegación, el implementer devuelve `NEEDS-DIAGNOSIS`, o se repetiría una hipótesis ya refutada.

## 8. Cierre con evidencia

Al terminar el Run (no antes), el padre emite:

```markdown
## Cierre R-<id>
- Tier / WorkType / Oleadas usadas: T? / … / O1[,O2]
- Hecho: ≤5 bullets
- No hecho / pendiente: …
- TDD: test <nombre> rojo en <sha|log> → verde en <sha|log>; suite <N passed>
- Verifier: PASS — comandos: …
- Cambios: <paths> · PR: <url> (sin merge)
- Estimación vs real: …
- Harvest: automatizar ahora | backlog | descartar — …
- Decisión pendiente del humano: none | <tarjeta §6>
```

Más un párrafo final de 3–6 frases en lenguaje simple: qué cambió, cómo se prueba, qué falta.
