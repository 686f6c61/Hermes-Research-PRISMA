# Agents and Services

El paquete combina servicios persistentes y agentes funcionales. La idea no es
que una persona tenga que orquestarlos a mano, sino que entienda qué papel
juega cada uno cuando la revisión se mueve sola.

## Servicios persistentes

### `hermes-agent`

Es el runtime principal. Aloja el gateway de Telegram, el wrapper público y la
ejecución real de las skills research.

### `hermes-prisma-watchdog`

Es el proceso de continuidad. Relee el estado material de las revisiones y
reintenta las que se quedan paradas sin depender de intervención humana.

## Agentes funcionales del flujo research

### Bootstrap público

Es la entrada determinista que convierte un intake corto en una revisión
materializada con protocolo, estructura de carpetas y estado inicial.

### Orquestador PRISMA

Vive principalmente en `complete_review.py`. Controla adquisición,
deduplicación, cribado, full text, extracción, shortlist y transición a la
capa editorial.

### Revisor editorial

Vive en `publication_peer_review.py`. Ejecuta la revisión cruzada del
manuscrito con dos modelos independientes y conserva los dictámenes por
separado.

### Auditor de integridad

Verifica coherencia material, cobertura de citas, presencia de artefactos y
consistencia metodológica antes del cierre.

### Gate de publicación

Decide si la revisión puede considerarse realmente cerrada. No basta con que
exista un texto: deben existir los artefactos de manuscrito, revisión,
auditoría y empaquetado.

## Qué significa “agentes” en este bundle

Aquí la palabra no se usa para inflar el producto. Significa que el trabajo se
divide en rutinas con responsabilidad clara:

- una crea
- otra continúa
- otra revisa
- otra audita
- otra decide el cierre

Ese reparto permite reanudar, auditar y explicar el proceso sin depender de un
único prompt gigante ni de una memoria verbal frágil.
