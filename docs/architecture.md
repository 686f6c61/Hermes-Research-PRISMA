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

Las discrepancias de texto completo añaden `/discrepancias` y
`/resolver_cribado`, pero solo como acciones contextuales. No aparecen en el
menú de trabajo diario.

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
watchdog relanza fases técnicas paradas con intentos y backoff acotados, pero
nunca atraviesa una decisión investigadora. El gate decide si la revisión
puede considerarse cerrada.

El cribado de texto completo produce dos juicios independientes. Si discrepan,
una recomendación automática organiza la evidencia, pero la revisión entra en
`waiting_for_researcher`. La decisión final se firma por DOI y protocolo; al
resolver el último caso, el ciclo reutiliza el checkpoint en lugar de repetir
búsqueda, descarga y lectura.

### 5. Extracción documental estructurada

El PDF sigue entrando primero por la ruta rápida de texto. La descarga rechaza
destinos privados, redirecciones inseguras, tipos incompatibles, tamaños
excesivos y archivos sin cabecera PDF. Cuando Docling está disponible, el
subconjunto focal recibe una segunda lectura estructural que reconstruye orden
de lectura, tablas, figuras y OCR. El gateway no instala PyTorch: envía el PDF
al servicio interno autenticado y recibe JSON y Markdown. Cada resultado queda
cacheado por hash del PDF y solo se acepta con DOI.

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

### 7. Inteligencia científica

La extracción no desemboca directamente en prosa. Una capa intermedia crea una
matriz de posiciones de evidencia y distingue convergencia, desacuerdo
direccional, resultado nulo, patrón condicionado y pregunta abierta. La unidad
de análisis sigue siendo el estudio y cada posición conserva DOI, contexto,
método y localización material.

`analysis/reading-priority.csv` organiza la atención humana por relevancia,
transparencia metodológica, evidencia recuperable, reproducibilidad y capacidad
de contraste. No cambia inclusión, exclusión ni selección focal, y asigna peso
cero a citas, productividad de autor y centralidad.

### 8. Publicación visual

Las figuras se tratan como argumentos visuales, no como decoración. El ranking
evalúa utilidad científica, densidad, no redundancia y trazabilidad. Propone
hasta cuatro figuras para el cuerpo del manuscrito por defecto. En el
subperfil de seguridad puede proponer cinco figuras sustantivas: panorama de
amenazas, matriz amenaza-control, comparabilidad metodológica, madurez de
evidencia y gramática analítica. La arquitectura operativa, el mapa general y
las redes exploratorias permanecen como suplemento o reserva.

`figures/gallery.html` reúne el portfolio completo sin dependencias externas.
Cada entrada explica por qué entra o no en el cuerpo y permite descargar PNG de
alta resolución y SVG editable. La exportación LaTeX sincroniza esa fuente
canónica, elimina copias antiguas y mantiene las figuras dentro del área
imprimible.

### 9. Memoria, linaje y auditoría de código

La memoria entre revisiones puede recuperar consultas, DOI, constructos y
precedentes, pero no reutiliza una decisión científica anterior. Vive en el
área privada del runtime y no entra en el ZIP público.

`notes/artifact-lineage.json` enlaza entradas y salidas mediante rutas
relativas, tamaño y SHA-256. Demuestra derivación material, no validez
epistemológica. La auditoría artículo-código es opcional y de solo lectura:
inventaría repositorios declarados y, si se autoriza, consulta metadatos
públicos sin clonar, instalar, importar ni ejecutar código de terceros.
