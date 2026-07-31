# Auditoría de modos metodológicos Hermes

- Estado global: **PASS**
- Modos auditados: 6
- Problemas detectados: 0

## Política general
Hermes puede preguntar o ubicar el campo. Si el usuario declara un modo, se respeta. Si no lo declara y la inferencia es alta o media, se persiste la inferencia con justificación. Si la confianza es baja y la interfaz es interactiva, se formula una sola pregunta de campo. Si el flujo es autónomo, no se bloquea: se aplica common-core o modo mixto documentado y se deja trazabilidad en `protocol/review-mode.md`.

## Matriz de cobertura
| Modo | Etiqueta | Marco | Score Rel/Cal/Rep | Tablas mín. | Figuras mín. | Estado |
| --- | --- | --- | --- | --- | --- | --- |
| biomedical | Modo biomédico | PICO/PICOS | 0.35/0.40/0.25 | 5 | 3 | PASS |
| technical | Modo técnico | Sistema-tarea-benchmark-metrica | 0.50/0.35/0.15 | 5 | 3 | PASS |
| social_sciences | Modo ciencias sociales | SPIDER/PEO/PICo | 0.30/0.45/0.25 | 5 | 3 | PASS |
| education | Modo educación | SPIDER/PEO educativo | 0.32/0.43/0.25 | 5 | 3 | PASS |
| management | Modo management | CIMO/TCCM | 0.33/0.42/0.25 | 5 | 3 | PASS |
| mixed | Modo mixto | marco compuesto | 0.35/0.40/0.25 | 5 | 3 | PASS |

## Catálogo por campo

## Modo biomédico

- Campo interno: `biomedical`
- Marco por defecto: PICO/PICOS
- Unidad de comparación: poblacion-intervencion/exposicion-outcome
- Pregunta que puede hacerse al usuario: ¿La revisión pertenece a salud, clínica, biomedicina o epidemiología y debe formularse con PICO/PICOS?
- Score focal: Rel=0.35, Cal=0.40, Rep=0.25

### Cuándo preguntar o inferir
- Preguntar solo si hay señales de salud mezcladas con educación, tecnología o ciencias sociales y la unidad de análisis no está clara.
- Inferir sin preguntar cuando aparecen población, intervención/exposición, outcome, ensayo, cohorte, paciente, clínica, hospital o salud pública.
- En modo autónomo, si la confianza es baja, usar common-core documentado y no bloquear el ciclo.

### Qué debe buscar y extraer
- poblacion
- intervencion/exposicion
- comparador
- outcome
- diseno
- ventana temporal

### Fuentes recomendadas
- PubMed
- Europe PMC
- OpenAlex
- Crossref
- Semantic Scholar
- ClinicalTrials.gov cuando aplique

### Evaluación crítica
- aleatorizacion o confounding
- comparador
- medicion del outcome
- datos faltantes
- selective reporting
- precision del efecto

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Tabla PICO/PICOS o PECO con población, intervención/exposición, comparador, outcomes y diseño.
- Características de estudios incluidos: país, muestra, diseño, intervención/exposición, outcome y fuente.
- Matriz de riesgo de sesgo o evaluación crítica por estudio.
- Matriz de certeza o perfil de evidencia cuando el corpus lo permita.

### Figuras con valor analítico
- Mapa población-outcome cuando mejora la lectura de la evidencia.
- Resumen visual de riesgo de sesgo si hay suficiente N y variedad de dominios.
- Figura de mecanismo clínico solo si el corpus sostiene una relación interpretable.

### Salidas específicas
- PICO/PICOS auditado.
- Risk-of-bias matrix.
- GRADE-style certainty note cuando proceda.
- Lista de outcomes primarios y secundarios.

### Requisitos de escritura
- Método con fuentes biomédicas, fecha exacta de búsqueda, PICO/PICOS y herramienta de riesgo de sesgo.
- Resultados separados por outcome y por diseño.
- Discusión que diferencie efecto, certeza, heterogeneidad y aplicabilidad clínica.
- Conclusiones que no conviertan asociación en causalidad si el diseño no lo permite.

### Red flags
- No declarar población u outcome.
- Usar estudios sin distinguir ensayo, observacional, revisión o protocolo.
- Citar resultados clínicos sin riesgo de sesgo.
- Generalizar a pacientes o práctica clínica sin evidencia suficiente.

### Qué lo hace sobresaliente
- La pregunta queda operacionalizada antes de buscar.
- Cada conclusión sustantiva tiene outcome, diseño y certeza identificables.
- Las figuras son analíticas, no decorativas.
- El lector puede recomputar selección, exclusión y evaluación crítica desde CSV.
## Modo técnico

