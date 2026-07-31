# Figures

- Source of truth: `figures/svg/`
- Rendered assets for the paper: `figures/png/`
- Inventory: `figures/manifest.csv`
- Publication plan: `figures/paper-figures-spec.csv`
- Source evidence inventory: `figures/evidence-manifest.csv`

Suggested figure set:
- PRISMA flow
- taxonomy of studies, methods, or agent types
- evidence map
- conceptual or architecture diagram
- benchmark/result comparison figures grounded in extracted evidence

Workflow:
1. Define or revise the paper-level plan in `figures/paper-figures-spec.csv`
2. Generate figure scaffolds with `python hermes-home/skills/research/prisma-systematic-review/scripts/prepare_paper_figures.py workspace/systematic-review`
3. Refine the SVG in `figures/svg/` so it reflects real evidence, not a generic placeholder
4. Register or update the row in `figures/manifest.csv`
5. Render to PNG with the local figure pipeline
6. Sync updated assets to Obsidian
