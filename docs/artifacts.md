# Artifacts

Una instalación buena de Hermes Research Pack deja rastros muy concretos en
disco. Esa es una parte central del producto.

El primer archivo que debe abrir una persona al recibir una revisión es
`paper/package/index.html`. Es una guía offline, no una landing: resume estado y
métricas, explica el orden de lectura y enlaza los doce bloques de la entrega.
`paper/package/deliverables-manifest.json` contiene la misma estructura en
formato máquina, con tamaños y hashes SHA-256.

## Artefactos tempranos

Después de crear una revisión nueva deberían aparecer muy pronto:

- `protocol/intake.md`
- `protocol/research-question.md`
- `protocol/eligibility-criteria.md`
- `protocol/search-strategy.md`
- `protocol/intake.json`
- `protocol/method-contract.json`
- `protocol/synthesis-plan.json`
- `protocol/journal-profile.json`
- `protocol/deliverables-contract.json`
- `protocol/contracts-manifest.json`
- `protocol/amendments.jsonl`
- `protocol/pending-amendment.json`, solo mientras una propuesta espera decisión
- `notes/runtime-state.json`

Estos archivos fijan el alcance y permiten releer el estado sin depender del
chat ni de la memoria del operador.

## Artefactos intermedios

Cuando la revisión entra en búsqueda, cribado y extracción, deberían aparecer:

- `searches/search-log.csv`
- `records/master-records.csv`
- `screening/title-abstract.csv`
- `screening/title-abstract-dual-review.csv`
- `screening/full-text.csv`
- `screening/full-text-dual-review.csv`
- `screening/screening-reliability.json`
- `screening/full-text-review-checkpoint.json`
- `screening/pending-disagreements.json`
- `screening/disagreement-resolutions.jsonl`
- `extraction/extraction-table.csv`
- `selection/ultraquality-shortlist.csv`
- `fulltext/docling/manifest.csv`
- `fulltext/docling/<doi>.json`
- `fulltext/docling/<doi>.md`
- `tables/source/<doi>-table-XX.csv`
- `tables/source/<doi>-table-XX.html`
- `figures/source/<doi>-figure-XX.png`

Después de extracción también se genera la capa estructural:

- `analysis/scientific-intelligence.json`
- `analysis/reading-priority.csv`
- `analysis/evidence/claim-position-matrix.csv`
- `analysis/evidence/evidence-position-summary.json`
- `analysis/evidence/consensus-disagreements-open-questions.md`
- `analysis/security/security-harness-comparison.csv` cuando el tema activa el subperfil de seguridad
- `analysis/security/dominance-frontier.csv` cuando el tema activa el subperfil de seguridad
- `analysis/security/security-harness-summary.json` cuando el tema activa el subperfil de seguridad
- `analysis/atlas/network-atlas.html`
- `analysis/data/nodes.csv`
- `analysis/data/edges.csv`
- `analysis/data/graph.graphml`
- `analysis/metrics/network-summary.json`
- `analysis/metrics/centrality.csv`
- `analysis/metrics/communities.csv`
- `analysis/metrics/author-production.csv`
- `analysis/metrics/selection-drift.csv`
- `analysis/audit/coverage.json`
- `analysis/audit/parameters.json`
- `analysis/audit/provenance.csv`
- `analysis/figures/png/topics-network.png`
- `analysis/figures/svg/topics-network.svg`
- `analysis/figures/png/authors-network.png`
- `analysis/figures/svg/authors-network.svg`

El atlas es autónomo y no descarga librerías al abrirse. Las tablas conservan
denominadores y permiten recalcular o cuestionar la lectura visual.

`claim-position-matrix.csv` clasifica la posición recuperable de cada estudio
para cada comparación: asociación positiva, negativa, nula, mixta o
condicionada, descriptiva o todavía incierta. El resumen separa convergencia,
desacuerdo direccional, evidencia inconsistente, patrones condicionados y
preguntas abiertas. No agrega por mayoría simple cuando diseño, población,
medición o contexto no son comparables.

La matriz conserva además `outcome_orientation` y `practical_valence` como
campos distintos. Esto evita presentar una reducción favorable de error o
latencia como si fuera un resultado práctico adverso solo porque su dirección
numérica es negativa. También distingue convergencia directa, alineación entre
contextos y alineación descriptiva.