- Campo interno: `technical`
- Marco por defecto: Sistema-tarea-benchmark-metrica
- Unidad de comparación: configuracion tecnica del sistema
- Pregunta que puede hacerse al usuario: ¿La revisión compara sistemas técnicos, arquitecturas, modelos, datasets, benchmarks o métricas?
- Score focal: Rel=0.50, Cal=0.35, Rep=0.15

### Cuándo preguntar o inferir
- Preguntar solo si la pregunta técnica también es claramente social, educativa o de management y no se sabe qué unidad manda.
- Inferir sin preguntar cuando aparecen arquitectura, sistema, benchmark, dataset, métrica, modelo, agente, pipeline, coste, latencia o robustez.
- En modo autónomo, elegir técnico si la unidad real es configuración de sistema aunque el dominio de aplicación sea humano.

### Qué debe buscar y extraer
- sistema o arquitectura
- tarea
- dataset o corpus
- benchmark
- metrica
- reproducibilidad

### Fuentes recomendadas
- OpenAlex
- Crossref
- Semantic Scholar
- arXiv
- OpenAIRE
- Lens

### Evaluación crítica
- descripcion arquitectonica
- baseline o comparador
- dataset
- metrica
- ablation
- replicabilidad
- coste/latencia

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Matriz sistema-arquitectura-componentes.
- Tabla dataset-benchmark-métrica-baseline.
- Tabla de reproducibilidad: código, datos, prompts, configuración, coste y entorno.
- Tabla de resultados observados con límites de comparabilidad.

### Figuras con valor analítico
- Arquitectura o taxonomía técnica generada por Hermes a partir del corpus.
- Mapa de cobertura benchmark-dataset-métrica.
- Matriz visual tarea-componente-resultado si reduce complejidad.

### Salidas específicas
- Architecture grammar.
- Benchmark comparability matrix.
- Reproducibility and artifact checklist.
- System-level contribution statement.

### Requisitos de escritura
- Método que explique cómo se comparan sistemas completos, no solo nombres de modelos.
- Resultados con arquitectura, dataset, métrica, baseline y limitación por estudio.
- Discusión centrada en configuraciones, no en rankings oportunistas.
- Implicaciones prácticas por tarea, coste, robustez y condiciones de uso.

### Red flags
- Confundir modelo base con arquitectura completa.
- Comparar benchmarks incompatibles como si fueran equivalentes.
- No reportar dataset, métrica o baseline.
- Incluir figuras de papers fuente sin aporte analítico propio.

### Qué lo hace sobresaliente
- La unidad de comparación es el sistema completo.
- La síntesis identifica gramática técnica reutilizable.
- Las tablas permiten ver qué se evaluó, cómo y contra qué.
- Las limitaciones separan rendimiento local de generalización.
## Modo ciencias sociales

- Campo interno: `social_sciences`
- Marco por defecto: SPIDER/PEO/PICo
- Unidad de comparación: constructo-contexto-metodo-evidencia
- Pregunta que puede hacerse al usuario: ¿La revisión estudia fenómenos, constructos, actores, contextos, teorías o mecanismos sociales?
- Score focal: Rel=0.30, Cal=0.45, Rep=0.25

### Cuándo preguntar o inferir
- Preguntar si la pregunta habla de personas, organizaciones o instituciones pero no define si prima educación, management, salud o ciencias sociales generales.
- Inferir sin preguntar cuando aparecen constructo, contexto, percepción, comportamiento, ideología, cultura, encuesta, entrevista, caso o teoría social.
- En modo autónomo, usar ciencias sociales como common-core si no hay señales disciplinares fuertes.

### Qué debe buscar y extraer
- fenomeno
- poblacion o caso
- constructo
- contexto
- metodo
- tipo de evidencia
- limite de transferencia

### Fuentes recomendadas
- OpenAlex
- Crossref
- Semantic Scholar
- OpenAIRE
- Lens

### Evaluación crítica
- claridad del constructo
- marco teorico
- contexto
- muestra/caso
- metodo y recogida de datos
- reflexividad
- coherencia analitica
- transferibilidad

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Tabla constructo-teoría-contexto-método.
- Tabla muestra/caso/población y contexto territorial o institucional.
- Tabla de diseños y técnicas de recogida/análisis de datos.
- Matriz de mecanismos, resultados y límites de transferibilidad.

### Figuras con valor analítico
- Mapa conceptual de constructos y relaciones.
- Mapa temático de mecanismos-contextos-resultados.
- Evidence gap map por población, contexto y método.

### Salidas específicas
- Construct-theory-method matrix.
- Transferability note.
- Context and mechanism synthesis.
- Confidence-in-synthesis statement.

### Requisitos de escritura
- Marco teórico que nombre constructos y familias conceptuales antes de contar papers.
- Método que no penalice lo cualitativo por no ser experimental.
- Resultados que separen hallazgo, mecanismo plausible y contexto.
- Conclusiones que declaren certeza, señal emergente y vacío crítico.

