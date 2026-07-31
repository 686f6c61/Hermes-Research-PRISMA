#!/usr/bin/env python3
"""Discipline-aware review-mode router for Hermes systematic reviews.

The router is intentionally deterministic. It gives Hermes a methodological
stance before search, screening, appraisal and writing start, so a social
science review is not judged with a biomedical or purely technical template.
"""

from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from copy import deepcopy

REVIEW_MODE_VERSION = "HERMES-REVIEW-MODE/2026-05-v1"

MODE_ORDER = [
    "biomedical",
    "technical",
    "social_sciences",
    "education",
    "management",
    "mixed",
]

MODE_ALIASES = {
    "biomedico": "biomedical",
    "biomedica": "biomedical",
    "biomed": "biomedical",
    "biomedical": "biomedical",
    "clinical": "biomedical",
    "clinico": "biomedical",
    "clinica": "biomedical",
    "salud": "biomedical",
    "tecnico": "technical",
    "tecnica": "technical",
    "technical": "technical",
    "ingenieria": "technical",
    "engineering": "technical",
    "software": "technical",
    "ciencias sociales": "social_sciences",
    "ciencia social": "social_sciences",
    "social": "social_sciences",
    "social_sciences": "social_sciences",
    "social sciences": "social_sciences",
    "educacion": "education",
    "education": "education",
    "educativo": "education",
    "educativa": "education",
    "pedagogia": "education",
    "management": "management",
    "direccion": "management",
    "empresa": "management",
    "negocio": "management",
    "strategy": "management",
    "estrategia": "management",
    "organizaciones": "management",
    "organizacion": "management",
    "mixto": "mixed",
    "mixed": "mixed",
    "hibrido": "mixed",
    "hybrid": "mixed",
}


