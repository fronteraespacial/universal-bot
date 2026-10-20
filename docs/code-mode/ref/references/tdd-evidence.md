# Evidencia TDD: contrato implementer ↔ verifier

## Lo que entrega el implementer (en su handoff)

```markdown
## TDD evidence
- unit: <comportamiento en una frase>
- red_commit: <sha>  (solo test + stub si hizo falta)
- red_cmd: <comando exacto, p. ej. pytest tests/test_x.py -q>
- red_result: <N failed> · motivo: AssertionError | NotImplementedError — <línea clave>
- green_commit: <sha>
- green_cmd: <mismo comando> + suite completa
- green_result: <N passed, 0 failed>
- refactor_commit: <sha> | none
- evidence_paths: [<log rojo>, <log verde>]
```

Una unidad por comportamiento. Si hay varias unidades, un bloque por cada una, en orden.

## Lo que hace el verifier (solo lectura sobre la rama)

1. `git log --oneline <base>..HEAD`: el commit rojo aparece antes que el verde de su unidad.
2. Checkout del commit rojo y correr `red_cmd`. Esperado: falla, y por aserción o `NotImplementedError`. Si falla por `SyntaxError`, `ImportError`, fixture rota o test que no colecta → gap `red-invalid`.
3. Checkout de HEAD y correr la suite completa. Esperado: todo verde. Si no → gap `green-fail`.
4. Revisar que el test de HEAD sea el mismo que el del commit rojo (no se aflojó la aserción). `git diff <red>..HEAD -- <test file>`: solo agregados de casos, nunca cambios de expectativa sin motivo escrito → si no, gap `test-weakened`.
5. Mutación manual: en una copia descartable, romper una línea clave de producción (invertir una condición, devolver un valor fijo). Algún test debe ponerse rojo. Si no → gap `test-hollow`.
6. Paths cambiados ⊆ allow-list del sobre → si no, gap `scope-escape`.
7. Lint/tipos del repo si existen.

Veredicto:

```markdown
Verdict: PASS | FAIL | INCONCLUSIVE
- Commands run: …
- Evidence: red <sha> → <motivo>; green <sha> → <N passed>; mutation → <test que falló>
- Gap inventory: (todos los gaps, no solo el primero)
```

Sin acceso a correr el código (sin entorno, sin dependencias) → `INCONCLUSIVE`, nunca PASS por lectura.

## Excepciones

- `TDD: N/A` declarado en el gate (docs, config sin lógica, rename sin cambio de conducta): el verifier solo confirma que el diff no cambia comportamiento y que la suite sigue verde.
- Bug sin test barato posible (requiere infraestructura cara o estado de producción): el implementer usa el check ejecutable más cercano (script de reproducción, aserción de log) y lo deja en `evidence_paths`. El padre lo aprueba en el gate, no el implementer por su cuenta.
- Si el squash del PR borra los commits rojo/verde, la evidencia válida son los logs guardados de ambas corridas más el sha de la rama antes del squash.

## Harvest R-classify-01 (2026-10-20)

Primera prueba: verdict PASS, PR fronteraespacial/universal-bot#4. Lecciones:

1. Tablas de casos con valores EXACTOS en todos los casos: tier exacto (nunca `None` ni `≥`) y conjunto exacto de signals (igualdad, no subconjunto). Toda aserción laxa es gap del verifier.
2. Cada rama de reglas, incluido el fallback por defecto, tiene al menos un caso dedicado en la tabla.
3. Reglas de clasificación como datos declarativos (lista de reglas con predicado, tier, signal), no una cadena larga de ifs; funciones chicas.
4. Matching de palabras por límite de palabra/token, nunca substring crudo (`pr` daba falsos positivos).
5. El verifier corre la suite completa también en `main` para separar fallos preexistentes de los nuevos.
6. Criterio de aceptación: "2+ commits (test rojo, feat verde), refactor opcional", para no contradecir el paso 5 de §3.
