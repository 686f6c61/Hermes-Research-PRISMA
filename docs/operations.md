# Operación

## Rutina diaria

```bash
./hermes-research status
./hermes-research logs --tail 200
```

Consulta el estado antes de relanzar. `resume` es idempotente respecto al
estado material y debe preferirse a ejecutar scripts internos:

```bash
./hermes-research resume
```

Si el estado es `waiting_for_researcher`, no ejecutes reintentos repetidos.
Consulta el bloqueo material:

```bash
./hermes-research disagreements <review>
./hermes-research amendment <review>
```

El primer comando muestra conflictos de elegibilidad; el segundo, una posible
modificación material del protocolo. Ninguno aprueba por sí solo.

## Inicio y parada

```bash
./hermes-research up
./hermes-research down
```

`down` conserva los directorios montados. Tras reiniciar el host, Compose aplica
`unless-stopped` y el watchdog relee las revisiones incompletas.

## Logs

```bash
./hermes-research logs --tail 300
./hermes-research logs --follow
```

Antes de compartir un log, elimina tokens, URLs firmadas, títulos sensibles,
fragmentos de documentos y datos personales. Los errores externos deben
documentarse con código HTTP y fase, no con credenciales.

## Copia de seguridad

Detén el paquete para obtener una copia coherente:

```bash
./hermes-research down
tar -czf hermes-workspace-backup.tar.gz runtime/workspace runtime/hermes-home
```

Protege el archivo como datos de investigación. `runtime/workspace` contiene
corpus, decisiones y manuscritos. `runtime/hermes-home` contiene estado,
bindings y configuración operativa. `.env` debe respaldarse por separado en un
gestor de secretos: contiene la clave que permite verificar adjudicaciones
existentes y la autenticación interna de Docling.

## Restauración

1. Instala la misma versión del paquete.
2. Restaura `runtime/workspace` y `runtime/hermes-home`.
3. Restaura el `.env` original desde el gestor de secretos.
4. Ejecuta `./hermes-research doctor`.
5. Levanta con `./hermes-research up`.
6. Revisa `status` antes de `resume`.

No regeneres `HERMES_ADJUDICATION_SECRET` si existen decisiones firmadas. No
restaures una semilla antigua sobre un runtime nuevo sin leer
`docs/upgrading.md`.

## Capacidad

Vigila:

```bash
docker stats
docker system df
du -sh runtime/*
```

El texto completo y las páginas renderizadas suelen dominar el disco. Conserva
los PDF de acuerdo con licencia y política de retención, y no elimines la
matriz o los logs metodológicos necesarios para reproducibilidad.

## Incidentes

Si una credencial se expone:

1. revócala en el proveedor;
2. detén el servicio afectado;
3. reemplázala mediante `setup`;
4. revisa logs e historial;
5. elimina el secreto del historial Git si llegó a confirmarse;
6. ejecuta el escaneo antes de publicar otra release.

No basta con borrar el valor del último commit.
