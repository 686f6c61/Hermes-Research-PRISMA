# Gate de calidad

Este documento fija dos límites distintos: cuándo una revisión puede llamarse
lista para publicación y cuándo una versión de Hermes Research Pack puede
distribuirse. Ninguno depende de una impresión conversacional ni de que un
modelo declare que ha terminado.

## Gate de una revisión

Una revisión solo puede cerrar cuando existen y son coherentes, como mínimo:

- protocolo y contratos versionados en `protocol/`;
- búsquedas, corpus DOI y decisiones de cribado;
- doble juicio de título/resumen y texto completo;
- métricas de fiabilidad y todas las discrepancias resueltas;
- biblioteca de texto completo legible;
- matriz de extracción y shortlist trazable;
- manuscrito Markdown, LaTeX editable y PDF;
- referencias, figuras y tablas materiales;
- revisión independiente e informe de integridad;
- ledger de afirmaciones y cobertura de evidencia;
- guía HTML, manifiesto de entregables y dos ZIP finales;
- publication gate en Markdown y JSON.

El archivo `paper/audit/publication-gate.md` debe declarar
`Estado global: **PASS**`. Un PASS determinista no sustituye un peer review que
bloquee el manuscrito ni una aprobación investigadora exigida por el modo de
validación.

## Gate de decisiones

- Título/resumen conserva los desacuerdos como `maybe`; no los convierte en
  exclusiones silenciosas.
- Texto completo requiere dos juicios independientes. Si discrepan, la
  recomendación automática no es vinculante.
- Todo desacuerdo de texto completo debe resolverse por DOI, con razón
  científica y firma válida para el protocolo y evidencia exactos.
- `waiting_for_researcher` es un checkpoint recuperable, no un fallo ni una
  autorización para que el watchdog decida.
- Un cambio material del protocolo debe mostrar su impacto y recibir aprobación
  firmada antes de aplicarse.
- En modo `adjudicated`, `paper/audit/human-adjudication.json` debe validar antes
  del cierre.

## Reglas científicas

- El manuscrito distingue corpus incluido y subconjunto focal.
- Si existe subconjunto focal, el método declara fórmula, hard gates, rango de
  N, ranking, sensibilidad y estudios incluidos no focales.
- Ningún estudio entra en la síntesis final sin texto completo local, legible y
  vinculado a su DOI.
- Ausencia de reporte no se transforma en cero, evidencia negativa ni dato
  inferido.
- Las afirmaciones críticas enlazan citas, DOI, fragmento y localización en
  `claim-evidence-ledger.csv`.
- El appraisal y la síntesis obedecen al perfil metodológico declarado o
  inferido: biomédico, técnico, ciencias sociales, educación, management o
  mixto.
- PRISMA describe el flujo de selección; no sustituye teoría, análisis crítico,
  comparación, discusión ni aportación del artículo.
- Las citas en texto y la bibliografía son internamente consistentes.

## Reglas de figuras y tablas

- Cada visual responde a una pregunta analítica y declara fuente o procedencia.
- Una figura extraída de otro paper solo entra si aporta evidencia necesaria en
  ese contexto.
- Ningún texto, leyenda, caja o tabla puede salir de los márgenes del PDF.
- Las tablas no usan puntos suspensivos para ocultar filas ni convierten `NA` en
  cero.
- Tipografía, jerarquía y tamaño son coherentes con el manuscrito.
- Los activos fuente, las versiones de publicación y su justificación quedan
  preservados.

## Referencia operacional

`paper/audit/gold/gold-manifest.json` distingue consenso automático,
recomendación y decisión investigadora firmada. Ese conjunto permite regresión
y repetibilidad, pero debe declarar `external_human_ground_truth: false` salvo
que especialistas externos hayan adjudicado realmente el corpus.

Las fixtures sintéticas demuestran que el evaluador funciona; no demuestran
calidad científica del modelo.

## Higiene de una release

El repositorio y los ZIP públicos deben excluir:

- API keys, tokens, secretos de adjudicación y credenciales Docling;
- `.env`, estado runtime, corpus, PDF privados y logs de investigación;
- rutas locales, URLs privadas y nombres de archivo internos;
- identificadores `RID-*`, `record_id` u otras identidades públicas opacas;
- cachés, bytecode y artefactos temporales.

Los ejemplos usan `HERMES_INFERENCE_API_KEY` y valores inertes. El paquete
público conserva DOI y procedencia suficiente, nunca la firma secreta ni datos
personales innecesarios.

## Validación obligatoria de la release

```bash
make check
make plugin-only
bash scripts/security-audit.sh
REQUIRE_CLEAN_RELEASE=1 ./hermes-research ship-release
```

El cierre exige:

1. tests en Python 3.11 y 3.13;
2. lint, shell, metadatos y Compose válidos;
3. imagen construida desde Hermes upstream fijado;
4. integración plugin-only sin overlays del núcleo;
5. cero secretos detectados;
6. cero vulnerabilidades HIGH/CRITICAL corregibles;
7. SBOM CycloneDX;
8. ZIP con SHA-256 y manifiesto de archivos;
9. extracción e instalación clean-room;
10. descarga de la release y nueva verificación del checksum.

Si falla un punto, no se etiqueta ni se comparte el ZIP. La corrección vuelve a
recorrer la cadena completa.
