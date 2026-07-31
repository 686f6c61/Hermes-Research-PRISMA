# Arquitectura

Hermes Research Pack se apoya en una arquitectura corta y bastante legible.

## Capas

### 1. Entrada pública

La superficie pública está pensada para Telegram y para un wrapper CLI pequeño.
La idea es que una persona no tenga que conocer comandos internos del gateway ni
la estructura de scripts original de Hermes.

En Telegram, la entrada pública queda reducida a:

- `/start`
- `/nueva_revision`
- `/estado`
- `/reanudar`
- `/cancelar`
- `/ayuda`

`/nueva_revision` no exige que la persona conozca la estructura interna del
intake: abre un wizard pregunta a pregunta, conserva estado por chat y solo
crea la revisión cuando recibe la confirmación `crear`. El bloque completo de
intake sigue disponible como atajo avanzado.

En CLI, la entrada equivalente es:

- `./hermes-research init`
- `./hermes-research status`
- `./hermes-research run`
- `./hermes-research resume`
- `./hermes-research package`

### 2. Runtime

El runtime se ejecuta con dos contenedores permanentes y un worker documental
opcional:

- `hermes-agent`
- `hermes-prisma-watchdog`
- `hermes-docling`, aislado mediante el perfil `docling`

Los dos servicios permanentes comparten:

- `runtime/hermes-home`
- `runtime/workspace`
- `runtime/obsidian`

El bundle no espera que `runtime/hermes-home` aparezca por generación
espontánea. Lo siembra desde `seed/hermes-home`, que contiene:

- `bin/`
- `config.yaml`
- `skills/research/`
- estructura mínima de `home/default`, `logs` y `watchdog`

### 3. Plantilla metodológica

La revisión nueva no nace sobre un directorio vacío. Nace copiando
`templates/systematic-review-template/` al workspace runtime.

Eso fija desde el principio:

- protocolo
- estrategia de búsqueda
- screening
- extracción
- análisis estructural
- manuscrito
- auditoría
- revisión editorial

### 4. Ciclo de revisión

El ciclo operativo combina cuatro piezas:

- bootstrap determinista
- pipeline PRISMA
- watchdog autónomo
- cierre editorial por gate

La entrada pública crea primero el protocolo. Después el pipeline llena
búsquedas, screening, full text y extracción. Una fase estructural separada
construye redes de autoría, temas, referencias y evidencia con cobertura y
parámetros explícitos. La síntesis y publicación consumen esos artefactos sin
permitir que centralidad, citas o productividad cambien la selección. El
watchdog relanza fases paradas y el gate decide si la revisión puede
considerarse cerrada.

### 5. Extracción documental estructurada

El PDF sigue entrando primero por la ruta rápida de texto. Cuando Docling está
disponible, el subconjunto focal recibe una segunda lectura estructural que
reconstruye orden de lectura, tablas, figuras y OCR. El gateway no instala
PyTorch: envía el PDF al servicio interno y recibe JSON y Markdown. Cada
resultado queda cacheado por hash del PDF y solo se acepta con DOI.

Una caída o un timeout de Docling no detiene la revisión. El manifiesto registra
el fallo y `publication_audit.py` conserva la extracción Poppler como fallback.

### 6. Atlas estructural

Después de extracción, `research-network-analysis` genera un atlas HTML que
funciona sin CDN ni servidor. Las capas de coautoría, citación, acoplamiento
bibliográfico, cocitación, palabras clave y evidencia se calculan por separado.
Los CSV, GraphML, parámetros, cobertura y procedencia permanecen junto al HTML.

Las comunidades solo se interpretan si tamaño, cobertura y estabilidad superan
los umbrales declarados. En caso contrario el grafo sigue disponible, pero su
estado es exploratorio. El paquete nunca combina esas métricas en un supuesto
índice de autoridad.
