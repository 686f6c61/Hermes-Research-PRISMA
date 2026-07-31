# Estructura de una revisión terminada

Cada revisión vive en su propio directorio dentro de `runtime/workspace`. Este
es un esquema abreviado; la lista contractual completa está en
`tests/expected-artifacts.md`.

```text
mi-revision/
├── protocol/                 # pregunta, alcance, criterios y búsqueda
├── searches/                 # consultas ejecutadas y resultados originales
├── records/                  # corpus normalizado, DOI y duplicados
├── screening/                # decisiones de título/resumen y texto completo
├── fulltext/                 # PDF, texto, HTML y extracción Docling
├── extraction/               # matriz de variables y evidencia por estudio
├── selection/                # corpus incluido y subconjunto focal
├── figures/                  # figuras fuente, manifiestos y figuras del paper
├── tables/                   # datos fuente y tablas finales
├── notes/                    # estado material y trazabilidad de ejecución
└── paper/
    ├── manuscript/           # Markdown, LaTeX editable y PDF
    ├── review/               # revisión independiente y hoja de cambios
    ├── audit/                # auditorías científica, editorial y de integridad
    └── package/              # paquetes finales para edición o envío
```

Los nombres de estudios expuestos en tablas y anexos usan DOI. Los
identificadores internos solo sirven para el funcionamiento local y no forman
parte del manuscrito publicable.