MODE_CONFIG: dict[str, dict[str, object]] = {
    "biomedical": {
        "label_es": "biomedico",
        "label_public_es": "Modo biomédico",
        "default_framework": "PICO/PICOS",
        "question_frameworks": ["PICO", "PICOS", "PECO", "PIRD"],
        "core_logic": (
            "Compara poblacion, intervencion o exposicion, comparador, outcomes, "
            "diseno y riesgo de sesgo."
        ),
        "primary_unit": "poblacion-intervencion/exposicion-outcome",
        "recommended_sources": [
            "PubMed",
            "Europe PMC",
            "OpenAlex",
            "Crossref",
            "Semantic Scholar",
            "ClinicalTrials.gov cuando aplique",
        ],
        "optional_sources": ["Embase", "CINAHL", "PsycINFO", "Cochrane Library", "Scopus", "Web of Science"],
        "screening_axes": [
            "poblacion",
            "intervencion/exposicion",
            "comparador",
            "outcome",
            "diseno",
            "ventana temporal",
        ],
        "appraisal_tools": ["RoB 2", "ROBINS-I", "JBI", "ROBIS", "AMSTAR 2", "GRADE"],
        "critical_appraisal_domains": [
            "aleatorizacion o confounding",
            "comparador",
            "medicion del outcome",
            "datos faltantes",
            "selective reporting",
            "precision del efecto",
        ],
        "synthesis_modes": ["meta-analisis si procede", "sintesis narrativa", "GRADE evidence profile"],
        "selection_score_weights": {"relevance": 0.35, "quality": 0.40, "representativeness": 0.25},
        "writing_rules": [
            "Separar inclusion en revision de certeza del efecto.",
            "No inferir causalidad si el diseno no la sostiene.",
            "Reportar riesgo de sesgo con instrumento nombrado cuando el corpus lo permita.",
        ],
    },
    "technical": {
        "label_es": "tecnico",
        "label_public_es": "Modo técnico",
        "default_framework": "Sistema-tarea-benchmark-metrica",
        "question_frameworks": ["sistema-tarea-benchmark-metrica", "arquitectura-capacidad-evaluacion", "pipeline-dataset-resultado"],
        "core_logic": (
            "Compara sistemas tecnicos, arquitecturas, componentes, datasets, benchmarks, "
            "metricas, coste, latencia, robustez y reproducibilidad."
        ),
        "primary_unit": "configuracion tecnica del sistema",
        "recommended_sources": ["OpenAlex", "Crossref", "Semantic Scholar", "arXiv", "OpenAIRE", "Lens"],
        "optional_sources": ["ACM Digital Library", "IEEE Xplore", "DBLP", "Scopus", "Web of Science"],
        "screening_axes": [
            "sistema o arquitectura",
            "tarea",
            "dataset o corpus",
            "benchmark",
            "metrica",
            "reproducibilidad",
        ],
        "appraisal_tools": ["rubro de reproducibilidad", "benchmark validity", "ablation/robustness checklist"],
        "critical_appraisal_domains": [
            "descripcion arquitectonica",
            "baseline o comparador",
            "dataset",
            "metrica",
            "ablation",
            "replicabilidad",
            "coste/latencia",
        ],
        "synthesis_modes": ["sintesis arquitectonica", "taxonomia tecnica", "comparacion por benchmark", "configurational synthesis"],
        "selection_score_weights": {"relevance": 0.50, "quality": 0.35, "representativeness": 0.15},
        "writing_rules": [
            "Comparar sistemas completos y no solo modelos base.",
            "Separar rendimiento reportado de condiciones de ejecucion.",
            "No convertir un benchmark aislado en superioridad general.",
        ],
    },
    "social_sciences": {
        "label_es": "ciencias_sociales",
        "label_public_es": "Modo ciencias sociales",
        "default_framework": "SPIDER/PEO/PICo",
        "question_frameworks": ["SPIDER", "PEO", "PICo", "teoria-contexto-metodo-evidencia"],
        "core_logic": (
            "Compara fenomenos, constructos, poblaciones, contextos, teorias, metodos, "
            "mecanismos, transferibilidad y limites de inferencia."
        ),
        "primary_unit": "constructo-contexto-metodo-evidencia",
        "recommended_sources": ["OpenAlex", "Crossref", "Semantic Scholar", "OpenAIRE", "Lens"],
        "optional_sources": ["Scopus", "Web of Science", "PsycINFO", "Sociological Abstracts", "ERIC", "SSRN"],
        "screening_axes": [
            "fenomeno",
            "poblacion o caso",
            "constructo",
            "contexto",
            "metodo",
            "tipo de evidencia",
            "limite de transferencia",
        ],
        "appraisal_tools": ["CASP", "JBI", "MMAT", "AXIS", "CERQual", "AACODS"],
        "critical_appraisal_domains": [
            "claridad del constructo",
            "marco teorico",
            "contexto",
            "muestra/caso",
            "metodo y recogida de datos",
            "reflexividad",
            "coherencia analitica",
            "transferibilidad",
        ],
        "synthesis_modes": ["thematic synthesis", "framework synthesis", "realist synthesis", "narrative synthesis", "CERQual-style confidence"],
        "selection_score_weights": {"relevance": 0.30, "quality": 0.45, "representativeness": 0.25},
        "writing_rules": [
            "No penalizar un estudio cualitativo por no ser experimental si la pregunta es interpretativa.",
            "Separar resultado observado, mecanismo plausible y contexto de validez.",
            "Nombrar constructos y teorias antes de contar frecuencias.",
        ],
    },
    "education": {
        "label_es": "educacion",
        "label_public_es": "Modo educación",
        "default_framework": "SPIDER/PEO educativo",
        "question_frameworks": ["SPIDER", "PEO", "PICo", "CIMO educativo"],
        "core_logic": (
            "Compara actividad educativa, rol docente/estudiante, contexto institucional, "
            "intervencion o herramienta, resultado pedagogico, adopcion y gobernanza."
        ),
        "primary_unit": "actividad educativa-sistema-contexto-resultado",
        "recommended_sources": ["ERIC", "OpenAlex", "Crossref", "Semantic Scholar", "OpenAIRE", "Lens"],
        "optional_sources": ["Education Source", "Scopus", "Web of Science", "PsycINFO", "Google Scholar para seguimiento manual"],
        "screening_axes": [
            "nivel educativo",
            "rol docente/estudiante",
            "actividad pedagogica",
            "tecnologia o practica",
            "resultado educativo",
            "contexto institucional",
            "equidad/etica",
        ],
        "appraisal_tools": ["MMAT", "JBI", "CASP", "WWC cuando proceda", "CERQual"],
        "critical_appraisal_domains": [
            "alineacion pedagogica",
            "contexto institucional",
            "muestra o participantes",
            "instrumento educativo",
            "resultado de aprendizaje/docencia",
            "comparador",
            "etica/equidad",
            "transferibilidad",
        ],
        "synthesis_modes": ["sintesis tematica", "framework synthesis", "mapa tarea-resultado", "narrative synthesis"],
        "selection_score_weights": {"relevance": 0.32, "quality": 0.43, "representativeness": 0.25},
        "writing_rules": [
            "No reducir educacion a percepciones si hay resultados pedagogicos disponibles.",
            "Separar adopcion, calidad docente, aprendizaje, evaluacion, feedback, carga de trabajo y gobernanza.",
            "Declarar nivel educativo y contexto institucional antes de generalizar.",
        ],
    },
    "management": {
        "label_es": "management",
        "label_public_es": "Modo management",
        "default_framework": "CIMO/TCCM",
        "question_frameworks": ["CIMO", "TCCM", "teoria-contexto-caracteristicas-metodo", "variables-mecanismos-resultados"],
        "core_logic": (
            "Compara teoria, contexto, unidad organizativa, variables, mecanismos, "
            "moderadores, mediadores, metodo, endogeneidad y decisiones directivas."
        ),
        "primary_unit": "teoria-contexto-variable-metodo-resultado",
        "recommended_sources": ["OpenAlex", "Crossref", "Semantic Scholar", "OpenAIRE", "Lens"],
        "optional_sources": ["Scopus", "Web of Science", "ABI/INFORM", "Business Source Complete", "SSRN", "EconLit"],
        "screening_axes": [
            "nivel de analisis",
            "contexto organizativo",
            "constructo o variable independiente",
            "resultado estrategico",
            "mecanismo",
            "moderador/mediador",
            "metodo y endogeneidad",
        ],
        "appraisal_tools": ["TCCM", "CIMO", "JBI", "MMAT", "AXIS", "ROBINS-I adaptado", "endogeneity checklist"],
        "critical_appraisal_domains": [
            "teoria declarada",
            "unidad de analisis",
            "operacionalizacion de variables",
            "muestra/firma/sector/pais",
            "identificacion causal o control de endogeneidad",
            "comparador/baseline",
            "robustez",
            "alcance de generalizacion",
        ],
        "synthesis_modes": ["TCCM synthesis", "CIMO synthesis", "framework synthesis", "configurational synthesis", "narrative causal caution"],
        "selection_score_weights": {"relevance": 0.33, "quality": 0.42, "representativeness": 0.25},
        "writing_rules": [
            "Separar correlacion, asociacion, mecanismo y causalidad.",
            "Extraer variables dependientes, independientes, moderadoras, mediadoras y controles cuando existan.",
            "No presentar senales de estrategia o liderazgo como efectos causales si el diseno no identifica causalidad.",
        ],
    },
    "mixed": {
        "label_es": "mixto",
        "label_public_es": "Modo mixto",
        "default_framework": "marco compuesto",
        "question_frameworks": ["marco compuesto", "SPIDER+CIMO", "PICO+framework synthesis", "sistema-contexto-resultado"],
        "core_logic": (
            "Combina reglas del modo principal y secundario sin convertir el corpus en un cajon metodologico. "
            "El modo principal decide la unidad de analisis; los secundarios anaden controles."
        ),
        "primary_unit": "unidad compuesta declarada por modo principal",
        "recommended_sources": ["OpenAlex", "Crossref", "Semantic Scholar", "OpenAIRE", "Lens"],
        "optional_sources": ["bases especializadas segun modos secundarios"],
        "screening_axes": [
            "unidad principal",
            "contexto",
            "constructo o sistema",
            "metodo",
            "resultado",
            "transferibilidad",
        ],
        "appraisal_tools": ["MMAT", "JBI", "framework-specific checklist", "CERQual/GRADE segun corpus"],
        "critical_appraisal_domains": [
            "ajuste epistemico pregunta-metodo",
            "claridad de unidad de analisis",
            "contexto",
            "comparador o mecanismo",
            "calidad metodologica",
            "transferibilidad",
        ],
        "synthesis_modes": ["framework synthesis", "narrative synthesis", "configurational synthesis", "two-level synthesis"],
        "selection_score_weights": {"relevance": 0.35, "quality": 0.40, "representativeness": 0.25},
        "writing_rules": [
            "Declarar que reglas se heredan de cada modo.",
            "No mezclar certeza causal, transferencia cualitativa y rendimiento tecnico como si fueran la misma magnitud.",
            "Separar sintesis general y sintesis focal por densidad de evidencia.",
        ],
    },
}


