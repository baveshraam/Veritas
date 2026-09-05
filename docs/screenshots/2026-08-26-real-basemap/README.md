# Real geographic basemap

Supersedes `docs/screenshots/2026-08-26-map-investigator-grade/`, which documented the old
self-drawn dark-canvas map. `MapView.tsx` now loads a real MapLibre style
(`https://tiles.openfreemap.org/styles/liberty`, OSM-derived, no API key — the fifth
documented Catalyst exception, `CLAUDE.md` §2); every Veritas overlay (FIR points,
hotspot polygons, district labels, legend, scale) is unchanged.

## Local verification (`01`–`04`)

API on `localhost:8000` against the sqlite mirror (same 10,000-case dataset), console on
`localhost:3000`, signed in as DSP, driven headlessly over CDP.

- **`01-tight-district-mandya.png`** — "Show me crime hotspots in Mandya": tight
  single-district cluster; neighbouring districts stay labeled at `maxZoom: 9`; real
  roads/rivers visible.
- **`02-broad-karnataka-bengaluru.png`** — bare statewide phrasing (falls back to the
  busiest district). 5 district labels plus the basemap's own "Bengaluru" city label.
- **`03-hotspot-query-bidar.png`** — Bidar, the state's northernmost district — confirms
  the basemap re-centers and reads as real terrain anywhere in the state.
- **`04-no-results-kodagu.png`** — a district with no hotspot evidence locally: honest
  refusal, falls back to the case index.

## Live verification (`05`–`09`)

Same four queries plus one explicit refusal, replayed against the deployed console after
`scripts/deploy-console.sh`. First attempt hit a cold AppSail container (roster
warm-up message, not a map bug); re-run after warm-up.

- **`05`–`07`** — identical basemap rendering to local: roads, water, terrain, OSM
  attribution, legend, scale, district chips, FIR points, hotspot polygons.
- **`08-live-kodagu-western-ghats.png`** — the live dataset *does* have hotspot evidence
  for Kodagu; renders dense Western Ghats forest, real town names (Madikeri).
- **`09-live-no-results-refusal.png`** — "Show me the money trail" (no subject named):
  honest refusal, falls back to the case index.

## Judge read

Real roads/terrain/water, real place names from the basemap itself plus Veritas's own
district reference chips, a working legend distinguishing an exact FIR point from a modeled
hotspot region, a scale bar, zoom controls, and required OSM/OpenFreeMap attribution
(bottom-right, compact). No fabricated boundaries — Karnataka's district *polygons* are
still not part of this dataset, so none are drawn; only real centroids, labeled.
