# Augmented Coding en el modo código

Code Mode adopta Augmented Coding (Kent Beck: la IA escribe, la persona o el orquestador pilota, de a pasos chicos con tests) y rechaza Spec Driven Development.

## Qué adoptamos

- Un backlog corto de historias. Cada ítem dice quién cambia qué y por qué importa. No un árbol de archivos.
- Una historia a la vez, refinada antes del worker: aceptación observable y fuera de alcance.
- Un slice vertical que ya se puede probar. La evidencia es el test (rojo → verde), no un documento de diseño.
- Cuando hay elección de modelo, el refine de la historia va a un modelo más capaz y la iteración del código a uno más rápido. La regla está en `code-story`; esta entrega no cambia el ruteo del runtime.

## Qué rechazamos de Spec Driven

- SpecKit, OpenSpec y specs de arquitectura en varias capas por defecto.
- Que el MAIN arme planes largos que crecen como documentación horizontal.
- Dar un slice por terminado sin una prueba ejecutable.

## Tres skills hermanas

Mismo texto que en los workflows de Frontera, versionado en este repo:

| Skill | Path |
| --- | --- |
| `code-backlog` | `docs/code-mode/skills/code-backlog/SKILL.md` |
| `code-story` | `docs/code-mode/skills/code-story/SKILL.md` |
| `code-pair` | `docs/code-mode/skills/code-pair/SKILL.md` |

`code-backlog` lista el trabajo y marca la próxima historia. `code-story` la refina (aceptación, fuera de alcance, cómo probar, slice) y no codea. `code-pair` implementa solo ese slice, con TDD corto, y para si salta una alarma.

## Tres alarmas = FAIL

El MAIN y el verifier reportan y frenan. No se cierra el trabajo "igual".

1. **Loops.** El mismo enfoque que falla, repetido, sin información nueva.
2. **Scope creep.** Trabajo fuera de la aceptación o del fuera de alcance.
3. **Fake tests.** Editar tests solo para que pasen. Sí se puede corregir un test cuando está demostrado que el test está mal.

El clasificador es `classify` en `src/universal_bot/code_mode/augmented_alarms.py`. Falla cerrado: sin historia refinada, sin un enfoque para comparar, sin allow-list de lo que se tocó, o sin evidencia de tests, el veredicto no es PASS. Las tres alarmas se listan juntas cuando coinciden.

## orquestador-sx y TDD

Siguen. El padre, las oleadas y los gates de orquestador-sx quedan. El ciclo rojo → verde → refactor y el contrato de `docs/code-mode/ref/references/tdd-evidence.md` también. Estas reglas los aprietan: una historia refinada antes del worker, slice vertical, y las tres alarmas como FAIL del verifier. El párrafo correspondiente está en `docs/code-mode/ref/SKILL-codemode-base.md` (cuándo frenar) y en el prompt del MAIN (`MAIN_SYSTEM_PROMPT`).