MODE_PUBLICATION_PLAYBOOK: dict[str, dict[str, object]] = {
    "biomedical": {
        "mode_question_es": "¿La revisión pertenece a salud, clínica, biomedicina o epidemiología y debe formularse con PICO/PICOS?",
        "ask_policy": [
            "Preguntar solo si hay señales de salud mezcladas con educación, tecnología o ciencias sociales y la unidad de análisis no está clara.",
            "Inferir sin preguntar cuando aparecen población, intervención/exposición, outcome, ensayo, cohorte, paciente, clínica, hospital o salud pública.",
            "En modo autónomo, si la confianza es baja, usar common-core documentado y no bloquear el ciclo.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Tabla PICO/PICOS o PECO con población, intervención/exposición, comparador, outcomes y diseño.",
            "Características de estudios incluidos: país, muestra, diseño, intervención/exposición, outcome y fuente.",
            "Matriz de riesgo de sesgo o evaluación crítica por estudio.",
            "Matriz de certeza o perfil de evidencia cuando el corpus lo permita.",
        ],
        "recommended_tables": [
            "Tabla de efectos, dirección del resultado y precisión si los estudios reportan tamaños de efecto.",
            "Tabla de sensibilidad por diseño, población o outcome.",
            "Tabla de exclusiones a texto completo con motivo explícito.",
        ],
        "minimum_figures": [
            "Mapa población-outcome cuando mejora la lectura de la evidencia.",
            "Resumen visual de riesgo de sesgo si hay suficiente N y variedad de dominios.",
            "Figura de mecanismo clínico solo si el corpus sostiene una relación interpretable.",
        ],
        "recommended_figures": [
            "Forest plot o harvest plot si los datos son comparables.",
            "Evidence gap map por población, intervención/exposición y outcome.",
        ],
        "mode_specific_outputs": [
            "PICO/PICOS auditado.",
            "Risk-of-bias matrix.",
            "GRADE-style certainty note cuando proceda.",
            "Lista de outcomes primarios y secundarios.",
        ],
        "publication_section_requirements": [
            "Método con fuentes biomédicas, fecha exacta de búsqueda, PICO/PICOS y herramienta de riesgo de sesgo.",
            "Resultados separados por outcome y por diseño.",
            "Discusión que diferencie efecto, certeza, heterogeneidad y aplicabilidad clínica.",
            "Conclusiones que no conviertan asociación en causalidad si el diseño no lo permite.",
        ],
        "red_flags": [
            "No declarar población u outcome.",
            "Usar estudios sin distinguir ensayo, observacional, revisión o protocolo.",
            "Citar resultados clínicos sin riesgo de sesgo.",
            "Generalizar a pacientes o práctica clínica sin evidencia suficiente.",
        ],
        "excellence_checklist": [
            "La pregunta queda operacionalizada antes de buscar.",
            "Cada conclusión sustantiva tiene outcome, diseño y certeza identificables.",
            "Las figuras son analíticas, no decorativas.",
            "El lector puede recomputar selección, exclusión y evaluación crítica desde CSV.",
        ],
    },
    "technical": {
        "mode_question_es": "¿La revisión compara sistemas técnicos, arquitecturas, modelos, datasets, benchmarks o métricas?",
        "ask_policy": [
            "Preguntar solo si la pregunta técnica también es claramente social, educativa o de management y no se sabe qué unidad manda.",
            "Inferir sin preguntar cuando aparecen arquitectura, sistema, benchmark, dataset, métrica, modelo, agente, pipeline, coste, latencia o robustez.",
            "En modo autónomo, elegir técnico si la unidad real es configuración de sistema aunque el dominio de aplicación sea humano.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Matriz sistema-arquitectura-componentes.",
            "Tabla dataset-benchmark-métrica-baseline.",
            "Tabla de reproducibilidad: código, datos, prompts, configuración, coste y entorno.",
            "Tabla de resultados observados con límites de comparabilidad.",
        ],
        "recommended_tables": [
            "Matriz de ablation, robustez y fallos.",
            "Tabla de costes, latencia, tokens o recursos cuando estén reportados.",
            "Tabla de familias arquitectónicas y patrones recurrentes.",
        ],
        "minimum_figures": [
            "Arquitectura o taxonomía técnica generada por Hermes a partir del corpus.",
            "Mapa de cobertura benchmark-dataset-métrica.",
            "Matriz visual tarea-componente-resultado si reduce complejidad.",
        ],
        "recommended_figures": [
            "Diagrama de pipeline comparado.",
            "Mapa de madurez técnica por reproducibilidad, robustez y evaluación.",
            "Heatmap de componentes frente a tareas o dominios.",
        ],
        "mode_specific_outputs": [
            "Architecture grammar.",
            "Benchmark comparability matrix.",
            "Reproducibility and artifact checklist.",
            "System-level contribution statement.",
        ],
        "publication_section_requirements": [
            "Método que explique cómo se comparan sistemas completos, no solo nombres de modelos.",
            "Resultados con arquitectura, dataset, métrica, baseline y limitación por estudio.",
            "Discusión centrada en configuraciones, no en rankings oportunistas.",
            "Implicaciones prácticas por tarea, coste, robustez y condiciones de uso.",
        ],
        "red_flags": [
            "Confundir modelo base con arquitectura completa.",
            "Comparar benchmarks incompatibles como si fueran equivalentes.",
            "No reportar dataset, métrica o baseline.",
            "Incluir figuras de papers fuente sin aporte analítico propio.",
        ],
        "excellence_checklist": [
            "La unidad de comparación es el sistema completo.",
            "La síntesis identifica gramática técnica reutilizable.",
            "Las tablas permiten ver qué se evaluó, cómo y contra qué.",
            "Las limitaciones separan rendimiento local de generalización.",
        ],
    },
    "social_sciences": {
        "mode_question_es": "¿La revisión estudia fenómenos, constructos, actores, contextos, teorías o mecanismos sociales?",
        "ask_policy": [
            "Preguntar si la pregunta habla de personas, organizaciones o instituciones pero no define si prima educación, management, salud o ciencias sociales generales.",
            "Inferir sin preguntar cuando aparecen constructo, contexto, percepción, comportamiento, ideología, cultura, encuesta, entrevista, caso o teoría social.",
            "En modo autónomo, usar ciencias sociales como common-core si no hay señales disciplinares fuertes.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Tabla constructo-teoría-contexto-método.",
            "Tabla muestra/caso/población y contexto territorial o institucional.",
            "Tabla de diseños y técnicas de recogida/análisis de datos.",
            "Matriz de mecanismos, resultados y límites de transferibilidad.",
        ],
        "recommended_tables": [
            "CERQual-style confidence table si hay síntesis cualitativa.",
            "Tabla de vacíos por teoría, muestra, país, variable y comparador.",
            "Tabla de conceptos equivalentes o etiquetas divergentes.",
        ],
        "minimum_figures": [
            "Mapa conceptual de constructos y relaciones.",
            "Mapa temático de mecanismos-contextos-resultados.",
            "Evidence gap map por población, contexto y método.",
        ],
        "recommended_figures": [
            "Diagrama de teoría del cambio si el corpus lo sostiene.",
            "Mapa de transferencia: dónde vale, para quién y con qué cautelas.",
        ],
        "mode_specific_outputs": [
            "Construct-theory-method matrix.",
            "Transferability note.",
            "Context and mechanism synthesis.",
            "Confidence-in-synthesis statement.",
        ],
        "publication_section_requirements": [
            "Marco teórico que nombre constructos y familias conceptuales antes de contar papers.",
            "Método que no penalice lo cualitativo por no ser experimental.",
            "Resultados que separen hallazgo, mecanismo plausible y contexto.",
            "Conclusiones que declaren certeza, señal emergente y vacío crítico.",
        ],
        "red_flags": [
            "Reducir constructos complejos a frecuencias sin teoría.",
            "No reportar contexto, muestra o unidad de análisis.",
            "Tratar evidencia cualitativa como si fuese causalidad estadística.",
            "Presentar transferibilidad como generalización universal.",
        ],
        "excellence_checklist": [
            "Cada concepto clave tiene definición operativa o límite explícito.",
            "La síntesis explica por qué los resultados podrían variar por contexto.",
            "Las figuras ayudan a ver mecanismos, no adornan.",
            "Las líneas futuras salen de vacíos diagnosticados, no de frases genéricas.",
        ],
    },
    "education": {
        "mode_question_es": "¿La revisión se centra en aprendizaje, docencia, profesorado, estudiantes, evaluación, feedback o instituciones educativas?",
        "ask_policy": [
            "Preguntar si la pregunta mezcla tecnología educativa con arquitectura técnica y no está claro si prima el sistema o la práctica pedagógica.",
            "Inferir sin preguntar cuando aparecen docente, estudiante, aprendizaje, enseñanza, evaluación, feedback, universidad, currículo o pedagogía.",
            "En modo autónomo, educación manda cuando el outcome principal es pedagógico o docente.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Tabla nivel educativo-actor-actividad pedagógica.",
            "Tabla herramienta/práctica-resultados educativos-instrumento de evaluación.",
            "Tabla muestra, institución, país/contexto y duración.",
            "Matriz de ética, equidad, carga docente y gobernanza cuando aparezcan.",
        ],
        "recommended_tables": [
            "Tabla de calidad docente, aprendizaje, feedback, evaluación y adopción.",
            "Tabla de instrumentos de medición educativa y validez reportada.",
            "Tabla de barreras/facilitadores por institución o actor.",
        ],
        "minimum_figures": [
            "Mapa actividad pedagógica-actor-resultado.",
            "Diagrama de flujo docente/estudiante si ayuda a replicar la intervención.",
            "Mapa de adopción y gobernanza educativa.",
        ],
        "recommended_figures": [
            "Evidence gap map por nivel educativo y outcome.",
            "Mapa de mecanismos pedagógicos y condiciones institucionales.",
        ],
        "mode_specific_outputs": [
            "Pedagogical activity matrix.",
            "Learning/teaching outcome map.",
            "Institutional context and equity note.",
            "Teacher workload and governance note when available.",
        ],
        "publication_section_requirements": [
            "Marco teórico educativo con nivel, actor, actividad y resultado definidos.",
            "Método que distinga percepción, adopción, aprendizaje, calidad docente y evaluación.",
            "Resultados que no confundan satisfacción con mejora de aprendizaje.",
            "Implicaciones prácticas accionables para docentes, universidades y responsables académicos.",
        ],
        "red_flags": [
            "No indicar nivel educativo o actor principal.",
            "Usar percepciones como si fueran resultados de aprendizaje.",
            "Ignorar equidad, privacidad, carga de trabajo o integridad académica.",
            "No explicar instrumento o criterio de evaluación.",
        ],
        "excellence_checklist": [
            "El lector sabe qué cambia en la práctica docente o de aprendizaje.",
            "La síntesis separa herramienta, actividad pedagógica y outcome.",
            "Las tablas sirven para tomar decisiones institucionales.",
            "Las líneas futuras derivan de fallos de evidencia educativa detectados.",
        ],
    },
    "management": {
        "mode_question_es": "¿La revisión pertenece a management, estrategia, organizaciones, liderazgo, gobierno corporativo, innovación o desempeño empresarial?",
        "ask_policy": [
            "Preguntar si la pregunta habla de organizaciones pero no aclara si la unidad principal es firma, directivo, equipo, sector, política pública o tecnología.",
            "Inferir sin preguntar cuando aparecen firma, empresa, estrategia, liderazgo, CEO, consejo, gobierno corporativo, innovación, desempeño o variables organizativas.",
            "En modo autónomo, management manda cuando el resultado es una decisión, práctica o performance de organización.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Tabla TCCM/CIMO: teoría, contexto, características, método y resultado.",
            "Tabla de variables: dependiente, independiente, mediadora, moderadora y controles.",
            "Tabla muestra/sector/país/nivel de análisis.",
            "Tabla de identificación empírica: endogeneidad, comparador, robustez y límites causales.",
        ],
        "recommended_tables": [
            "Matriz mecanismo-resultado-decisión estratégica.",
            "Tabla de diseños longitudinales, panel, IV, DiD, experimentos o estudios de caso.",
            "Tabla de vacíos por teoría, variable, contexto, país y comparador.",
        ],
        "minimum_figures": [
            "Mapa teórico de variables y mecanismos.",
            "Diagrama de cautela causal: asociación, mecanismo, moderador y resultado.",
            "Matriz visual contexto-método-resultado si aporta lectura comparada.",
        ],
        "recommended_figures": [
            "Mapa de madurez de evidencia por identificación causal y robustez.",
            "Arquitectura conceptual de la decisión o práctica organizativa investigada.",
        ],
        "mode_specific_outputs": [
            "TCCM/CIMO synthesis.",
            "Variable role matrix.",
            "Endogeneity and robustness note.",
            "Managerial decision implications.",
        ],
        "publication_section_requirements": [
            "Marco teórico con unidad de análisis, teoría y constructos organizativos.",
            "Método que evalúe identificación, controles, muestra, sector, país y robustez.",
            "Resultados que separen asociación, mecanismo y causalidad.",
            "Aportación original que explique qué cambia para la comparación acumulativa del campo.",
        ],
        "red_flags": [
            "No declarar unidad de análisis.",
            "No separar variable dependiente, independiente, moderadora, mediadora y controles.",
            "Afirmar causalidad con diseños transversales o meramente correlacionales.",
            "No reportar sector, país, muestra o estrategia de identificación.",
        ],
        "excellence_checklist": [
            "La revisión produce una gramática de comparación para decisiones organizativas.",
            "Las conclusiones dicen qué está establecido, qué es señal y qué sigue vacío.",
            "Las tablas permiten reconstruir teoría, variables, método y resultado.",
            "Las implicaciones prácticas son útiles para dirección sin sobreprometer causalidad.",
        ],
    },
    "mixed": {
        "mode_question_es": "¿La revisión combina más de un campo y necesitas declarar cuál es el modo principal y cuáles son secundarios?",
        "ask_policy": [
            "Preguntar cuando dos o más modos tienen señales similares y la unidad de análisis cambia según el campo elegido.",
            "Inferir modo mixto cuando la pregunta combina de forma sustantiva sistema técnico, fenómeno social, educación, salud o management.",
            "En modo autónomo, fijar un modo principal y documentar qué salvaguardas hereda de los secundarios.",
        ],
        "minimum_tables": [
            "Flujo de selección de estudios como tabla metodológica.",
            "Tabla de modo principal/secundario y reglas heredadas.",
            "Matriz de tipos de evidencia y unidad de comparación.",
            "Tabla de evaluación crítica por familia metodológica.",
            "Tabla de integración: qué evidencia sostiene cada conclusión.",
        ],
        "recommended_tables": [
            "Tabla de tensiones epistemológicas entre modos.",
            "Tabla de transferibilidad por dominio y contexto.",
            "Tabla de sensibilidad del score focal por pesos alternativos.",
        ],
        "minimum_figures": [
            "Arquitectura de síntesis por capas.",
            "Mapa de integración entre modos y tipos de evidencia.",
            "Figura de límites: qué puede compararse y qué no.",
        ],
        "recommended_figures": [
            "Evidence gap map multimodo.",
            "Mapa de confianza por dominio, método y resultado.",
        ],
        "mode_specific_outputs": [
            "Primary-secondary mode contract.",
            "Cross-mode appraisal matrix.",
            "Two-level synthesis note.",
            "Boundary and comparability statement.",
        ],
        "publication_section_requirements": [
            "Método que declare qué modo decide la unidad de análisis.",
            "Resultados separados por lógica de evidencia antes de integrarlos.",
            "Discusión que no mezcle causalidad, transferencia y rendimiento como si fueran una misma magnitud.",
            "Conclusión con alcance explícito por dominio.",
        ],
        "red_flags": [
            "Usar mixto como cajón de sastre.",
            "No declarar modo principal.",
            "Aplicar una única herramienta de calidad a diseños incompatibles.",
            "Fusionar resultados heterogéneos sin explicar equivalencias.",
        ],
        "excellence_checklist": [
            "El modo principal gobierna la pregunta y los secundarios añaden controles.",
            "La síntesis separa niveles antes de integrarlos.",
            "La evidencia no se fuerza en una métrica falsa.",
            "El paper explica sus fronteras sin debilitar la aportación.",
        ],
    },
}


