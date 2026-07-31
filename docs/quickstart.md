# Inicio en 10 minutos

## 1. Comprueba los requisitos

Necesitas Docker Engine o Docker Desktop con Compose v2, Python 3.11 o
superior y al menos 12 GB de RAM recomendados si vas a usar Docling.

```bash
docker version
docker compose version
python3 --version
```

## 2. Configura la instalación

Para delegar el acompañamiento completo, pide a tu agente:

> Lee `Setup_Hermes.txt`, guíame paso a paso y no declares la instalación
> terminada hasta que hayan pasado todas las pruebas de aceptación.

```bash
./hermes-research setup
```

Elige `cli`, `telegram` o `both`. Introduce la URL base OpenAI-compatible, la
API key y tres identificadores de modelo: principal, visión y revisión
independiente. El asistente ofrece configuración académica adicional. En modo
Telegram también valida el token, detecta tu ID tras `/start`, restringe el bot
y fija el chat de avisos.

La clave se escribe sin eco en pantalla. La configuración queda en `.env` con
permisos `0600` y no se incluye en Git ni en los ZIP.

## 3. Arranca y valida

```bash
./hermes-research up
./hermes-research smoke-test
```

`up` ejecuta primero `doctor`. Si el endpoint no responde o un modelo no existe,
el proceso se detiene antes de iniciar una revisión.

La primera construcción descarga la imagen base, Hermes y, con el perfil
predeterminado, Docling. Puede tardar varios minutos.

Si el host tiene poca memoria:

```bash
./hermes-research up --without-docling
```

El pipeline conserva la extracción Poppler, aunque pierde parte de la
reconstrucción estructural, OCR y recuperación tabular.

## 4. Crea una revisión

```bash
./hermes-research init
```

El wizard solicita tema, pregunta, años, inclusión, exclusión, objetivo de N,
medio y modo autónomo. El N puede ser exacto (`35`) o un rango (`23-63`).

Para automatización:

```bash
./hermes-research init \
  --topic "Tema de la revisión" \
  --question "Pregunta de investigación" \
  --years 2024-2026 \
  --include "Criterios positivos verificables" \
  --exclude "Criterios negativos verificables" \
  --final-n 23-63
```

## 5. Sigue el ciclo

```bash
./hermes-research status
./hermes-research logs --follow
./hermes-research resume
```

Los artefactos aparecen dentro de `runtime/workspace/<revision>/`. El estado
no depende de mantener abierta la terminal: se reconstruye desde archivos y el
watchdog puede reanudar una fase incompleta.

## 6. Comprueba PDF y paquete final

```bash
./hermes-research multimodal-test
./hermes-research docling-test
./hermes-research package
```

El paquete final debe incluir Markdown, LaTeX editable, PDF, anexos,
bibliografía, auditoría y revisión. Un `PASS` técnico no elimina la revisión
académica y editorial humana.

## 7. Detén sin perder datos

```bash
./hermes-research down
```

Este comando detiene los servicios y conserva los bind mounts. No uses
`docker compose down -v` salvo que pretendas eliminar volúmenes adicionales de
forma deliberada.
