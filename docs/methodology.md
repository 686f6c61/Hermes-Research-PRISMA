# Methodology

La idea metodológica del paquete no es “hacer búsquedas con IA”, sino fijar una
revisión PRISMA con trazabilidad material desde el primer artefacto.

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

La lectura se hace en dos niveles. `pdftotext` mantiene una ruta rápida y
determinista. Docling añade una lectura estructural del subconjunto focal:
orden de lectura, OCR, tablas y figuras. Esta segunda capa no decide inclusión,
no interpreta resultados y no sustituye al agente revisor; produce evidencia
material que los pasos posteriores pueden auditar.

### 4. Decisiones trazables

Las salidas de screening no se quedan en una conversación. Se vuelcan a CSV y
se vuelven a leer después para recomputar conteos, auditar exclusiones y
reanudar el trabajo sin depender de memoria verbal.

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

## Qué intenta reducir este enfoque

- improvisación al definir el alcance
- duplicados silenciosos
- inclusiones sin full text
- pérdida de contexto tras una interrupción
- cierres falsos sin paquete publicable