def _load_declarative_profiles() -> None:
    """Apply versioned profile overrides without making configuration mandatory."""
    path = pathlib.Path(__file__).resolve().parent.parent / "config" / "methodology-profiles.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("schema_version") != "hermes.methodology-profiles/v1":
        return
    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        return
    for mode, profile in profiles.items():
        if mode not in MODE_CONFIG or not isinstance(profile, dict):
            continue
        config_override = profile.get("config")
        playbook_override = profile.get("publication_playbook")
        if isinstance(config_override, dict):
            MODE_CONFIG[mode].update(deepcopy(config_override))
        if isinstance(playbook_override, dict):
            MODE_PUBLICATION_PLAYBOOK[mode].update(deepcopy(playbook_override))


_load_declarative_profiles()


MODE_MARKERS: dict[str, tuple[str, ...]] = {
    "biomedical": (
        "clinical", "clinico", "clinica", "patient", "paciente", "hospital", "health", "salud",
        "medicine", "medicina", "disease", "enfermedad", "treatment", "tratamiento", "therapy",
        "diagnostic", "diagnostico", "public health", "mental health", "randomized", "trial",
        "cohort", "case-control", "prevalence", "epidemiology", "farmaco", "pharma",
    ),
    "technical": (
        "artificial intelligence", "inteligencia artificial", "llm", "large language model",
        "ia", "software", "algorithm", "algoritmo", "architecture", "arquitectura", "arquitecturas",
        "sistema de ia", "sistemas de ia", "benchmark", "benchmarks", "dataset",
        "machine learning", "deep learning", "rag", "agent", "agents", "agente", "agentes", "inference",
        "latency", "robustness", "reproducibility", "multimodal", "transformer", "moe",
    ),
    "social_sciences": (
        "society", "social", "sociology", "sociologia", "political", "politica", "ideologia",
        "culture", "cultura", "behavior", "behaviour", "comportamiento", "attitude", "perception",
        "percepcion", "identity", "identidad", "inequality", "desigualdad", "qualitative",
        "interviews", "entrevistas", "survey", "encuesta", "ethnography", "etnografia",
    ),
    "education": (
        "education", "educacion", "educación", "higher education", "university", "universidad",
        "teacher", "teachers", "docente", "docentes", "profesor", "profesorado", "student",
        "students", "learning", "aprendizaje", "teaching", "ensenanza", "enseñanza", "pedagogy",
        "pedagogia", "assessment", "evaluacion", "feedback", "curriculum",
    ),
    "management": (
        "management", "strategy", "estrategia", "strategic", "firm", "firma", "empresa",
        "corporate", "organization", "organisation", "organizacion", "organización", "leadership",
        "liderazgo", "corporativo", "corporativa", "estrategia corporativa", "decisiones estrategicas",
        "decision estrategica", "direccion", "alta direccion", "directivo", "directivos", "ceo",
        "executive", "top management", "board", "governance", "gobierno corporativo", "innovation",
        "innovacion", "performance", "desempeno", "rendimiento", "csr", "esg", "entrepreneurship",
        "emprendimiento", "business",
    ),
}


