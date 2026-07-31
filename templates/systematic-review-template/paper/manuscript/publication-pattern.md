# Patrón de Manuscrito Publicable para Revisiones Sistemáticas

Este patrón editorial resume la estructura que Hermes debe perseguir cuando genera un manuscrito `publication-ready.md` y su exportación `publication-ready.tex`.

## Base normativa y ejemplares

- PRISMA 2020 Statement: Page et al. (2021), BMJ, 372:n71. [BMJ](https://www.bmj.com/content/372/bmj.n71)
- PRISMA 2020 Checklist y abstract checklist. [PRISMA Statement](https://www.prisma-statement.org/prisma-2020-checklist)
- Ejemplar abierto en software engineering: Hou y Jansen, *A systematic literature review on trust in the software ecosystem*. [Springer](https://link.springer.com/article/10.1007/s10664-022-10238-y)
- Ejemplar reciente de revisión sistemática en SE con mapeo temático: *Unlocking the Potential of the Prompt Engineering Paradigm in Software Engineering: A Systematic Literature Review*. [MDPI](https://www.mdpi.com/2673-2688/6/9/206)

## Estructura objetivo

1. Título
   Título preciso, no publicitario, alineado con la pregunta de investigación y la ventana temporal.
2. Resumen
   Debe condensar problema, objetivo/pregunta, fuentes y criterios, conteos PRISMA principales, corpus final, hallazgos comparativos y aportación del artículo.
3. Palabras clave
   Entre 6 y 10 términos controlados. Usar versión en inglés solo si la revista lo exige.
4. Introducción
   Contexto del problema, brecha, necesidad de la revisión y pregunta de investigación explícita.
5. Marco teórico
   Familias conceptuales, tesis teóricas y estado de la discusión doctrinal del campo.
6. Método
   PRISMA 2020, fuentes, estrategia de búsqueda, elegibilidad, selección, recuperación PDF, extracción, confianza, síntesis focal y amenazas metodológicas del pipeline.
7. Resultados
   Flujo PRISMA, características del corpus, tablas comparativas, síntesis temática/arquitectónica y hallazgos empíricos.
8. Discusión
   Interpretación, comparación entre familias de estudios, implicaciones teóricas y prácticas, amenazas a la validez y aportación original.
9. Conclusiones
   Respuesta breve a la pregunta, valor del artículo y líneas futuras.
10. Declaraciones editoriales
   Financiación, conflictos, disponibilidad de datos/materiales y ajuste editorial.
11. Referencias
   APA consistente y resoluble desde el corpus.
12. Anexos y trazabilidad
   CSV, manifiestos, librería visual/tabular y PDFs focales.

## Resumen modelo

El resumen debe cubrir, en este orden:

1. Problema y brecha.
2. Pregunta de investigación u objetivo.
3. Método: PRISMA, fuentes, rango temporal y regla de PDF completo.
4. Resultados: identificados, evaluados en full text, incluidos y tamaño del subconjunto focal.
5. Hallazgo principal comparativo.
6. Aportación documental y metodológica del artículo.

## Figuras mínimas

- Figura 1. Diagrama PRISMA.
- Figura 2. Arquitectura operativa del pipeline, solo si el sistema o método es parte de la aportación.
- Figura 3. Mapa del corpus.
- Figura 4. Paisaje temático o de constructos.
- Figura 5. Matriz comparativa o diagrama de síntesis.
- Figura 6+. Solo si añaden valor analítico real.

Regla editorial:
- no usar páginas completas del PDF como figuras del manuscrito;
- preferir figuras científicas extraídas o capturas de región de figura;
- mantener el texto interno del SVG en ASCII para robustez tipográfica;
- reservar acentos y redacción rica para captions y cuerpo del manuscrito.

## Tablas mínimas

- Conteos PRISMA.
- Fuentes o queries.
- Reglas del subconjunto focal.
- Distribución del corpus.
- Comparativa estudio a estudio.
- Comparativa empírica.
- Sesgo/reporting o confianza de extracción.

## Criterios de estilo publicable

- Prosa compacta, sin tono promocional.
- Cada afirmación interpretativa debe estar anclada a varios estudios o a una tabla/figura.
- Evitar listas infinitas de papers; sintetizar por familias, patrones y diferencias.
- Separar claramente corpus incluido, subconjunto focal y evidencia suplementaria.
- Si una evidencia tiene confianza baja o extracción provisional, moverla al suplemento, no al núcleo analítico.

## Salida dual

- Fuente canónica de trabajo: `paper/manuscript/publication-ready.md`
- Exportación para Overleaf: `paper/manuscript/publication-ready.tex`
- Compilación obligatoria en el ciclo completo: `paper/manuscript/publication-ready.pdf`

Hermes debe generar primero un Markdown impecable y, a partir de él, exportar LaTeX con `export_publication_latex.py` usando `pandoc`, compilar el PDF y empaquetar ambos artefactos dentro del ciclo completo antes de declarar el artículo como publicable.
