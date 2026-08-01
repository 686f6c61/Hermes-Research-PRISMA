# Guía de mantenimiento

## Fuentes de verdad

- `VERSION`: versión del producto.
- `CITATION.cff`: metadatos citables de esa misma versión.
- `COMPATIBILITY.md`: Hermes, host y proveedor soportados.
- `seed/hermes-home/plugins/hermes_research/plugin.yaml`: versión del plugin.
- `Dockerfile.research`: commit upstream y dependencias runtime.
- `.env.example`: contrato de configuración.
- `templates/`: esquema de una revisión nueva.
- `seed/hermes-home/skills/research/`: implementación research.

La carpeta `runtime/` nunca es fuente de verdad. Puede contener cambios
materiales de una ejecución y no debe copiarse al release.

## Cambios de código

```bash
python3 -m venv .venv
make install-dev PYTHON=./.venv/bin/python
make check PYTHON=./.venv/bin/python
./scripts/sync-bundle-assets.sh
./hermes-research cleanroom-validate
```

No ejecutes `python3 -m pytest` con un Python del host sin preparar. La suite
incluye el análisis de redes y necesita las versiones fijadas en
`build/research-requirements.txt`; `make install-dev` instala ese contrato y
evita convertir una dependencia ausente en un falso fallo del producto.

Si cambia PDF, modelos o Docker:

```bash
./hermes-research multimodal-test
./hermes-research docling-test
./scripts/security-audit.sh
```

## Dependencias

Fija versiones, commits o digests. No uses `latest`. Justifica una excepción en
el changelog y vuelve a generar el SBOM.

Los hallazgos HIGH/CRITICAL con corrección disponible bloquean el release. Los
hallazgos sin corrección se registran, se evalúan según superficie alcanzable y
se revisan en cada versión.

## Datos de prueba

Los fixtures públicos deben ser sintéticos, pequeños y libres de derechos
ambiguos. No incluyas un “ejemplo” derivado de una revisión real. Las pruebas
de integración pueden descargar fuentes autorizadas durante CI, pero no deben
empaquetarlas.

## Revisión del ZIP

El ZIP final debe:

- instalarse sin acceso a carpetas del mantenedor;
- excluir `.env`, `runtime`, landing, caches y corpus;
- contener licencia, seguridad, avisos de terceros y manifiesto;
- verificar hashes internos;
- pasar tests tras extraerse;
- incluir checksum y SBOM como archivos separados en la release.

## Coherencia de metadatos

`python3 scripts/validate-publication-metadata.py` exige que `VERSION`,
`plugin.yaml`, `CITATION.cff` y `CHANGELOG.md` describan la misma versión. No
edites uno sin actualizar los demás.

Los comentarios de código nuevos deben estar en inglés y explicar decisiones,
invariantes o controles de fallo. Los detalles de uso permanecen en la
documentación para no convertir los scripts en manuales duplicados.

Antes de una release documental, contrasta además:

- todos los subcomandos de `./hermes-research -h`;
- todas las variables de `.env.example`;
- comandos del menú y acciones contextuales de Telegram;
- artefactos exigidos por los esquemas y el publication gate;
- restauración de secretos y decisiones firmadas;
- versión visible en landing, README, issue forms y capturas.

Las imágenes del README deben ser renders de la landing de la misma versión.
Captura los bloques de producto, entregables, proceso, lectura y agentes a
anchura de escritorio; revisa que no haya overlays, animaciones a medias,
texto cortado ni contenido fuera del viewport. Conserva nombres estables en
`docs/images/` para no romper enlaces históricos del README.

## Plugin

La integración research debe permanecer fuera del núcleo de Hermes. Antes de
cada release ejecuta `make plugin-only`: el test descarga los tres módulos
upstream críticos, los compara byte a byte con la imagen, descubre el plugin,
comprueba sus comandos, ejercita el hook de Telegram y arranca el gateway.

No añadas una copia de `hermes_cli/commands.py`, `gateway/run.py` o
`gateway/slash_commands.py` al Dockerfile. Si una futura versión upstream rompe
el contrato, adapta el plugin o documenta el bloqueo antes de publicar.
