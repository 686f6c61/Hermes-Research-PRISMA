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

## Telegram

| Variable | Función |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot dedicado. Vacío en modo CLI. |
| `HERMES_TELEGRAM_PUBLIC_MENU_ONLY` | Limita el menú a la superficie pública. |
| `HERMES_TELEGRAM_DISABLE_FALLBACK_IPS` | Evita transportes alternativos innecesarios. |

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
| `PRISMA_WATCHDOG_MODELS` | Cadena opcional de modelos para continuidad. |

No reduzcas los tiempos para “acelerar” el sistema sin revisar límites del
proveedor. Un reintento agresivo puede duplicar coste o peticiones.

## Docling

| Variable | Función |
|---|---|
| `HERMES_DOCLING_ENABLED` | `auto` usa el servicio si está healthy. |
| `DOCLING_SERVE_URL` | URL interna del worker. |
| `HERMES_DOCLING_DOCUMENT_TIMEOUT` | Límite por documento. |
| `HERMES_DOCLING_MAX_FILE_MB` | Tamaño máximo enviado. |
| `HERMES_DOCLING_DOCUMENT_LIMIT` | `0` procesa todos los focales. |
| `DOCLING_SERVE_MAX_NUM_PAGES` | Protección por número de páginas. |
| `DOCLING_NUM_THREADS` | Paralelismo CPU. |

La imagen de Docling está fijada por digest en `.env.example`. Cambiarla exige
prueba documental, escaneo y validación de release.

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
