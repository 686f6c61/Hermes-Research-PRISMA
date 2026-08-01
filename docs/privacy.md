# Privacidad y gobierno de datos

Hermes Research Pack procesa documentos académicos y puede procesar nombres,
correos, afiliaciones, entrevistas, muestras o datos sensibles contenidos en
ellos. La instalación técnica no determina por sí sola que ese tratamiento sea
lícito.

## Flujo de datos

- Los archivos se guardan en bind mounts locales.
- Los fragmentos y páginas necesarias pueden enviarse al proveedor de modelos.
- Telegram recibe los mensajes de intake si se usa ese modo.
- Las fuentes bibliográficas reciben consultas y metadatos técnicos.
- Docling procesa localmente dentro de Compose, autentica las llamadas internas
  y no publica puerto.
- Obsidian es un directorio local salvo que la persona lo sincronice fuera.

## Antes de investigar

Documenta:

1. responsable y finalidad;
2. base jurídica cuando haya datos personales;
3. categorías de datos y población;
4. proveedores externos y regiones;
5. retención y eliminación;
6. controles de acceso;
7. derechos de autor y licencias de texto completo;
8. si se permite enviar contenido a modelos externos.

## Minimización

No envíes un PDF completo al modelo si bastan páginas identificadas. No guardes
tokens en logs. No publiques correos de autores extraídos. No redistribuyas el
corpus dentro del ZIP del programa o del manuscrito.

Los registros de discrepancias y cambios de protocolo contienen identidad,
razón científica y firmas verificables. Permanecen en el workspace privado; el
paquete público conserva la decisión metodológica necesaria, no el secreto ni
identificadores internos.

Para datos sensibles, usa un proveedor con garantías contractuales adecuadas o
una infraestructura autorizada. El modo CLI evita Telegram, pero no evita la
salida hacia el proveedor de inferencia.

## Publicación

Los anexos deben conservar trazabilidad sin exponer datos innecesarios. Usa DOI
y procedencia bibliográfica; no identificadores internos. Revisa manualmente
figuras fuente, citas extensas, tablas y metadatos antes de compartir el paquete
editorial.

## Eliminación

Detener contenedores no elimina datos. Aplica la política de retención sobre
`runtime/workspace`, copias, cachés, Obsidian y archivos exportados. Revocar una
API key tampoco borra datos ya enviados al proveedor.
