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
