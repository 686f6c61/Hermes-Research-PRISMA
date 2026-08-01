# Commands

Este paquete expone dos superficies públicas: Telegram y CLI. La intención es
que una persona pueda empezar una revisión sin aprender primero comandos
internos del gateway original de Hermes.

## Telegram

Los comandos públicos principales son:

- `/start`
- `/nueva_revision`
- `/estado`
- `/reanudar`
- `/cancelar`
- `/ayuda`
- `/discrepancias`
- `/resolver_cribado DOI include|exclude MOTIVO`

### Qué hace cada uno

`/start` sirve como onboarding corto. Explica qué datos mínimos hacen falta y
orienta al usuario hacia un primer arranque limpio.

`/nueva_revision` crea una revisión nueva mediante un wizard conversacional:
pregunta tema, años, criterios de inclusión, criterios de exclusión, pregunta
de investigación opcional, campo metodológico, N final, outlet objetivo,
autoría, correo, fecha y modo autónomo. El campo metodológico puede declararse
o inferirse; los datos editoriales pueden omitirse sin inventar identidad. Al
final muestra un resumen y solo crea artefactos cuando la persona responde
`crear`. Si el mensaje incluye ya un bloque de intake completo, Hermes mantiene
el modo avanzado y materializa el protocolo al instante.

`/estado` lee el estado material de la revisión ligada a ese chat. No depende
de recordar verbalmente en qué fase se quedó el trabajo.

`/reanudar` relanza una revisión detenida o informa del bloqueo real si existe.
No obliga al usuario a conocer nombres internos de skills ni scripts. Si hay
una discrepancia de texto completo, no la ignora ni fuerza una decisión:
mantiene el ciclo en pausa hasta que se resuelva.

`/cancelar` borra el wizard de intake en curso para ese chat. No borra una
revisión que ya haya sido creada.

`/ayuda` resume el formato esperado para el intake y la superficie pública
disponible.

`/discrepancias` muestra, por DOI, los estudios en los que los dos juicios de
elegibilidad no coinciden. Incluye el título, la decisión A, la decisión B, la
recomendación automática no vinculante y sus razones.

`/resolver_cribado DOI include|exclude MOTIVO` registra una decisión científica
firmada. Si quedan más casos, la revisión continúa pausada; cuando se resuelve
el último, se reanuda automáticamente desde el checkpoint. Los alias avanzados
son `/research disagreements` y `/research resolve`.

## CLI

El wrapper principal del bundle es:

```bash
./hermes-research
```

Subcomandos actuales:

- `setup`
- `doctor`
- `up`
- `down`
- `logs`
- `smoke-test`
- `capability-test`
- `multimodal-test`
- `docling-test`
- `golden-eval`
- `cleanroom-validate`
- `release-bundle`
- `verify-release`
- `ship-release`
- `init`
- `status`
- `run`
- `resume`
- `package`
- `adjudicate`
- `amendment`
- `disagreements`
- `resolve-screening`

### Qué problema resuelve cada bloque

`setup` instala la estructura si falta y configura modo, proveedor, modelos y
Telegram sin mostrar secretos.

`doctor` comprueba estructura, entorno, compose, credenciales y conectividad
del proveedor.

`up`, `down` y `logs` controlan la distribución sin exigir que la persona
recuerde perfiles o nombres internos de Compose. `up` ejecuta `doctor` antes de
construir.

`smoke-test` ejerce el flujo público mínimo y valida que la revisión nace y
deja artefactos reales en disco. Su adquisición está acotada a dos fuentes y
termina antes del cribado intensivo para no dejar costes ocultos.

`capability-test` llama al proveedor y prueba el contrato de cada función. El
modelo principal y el revisor deben terminar texto y JSON válidos sin que el
proveedor sustituya silenciosamente el identificador solicitado.

`multimodal-test` valida por separado que el modelo visual pueda interpretar una
página científica renderizada. Separar ambas pruebas evita exigir visión a un
modelo que solo se usa para redacción o revisión.

`docling-test` arranca el worker documental aislado y comprueba orden de
lectura, OCR y extracción material de tablas sobre tres PDF distintos.

`golden-eval` compara predicciones con etiquetas adjudicadas para cribado,
extracción y localización de evidencia. Sin argumentos ejecuta una fixture
sintética que prueba el evaluador; para medir calidad científica hay que pasar
un directorio gold de dominio y sus predicciones.

`cleanroom-validate` responde a una pregunta de distribución: si copio el
bundle a una carpeta nueva, ¿sigue instalándose y construyéndose desde cero?

`release-bundle`, `verify-release` y `ship-release` forman la cadena de
mantenimiento del producto público. No son comandos para quien investiga, sino
para quien publica y valida el paquete.

`init`, `status`, `run`, `resume` y `package` son la cara CLI del ciclo
research. Permiten usar el flujo incluso sin Telegram.

`init --final-n` acepta un entero o rango inclusivo, por ejemplo `35` o
`23-63`. El rango permite que una revisión se adapte a la evidencia disponible
sin inventar un tamaño final exacto antes de buscar.

`init` también admite `validation_mode` en un bloque de intake avanzado:
`autonomous`, `assisted` o `adjudicated`. En modo adjudicado, el gate exige un
registro humano de aprobación antes de cerrar.

`adjudicate` firma la aprobación o rechazo final cuando el contrato de la
revisión exige validación humana. `amendment` permite inspeccionar y aprobar una
modificación material del protocolo antes de aplicarla.

`disagreements REVIEW` lista conflictos de elegibilidad a texto completo.
`resolve-screening REVIEW --doi DOI --decision include|exclude --reason MOTIVO`
firma una decisión. El comando reanuda el ciclo únicamente después del último
caso pendiente.