### Red flags
- Reducir constructos complejos a frecuencias sin teoría.
- No reportar contexto, muestra o unidad de análisis.
- Tratar evidencia cualitativa como si fuese causalidad estadística.
- Presentar transferibilidad como generalización universal.

### Qué lo hace sobresaliente
- Cada concepto clave tiene definición operativa o límite explícito.
- La síntesis explica por qué los resultados podrían variar por contexto.
- Las figuras ayudan a ver mecanismos, no adornan.
- Las líneas futuras salen de vacíos diagnosticados, no de frases genéricas.
## Modo educación

- Campo interno: `education`
- Marco por defecto: SPIDER/PEO educativo
- Unidad de comparación: actividad educativa-sistema-contexto-resultado
- Pregunta que puede hacerse al usuario: ¿La revisión se centra en aprendizaje, docencia, profesorado, estudiantes, evaluación, feedback o instituciones educativas?
- Score focal: Rel=0.32, Cal=0.43, Rep=0.25

### Cuándo preguntar o inferir
- Preguntar si la pregunta mezcla tecnología educativa con arquitectura técnica y no está claro si prima el sistema o la práctica pedagógica.
- Inferir sin preguntar cuando aparecen docente, estudiante, aprendizaje, enseñanza, evaluación, feedback, universidad, currículo o pedagogía.
- En modo autónomo, educación manda cuando el outcome principal es pedagógico o docente.

### Qué debe buscar y extraer
- nivel educativo
- rol docente/estudiante
- actividad pedagogica
- tecnologia o practica
- resultado educativo
- contexto institucional
- equidad/etica

### Fuentes recomendadas
- ERIC
- OpenAlex
- Crossref
- Semantic Scholar
- OpenAIRE
- Lens

### Evaluación crítica
- alineacion pedagogica
- contexto institucional
- muestra o participantes
- instrumento educativo
- resultado de aprendizaje/docencia
- comparador
- etica/equidad
- transferibilidad

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Tabla nivel educativo-actor-actividad pedagógica.
- Tabla herramienta/práctica-resultados educativos-instrumento de evaluación.
- Tabla muestra, institución, país/contexto y duración.
- Matriz de ética, equidad, carga docente y gobernanza cuando aparezcan.

### Figuras con valor analítico
- Mapa actividad pedagógica-actor-resultado.
- Diagrama de flujo docente/estudiante si ayuda a replicar la intervención.
- Mapa de adopción y gobernanza educativa.

### Salidas específicas
- Pedagogical activity matrix.
- Learning/teaching outcome map.
- Institutional context and equity note.
- Teacher workload and governance note when available.

### Requisitos de escritura
- Marco teórico educativo con nivel, actor, actividad y resultado definidos.
- Método que distinga percepción, adopción, aprendizaje, calidad docente y evaluación.
- Resultados que no confundan satisfacción con mejora de aprendizaje.
- Implicaciones prácticas accionables para docentes, universidades y responsables académicos.

### Red flags
- No indicar nivel educativo o actor principal.
- Usar percepciones como si fueran resultados de aprendizaje.
- Ignorar equidad, privacidad, carga de trabajo o integridad académica.
- No explicar instrumento o criterio de evaluación.

### Qué lo hace sobresaliente
- El lector sabe qué cambia en la práctica docente o de aprendizaje.
- La síntesis separa herramienta, actividad pedagógica y outcome.
- Las tablas sirven para tomar decisiones institucionales.
- Las líneas futuras derivan de fallos de evidencia educativa detectados.
## Modo management

- Campo interno: `management`
- Marco por defecto: CIMO/TCCM
- Unidad de comparación: teoria-contexto-variable-metodo-resultado
- Pregunta que puede hacerse al usuario: ¿La revisión pertenece a management, estrategia, organizaciones, liderazgo, gobierno corporativo, innovación o desempeño empresarial?
- Score focal: Rel=0.33, Cal=0.42, Rep=0.25

### Cuándo preguntar o inferir
- Preguntar si la pregunta habla de organizaciones pero no aclara si la unidad principal es firma, directivo, equipo, sector, política pública o tecnología.
- Inferir sin preguntar cuando aparecen firma, empresa, estrategia, liderazgo, CEO, consejo, gobierno corporativo, innovación, desempeño o variables organizativas.
- En modo autónomo, management manda cuando el resultado es una decisión, práctica o performance de organización.

### Qué debe buscar y extraer
- nivel de analisis
- contexto organizativo
- constructo o variable independiente
- resultado estrategico
- mecanismo
- moderador/mediador
- metodo y endogeneidad

### Fuentes recomendadas
- OpenAlex
- Crossref
- Semantic Scholar
- OpenAIRE
- Lens

