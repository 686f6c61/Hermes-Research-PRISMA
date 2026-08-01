# Proceso de release

Esta guía es para quien mantiene y publica Hermes Research Pack. Una persona
que solo quiere investigar no necesita ejecutar estos comandos.

## Regla de publicación

No publiques desde un árbol con secretos, runtime vivo o corpus real. El
artefacto distribuible se genera siempre con:

```bash
REQUIRE_CLEAN_RELEASE=1 ./hermes-research ship-release
```

La cadena:

1. reconstruye el manifiesto de skills desde la fuente pública;
2. ejecuta todos los tests;
3. construye la imagen Hermes fijada;
4. escanea secretos y vulnerabilidades corregibles;
5. genera un SBOM CycloneDX;
6. crea un ZIP saneado;
7. calcula SHA-256;
8. extrae el ZIP en una carpeta temporal;
9. instala y prueba esa copia;
10. verifica cada archivo contra `RELEASE-MANIFEST.json`.

## Artefactos

Para la versión `X.Y.Z` se generan:

- `dist/hermes-research-pack-vX.Y.Z-YYYYMMDD-HHMMSS.zip`
- el checksum `.zip.sha256`;
- `dist/security/hermes-research-pack-vX.Y.Z.cdx.json`;
- el informe de vulnerabilidades corregibles;
- `dist/LATEST.txt` con un nombre de archivo relativo;
- `dist/LATEST_SHA256.txt`.

## Publicación recomendada

1. Actualiza `VERSION`, `plugin.yaml`, `CITATION.cff` y `CHANGELOG.md`.
2. Comprueba `COMPATIBILITY.md` y el commit de Hermes.
3. Ejecuta `make check`, `make plugin-only` y
   `REQUIRE_CLEAN_RELEASE=1 ./hermes-research ship-release`.
4. Revisa que el informe corregible tenga cero hallazgos.
5. Crea y sube un tag anotado `vX.Y.Z`; si el repositorio exige firma
   criptográfica, aplica además su política de tags firmados.
6. El workflow `Release` repite las pruebas y publica ZIP, SHA-256, SBOM e informe.
7. Verifica la descarga publicada y vuelve a calcular el checksum.
8. Instala ese archivo descargado en una máquina limpia.

El workflow también puede lanzarse manualmente sobre un tag existente. No
publica desde una rama ni acepta un tag cuya versión difiera de `VERSION`.

No subas `.env`, logs, capturas, tokens, rutas locales ni carpetas
`runtime/`. No conviertas el repositorio en público hasta que el escaneo del
árbol y del ZIP haya pasado.

Sin `REQUIRE_CLEAN_RELEASE=1` puede generarse un candidato local para pruebas.
Su manifiesto marcará `source_tree_dirty: true`; ese artefacto no debe
publicarse como release oficial.

Las attestations nativas de GitHub pueden añadirse cuando la visibilidad y el
plan del repositorio las soporten. No sustituyen el checksum ni la verificación
clean-room del ZIP.

## Actualizar Hermes o Docling

Una actualización de upstream no es un cambio de texto. Debe fijar tag, commit
o digest, reconstruir la imagen, ejecutar pruebas documentales, pasar Trivy y
validar una revisión representativa. Si cambia el contrato de plugins,
gateway, modelos o PDF, actualiza `COMPATIBILITY.md`.
