# Runtime Seed

Este directorio contiene la semilla mínima de `hermes-home` que el paquete
necesita para arrancar sus contenedores sin depender de un estado previo del
repositorio local.

## Qué incluye

- `bin/`
- `config.yaml`
- `skills/research/`
- `public-prisma-bindings.json`
- directorios base de `home/default`, `logs` y `watchdog`

## Qué no incluye

No incluye estados vivos, sesiones, logs históricos, bases de datos, memoria
acumulada ni secretos locales.

## Objetivo

Separar la **configuración ejecutable mínima** del ruido operativo que existe
en un `hermes-home` de desarrollo real.
