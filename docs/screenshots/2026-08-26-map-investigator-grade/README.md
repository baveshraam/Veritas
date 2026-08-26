# Screenshots — map made investigator-grade, 2026-08-26

Captured live against the deployed console
(`https://veritas-60077763394.development.catalystserverless.in/app/index.html?as=DSP`)
via headless Chrome driven over CDP, per `[[veritas-console-verification]]`.

**The defect**: `MapView.tsx`'s `fitBounds()` call zoomed to `maxZoom: 11` whenever a
query returned a tightly-clustered result set (a handful of FIRs in one taluk). At that
zoom, every neighbouring district dot/label fell outside the viewport, leaving one label
floating in an unlabeled dark field — a hotspot with no visible geography around it. No
legend existed anywhere, so an officer had no way to tell an exact FIR point from a
modeled hotspot-density region. Confirmed by comparing the committed
`docs/screenshots/2026-08-26-conversational-architecture/06-case-locations-map.png`
against the code before this pass — that screenshot shows exactly one district label
("Mandya") on an otherwise blank canvas.

**The fix** (`apps/web/components/viz/MapView.tsx`, `apps/web/app/globals.css`):
1. `maxZoom` capped at 9 instead of 11 — a tight cluster now keeps a ~150-250km window,
   so several neighbouring districts stay in frame no matter how tight the underlying
   points are.
2. A small legend (`.map-legend`) added top-left: an amber dot = an individual cited FIR
   location; a green→amber→red gradient bar = hotspot density (low→high), matching the
   same severity ramp used everywhere else in the console.
3. Hotspot polygon fill/line opacity raised (0.26→0.4, line 1.6→2/0.85→0.95) so the
   aggregate density region reads as distinct from the individual points inside it,
   where the polygon area is large enough to render at all.

No district *boundary* polygons were added — none exist in this dataset (no shapefile is
bundled, and the architecture forbids fetching one from a third-party tile/boundary
service at request time), so this renders what the data actually supports honestly: real
district centres, labeled, not a fabricated outline.

| File | Query | What it shows |
|---|---|---|
| `01-live-tight-cluster-mandya.png` | "Where are the theft hotspots in Mandya district?" | The exact previously-broken case: a tight single-district cluster (4 hotspots, ~90 FIR points, all near Mandya). Now shows 3 district labels (Mandya, Ramanagara, Mysuru), the legend, a 10km scale bar, and zoom control — an officer can tell where this is relative to its neighbours in under 3 seconds |
| `02-live-statewide-hotspots.png` | "Show me crime hotspots" (bare, no district named) | The broad/unscoped path, unaffected by the `maxZoom` cap since its natural bounds are already wide. 6 district labels visible (Chikkaballapura, Bengaluru Rural, Kolar, Bengaluru Urban, Ramanagara, one partially clipped), plus a visible hotspot polygon outline around the two densest clusters — confirms the opacity fix, not just the zoom fix |

Both screenshots were also reproduced against a local API run (sqlite mirror, same
10,000-case dataset) before deploying, to isolate the frontend change from any live
platform variable — see the session's own verification log in `docs/WORK_LOG.md`.
