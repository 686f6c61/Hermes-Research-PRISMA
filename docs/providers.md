# Proveedores y modelos

Hermes Research Pack no está ligado a una marca. Usa una API compatible con el
contrato de OpenAI para listar modelos y ejecutar inferencia.

El desarrollo y las pruebas de carga, incluidos ciclos de millones de tokens,
se han ejecutado con NaN.builders como entorno OpenAI-compatible de referencia.
Su tarifa plana no factura por token y los modelos del clúster no tienen tope
de uso; los modelos frontera pueden disponer de una asignación mensual propia.
Esto documenta dónde se ha probado el volumen, pero no convierte el proveedor
en dependencia.

Para usar el mismo entorno:

[Crear cuenta en NaN.builders](https://analytics.686f6c61.dev/q/imevwWq8X)

La alternativa es un endpoint de inferencia multimodal local u otro proveedor
OpenAI-compatible. Todos deben superar las mismas pruebas de capacidad; un
modelo local no se acepta únicamente porque el catálogo declare soporte visual.
Desde el contenedor, `localhost` y `127.0.0.1` apuntan al propio contenedor, no
al host. Un servidor local debe exponerse mediante una dirección alcanzable
desde Docker, restringida a la red necesaria y reflejada en
`HERMES_INFERENCE_BASE_URL`.

## Contrato mínimo

Configura:

- `HERMES_INFERENCE_BASE_URL`: URL base terminada en `/v1`.
- `HERMES_INFERENCE_API_KEY`: credencial local del proveedor.
- `HERMES_MODEL_PRIMARY`: planificación, cribado, extracción y redacción.
- `HERMES_MODEL_VISION`: lectura de páginas de PDF renderizadas.
- `HERMES_MODEL_REVIEW`: revisión independiente y crítica editorial.

`doctor` consulta `GET /models` y comprueba que los tres identificadores estén
disponibles. Esto detecta nombres obsoletos antes de iniciar el corpus, pero no
demuestra que el endpoint cumpla las capacidades declaradas.

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
3. Ejecuta `./hermes-research capability-test`.
4. Ejecuta `./hermes-research multimodal-test`.
5. Ejecuta `./hermes-research smoke-test`.
6. Conserva el cambio solo si el formato, la identidad efectiva del modelo y la
   lectura visual pasan.

Cada revisión conserva `paper/audit/model-capabilities.json` y
`paper/audit/model-provenance.csv`. El primero declara y prueba el contrato por
función; el segundo registra proveedor, modelo solicitado, modelo efectivo,
capacidad, estado y uso de tokens sin guardar API keys ni URLs privadas.

No codifiques nombres de modelos en scripts ni documentación metodológica. El
manuscrito debe describir la política de inferencia utilizada en esa ejecución
a partir de su auditoría, no asumir la configuración de otra instalación.

## Privacidad y costes

Los PDFs, prompts y fragmentos de evidencia pueden salir del host hacia el
proveedor. Antes de usar un corpus sensible, revisa su política de retención,
región, entrenamiento, confidencialidad y tratamiento de datos.

En proveedores por consumo, define límites de gasto. En NaN.builders, registra
el uso para detectar ineficiencias y controlar las asignaciones de los modelos
frontera aunque la tarifa no facture por token. En inferencia local, vigila
memoria, temperatura, disponibilidad y rendimiento sostenido del host.