`reading-priority.csv` ordena la atención humana por relevancia, transparencia
metodológica, evidencia localizable, reproducibilidad y capacidad de contrastar
la síntesis. Es una cola de lectura, no un segundo algoritmo de inclusión.
Centralidad, productividad y citas no aportan puntos ni cambian una decisión
`OK/KO`.

En revisiones de harnesses de seguridad,
`security-harness-comparison.csv` conserva por DOI la amenaza, la arquitectura
de control, el punto de enforcement, el atacante, el baseline, las métricas de
seguridad y los costes operativos. `dominance-frontier.csv` no elige un ganador
por mayoría ni agrega tasas incompatibles: solo identifica dónde existen las
dimensiones necesarias para contrastar una dominancia condicionada y dónde la
evidencia sigue siendo insuficiente.

Los campos `security_effect_evidence` y
`operational_tradeoff_evidence` distinguen `quantified`, `qualitative`,
`mention_only` y `missing`. Un encabezado, un nombre de métrica o una referencia
a una tabla no se promueve a resultado cuantificado. Del mismo modo,
`with_adaptive_attacker` solo cuenta evaluaciones adaptativas reales y
`with_open_artifact` exige una señal positiva de disponibilidad.

Cada vista se puede descargar en PNG o SVG para comunicación y en GEXF para
análisis en Gephi. La exportación conserva la capa, la fase y el filtro de
búsqueda activos; `analysis/data/graph.graphml` mantiene la red completa como
formato de intercambio independiente.

`figures/gallery.html` reúne el portfolio visual completo con estilo de
publicación universitaria. Separa figuras propuestas para el cuerpo,
suplementos y reserva editorial; cada ficha explica su función y permite
descargar PNG de alta resolución o SVG editable. La clasificación no obliga a
insertar todas las figuras en el artículo: el gate mantiene un máximo de cuatro
en el cuerpo y prioriza valor científico, densidad, no redundancia y
trazabilidad.

La figura de madurez de evidencia distingue alineación descriptiva, evidencia
insuficiente y preguntas abiertas. Las redes temática y de coautoría se
entregan también como activos estáticos; la primera puede entrar en el
manuscrito si supera cobertura y estabilidad, mientras la coautoría queda como
exploración suplementaria y nunca modifica la elegibilidad.

`fulltext/docling/manifest.csv` registra el hash exacto del PDF, estado,
duración, páginas, tablas, figuras, versión y error saneado. Los nombres de los
activos se derivan del DOI; no se publican identificadores internos.

`full-text-review-checkpoint.json` vincula los dos juicios con el protocolo y
el hash del texto completo. `pending-disagreements.json` conserva todos los
casos A/B, incluso después de resolverlos, y distingue cuántos siguen
pendientes. `disagreement-resolutions.jsonl` es un registro append-only de las
decisiones firmadas por DOI y de su razón científica.

Estos tres archivos son privados: preservan trazabilidad y reanudación, pero no
entran en el paquete público con identidades internas o datos de firma.

La memoria entre revisiones sigue la misma frontera. El catálogo
`.hermes/research-memory.json` vive en la raíz privada del workspace y cada
revisión recibe `notes/prior-research-context.json` y `.md`. Conservan consultas,
constructos, DOI y precedentes, pero marcan expresamente que una decisión previa
no puede reutilizarse como decisión científica actual. Estos archivos tampoco
entran en el ZIP público.

La auditoría artículo-código es opcional y, cuando se solicita, añade:

- `analysis/reproducibility/paper-code-consistency.csv`
- `analysis/reproducibility/paper-code-audit.json`
- `analysis/reproducibility/paper-code-audit.md`

La auditoría solo inventariaría repositorios declarados y, con permiso explícito,
consulta metadatos remotos de solo lectura. No descarga ni ejecuta código ajeno,
por lo que sus resultados son señales de reproducibilidad documental, no una
certificación de que el software reproduce los resultados del artículo.

## Artefactos de publicación

Cuando la capa editorial termina bien, deberían existir:

