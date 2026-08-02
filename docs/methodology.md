# Methodology

La idea metodológica del paquete no es “hacer búsquedas con IA”, sino fijar una
revisión sistemática con trazabilidad material desde el primer artefacto.
PRISMA ordena el reporte del flujo, pero no sustituye la teoría, la evaluación
crítica, la comparación entre estudios ni la lógica de síntesis.

## Principios

### 1. La pregunta se escribe antes del corpus

El tema, la ventana temporal y los criterios de inclusión y exclusión se
materializan en `protocol/intake.md`, `protocol/research-question.md` y
`protocol/eligibility-criteria.md`.

Eso evita que la frontera de la revisión cambie de manera silenciosa cuando ya
han empezado a llegar registros.

### 2. DOI-first

Antes de tomar decisiones editoriales profundas, Hermes intenta estabilizar la
identidad bibliográfica del corpus. El objetivo no es solo deduplicar, sino
saber qué registros son realmente únicos, cuáles siguen siendo ambiguos y qué
metadatos faltan.

### 3. Full text obligatorio

El paquete no considera “incluido” un estudio solo porque el abstract parezca
prometedor. Para entrar en el corpus final, la revisión necesita evidencia de
texto completo legible y útil.

La descarga forma parte del método y de la seguridad. Cada URL y redirección se
valida contra destinos privados, esquemas y puertos no autorizados; el archivo
debe respetar tamaño, tipo y cabecera PDF. Un HTML de login guardado con
extensión `.pdf` no cuenta como texto completo.

La lectura se hace en dos niveles. `pdftotext` mantiene una ruta rápida y
determinista. Docling añade una lectura estructural del subconjunto focal:
orden de lectura, OCR, tablas y figuras. Esta segunda capa no decide inclusión,
no interpreta resultados y no sustituye al agente revisor; produce evidencia
material que los pasos posteriores pueden auditar.

### 4. Decisiones trazables

Las salidas de screening no se quedan en una conversación. Se vuelcan a CSV y
se vuelven a leer después para recomputar conteos, auditar exclusiones y
reanudar el trabajo sin depender de memoria verbal.

El cribado usa dos juicios automáticos independientes. En título y resumen, un
desacuerdo conserva el registro como `maybe` para evitar una exclusión
prematura. En texto completo, el sistema añade una tercera recomendación
automática, pero esa recomendación es informativa y no toma la decisión final.

Si A y B discrepan, la ejecución entra en `waiting_for_researcher`. No es un
fallo ni un "hasta aquí he llegado": búsqueda, descargas, protocolo, decisiones
A/B, recomendación y conteos quedan guardados. La persona investigadora recibe
el DOI, el título, ambos juicios y la recomendación, y decide `include` o
`exclude` con una razón científica. La decisión queda firmada con la identidad
configurada y vinculada al caso exacto, al protocolo congelado y al texto
completo analizado.

La ejecución solo se reanuda cuando no quedan discrepancias sin resolver. La
reanudación reutiliza `full-text-review-checkpoint.json`, por lo que no repite
búsqueda, descarga ni juicios A/B si el protocolo y la evidencia no han
cambiado. Los casos ya resueltos también se conservan: una caída posterior no
puede obligar a decidirlos de nuevo ni sustituirlos por otra salida del modelo.

### 5. Cierre editorial duro

Una revisión no queda cerrada solo porque exista un manuscrito en Markdown. El
gate exige artefactos reales, entre ellos:

- manuscrito `MD`
- export LaTeX
- PDF
- paquete editorial
- revisión cruzada
- auditoría de integridad
- estado `PASS`

### 6. Contratos metodológicos ejecutables

El intake no queda solo en prosa. La ejecución genera cinco contratos:

- `protocol/intake.json` fija pregunta, ventana, criterios, rango de N y modo de
  validación.
- `protocol/method-contract.json` declara unidad de comparación, fuentes, ejes
  de evaluación y red flags del campo.
- `protocol/synthesis-plan.json` especifica cuándo procede meta-análisis, SWiM,
  síntesis temática o comparación configuracional.
- `protocol/journal-profile.json` separa el núcleo científico común de una
  adaptación posterior a una revista concreta.
- `protocol/deliverables-contract.json` define qué debe existir para considerar
  completa la entrega.

