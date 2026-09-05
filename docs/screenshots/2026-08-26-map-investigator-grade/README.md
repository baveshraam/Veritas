# Screenshots — map made investigator-grade, 2026-08-26

**Superseded** by `docs/screenshots/2026-08-26-real-basemap/`: the self-drawn dark canvas
shown here was replaced with a real MapLibre + OpenFreeMap basemap. Kept for history —
the zoom-cap and legend fixes below are still in effect, just now drawn over real
geography.

Captured live against the deployed console via headless Chrome/CDP.

**The defect**: `MapView.tsx`'s `fitBounds()` zoomed to `maxZoom: 11` on a
tightly-clustered result (a handful of FIRs in one taluk), pushing every neighbouring
district dot/label out of the viewport — a hotspot with no visible geography around it,
and no legend to tell an exact FIR point from a modeled density region.

**The fix** (`apps/web/components/viz/MapView.tsx`, `globals.css`): `maxZoom` capped at 9
(keeps a ~150-250km window regardless of cluster tightness); a legend added (amber dot =
cited FIR, green→amber→red = hotspot density); hotspot fill/line opacity raised
(0.26→0.4) so density regions read as distinct from the points inside them.

No district *boundary* polygons were added — none exist in this dataset, so this renders
what the data actually supports: real district centres, labeled, not a fabricated outline.

| File | Query | What it shows |
|---|---|---|
| `01-live-tight-cluster-mandya.png` | "Where are the theft hotspots in Mandya district?" | The previously-broken case: tight single-district cluster, now shows 3 district labels, legend, scale bar and zoom control |
| `02-live-statewide-hotspots.png` | "Show me crime hotspots" (bare) | The broad/unscoped path — 6 district labels, plus a visible hotspot polygon outline confirming the opacity fix |

Both were also reproduced against a local API run before deploying, to isolate the
frontend change from any live platform variable.
