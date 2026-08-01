# Docling en Hermes Research

## Decisión de arquitectura

Docling no forma parte de la imagen `hermes-agent`. Se ejecuta en
`hermes-docling`, un contenedor CPU independiente, sin puerto publicado y
accesible solo desde la red interna de Compose. Las llamadas y el healthcheck
usan una API key local generada durante `setup`. Así, PyTorch y los modelos de
documentos no amplían el gateway, no tienen acceso a Telegram y no convierten
la disponibilidad del worker en una condición de continuidad.

La imagen está fijada por digest. La versión puede actualizarse de forma
deliberada en `DOCLING_IMAGE`, pero nunca queda flotando silenciosamente.

## Punto de entrada en el ciclo

Docling actúa después de recuperar un PDF DOI-válido y antes de construir la
evidencia visual, tabular y narrativa del manuscrito.

1. La ruta rápida extrae texto con Poppler.
2. Docling reconstruye el documento focal como Markdown y JSON.
3. Las tablas fuente se exportan completas a CSV y HTML.
4. Las figuras recuperables se exportan con DOI y página.
5. El resultado se cachea usando SHA-256 del PDF.
6. Un fallo conserva Poppler como fallback y nunca cierra falsamente la fase.

Docling no busca papers, no decide criterios de inclusión, no redacta el
manuscrito y no sustituye a los modelos principal, visual o revisor.

## Activación

```bash
./hermes-research up
./hermes-research docling-test
```

La prueba crea y elimina tres fixtures: PDF digital a dos columnas, PDF con
tabla y PDF escaneado. Puede conservarlos para inspección con:

```bash
KEEP_DOCLING_TEST_ARTIFACTS=1 ./hermes-research docling-test
```

## Configuración

- `HERMES_DOCLING_ENABLED=auto` usa Docling si está disponible.
- `HERMES_DOCLING_API_KEY` autentica el tráfico interno y debe conservar al
  restaurar la instalación.
- `DOCLING_SERVE_URL` apunta al servicio interno.
- `HERMES_DOCLING_DOCUMENT_TIMEOUT` limita cada PDF.
- `HERMES_DOCLING_MAX_FILE_MB` limita el archivo enviado.
- `HERMES_DOCLING_DOCUMENT_LIMIT=0` procesa todos los PDF focales disponibles.
- `DOCLING_SERVE_MAX_NUM_PAGES` protege al worker de documentos desmesurados.
- `DOCLING_SERVE_MAX_FILE_SIZE` fija el techo del archivo recibido, en bytes.
- `DOCLING_SERVE_MAX_DOCUMENT_TIMEOUT` limita el procesamiento total.
- `DOCLING_SERVE_MAX_SYNC_WAIT` limita la espera de la llamada síncrona.
- `DOCLING_NUM_THREADS` y `DOCLING_PERF_PAGE_BATCH_SIZE` acotan CPU y lote.

El servicio no publica ningún puerto y no comparte la red de Compose con
aplicaciones ajenas al bundle. La clave se guarda en `.env` con permisos
privados, se inyecta en ambos extremos y no entra en logs, artefactos o ZIP. Si
una instalación decide exponer Docling, queda fuera de este contrato seguro:
la clave interna no sustituye una política de autenticación, TLS y control de
red para acceso público.

## Criterios de aceptación

Una extracción estructurada se acepta solo si:

- existe un DOI normalizado;
- el PDF existe y respeta los límites;
- Docling devuelve JSON estructurado;
- el artefacto queda ligado al hash del PDF;
- las tablas conservan todas las celdas, sin puntos suspensivos;
- la procedencia incluye DOI y página cuando Docling la reporta.

La ausencia de una figura o tabla no se interpreta como error. Puede significar
que el documento no contiene ese tipo de evidencia. Los errores reales quedan
como `failed_fallback_poppler` y se pueden reintentar sin perder el resto del
ciclo.
