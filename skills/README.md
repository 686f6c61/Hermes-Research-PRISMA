# Skills

Este directorio no intenta duplicar todavía todo el árbol de skills ejecutables
de Hermes. Su función en esta fase es documentar el **contrato research** del
bundle y dejar trazable qué skills forman parte del flujo PRISMA publicable.

## Archivo principal

- `research-manifest.json`

Ese manifiesto lista:

- nombre de la skill
- si existe `SKILL.md`
- cuántos scripts Python expone
- qué scripts concretos contiene
- cuántas referencias auxiliares tiene

## Skills que importan más en este paquete

- `prisma-systematic-review`
- `prisma-status`
- `academic-paper-reviewer`
- `research-integrity-audit`
- `revision-roadmap`

## Uso previsto

El manifiesto sirve para tres tareas:

1. revisar qué depende realmente del modo research
2. detectar cambios entre versiones del bundle
3. preparar una futura exportación standalone de skills
