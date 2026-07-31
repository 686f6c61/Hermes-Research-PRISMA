# Instalación

## Antes de empezar

Hermes Research Pack está pensado para una máquina personal o servidor
controlado por la persona investigadora. La instalación predeterminada no
publica puertos.

Requisitos mínimos:

- Linux o macOS.
- Docker Engine o Docker Desktop con Compose v2.
- Python 3.11 o superior.
- `bash`, `curl`, `rsync`, `zip` y `unzip`.
- 8 GB de RAM sin Docling; 12 GB recomendados con Docling.
- 20 GB libres para imágenes, cachés documentales y corpus.
- Un endpoint de inferencia compatible con OpenAI.

Comprueba:

```bash
docker version
docker compose version
python3 --version
```

## Obtener y verificar

Descarga el ZIP y su archivo `.sha256` desde la misma release. Verifica antes
de descomprimir:

```bash
shasum -a 256 -c hermes-research-pack-vX.Y.Z-*.zip.sha256
unzip hermes-research-pack-vX.Y.Z-*.zip
cd hermes-research-pack
```

En Linux, `sha256sum -c` ofrece la comprobación equivalente.

## Configuración guiada

```bash
./hermes-research setup
```

En una instalación nueva, el comando ejecuta primero el instalador estructural:

- crea `runtime/hermes-home`;
- crea `runtime/workspace`;
- crea `runtime/obsidian`;
- copia la plantilla de revisión;
- habilita el plugin;
- crea `.env` sin valores reales.

Después solicita:

1. modo `cli`, `telegram` o `both`;
2. endpoint OpenAI-compatible;
3. modelo principal;
4. modelo con visión;
5. modelo revisor;
6. API key;
7. token de Telegram cuando corresponde.

Los secretos no se muestran y `.env` queda con permisos `0600`.

## Telegram

Si eliges `telegram` o `both`:

1. abre BotFather en Telegram;
2. crea un bot dedicado;
3. copia el token una sola vez en `setup`;
4. no reutilices un bot que ya esté ejecutándose en otro host.

El paquete registra su menú público al arrancar. No necesitas editar comandos
internos ni archivos Python.

## Arranque

```bash
./hermes-research up
```

Antes de construir, `up` ejecuta `doctor`, que valida estructura, configuración,
endpoint y catálogo de modelos. Después levanta:

- `hermes-agent`;
- `hermes-prisma-watchdog`;
- `hermes-docling`, salvo que se omita.

Para un host limitado:

```bash
./hermes-research up --without-docling
```

## Aceptación

```bash
./hermes-research smoke-test
./hermes-research multimodal-test
./hermes-research docling-test
```

`smoke-test` es obligatorio. Los otros dos validan visión y extracción
estructurada. No inicies un corpus costoso si el diagnóstico o el smoke test
fallan.

El smoke test usa un modo interno acotado: consulta OpenAlex y Crossref, escribe
registros reales y termina antes del cribado intensivo. No deja una revisión
editorial consumiendo inferencia en segundo plano. Ese límite no se aplica a
una revisión normal.

## Instalación no interactiva

Para automatización local, exporta las variables sin escribirlas en scripts:

```bash
export HERMES_INSTALL_MODE=cli
export HERMES_INFERENCE_BASE_URL=https://provider.example/v1
export HERMES_INFERENCE_API_KEY='secret'
export HERMES_MODEL_PRIMARY=model-primary
export HERMES_MODEL_VISION=model-vision
export HERMES_MODEL_REVIEW=model-review
./hermes-research setup --non-interactive
```

Usa un gestor de secretos del host o del CI. No guardes esos `export` en el
historial, documentación o repositorio.

## Desinstalación

Primero detén:

```bash
./hermes-research down
```

Archiva o elimina manualmente `runtime/` según la política de conservación del
proyecto. Borrar la carpeta del programa sin revisar `runtime/workspace` puede
eliminar el corpus, las decisiones y los manuscritos.