def normalized_text(text: object) -> str:
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9+_.:/ -]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def token_present(blob: str, token: str) -> bool:
    value = normalized_text(token)
    if not value:
        return False
    if re.fullmatch(r"[a-z0-9+_.-]+", value):
        return re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", blob) is not None
    return value in blob


def normalize_mode_name(value: str) -> str:
    blob = normalized_text(value)
    if not blob:
        return ""
    for alias in ("mixto", "mixed", "hibrido", "hybrid"):
        if token_present(blob, alias):
            return "mixed"
    for alias, mode in MODE_ALIASES.items():
        if token_present(blob, alias):
            return mode
    compact = blob.replace("-", "_").replace(" ", "_")
    return compact if compact in MODE_CONFIG else ""


def mode_name_from_text(value: str, *, exclude: set[str] | None = None) -> str:
    """Find the first declared mode inside a short free-text segment.

    Public intakes often use natural language such as
    ``mixto; principal: management; secundario: ciencias sociales``. The router
    should preserve that authorial choice instead of re-inferring the primary
    mode from the topic vocabulary alone.
    """

    exclude = exclude or set()
    blob = normalized_text(value)
    if not blob:
        return ""
    for alias, mode in sorted(MODE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if mode in exclude:
            continue
        if token_present(f" {blob} ", alias):
            return mode
    compact = blob.replace("-", "_").replace(" ", "_")
    return compact if compact in MODE_CONFIG and compact not in exclude else ""


def parse_declared_mode_roles(value: str) -> tuple[str, list[str]]:
    """Extract optional primary/secondary roles from an explicit mixed mode."""

    blob = normalized_text(value)
    if not blob:
        return "", []

    primary = ""
    secondary: list[str] = []
    role_patterns = [
        ("primary", r"(?:principal|primary)\s*[:= -]+\s*(.+?)(?=\s+(?:secundario|secundaria|secondary|principal|primary)\s*[:= -]+|$)"),
        ("secondary", r"(?:secundario|secundaria|secondary)\s*[:= -]+\s*(.+?)(?=\s+(?:principal|primary|secundario|secundaria|secondary)\s*[:= -]+|$)"),
    ]
    for role, pattern in role_patterns:
        for match in re.finditer(pattern, blob):
            mode = mode_name_from_text(match.group(1), exclude={"mixed"})
            if not mode:
                continue
            if role == "primary" and not primary:
                primary = mode
            elif role == "secondary" and mode != primary and mode not in secondary:
                secondary.append(mode)

    return primary, secondary


def mode_config(mode: str) -> dict[str, object]:
    key = mode if mode in MODE_CONFIG else "mixed" if mode == "mixto" else "social_sciences"
    config = deepcopy(MODE_CONFIG.get(key, MODE_CONFIG["social_sciences"]))
    config.update(deepcopy(MODE_PUBLICATION_PLAYBOOK.get(key, {})))
    return config


def score_modes(text: str) -> dict[str, int]:
    blob = f" {normalized_text(text)} "
    scores: dict[str, int] = {}
    for mode, markers in MODE_MARKERS.items():
        score = 0
        for marker in markers:
            if token_present(blob, marker):
                score += 2 if " " in normalized_text(marker) else 1
        scores[mode] = score
    # Education and management are specialized social-science modes.
    if scores.get("education", 0):
        scores["social_sciences"] = max(scores.get("social_sciences", 0), scores["education"] // 2)
    if scores.get("management", 0):
        scores["social_sciences"] = max(scores.get("social_sciences", 0), scores["management"] // 2)
    return scores


def infer_review_mode(
    *,
    topic: str = "",
    question: str = "",
    inclusion: str = "",
    exclusion: str = "",
    target_outlet: str = "",
    explicit_mode: str = "",
) -> dict[str, object]:
    explicit = normalize_mode_name(explicit_mode)
    text = " ".join([topic, question, inclusion, exclusion, target_outlet])
    scores = score_modes(text)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], MODE_ORDER.index(item[0]) if item[0] in MODE_ORDER else 99))

    if explicit and explicit != "mixed":
        chosen = explicit
        primary = explicit
        secondary = [mode for mode, score in ranked if mode != explicit and score >= 3][:2]
        confidence = "declarado"
        rationale = f"Modo declarado en intake: {MODE_CONFIG[explicit]['label_public_es']}."
    elif explicit == "mixed":
        nonzero = [mode for mode, score in ranked if score > 0 and mode != "mixed"]
        declared_primary, declared_secondary = parse_declared_mode_roles(explicit_mode)
        primary = declared_primary or (nonzero[0] if nonzero else "social_sciences")
        secondary = [
            mode
            for mode in [*declared_secondary, *nonzero]
            if mode != primary and mode in MODE_CONFIG
        ][:2]
        secondary = [mode for index, mode in enumerate(secondary) if mode not in secondary[:index]]
        chosen = "mixed"
        confidence = "declarado"
        rationale = "Modo mixto declarado en intake; se conserva el modo principal y los secundarios cuando se especifican."
    else:
        top_mode, top_score = ranked[0]
        second_mode, second_score = ranked[1]
        # Education and management are specialized social-science modes. If the
        # generic social bucket wins only by a tiny margin, keep the more
        # actionable specialized mode so appraisal and synthesis do not become
        # bland.
        for specialized in ("education", "management"):
            specialized_score = scores.get(specialized, 0)
            if top_mode == "social_sciences" and specialized_score >= 3 and specialized_score >= top_score - 1:
                top_mode, top_score = specialized, specialized_score
                break
        if top_score <= 0:
            chosen = "social_sciences"
            primary = "social_sciences"
            secondary = []
            confidence = "baja"
            rationale = "No hay señales disciplinares fuertes; Hermes usa ciencias sociales como common-core interpretativo."
        elif second_score >= 4 and second_score >= top_score - 2:
            chosen = "mixed"
            primary = top_mode
            secondary = [mode for mode, score in ranked[1:] if score >= 4][:2]
            confidence = "media"
            rationale = (
                "La pregunta activa mas de una logica epistemica; Hermes usa modo mixto "
                f"con principal {MODE_CONFIG[primary]['label_public_es']}."
            )
        else:
            chosen = top_mode
            primary = top_mode
            secondary = [mode for mode, score in ranked[1:] if score >= 3][:2]
            confidence = "alta" if top_score >= 5 else "media"
            rationale = f"El vocabulario del protocolo se ajusta principalmente a {MODE_CONFIG[chosen]['label_public_es']}."

    config = mode_config(chosen)
    primary_config = mode_config(primary)
    inherited_modes = [primary, *secondary] if chosen == "mixed" else [chosen, *secondary]
    inherited_modes = [mode for index, mode in enumerate(inherited_modes) if mode in MODE_CONFIG and mode not in inherited_modes[:index]]
    inherited_frameworks: list[str] = []
    inherited_appraisal: list[str] = []
    inherited_synthesis: list[str] = []
    inherited_tables_min: list[str] = []
    inherited_tables_recommended: list[str] = []
    inherited_figures_min: list[str] = []
    inherited_figures_recommended: list[str] = []
    inherited_outputs: list[str] = []
    inherited_section_requirements: list[str] = []
    inherited_red_flags: list[str] = []
    inherited_excellence: list[str] = []
    inherited_ask_policy: list[str] = []
    for mode in inherited_modes:
        cfg = mode_config(mode)
        inherited_frameworks.extend(str(item) for item in cfg.get("question_frameworks", []))
        inherited_appraisal.extend(str(item) for item in cfg.get("appraisal_tools", []))
        inherited_synthesis.extend(str(item) for item in cfg.get("synthesis_modes", []))
        inherited_tables_min.extend(str(item) for item in cfg.get("minimum_tables", []))
        inherited_tables_recommended.extend(str(item) for item in cfg.get("recommended_tables", []))
        inherited_figures_min.extend(str(item) for item in cfg.get("minimum_figures", []))
        inherited_figures_recommended.extend(str(item) for item in cfg.get("recommended_figures", []))
        inherited_outputs.extend(str(item) for item in cfg.get("mode_specific_outputs", []))
        inherited_section_requirements.extend(str(item) for item in cfg.get("publication_section_requirements", []))
        inherited_red_flags.extend(str(item) for item in cfg.get("red_flags", []))
        inherited_excellence.extend(str(item) for item in cfg.get("excellence_checklist", []))
        inherited_ask_policy.extend(str(item) for item in cfg.get("ask_policy", []))

    weights = dict(primary_config.get("selection_score_weights", config.get("selection_score_weights", {})))
    decision = {
        "version": REVIEW_MODE_VERSION,
        "mode": chosen,
        "mode_label": config["label_public_es"],
        "primary_mode": primary,
        "primary_mode_label": primary_config["label_public_es"],
        "secondary_modes": secondary,
        "secondary_mode_labels": [MODE_CONFIG[mode]["label_public_es"] for mode in secondary if mode in MODE_CONFIG],
        "confidence": confidence,
        "rationale": rationale,
        "scores": scores,
        "default_framework": primary_config.get("default_framework", config.get("default_framework")),
        "question_frameworks": dedupe(inherited_frameworks),
        "primary_unit": primary_config.get("primary_unit", config.get("primary_unit")),
        "core_logic": primary_config.get("core_logic", config.get("core_logic")),
        "screening_axes": dedupe(
            [axis for mode in inherited_modes for axis in MODE_CONFIG[mode].get("screening_axes", [])]
        ),
        "recommended_sources": dedupe(
            [source for mode in inherited_modes for source in MODE_CONFIG[mode].get("recommended_sources", [])]
        ),
        "optional_sources": dedupe(
            [source for mode in inherited_modes for source in MODE_CONFIG[mode].get("optional_sources", [])]
        ),
        "critical_appraisal_tools": dedupe(inherited_appraisal),
        "critical_appraisal_domains": dedupe(
            [domain for mode in inherited_modes for domain in MODE_CONFIG[mode].get("critical_appraisal_domains", [])]
        ),
        "synthesis_modes": dedupe(inherited_synthesis),
        "selection_score_weights": weights,
        "writing_rules": dedupe(
            [rule for mode in inherited_modes for rule in MODE_CONFIG[mode].get("writing_rules", [])]
        ),
        "mode_question_es": primary_config.get("mode_question_es", ""),
        "ask_policy": dedupe(inherited_ask_policy),
        "minimum_tables": dedupe(inherited_tables_min),
        "recommended_tables": dedupe(inherited_tables_recommended),
        "minimum_figures": dedupe(inherited_figures_min),
        "recommended_figures": dedupe(inherited_figures_recommended),
        "mode_specific_outputs": dedupe(inherited_outputs),
        "publication_section_requirements": dedupe(inherited_section_requirements),
        "red_flags": dedupe(inherited_red_flags),
        "excellence_checklist": dedupe(inherited_excellence),
    }
    return decision


