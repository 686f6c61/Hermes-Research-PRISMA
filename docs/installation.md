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
shasum -a 256 -c hermes-research-pack-vX.Y.Z.zip.sha256
unzip hermes-research-pack-vX.Y.Z.zip
cd hermes-research-pack
```

En Linux, `sha256sum -c` ofrece la comprobación equivalente.

## Configuración guiada

Puedes hacer que Hermes dirija la instalación. Abre la carpeta descomprimida
con tu agente y usa esta instrucción:

> Lee `Setup_Hermes.txt`, guíame paso a paso y no declares la instalación
> terminada hasta que hayan pasado todas las pruebas de aceptación.

El runbook obliga al agente a comprobar la máquina, explicar cada credencial,
mantener los secretos fuera de la conversación, resolver fallos y entregar un
resumen de aceptación. No sustituye a `setup`: lo supervisa y comprueba.

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
7. email de contacto y credenciales académicas opcionales;
8. nombre, email y ORCID opcional de la persona investigadora responsable;
9. token de Telegram cuando corresponde;
10. usuarios autorizados y chat privado de avisos.

La identidad firma adjudicaciones y cambios de protocolo; no se inventa a
partir del manuscrito. `setup` genera secretos independientes para firmas y
Docling, no los muestra y deja `.env` con permisos `0600`. Conserva ese archivo
en un gestor de secretos: regenerar `HERMES_ADJUDICATION_SECRET` puede
invalidar decisiones ya firmadas.

## Telegram

Si eliges `telegram` o `both`:

1. abre BotFather en Telegram;
2. crea un bot dedicado;
3. abre ese bot y envíale `/start`;
4. copia el token una sola vez en `setup`;
5. confirma el ID numérico que descubre el asistente;
6. no reutilices un bot que ya esté ejecutándose en otro host.

El paquete registra su menú público al arrancar. `TELEGRAM_ALLOWED_USERS`
restringe quién puede controlarlo; `TELEGRAM_HOME_CHANNEL` y
`TELEGRAM_PRISMA_CHAT_ID` fijan el chat privado que recibe progreso y avisos.
El token por sí solo no completa ni protege la instalación. No necesitas editar
comandos internos ni archivos Python.

## APIs académicas

Crossref, OpenAIRE, Europe PMC y arXiv funcionan sin API key. OpenAlex permite
una cuota anónima pequeña, pero para una revisión real conviene configurar su
clave gratuita. El asistente también permite configurar:

- un email técnico privado para acceso cortés;
- email de Unpaywall para localizar texto completo abierto;
- API key gratuita recomendada de OpenAlex;
- API key opcional de Semantic Scholar;
- API key opcional de Lens Scholarly;
- email y API key opcional de NCBI/PubMed;
- credenciales opcionales de Scopus, Web of Science, Embase e IEEE Xplore.

Una credencial ausente no se inventa ni bloquea fuentes independientes: la
fuente afectada queda omitida de forma trazable. Scopus, Web of Science, Embase
e IEEE Xplore se consultan mediante sus adaptadores cuando el acceso está
activo. PsycINFO y ACM Digital Library requieren una exportación autorizada o
una integración propia.

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
./hermes-research capability-test
./hermes-research multimodal-test
./hermes-research docling-test
```

`smoke-test` es obligatorio. `capability-test` prueba texto, JSON e identidad
efectiva de los modelos; `multimodal-test` valida visión y, cuando recibe una
revisión real, localiza automáticamente el PDF material más reciente y
contrasta el título recuperado desde la imagen de su primera página con la capa
textual del documento. El comprobante queda en
`paper/audit/multimodal-pdf-verification.json`. `docling-test` comprueba
extracción estructurada. No inicies un corpus costoso si falla una capacidad que
vaya a usar el protocolo.

El smoke test usa un modo interno acotado: consulta OpenAlex y Crossref, escribe
registros reales y termina antes del cribado intensivo. No deja una revisión
editorial consumiendo inferencia en segundo plano. Ese límite no se aplica a
una revisión normal.

## Capacidades de análisis de 0.6.0

Tras completar una revisión, estas capas se generan dentro del ciclo y también
pueden reconstruirse explícitamente:

```bash
./hermes-research intelligence <review>
./hermes-research memory <review>
./hermes-research code-audit <review>
./hermes-research package <review>
```

`intelligence` ordena posiciones de evidencia y prioridad de lectura sin
cambiar la selección. `memory` conserva contexto privado entre revisiones sin
heredar decisiones. `code-audit` es opcional y no ejecuta repositorios ajenos.
`package` actualiza el atlas cuando sea necesario y entrega la galería visual,
GraphML, exportación GEXF, Markdown, LaTeX, PDF y anexos saneados.

## Pausas por discrepancia

Un desacuerdo entre los dos juicios de elegibilidad a texto completo no se
convierte en rechazo ni en error de ejecución. El estado pasa a
`waiting_for_researcher` y conserva búsqueda, PDF, protocolo, juicios,
recomendación automática y conteos.

Consulta y resuelve por DOI:

```bash
./hermes-research disagreements <review>
./hermes-research resolve-screening <review> \
  --doi 10.xxxx/xxxxx \
  --decision include \
  --reason "Cumple población, fenómeno y resultado del protocolo."
```

La recomendación automática no es vinculante. La revisión continúa después de
la última decisión firmada y reutiliza el checkpoint si no han cambiado el
protocolo o el texto completo.

## Instalación no interactiva

Para automatización local, exporta las variables sin escribirlas en scripts:

```bash
export HERMES_INSTALL_MODE=cli
export HERMES_INFERENCE_BASE_URL=https://provider.example/v1
export HERMES_INFERENCE_API_KEY='secret'
export HERMES_MODEL_PRIMARY=model-primary
export HERMES_MODEL_VISION=model-vision
export HERMES_MODEL_REVIEW=model-review
export HERMES_CONTACT_EMAIL=research-api@example.org
export HERMES_UNPAYWALL_EMAIL=research-api@example.org
export HERMES_RESEARCHER_NAME='Research Owner'
export HERMES_RESEARCHER_EMAIL=owner@example.org
export HERMES_ADJUDICATION_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export HERMES_DOCLING_API_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
./hermes-research setup --non-interactive
```

En modo Telegram también debes exportar `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_ALLOWED_USERS`, `TELEGRAM_HOME_CHANNEL` y
`TELEGRAM_PRISMA_CHAT_ID`.

Estos comandos generan los dos secretos localmente sin imprimirlos. El texto
del comando puede quedar en el historial, pero no los valores resultantes.
Entrégalos mediante el gestor de secretos del host o del CI y nunca los
incorpores a documentación o repositorios.

## Desinstalación

Primero detén:

```bash
./hermes-research down
```

Archiva o elimina manualmente `runtime/` según la política de conservación del
proyecto. Borrar la carpeta del programa sin revisar `runtime/workspace` puede
eliminar el corpus, las decisiones y los manuscritos.
