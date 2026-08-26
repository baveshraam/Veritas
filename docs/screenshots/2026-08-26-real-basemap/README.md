# Real geographic basemap

Supersedes `docs/screenshots/2026-08-26-map-investigator-grade/`, which documented the old
self-drawn dark-canvas map (no roads, no terrain, no real place recognition — just a plain
background with hand-placed district dots). `MapView.tsx` now loads a real MapLibre style
(`https://tiles.openfreemap.org/styles/liberty`, OSM-derived, no API key/registration — the
fifth documented Catalyst exception, `CLAUDE.md` §2) as the basemap; every Veritas overlay
(FIR points, hotspot density polygons, district reference labels, legend, scale, evidence
rail) is unchanged.

## Local verification (`01`–`04`)

API on `localhost:8000` against the existing sqlite mirror (`data/.veritas/ds.sqlite3`, the
same 10,000-case dataset), console on `localhost:3000` against it, signed in as DSP via
`?as=DSP`, driven headlessly over CDP (Chrome `--headless=new --remote-debugging-port=9222`),
per the `veritas-console-verification` pattern.

- **`01-tight-district-mandya.png`** — "Show me crime hotspots in Mandya": a tight,
  single-district cluster. Neighbouring districts (Mysuru, Ramanagara) stay labeled in
  frame at `maxZoom: 9`; real roads (NH275, NH948…), rivers and waterbodies are all visible.
- **`02-broad-karnataka-bengaluru.png`** — "Where are the crime hotspots?" (bare, statewide
  phrasing; the engine falls back to the busiest district rather than guessing a location).
  Renders around Bengaluru with 5 district labels in frame plus the basemap's own
  "Bengaluru" city label.
- **`03-hotspot-query-bidar.png`** — "Show me crime hotspots in Bidar", the state's
  northernmost district, on the Telangana border — confirms the basemap re-centers
  correctly and reads as real terrain anywhere in the state, not just near Bengaluru.
- **`04-no-results-kodagu.png`** — a district with no hotspot evidence in the local mirror:
  the evaluator refuses honestly and the centre pane falls back to the case index rather
  than rendering a broken or misleading map.

## Live verification (`05`–`09`)

Same four queries (plus one explicit refusal) replayed against the deployed console —
`https://veritas-60077763394.development.catalystserverless.in/app/index.html?as=DSP` —
after `scripts/deploy-console.sh`. The live AppSail container was cold at the first attempt
(the roster gate showed "Still loading the duty roster — the service is warming up", not a
map bug); re-run after the warm-up completed.

- **`05-live-tight-mandya.png`** / **`06-live-broad-statewide-phrased.png`** /
  **`07-live-bidar-far-district.png`** — identical basemap rendering to local: real roads,
  water, terrain, OpenFreeMap/OSM attribution bottom-right, legend top-left, scale
  bottom-left, district chips, FIR points, hotspot polygons.
- **`08-live-kodagu-western-ghats.png`** — the live dataset has hotspot evidence for Kodagu
  (the local mirror didn't); rendered instead of refusing, and turned out to be the most
  striking shot of the set — dense Western Ghats forest green, real town names (Madikeri),
  immediately recognizable as hill-district terrain.
- **`09-live-no-results-refusal.png`** — "Show me the money trail" (no subject named): the
  evaluator refuses honestly, centre pane falls back to the case index. Confirms the
  no-results path live, since Kodagu didn't exercise it live as expected.

## Judge read

Real roads/terrain/water, real place names from the basemap itself plus Veritas's own
district reference chips, a working legend distinguishing an exact FIR point from a modeled
hotspot region, a scale bar, zoom controls, and required OSM/OpenFreeMap attribution
(bottom-right, compact). No fabricated boundaries — Karnataka's district *polygons* are
still not part of this dataset, so none are drawn; only real centroids, labeled.