`protocol/contracts-manifest.json` registra hashes de esos contratos y
`protocol/amendments.jsonl` conserva desviaciones posteriores. El N final se
trata como rango deseado, nunca como cuota de inclusión.

La preselección focal se congela antes de la extracción profunda con señales
comparables disponibles para todos los textos completos: relevancia, calidad
metodológica y representatividad. Una ficha ya enriquecida no puede desplazar a
otra todavía no extraída por el simple orden de ejecución o por una
reanudación. La confianza de extracción activa revisión y cautela, pero no
reescribe retrospectivamente la frontera focal.

Una desviación material no se aplica por conveniencia del pipeline. Se escribe
como propuesta, explica qué contrato cambia y espera aprobación investigadora
firmada. Así se distingue una corrección operativa de una redefinición
post-hoc de la pregunta, los criterios o la síntesis.

### 7. Afirmaciones enlazadas con evidencia

`paper/audit/claim-evidence-ledger.csv` relaciona cada afirmación crítica del
manuscrito con citas, DOI, fragmento y localización en el texto completo.
`evidence-coverage.json` separa evidencia localizada, apoyo parcial y apoyo
insuficiente. El gate bloquea afirmaciones críticas sin soporte y avisa cuando
la localización todavía es parcial.

### 8. Evaluación crítica dependiente del campo

El router elige o recibe uno de seis perfiles: biomédico, técnico, ciencias
sociales, educación, management o mixto. Cada perfil cambia la unidad de
comparación, las fuentes, el appraisal, las tablas mínimas, las figuras útiles y
las condiciones de síntesis. El perfil evita aplicar una gramática biomédica a
una pregunta social o reducir una revisión técnica a frecuencias documentales.

Dentro del perfil técnico, las preguntas sobre seguridad de modelos o agentes
activan una extracción especializada. Una defensa no se considera superior por
reducir una tasa de ataque aislada: la comparación exige amenaza, superficie,
control, punto de enforcement, baseline y adaptabilidad equivalentes, además de
eficacia, falsos positivos, utilidad, latencia o coste y evidencia de robustez.
Cuando faltan esas dimensiones, el resultado se conserva como señal de
seguridad, pero no como ganador general.

La frontera distingue tres intensidades. Una mención a una métrica o a una tabla
no cuenta como resultado; una dirección cualitativa se conserva como señal; y
solo un valor cuantificado puede sostener comparabilidad fuerte. La categoría
`frontier_ready` exige, como mínimo, efecto de seguridad cuantificado, trade-off
operativo cuantificado, baseline explícito y robustez. Incluso entonces la
dominancia es condicionada: no agrega tasas obtenidas bajo amenazas,
presupuestos o atacantes incompatibles.

La taxonomía de seguridad es bilingüe y separa amenazas de familias de control.
Distingue inyección y jailbreak, envenenamiento de herramientas o memoria,
exfiltración y abuso de privilegios; y diferencia filtros, monitores de
activaciones, autorización de herramientas, procedencia y flujo de información,
aislamiento, contención criptográfica, control de memoria y verificación causal.

### 9. Estructura relacional con límites explícitos

Las relaciones del corpus se analizan después de la extracción y nunca
participan en `OK/KO`. El DOI es la identidad de estudio. La productividad de
un autor dentro del corpus se mantiene separada de su recuento externo en
OpenAlex; ambos son contexto descriptivo, no una evaluación de calidad.

Las redes de autoría, citas, acoplamiento bibliográfico, cocitación, palabras
clave y evidencia no se fusionan en un indicador único. Cada capa declara
cobertura, densidad, componentes, centralidad, concentración, modularidad,
estabilidad y estado interpretativo. Por debajo de los umbrales, una comunidad
se reporta como exploratoria y no como escuela consolidada.

El portfolio visual aplica la misma frontera. La red temática puede proponerse
para el cuerpo cuando la cobertura y estabilidad permiten interpretar
comunidades y puentes; la coautoría permanece suplementaria y nunca altera
elegibilidad o calidad. La figura de madurez de evidencia separa alineación
descriptiva, evidencia insuficiente y preguntas abiertas para impedir que la
repetición de una señal se presente como causalidad. El ranking limita el
cuerpo a cuatro figuras y conserva el resto en un catálogo descargable.

### 10. Validación del propio harness

