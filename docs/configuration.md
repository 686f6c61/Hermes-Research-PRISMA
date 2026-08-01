# Configuración

La configuración local vive en `.env`. No la compartas ni la añadas a Git.
Usa `./hermes-research setup` para los cambios habituales.

## Núcleo

| Variable | Función |
|---|---|
| `HERMES_INSTALL_MODE` | `cli`, `telegram` o `both`. |
| `HERMES_UID` / `HERMES_GID` | Usuario y grupo no privilegiados del contenedor. |
| `TZ` | Zona horaria para logs y watchdog. |
| `COMPOSE_PROJECT_NAME` | Evita colisiones con otra instalación Docker. |

## Inferencia

| Variable | Función |
|---|---|
| `HERMES_INFERENCE_BASE_URL` | Base OpenAI-compatible terminada en `/v1`. |
| `HERMES_INFERENCE_API_KEY` | Credencial del proveedor. |
| `HERMES_MODEL_PRIMARY` | Planificación, extracción, síntesis y escritura. |
| `HERMES_MODEL_VISION` | Lectura de páginas, tablas y figuras. |
| `HERMES_MODEL_REVIEW` | Revisión independiente y crítica editorial. |

Los identificadores deben coincidir exactamente con `GET /models`.

## Identidad y decisiones firmadas

| Variable | Función |
|---|---|
| `HERMES_RESEARCHER_NAME` | Nombre del investigador responsable que firma decisiones. |
| `HERMES_RESEARCHER_EMAIL` | Email del investigador responsable. |
| `HERMES_RESEARCHER_ORCID` | ORCID opcional. |
| `HERMES_ADJUDICATION_SECRET` | Secreto local generado por `setup` para vincular firmas y contratos. |
| `HERMES_ADJUDICATION_ALLOWED_USERS` | IDs de Telegram autorizados para decidir, derivados de la allowlist. |

El secreto nunca entra en manuscritos, ZIP, logs o Git. Una discrepancia de
texto completo solo queda resuelta si la decisión está firmada para el DOI, el
caso y el protocolo exactos.

## Telegram

| Variable | Función |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot dedicado. Vacío en modo CLI. |
| `TELEGRAM_ALLOWED_USERS` | IDs numéricos autorizados, separados por comas. Obligatorio en Telegram. |
| `TELEGRAM_HOME_CHANNEL` | Chat privado que recibe avisos del gateway y watchdog. |
| `TELEGRAM_PRISMA_CHAT_ID` | Chat privado para el progreso de las revisiones. |
| `HERMES_TELEGRAM_PUBLIC_MENU_ONLY` | Limita el menú a la superficie pública. |
| `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS` | Evita transportes alternativos innecesarios. |

`setup` valida el bot, descubre candidatos después de que el propietario envíe
`/start` y comprueba que el bot accede al chat configurado. No uses `*` ni
habilites acceso global en una instalación pública.

## Fuentes académicas

| Variable | Función |
|---|---|
| `HERMES_CONTACT_EMAIL` | Identidad técnica privada para APIs con acceso cortés. |
| `HERMES_UNPAYWALL_EMAIL` | Email exigido por Unpaywall para resolver acceso abierto. |
| `HERMES_ENABLE_SEMANTIC_SCHOLAR` | Permite acceso sin key, sujeto a rate limits. |
| `HERMES_SEMANTIC_SCHOLAR_API_KEY` | Credencial opcional de Semantic Scholar. |
| `HERMES_LENS_API_KEY` | Credencial opcional de Lens Scholarly. |
| `HERMES_NCBI_EMAIL` | Contacto para NCBI/PubMed. |
| `HERMES_NCBI_API_KEY` | Credencial opcional para mayor cuota de NCBI. |
| `HERMES_SCOPUS_API_KEY` | Credencial opcional para Scopus Search API. |
| `HERMES_ELSEVIER_INST_TOKEN` | Token institucional opcional compartido por Scopus/Embase. |
| `HERMES_WOS_API_KEY` | Credencial opcional para Web of Science Starter API. |
| `HERMES_EMBASE_API_KEY` | Credencial opcional para Embase Search API. |
| `HERMES_IEEE_API_KEY` | Credencial opcional para IEEE Xplore Metadata API. |

Los emails y claves viven solo en `.env`. Los artefactos registran si una fuente
se consultó o se omitió, pero nunca copian esas credenciales. Si falta acceso
institucional, la búsqueda abierta continúa y el `search-log.csv` conserva la
omisión como limitación de cobertura.

## Datos

| Variable | Función |
|---|---|
| `HERMES_DATA_DIR` | Estado, plugin, skills, logs y sesiones. |
| `HERMES_WORKSPACE_DIR` | Revisiones y artefactos científicos. |
| `OBSIDIAN_VAULT_HOST_PATH` | Vault local opcional. |
| `HERMES_PUBLIC_REVIEW_WORKSPACE` | Ruta interna, normalmente `/workspace`. |

