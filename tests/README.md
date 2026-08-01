# Tests

Este directorio documenta la batería mínima que debe pasar el paquete antes de
considerarse apto para una distribución pública.

## Preparar la suite local

```bash
python3 -m venv .venv
make install-dev PYTHON=./.venv/bin/python
make check PYTHON=./.venv/bin/python
```

No uses el Python global sin instalar antes
`build/research-requirements.txt`. La suite de análisis estructural requiere
`networkx`; una colección parcial por dependencia ausente no representa el
estado del runtime Docker ni el resultado completo de las pruebas.

## Niveles de verificación

1. `doctor`
   Comprueba estructura, variables, contenedores y reachability básica.

2. `smoke-test`
   Simula el recorrido público mínimo de Telegram y verifica artefactos reales
   en disco.

3. revisión humana corta
   Confirma que el bot responde con copy entendible y que el onboarding no
   expone rutas, claves o comandos internos innecesarios.

4. `docling-test`
   Procesa un PDF digital a dos columnas, un PDF tabular y un PDF escaneado.
   Comprueba orden de lectura, OCR, celdas completas, figura fuente y
   procedencia basada únicamente en DOI.

5. `cleanroom-validate`
   Instala una copia nueva del bundle, materializa su runtime, renderiza
   Compose y construye la imagen principal sin depender del árbol de
   desarrollo.

## Resultado esperado

Una instalación pública buena debería permitir:

- arrancar contenedores
- pasar `doctor`
- pasar `smoke-test`
- pasar `docling-test` cuando se habilita el perfil `docling`
- continuar con fallback Poppler cuando Docling no está disponible
- exportar Markdown, JSON, tablas y figuras fuente con DOI y hash del PDF
- crear una revisión nueva por Telegram o CLI
- consultar estado
- reanudar una revisión sin conocer comandos internos del gateway