### Evaluación crítica
- teoria declarada
- unidad de analisis
- operacionalizacion de variables
- muestra/firma/sector/pais
- identificacion causal o control de endogeneidad
- comparador/baseline
- robustez
- alcance de generalizacion

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Tabla TCCM/CIMO: teoría, contexto, características, método y resultado.
- Tabla de variables: dependiente, independiente, mediadora, moderadora y controles.
- Tabla muestra/sector/país/nivel de análisis.
- Tabla de identificación empírica: endogeneidad, comparador, robustez y límites causales.

### Figuras con valor analítico
- Mapa teórico de variables y mecanismos.
- Diagrama de cautela causal: asociación, mecanismo, moderador y resultado.
- Matriz visual contexto-método-resultado si aporta lectura comparada.

### Salidas específicas
- TCCM/CIMO synthesis.
- Variable role matrix.
- Endogeneity and robustness note.
- Managerial decision implications.

### Requisitos de escritura
- Marco teórico con unidad de análisis, teoría y constructos organizativos.
- Método que evalúe identificación, controles, muestra, sector, país y robustez.
- Resultados que separen asociación, mecanismo y causalidad.
- Aportación original que explique qué cambia para la comparación acumulativa del campo.

### Red flags
- No declarar unidad de análisis.
- No separar variable dependiente, independiente, moderadora, mediadora y controles.
- Afirmar causalidad con diseños transversales o meramente correlacionales.
- No reportar sector, país, muestra o estrategia de identificación.

### Qué lo hace sobresaliente
- La revisión produce una gramática de comparación para decisiones organizativas.
- Las conclusiones dicen qué está establecido, qué es señal y qué sigue vacío.
- Las tablas permiten reconstruir teoría, variables, método y resultado.
- Las implicaciones prácticas son útiles para dirección sin sobreprometer causalidad.
## Modo mixto

- Campo interno: `mixed`
- Marco por defecto: marco compuesto
- Unidad de comparación: unidad compuesta declarada por modo principal
- Pregunta que puede hacerse al usuario: ¿La revisión combina más de un campo y necesitas declarar cuál es el modo principal y cuáles son secundarios?
- Score focal: Rel=0.35, Cal=0.40, Rep=0.25

### Cuándo preguntar o inferir
- Preguntar cuando dos o más modos tienen señales similares y la unidad de análisis cambia según el campo elegido.
- Inferir modo mixto cuando la pregunta combina de forma sustantiva sistema técnico, fenómeno social, educación, salud o management.
- En modo autónomo, fijar un modo principal y documentar qué salvaguardas hereda de los secundarios.

### Qué debe buscar y extraer
- unidad principal
- contexto
- constructo o sistema
- metodo
- resultado
- transferibilidad

### Fuentes recomendadas
- OpenAlex
- Crossref
- Semantic Scholar
- OpenAIRE
- Lens

### Evaluación crítica
- ajuste epistemico pregunta-metodo
- claridad de unidad de analisis
- contexto
- comparador o mecanismo
- calidad metodologica
- transferibilidad

### Tablas mínimas
- Flujo de selección de estudios como tabla metodológica.
- Tabla de modo principal/secundario y reglas heredadas.
- Matriz de tipos de evidencia y unidad de comparación.
- Tabla de evaluación crítica por familia metodológica.
- Tabla de integración: qué evidencia sostiene cada conclusión.

### Figuras con valor analítico
- Arquitectura de síntesis por capas.
- Mapa de integración entre modos y tipos de evidencia.
- Figura de límites: qué puede compararse y qué no.

### Salidas específicas
- Primary-secondary mode contract.
- Cross-mode appraisal matrix.
- Two-level synthesis note.
- Boundary and comparability statement.

### Requisitos de escritura
- Método que declare qué modo decide la unidad de análisis.
- Resultados separados por lógica de evidencia antes de integrarlos.
- Discusión que no mezcle causalidad, transferencia y rendimiento como si fueran una misma magnitud.
- Conclusión con alcance explícito por dominio.

### Red flags
- Usar mixto como cajón de sastre.
- No declarar modo principal.
- Aplicar una única herramienta de calidad a diseños incompatibles.
- Fusionar resultados heterogéneos sin explicar equivalencias.

### Qué lo hace sobresaliente
- El modo principal gobierna la pregunta y los secundarios añaden controles.
- La síntesis separa niveles antes de integrarlos.
- La evidencia no se fuerza en una métrica falsa.
- El paper explica sus fronteras sin debilitar la aportación.

## Regla editorial transversal
Una figura o tabla entra en el cuerpo del paper solo si reduce complejidad, muestra una relación analítica, permite auditar una decisión o sostiene una tesis. Si solo decora, se mueve a anexo o se elimina.