def dedupe(items: list[object]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        key = normalized_text(value)
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def selection_weights(decision_or_mode: dict[str, object] | str) -> tuple[float, float, float]:
    if isinstance(decision_or_mode, dict):
        weights = decision_or_mode.get("selection_score_weights") or {}
    else:
        weights = MODE_CONFIG.get(str(decision_or_mode), MODE_CONFIG["mixed"]).get("selection_score_weights", {})
    if not isinstance(weights, dict):
        weights = {}
    relevance = float(weights.get("relevance", 0.35))
    quality = float(weights.get("quality", 0.40))
    representativeness = float(weights.get("representativeness", 0.25))
    total = relevance + quality + representativeness
    if total <= 0:
        return 0.35, 0.40, 0.25
    return relevance / total, quality / total, representativeness / total


def should_ask_for_review_mode(decision: dict[str, object], *, autonomous_mode: bool = True) -> bool:
    """Return whether an interactive frontend should ask the user to choose a field.

    Autonomous Hermes runs never stop only because the field was not declared:
    they infer a common-core mode and document the rationale. Telegram or any
    future UI can still ask this single question when the run is interactive.
    """

    if autonomous_mode:
        return False
    return str(decision.get("confidence", "")).strip().lower() == "baja"


def read_review_mode_decision(review_dir: pathlib.Path) -> dict[str, object]:
    path = review_dir / "protocol" / "review-mode.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def render_review_mode_markdown(decision: dict[str, object]) -> str:
    def list_lines(values: object) -> list[str]:
        if not isinstance(values, list):
            return []
        return [f"- {value}" for value in values if str(value).strip()]

    weights = decision.get("selection_score_weights") if isinstance(decision.get("selection_score_weights"), dict) else {}
    wr, wq, wp = selection_weights(decision)
    lines = [
        "# Modo metodológico de revisión",
        "",
        f"- Norma: {decision.get('version', REVIEW_MODE_VERSION)}",
        f"- Modo aplicado: {decision.get('mode_label', '')}",
        f"- Modo principal: {decision.get('primary_mode_label', '')}",
        f"- Modos secundarios: {', '.join(decision.get('secondary_mode_labels') or []) or 'ninguno'}",
        f"- Confianza de inferencia: {decision.get('confidence', '')}",
        f"- Justificación: {decision.get('rationale', '')}",
        f"- Marco de pregunta por defecto: {decision.get('default_framework', '')}",
        f"- Unidad primaria de comparación: {decision.get('primary_unit', '')}",
        "",
        "## Pregunta de campo",
        str(decision.get("mode_question_es", "") or "Si el campo no está claro, preguntar por el modo metodológico antes de buscar."),
        "",
        "## Política preguntar/inferir",
        *list_lines(decision.get("ask_policy")),
        "",
        "## Lógica metodológica",
        str(decision.get("core_logic", "")),
        "",
        "## Ejes obligatorios de cribado y extracción",
        *list_lines(decision.get("screening_axes")),
        "",
        "## Fuentes recomendadas",
        *list_lines(decision.get("recommended_sources")),
        "",
        "## Fuentes opcionales por disciplina",
        *list_lines(decision.get("optional_sources")),
        "",
        "## Evaluación crítica",
        "### Instrumentos o familias de instrumentos",
        *list_lines(decision.get("critical_appraisal_tools")),
        "",
        "### Dominios mínimos",
        *list_lines(decision.get("critical_appraisal_domains")),
        "",
        "## Síntesis admitida",
        *list_lines(decision.get("synthesis_modes")),
        "",
        "## Tablas mínimas del paper",
        *list_lines(decision.get("minimum_tables")),
        "",
        "## Tablas recomendadas",
        *list_lines(decision.get("recommended_tables")),
        "",
        "## Figuras mínimas con aporte analítico",
        *list_lines(decision.get("minimum_figures")),
        "",
        "## Figuras recomendadas",
        *list_lines(decision.get("recommended_figures")),
        "",
        "## Salidas específicas del modo",
        *list_lines(decision.get("mode_specific_outputs")),
        "",
        "## Requisitos por sección publicable",
        *list_lines(decision.get("publication_section_requirements")),
        "",
        "## Regla de score focal",
        f"- Relevancia temática: {weights.get('relevance', wr):.2f}",
        f"- Calidad metodológica / densidad analítica: {weights.get('quality', wq):.2f}",
        f"- Representatividad / diversidad: {weights.get('representativeness', wp):.2f}",
        "",
        "## Reglas de escritura",
        *list_lines(decision.get("writing_rules")),
        "",
        "## Alertas editoriales",
        *list_lines(decision.get("red_flags")),
        "",
        "## Checklist sobresaliente",
        *list_lines(decision.get("excellence_checklist")),
        "",
        "## Regla de oro",
        "Hermes no evalúa todos los campos con el mismo molde: adapta la revisión a la lógica epistemológica del área antes de buscar, cribar, sintetizar y escribir.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def write_review_mode_artifacts(review_dir: pathlib.Path, decision: dict[str, object]) -> None:
    protocol_dir = review_dir / "protocol"
    audit_dir = review_dir / "audit"
    protocol_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)
    (protocol_dir / "review-mode.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rendered = render_review_mode_markdown(decision)
    (protocol_dir / "review-mode.md").write_text(rendered, encoding="utf-8")
    (audit_dir / "mode-decision.md").write_text(rendered, encoding="utf-8")


def review_mode_summary(decision: dict[str, object]) -> str:
    if not decision:
        return "modo no declarado"
    secondary = ", ".join(decision.get("secondary_mode_labels") or [])
    suffix = f"; secundarios: {secondary}" if secondary else ""
    return f"{decision.get('mode_label', '')}; principal: {decision.get('primary_mode_label', '')}{suffix}"