Las rutas relativas se resuelven desde la carpeta del paquete. Si una ruta
contiene espacios, `setup` la conserva citada correctamente.

## Watchdog

| Variable | Función |
|---|---|
| `PRISMA_WATCHDOG_INTERVAL_SECONDS` | Frecuencia de inspección. |
| `PRISMA_WATCHDOG_STALLED_MINUTES` | Tiempo sin progreso antes de considerar bloqueo. |
| `PRISMA_WATCHDOG_COOLDOWN_MINUTES` | Espera mínima entre reintentos. |
| `PRISMA_WATCHDOG_AGENT_TIMEOUT_SECONDS` | Límite de una ejecución reanudada. |
| `PRISMA_WATCHDOG_MAX_ATTEMPTS_PER_STATE` | Intentos permitidos para el mismo estado material. |
| `PRISMA_WATCHDOG_MAX_TOTAL_ATTEMPTS` | Límite total de continuidad para una revisión. |
| `PRISMA_WATCHDOG_MAX_BACKOFF_MINUTES` | Techo del backoff exponencial. |
| `PRISMA_WATCHDOG_EXECUTION_MODE` | Runner versionado utilizado para reanudar. |
| `PRISMA_WATCHDOG_MODELS` | Cadena opcional de modelos para continuidad. |
| `PRISMA_WATCHDOG_ALLOW_YOLO` | Compatibilidad heredada del runner `agentic`; debe permanecer en `0`. |

No reduzcas los tiempos para “acelerar” el sistema sin revisar límites del
proveedor. Un reintento agresivo puede duplicar coste o peticiones. El watchdog
no cruza `waiting_for_researcher`, una adjudicación pendiente ni un cambio
material de protocolo aunque queden intentos disponibles.

## Recuperación segura de texto completo

| Variable | Función |
|---|---|
| `HERMES_FULLTEXT_MAX_BYTES` | Tamaño máximo descargable antes de rechazar el documento. |
| `HERMES_FULLTEXT_ALLOW_HTTP` | Excepción explícita para HTTP; desactivada por defecto. |
| `HERMES_FULLTEXT_ALLOW_CUSTOM_PORTS` | Excepción explícita para puertos no estándar; desactivada por defecto. |

La recuperación valida cada redirección, resolución DNS, rango de red, tipo de
contenido, tamaño y cabecera PDF. Las dos excepciones reducen la protección
SSRF y solo deben activarse para una fuente institucional controlada y
documentada.

## Docling

| Variable | Función |
|---|---|
| `HERMES_DOCLING_ENABLED` | `auto` usa el servicio si está healthy. |
| `HERMES_DOCLING_API_KEY` | Secreto local generado para autenticar gateway, healthcheck y worker. |
| `DOCLING_SERVE_URL` | URL interna del worker. |
| `HERMES_DOCLING_DOCUMENT_TIMEOUT` | Límite por documento. |
| `HERMES_DOCLING_MAX_FILE_MB` | Tamaño máximo enviado. |
| `HERMES_DOCLING_DOCUMENT_LIMIT` | `0` procesa todos los focales. |
| `DOCLING_SERVE_MAX_NUM_PAGES` | Protección por número de páginas. |
| `DOCLING_SERVE_MAX_FILE_SIZE` | Techo del archivo aceptado por el servicio, en bytes. |
| `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` | Tiempo total máximo de procesamiento, en segundos. |
| `DOCLING_SERVE_MAX_SYNC_WAIT` | Espera máxima de una llamada síncrona, en segundos. |
| `DOCLING_NUM_THREADS` | Paralelismo CPU. |
| `DOCLING_PERF_PAGE_BATCH_SIZE` | Número de páginas procesadas por lote. |

La imagen de Docling está fijada por digest en `.env.example`. La API key no se
publica ni se reutiliza como credencial de inferencia. Cambiar la imagen exige
prueba documental, escaneo y validación de release.

`PRISMA_WATCHDOG_ALLOW_YOLO=1` solo afecta al modo heredado `agentic` y añade
`--yolo` al proceso reanudado. No forma parte del contrato seguro ni debe
activarse en una instalación pública.

## Pines de mantenimiento

`HERMES_SOURCE_REF`, `HERMES_SOURCE_COMMIT` y `HERMES_IMAGE_TAG` fijan la
versión upstream de Hermes y el nombre de la imagen. No son ajustes cotidianos:
si cambian, deben actualizarse `COMPATIBILITY.md`, reconstruirse la imagen y
repetirse plugin-only, pruebas, escaneos y clean-room.

## Múltiples instalaciones

Asigna un proyecto y nombres únicos:

```dotenv
COMPOSE_PROJECT_NAME=hermes-research-team-a
HERMES_CONTAINER_NAME=hermes-research-team-a
HERMES_WATCHDOG_CONTAINER_NAME=hermes-research-team-a-watchdog
DOCLING_CONTAINER_NAME=hermes-research-team-a-docling
```

Usa también rutas de datos distintas. Compartir `runtime/hermes-home` entre
instancias simultáneas no está soportado.
