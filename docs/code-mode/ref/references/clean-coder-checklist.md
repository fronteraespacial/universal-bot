# Checklist de profesionalismo

Basado en ideas generales de *The Clean Coder* (Robert C. Martin), parafraseadas y convertidas en checks. No es una cita del libro.

## Antes de empezar (padre, en el gate)

- [ ] Hay DoD escrita y verificable: aceptación concreta, comando de tests, qué docs cambian. Si no se puede escribir, el pedido es borroso → preguntar.
- [ ] Estimación de tres puntos (optimista / probable / pesimista). Se presenta como rango, no como promesa.
- [ ] Si el plazo o el alcance no cierran: se dice "no" con una alternativa (menos alcance, más tiempo, otro enfoque). No se acepta un "intentalo" como compromiso.
- [ ] Compromiso con forma: "voy a entregar X, verificado con Y, para Z; lo que puede bloquearlo es W".
- [ ] Riesgo de daño identificado: qué puede romper el cambio fuera del diff.

## Durante (implementer)

- [ ] Primero el test que falla (ver `tdd-evidence.md`).
- [ ] No dañar la función: suite verde antes de tocar y después de cada unidad.
- [ ] No dañar la estructura: el código queda igual o más limpio de lo que estaba.
- [ ] Nombres que dicen la intención; funciones chicas con una sola tarea; sin código muerto; sin parámetros que no se usan.
- [ ] Sin comentarios que justifiquen un workaround; si hace falta explicarlo, se arregla el código.
- [ ] Si aparece un bloqueo, se avisa enseguida (`ESCALATE`/`ANOMALIA`) en vez de esconderlo o seguir a ciegas.
- [ ] Bajo presión no se sacan tests ni revisión: se recorta alcance y se informa.

## Antes de entregar (verifier y padre)

- [ ] Nada se declara listo sin tests en verde y verifier PASS.
- [ ] La aceptación la verifica alguien distinto del que escribió.
- [ ] Revisión cruzada en T2/T3 (otro agente u otro modelo).
- [ ] Estimación vs real anotada en el cierre, para calibrar la próxima.
- [ ] Lo pendiente se dice con nombre, no se esconde en "casi listo".

## Fuera del Run

- [ ] Práctica: kata TDD chica periódica para calibrar el ciclo y el tiempo por unidad.
- [ ] Colaboración: los handoffs se escriben para que otro los retome sin preguntar.
- [ ] Aprendizaje: cada error que se repite se vuelve un check automático (arquitectura, tipo, lint o test; docs último).