Los corpus golden separan tres problemas: clasificación de inclusión/exclusión,
extracción de campos y localización de evidencia. El informe produce matriz de
confusión, precisión, recall, F1, especificidad, exactitud por campo y análisis
de errores.

Cada revisión genera además un conjunto de referencia operacional a partir de
consensos automáticos, recomendaciones y decisiones firmadas. Sirve para
regresión, repetibilidad y detección de cambios del harness, pero se etiqueta
expresamente como `external_human_ground_truth: false`. Las fixtures sintéticas
solo validan el software de evaluación y una afirmación externa de rendimiento
científico exige un conjunto independiente adjudicado por especialistas del
dominio.

### 11. Posiciones de evidencia antes que recuentos

La síntesis no trata todos los resultados como votos equivalentes. Cada estudio
se posiciona frente a una comparación explícita y conserva dirección, alcance,
fragmento y localización. La salida distingue asociaciones positivas,
negativas, nulas, mixtas o condicionadas, aportaciones descriptivas y casos
donde la dirección sigue sin poder determinarse.

La dirección estadística y la utilidad práctica se almacenan por separado. Una
reducción de latencia, coste, error o riesgo puede ser una asociación negativa
y, a la vez, un resultado favorable. Los trabajos teóricos o descriptivos se
marcan como no aplicables en lugar de convertirse artificialmente en evidencia
de beneficio.

Una convergencia solo se declara cuando las posiciones son compatibles y existe
base suficiente para compararlas. Si cambian el constructo, la medida, la
población, el contexto o el diseño, el sistema conserva el desacuerdo o la
pregunta abierta en vez de fabricar un consenso por mayoría documental. La
repetición de un patrón en contextos distintos se reporta como alineación entre
contextos, no como convergencia directa; una repetición sin dirección recuperable
solo puede sostener una alineación descriptiva.

### 12. Orden de lectura separado de selección

Después de la extracción, la revisión calcula una prioridad de lectura para
concentrar el juicio humano en los estudios más relevantes, transparentes,
localizables, reproducibles y útiles para contrastar la tesis. Este score no
reabre el cribado ni sustituye el appraisal.

Las señales bibliométricas tienen peso cero. Un autor central, un trabajo muy
citado o una comunidad grande pueden orientar exploración, pero nunca hacen un
estudio más elegible, más riguroso ni más verdadero.

### 13. Artículo y código como contrato opcional

Cuando un artículo declara software, la auditoría opcional contrasta esa
declaración con señales documentales del repositorio: disponibilidad, licencia,
README, entorno, tests, datos y estado de archivo. El modo predeterminado es un
inventario local; la inspección remota debe solicitarse de forma explícita.

El proceso es de solo lectura. No clona, instala, importa ni ejecuta código
externo y, por tanto, no confunde presencia de un repositorio con reproducción
exitosa. Una reproducción computacional completa requeriría un sandbox, un
presupuesto y un protocolo de seguridad propios.

### 14. Linaje y memoria con fronteras científicas

Cada fase registra hashes de sus entradas y salidas y construye un grafo de
linaje material. Ese grafo permite responder qué archivo derivó de cuál,
detectar cambios y reanudar sin repetir trabajo estable. Prueba procedencia de
artefactos, no validez científica.

El workspace mantiene además una memoria privada entre revisiones con consultas,
DOI, constructos y decisiones previas. Su función es recuperar contexto y evitar
duplicar esfuerzo. Cada nueva revisión debe volver a aplicar sus criterios:
heredar una decisión anterior está prohibido porque pregunta, ventana y
protocolo pueden haber cambiado. Ni el contexto privado ni su paso de ejecución
aparecen en el linaje o estado incluidos en el ZIP público.

## Qué intenta reducir este enfoque

- improvisación al definir el alcance
- duplicados silenciosos
- inclusiones sin full text
- pérdida de contexto tras una interrupción
- exclusiones terminales cuando dos juicios no coinciden
- repetición del trabajo tras una pausa de decisión
- cierres falsos sin paquete publicable
- afirmaciones sin fragmento o página verificable
- sustitución silenciosa de modelos por el proveedor
- repetición completa de fases cuyos inputs no han cambiado
- consenso aparente producido por contar estudios no comparables
- confusión entre prioridad de lectura y elegibilidad científica
- ejecución accidental de código asociado a artículos
- reutilización acrítica de decisiones entre revisiones
