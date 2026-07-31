# Resolución de problemas

## `setup` no puede escribir `.env`

Comprueba que el directorio pertenece a tu usuario. No ejecutes todo el paquete
con `sudo`; eso suele dejar `runtime/` con propietarios incompatibles.

```bash
ls -ld . runtime
ls -l .env
```

`.env` debe tener permisos `-rw-------`.

## `doctor` no encuentra el endpoint

Comprueba que la URL termina en `/v1`, que la API key sigue activa y que el
host puede resolver DNS y salir por HTTPS. No pegues la clave en un issue.

```bash
./hermes-research setup
./hermes-research doctor
```

Un `401` o `403` suele indicar credencial o autorización. Un `404` suele
indicar una URL base incorrecta. Un timeout suele indicar red, proxy o firewall.

## El modelo configurado no aparece

Los nombres cambian entre proveedores. Consulta su catálogo y vuelve a ejecutar
`setup`. Los tres modelos deben aparecer exactamente en `GET /models`.

## Telegram no responde

Comprueba el modo en `.env`, el token y los logs:

```bash
./hermes-research logs --tail 300
```

Un token de Telegram solo admite un consumidor de polling activo. Detén otra
instancia que use el mismo bot o crea un bot dedicado.

## El contenedor pertenece a otra instalación

`doctor` compara los mounts. Si avisa de una colisión, define valores únicos
para `COMPOSE_PROJECT_NAME`, `HERMES_CONTAINER_NAME` y
`HERMES_WATCHDOG_CONTAINER_NAME`, y vuelve a levantar el paquete.

## Docling no queda healthy

La primera ejecución puede descargar modelos y tardar. Comprueba memoria,
espacio y logs:

```bash
docker system df
./hermes-research logs --tail 300
```

Puedes continuar con:

```bash
./hermes-research down
./hermes-research up --without-docling
```

El fallback Poppler mantiene texto y renderizado, pero la auditoría debe dejar
constancia de la reducción en OCR, orden de lectura y tablas.

## Una revisión queda parada

```bash
./hermes-research status
./hermes-research logs --tail 300
./hermes-research resume
```

No borres `notes/runtime-state.json` ni los CSV para “forzar” el avance. Esos
archivos permiten distinguir una espera externa, un bloqueo metodológico y una
fase incompleta.

## Las figuras o tablas salen mal en el PDF

Comprueba primero el activo fuente y después el render final. Una figura debe
tener función analítica, anchura compatible, tipografía coherente y texto
legible. Una tabla no puede contener puntos suspensivos como sustituto de
filas.

Si el PDF excede márgenes, bloquea la publicación y corrige la generación; no
reduzcas toda la página hasta hacer ilegible el contenido.

## La construcción tarda o ocupa demasiado

La imagen Hermes y Docling son separadas. `hermes-agent-local` no debe contener
compiladores, Git ni PyTorch. Limpia cachés de build solo si necesitas espacio:

```bash
docker builder prune
```

Ese comando afecta a la caché global de Docker; revisa antes qué otros proyectos
comparten el host.

## Recuperación

Restaura `runtime/workspace` para recuperar revisiones y
`runtime/hermes-home` para conservar estado operativo. Después ejecuta
`./hermes-research doctor` antes de reanudar.
