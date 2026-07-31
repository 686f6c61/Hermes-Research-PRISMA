# Proveedores y modelos

Hermes Research Pack no está ligado a una marca. Usa una API compatible con el
contrato de OpenAI para listar modelos y ejecutar inferencia.

## Contrato mínimo

Configura:

- `HERMES_INFERENCE_BASE_URL`: URL base terminada en `/v1`.
- `HERMES_INFERENCE_API_KEY`: credencial local del proveedor.
- `HERMES_MODEL_PRIMARY`: planificación, cribado, extracción y redacción.
- `HERMES_MODEL_VISION`: lectura de páginas de PDF renderizadas.
- `HERMES_MODEL_REVIEW`: revisión independiente y crítica editorial.

`doctor` consulta `GET /models` y comprueba que los tres identificadores estén
disponibles. Esto detecta nombres obsoletos antes de iniciar el corpus.

## Cómo elegir modelos

El modelo principal debe seguir instrucciones largas, producir JSON estable,
mantener citas y trabajar con contexto suficiente para matrices de evidencia.

El modelo visual debe aceptar imágenes y leer texto pequeño, tablas, ejes y
diagramas. Un modelo textual no debe declararse como visual aunque sea más
capaz en razonamiento.

El revisor debe ser distinto del principal cuando sea posible. La independencia
no es perfecta si comparten proveedor o familia, pero reduce la autocorrección
complaciente y hace visibles desacuerdos.

## Probar un cambio

1. Ejecuta `./hermes-research setup` y cambia solo los identificadores.
2. Ejecuta `./hermes-research doctor`.
3. Ejecuta `./hermes-research multimodal-test`.
4. Ejecuta `./hermes-research smoke-test`.
5. Conserva el cambio solo si el formato, las citas y la lectura visual pasan.

No codifiques nombres de modelos en scripts ni documentación metodológica. El
manuscrito debe describir la política de inferencia utilizada en esa ejecución
a partir de su auditoría, no asumir la configuración de otra instalación.

## Privacidad y costes

Los PDFs, prompts y fragmentos de evidencia pueden salir del host hacia el
proveedor. Antes de usar un corpus sensible, revisa su política de retención,
región, entrenamiento, confidencialidad y tratamiento de datos.

Define límites de gasto en el proveedor. Los procesos autónomos pueden consumir
más inferencia de la esperada durante recuperación, reintentos o revisión.
