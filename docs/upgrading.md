# Actualización

## Principio

Actualiza el paquete como una unidad. No reemplaces solo el plugin, el
Dockerfile o una skill: la versión pública combina un plugin standalone,
dependencias científicas, plantilla, scripts y una versión fijada de Hermes
Agent sin reemplazar módulos de su núcleo.

## Antes de actualizar

1. Lee `CHANGELOG.md` y `COMPATIBILITY.md`.
2. Detén revisiones activas en un punto recuperable.
3. Ejecuta `./hermes-research status` y conserva la salida.
4. Detén con `./hermes-research down`.
5. Copia `runtime/workspace`, `runtime/hermes-home` y `.env` de forma segura.
6. Conserva el ZIP y checksum de la versión anterior.

## Instalación de la nueva versión

1. Verifica el checksum del nuevo ZIP.
2. Descomprime en una carpeta nueva.
3. Copia o restaura los bind mounts y el `.env` original; no sobrescribas la
   copia de seguridad ni regeneres el secreto de adjudicación.
4. Ejecuta `./hermes-research setup` solo para reconciliar campos nuevos,
   conservando los valores privados existentes.
5. Ejecuta `HERMES_REFRESH_RUNTIME_HOME=1 bash install.sh` solo cuando las
   notas indiquen que la semilla debe actualizarse.
6. Ejecuta `./hermes-research doctor`.
7. Ejecuta `./hermes-research up`.
8. Ejecuta `./hermes-research smoke-test`.
9. Ejecuta `capability-test` y `multimodal-test` si cambia proveedor, modelo o
   runtime.
10. Comprueba una revisión existente con `status`, `disagreements` y
    `amendment` antes de reanudarla.

## Comprobaciones al actualizar a 0.6.0

1. Ejecuta `./hermes-research intelligence <review>` sobre una revisión
   existente y confirma que genera posiciones y prioridad de lectura sin
   modificar las decisiones de cribado.
2. Ejecuta `./hermes-research package <review>` y abre
   `figures/gallery.html` y `analysis/atlas/network-atlas.html`.
3. Comprueba que el manuscrito propone hasta cuatro figuras por defecto, o
   cinco figuras sustantivas en el subperfil de seguridad, y que el resto
   permanece disponible como suplemento.
4. Confirma que `.hermes/research-memory.json` sigue privado y que
   `notes/artifact-lineage.json` solo contiene rutas relativas.
5. Si activas `code-audit`, empieza sin `--inspect-remote`; no se debe clonar ni
   ejecutar código de artículos.

## Retroceso

Si falla la validación:

1. ejecuta `./hermes-research down`;
2. conserva los logs de diagnóstico saneados;
3. vuelve a la carpeta y runtime respaldados;
4. restaura la versión anterior de `.env`;
5. ejecuta `doctor` y `up`;
6. confirma que el estado coincide con el registrado antes del cambio.

No migres artefactos parcialmente escritos hacia atrás sin comprobar sus
esquemas.

## Mantenedores

Actualizar Hermes Agent requiere fijar tag y commit. Actualizar Docling requiere
fijar digest. Ambos cambios deben pasar tests, lectura multimodal, corpus
documental, Trivy, SBOM y clean-room. Consulta `docs/maintainers.md`.