- `paper/manuscript/publication-ready.md`
- `paper/manuscript/publication-ready.tex`
- `paper/manuscript/publication-ready.pdf`
- `paper/audit/model-capabilities.json`
- `paper/audit/model-provenance.csv`
- `paper/audit/multimodal-pdf-verification.json`
- `paper/audit/extraction-provider-assessment.json`, cuando una fase rechaza un
  modelo o fallback después de evaluarlo
- `paper/audit/model-provenance-discarded-*.csv`, cuando existen llamadas cuyo
  resultado no alimenta la evidencia final
- `paper/audit/claim-evidence-ledger.csv`
- `paper/audit/evidence-coverage.json`
- `paper/audit/publication-gate.json`
- `paper/audit/gold/gold-manifest.json`
- `paper/audit/gold/title-abstract-gold.csv`
- `paper/audit/gold/full-text-gold.csv`
- `paper/audit/gold/extraction-gold.jsonl`
- `paper/package/index.html`
- `figures/gallery.html`
- `paper/package/deliverables-manifest.json`
- `paper/audit/publication-gate.md`
- `paper/package/publication-package.zip`
- `paper/package/publication-latex-editable.zip`
- `notes/artifact-lineage.json`

`model-provenance.csv` es un registro de llamadas, no una lista de resultados
aceptados. Conserva también intentos fallidos o descartados para que el consumo
y los fallos no desaparezcan de la auditoría. Los archivos de assessment y
provenance descartada explican qué salida se rechazó, por qué se repitió y qué
modelo produjo finalmente el artefacto utilizado.

`multimodal-pdf-verification.json` demuestra una capacidad distinta de la
conectividad o del reconocimiento de una tarjeta sintética. Renderiza la primera
página de un PDF científico de la revisión, pide al modelo visual recuperar el
título y compara la respuesta con la capa textual del mismo documento. Registra
modelo solicitado, modelo efectivo y resultado, pero nunca la API key.

El ZIP de publicación abre también con `index.html`. Sus anexos eliminan
`record_id`, convierten `assigned_doi` en `doi`, sustituyen nombres de PDF
internos por DOI y sanean rutas locales. Los registros sin DOI pueden conservarse
en conteos de exclusión, pero no reciben una identidad pública opaca.

El directorio `paper/audit/gold/` contiene la referencia operacional generada
durante el ciclo. El manifiesto declara si cada etiqueta procede de consenso,
recomendación o decisión investigadora firmada y deja explícito que no es un
ground truth humano externo.

`notes/artifact-lineage.json` registra, con rutas relativas, tamaño y SHA-256,
qué entradas materiales produjeron cada salida del ciclo. Sirve para verificar
derivación y detectar cambios; no demuestra por sí solo que una interpretación
sea científicamente válida. El linaje incrustado en el ZIP contiene las
derivaciones verificadas anteriores al empaquetado. Los comandos directos
`intelligence`, `memory` y `code-audit` actualizan también el estado material;
el paso privado `memory` se elimina del estado y linaje publicables.

## Los doce bloques de entrega

1. Método y protocolo: frontera científica, unidad de comparación y lógica de síntesis.
2. Corpus bibliográfico: búsquedas, DOI, duplicados y referencias.
3. Cribado y selección: decisión, motivo y frontera focal.
4. Biblioteca de texto completo: documentos, hashes y extracción estructurada.
5. Matriz de evidencia: método, variables, resultados, fragmentos y páginas.
6. Síntesis y análisis: appraisal, sensibilidad, redes y comunidades.
7. Figuras y tablas: fuente editable, versión de publicación y justificación.
8. Manuscrito publicable: Markdown, LaTeX, PDF, referencias y anexos.
9. Preparación editorial: peer review, roadmap, carta, declaraciones y checklists.
10. Auditoría y procedencia: modelos, evidencia, integridad y gates.
11. Reanudación y actualización: estado por contenido, jobs y eventos.
12. Exploración interactiva: atlas offline y exportación GraphML/GEXF.

## Qué significa todo esto

La revisión no es solo un output textual. Es un conjunto de artefactos que
permiten comprobar:

- qué se buscó
- qué se excluyó
- qué se extrajo
- cómo se relacionan autores, temas, referencias y dimensiones analíticas
- con qué cobertura y estabilidad puede interpretarse esa estructura
- cómo se redactó
- por qué se cerró o por qué sigue bloqueada
