"use client";
import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { ramp, rgba, ACCENT, MAP_POINT } from "./palette";

type Hotspot = { polygon: [number, number][]; intensity: number; crime_count: number };
type Point = { lat: number; lng: number; fir_id: string; crime_no?: string | null; filed?: string | null };

// Karnataka's 31 real districts — code, name, and the same real centroid the
// generator's own geo sampling uses (data/data/seed/derived/district_centroids.csv),
// duplicated here rather than fetched, because it is static reference data an
// officer needs to orient a hotspot against, not a live query result. True district
// *boundary* polygons are not part of this dataset (no shapefile is bundled, and
// none is fetched from a third-party service at runtime per the architecture's own
// constraint on FIR-coordinate requests), so this renders what the data actually
// supports honestly: the real district centre, labeled — not a fabricated outline.
const DISTRICTS: { code: string; name: string; lat: number; lng: number }[] = [
  { code: "KA01", name: "Bagalkot", lat: 16.18, lng: 75.70 },
  { code: "KA02", name: "Ballari", lat: 15.14, lng: 76.92 },
  { code: "KA03", name: "Belagavi", lat: 15.85, lng: 74.50 },
  { code: "KA04", name: "Bengaluru Rural", lat: 13.22, lng: 77.57 },
  { code: "KA05", name: "Bengaluru Urban", lat: 12.97, lng: 77.59 },
  { code: "KA06", name: "Bidar", lat: 17.91, lng: 77.52 },
  { code: "KA07", name: "Vijayapura", lat: 16.83, lng: 75.71 },
  { code: "KA08", name: "Chamarajanagar", lat: 11.92, lng: 76.94 },
  { code: "KA09", name: "Chikkaballapura", lat: 13.43, lng: 77.73 },
  { code: "KA10", name: "Chikkamagaluru", lat: 13.32, lng: 75.77 },
  { code: "KA11", name: "Chitradurga", lat: 14.23, lng: 76.40 },
  { code: "KA12", name: "Dakshina Kannada", lat: 12.87, lng: 75.10 },
  { code: "KA13", name: "Davanagere", lat: 14.47, lng: 75.92 },
  { code: "KA14", name: "Dharwad", lat: 15.46, lng: 75.01 },
  { code: "KA15", name: "Gadag", lat: 15.43, lng: 75.63 },
  { code: "KA16", name: "Kalaburagi", lat: 17.33, lng: 76.83 },
  { code: "KA17", name: "Hassan", lat: 13.00, lng: 76.10 },
  { code: "KA18", name: "Haveri", lat: 14.80, lng: 75.40 },
  { code: "KA19", name: "Kodagu", lat: 12.42, lng: 75.74 },
  { code: "KA20", name: "Kolar", lat: 13.14, lng: 78.13 },
  { code: "KA21", name: "Koppal", lat: 15.35, lng: 76.15 },
  { code: "KA22", name: "Mandya", lat: 12.52, lng: 76.90 },
  { code: "KA23", name: "Mysuru", lat: 12.30, lng: 76.64 },
  { code: "KA24", name: "Raichur", lat: 16.21, lng: 77.36 },
  { code: "KA25", name: "Ramanagara", lat: 12.72, lng: 77.28 },
  { code: "KA26", name: "Shivamogga", lat: 13.93, lng: 75.57 },
  { code: "KA27", name: "Tumakuru", lat: 13.34, lng: 77.10 },
  { code: "KA28", name: "Udupi", lat: 13.34, lng: 74.75 },
  { code: "KA29", name: "Uttara Kannada", lat: 14.80, lng: 74.60 },
  { code: "KA30", name: "Yadgir", lat: 16.77, lng: 77.14 },
  { code: "KA31", name: "Vijayanagara", lat: 15.27, lng: 76.39 },
];

// OpenFreeMap — an OSM-derived, MapLibre-compatible tile service with no API key, no
// registration and no per-request quota. No Catalyst service is a map tile provider
// (the catalog has no mapping capability at all), so this is the same documented-
// exception category as Kannada ASR/TTS or the graph/vector store (§2 of CLAUDE.md).
// What crosses the network is a tile z/x/y for the current viewport — never an FIR's
// exact coordinates or any investigative text.
//
// "dark" over "liberty": Veritas's entire console is ink-dark glass with a brass
// accent (the "Registry" identity — CLAUDE.md §8), and the light "liberty" basemap
// sat in the middle of it as a bright cutout window that every overlay colour then
// had to fight for contrast against. "dark" (background rgb(12,12,12) — confirmed
// directly, not assumed) is close to the console's own --bg, so the map now reads as
// part of the instrument instead of a foreign widget floating on it, and every
// investigative mark gets to be genuinely LUMINOUS against it rather than merely
// higher-contrast than cropland.
const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/dark";

const CASE_RING_R = 6;
const CASE_CORE_R = 2.25;
const SELECT_RING_R = CASE_RING_R + 4;
const SELECT_HALO_R = CASE_RING_R + 9;

function fmtDate(d?: string | null): string {
  if (!d) return "";
  const t = new Date(d);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}

/**
 * The investigative map layer. Visual hierarchy, back to front, is deliberate:
 * geography (basemap) -> hotspot density (soft, ambient) -> clusters (aggregate
 * chips) -> individual cases (precise marks) -> the selected case (the one thing
 * that should out-rank everything else on screen). One shape grammar — a ring
 * around a core — expresses all three investigative mark types at different scales
 * and weights (a case is a small ring+dot; a cluster is a wider ring+count; the
 * selection is the widest ring of all, in the console's one reserved accent colour)
 * rather than three unrelated treatments bolted together.
 */
export default function MapView({
  data, onSelect, activeEvidenceId,
}: {
  data: { polygons: Hotspot[]; fir_points: Point[] };
  onSelect?: (id: string) => void;
  activeEvidenceId?: string | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  // Latest callback without re-registering the click handler on every render —
  // interactions are wired up ONCE (see addInteractions below).
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    if (!ref.current || map.current) return;
    const style = process.env.NEXT_PUBLIC_MAP_STYLE || DEFAULT_STYLE;

    map.current = new maplibregl.Map({
      container: ref.current,
      style,
      center: [76.6, 14.5],
      zoom: 5.6,
      attributionControl: false,
    });
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
    map.current.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const addDistricts = () => {
      const m = map.current;
      if (!m) return;
      m.addSource("districts", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: DISTRICTS.map((d) => ({
            type: "Feature" as const,
            properties: { name: d.name, code: d.code },
            geometry: { type: "Point" as const, coordinates: [d.lng, d.lat] },
          })),
        },
      });
      // District reference geography sits at the QUIET end of the hierarchy — small,
      // desaturated, present for orientation only. Investigative marks are drawn in
      // later draw() calls and layer on top, so they always read as the foreground.
      m.addLayer({
        id: "district-dot", type: "circle", source: "districts",
        paint: {
          "circle-radius": 2.25,
          "circle-color": rgba("#ffffff", 0.55),
          "circle-stroke-width": 1,
          "circle-stroke-color": rgba("#000000", 0.6),
        },
      });
      for (const d of DISTRICTS) {
        const el = document.createElement("div");
        el.textContent = d.name;
        el.className = "map-district-label";
        new maplibregl.Marker({ element: el, anchor: "top" })
          .setLngLat([d.lng, d.lat]).addTo(m);
      }
    };

    // Interaction handlers registered ONCE here, not inside the per-`data` draw
    // effect below: MapLibre's `on(event, layerId, handler)` is layer-ID-scoped and
    // simply doesn't fire until a layer with that ID exists — it does NOT require
    // the layer to exist at registration time. Registering inside draw() (which
    // re-runs on every new query result, removing and re-adding the layers each
    // time) would stack a new duplicate handler on every redraw with nothing ever
    // unregistering the old ones.
    const addInteractions = () => {
      const m = map.current;
      if (!m) return;
      const popup = new maplibregl.Popup({
        closeButton: false, closeOnClick: false, offset: 14, className: "veritas-map-popup",
      });
      const show = (e: maplibregl.MapLayerMouseEvent, html: string) => {
        m.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML(html).addTo(m);
      };
      const hide = () => { m.getCanvas().style.cursor = ""; popup.remove(); };

      // The ring layer (radius CASE_RING_R) is the interactive target, not the
      // smaller solid core — a bigger hit area is more forgiving to hover/click
      // without changing what's visually the "precise" mark (the core).
      m.on("mouseenter", "fir-pts-ring", (e) => {
        const p = e.features?.[0]?.properties ?? {};
        const crimeNo = p.crime_no ? `FIR ${escapeHtml(String(p.crime_no))}` : `Case ${escapeHtml(String(p.fir_id))}`;
        const filed = p.filed ? `<div class="veritas-map-popup-sub">Filed ${escapeHtml(fmtDate(p.filed))}</div>` : "";
        show(e, `<div class="veritas-map-popup-title mono">${crimeNo}</div>${filed}` +
          `<div class="veritas-map-popup-hint">Click to select</div>`);
      });
      m.on("mouseleave", "fir-pts-ring", hide);
      m.on("click", "fir-pts-ring", (e) => {
        const fid = e.features?.[0]?.properties?.fir_id;
        if (fid != null) onSelectRef.current?.(`fir:${fid}`);
      });

      m.on("mouseenter", "clusters", (e) => {
        const n = e.features?.[0]?.properties?.point_count;
        show(e, `<div class="veritas-map-popup-title">${n} case${n === 1 ? "" : "s"} here</div>` +
          `<div class="veritas-map-popup-hint">Click to zoom in</div>`);
      });
      m.on("mouseleave", "clusters", hide);
      m.on("click", "clusters", (e) => {
        const f = e.features?.[0];
        const clusterId = f?.properties?.cluster_id;
        const src = m.getSource("firs") as maplibregl.GeoJSONSource | undefined;
        if (clusterId == null || !src?.getClusterExpansionZoom) return;
        src.getClusterExpansionZoom(clusterId).then((zoom) => {
          m.easeTo({ center: (f!.geometry as any).coordinates, zoom });
        });
      });
    };

    map.current.isStyleLoaded() ? addInteractions() : map.current.once("load", addInteractions);
    map.current.isStyleLoaded() ? addDistricts() : map.current.once("load", addDistricts);

    return () => { map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const draw = () => {
      for (const id of [
        "hot-glow", "hot-fill", "hot-line", "clusters", "cluster-count",
        "fir-pts-ring", "fir-pts-core", "fir-pts-selected-halo", "fir-pts-selected",
      ]) {
        if (m.getLayer(id)) m.removeLayer(id);
      }
      for (const id of ["hotspots", "firs"]) {
        if (m.getSource(id)) m.removeSource(id);
      }

      const polys = data.polygons ?? [];
      if (polys.length) {
        m.addSource("hotspots", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: polys.map((h) => ({
              type: "Feature" as const,
              properties: { color: ramp(h.intensity), count: h.crime_count },
              geometry: { type: "Polygon" as const, coordinates: [closeRing(h.polygon)] },
            })),
          },
        });
        // Hotspot density is analytical CONTEXT, not a record — it has to read as
        // ambient background the eye settles past, never as a shape competing with
        // the discrete case/cluster marks drawn on top of it. A soft blurred glow
        // line (native `line-blur`, no extra layer machinery beyond one more line
        // layer) reads as "heat" the way a filled polygon alone does not.
        m.addLayer({
          id: "hot-glow", type: "line", source: "hotspots",
          paint: {
            "line-color": ["get", "color"], "line-width": 14,
            "line-opacity": 0.16, "line-blur": 10,
          },
        });
        m.addLayer({
          id: "hot-fill", type: "fill", source: "hotspots",
          paint: { "fill-color": ["get", "color"], "fill-opacity": 0.24 },
        });
        m.addLayer({
          id: "hot-line", type: "line", source: "hotspots",
          paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.85 },
        });
      }

      const pts = data.fir_points ?? [];
      if (pts.length) {
        // Clustering (native MapLibre/GL-JS GeoJSON source option, not a new
        // dependency): the failure mode this fixes is a dense area — dozens of FIRs
        // in one taluk — rendering as one indistinct smear with no way to tell "12
        // cases here" from "40". Below `clusterMaxZoom` the source aggregates nearby
        // points into a cluster feature carrying `point_count`; zooming in (or
        // clicking a cluster) breaks it apart into sub-clusters or real, individually
        // selectable points.
        m.addSource("firs", {
          type: "geojson",
          cluster: true,
          clusterMaxZoom: 12,
          clusterRadius: 44,
          data: {
            type: "FeatureCollection",
            features: pts.map((p) => ({
              type: "Feature" as const,
              properties: { fir_id: p.fir_id, crime_no: p.crime_no ?? null, filed: p.filed ?? null },
              geometry: { type: "Point" as const, coordinates: [p.lng, p.lat] },
            })),
          },
        });

        // A cluster is a ring-badge, not a filled bubble: a wide stroke at high
        // opacity carries the shape, a LOW-opacity fill keeps the interior reading
        // as glass rather than a solid disc, so even a 500-case cluster stays calm.
        // Radius steps with count (restrained top end — a huge cluster gets visibly
        // bigger, never dominant) and the count label's own size steps with it, the
        // "intelligent size/weight progression" a flat size can't communicate.
        m.addLayer({
          id: "clusters", type: "circle", source: "firs",
          filter: ["has", "point_count"],
          paint: {
            "circle-radius": ["step", ["get", "point_count"], 11, 10, 14, 50, 17, 200, 20],
            "circle-color": MAP_POINT,
            "circle-opacity": 0.17,
            "circle-stroke-width": ["step", ["get", "point_count"], 1.4, 50, 1.8],
            "circle-stroke-color": rgba(MAP_POINT, 0.9),
          },
        });
        m.addLayer({
          id: "cluster-count", type: "symbol", source: "firs",
          filter: ["has", "point_count"],
          layout: {
            "text-field": ["get", "point_count_abbreviated"],
            "text-size": ["step", ["get", "point_count"], 10, 10, 11, 50, 12, 200, 13],
            "text-font": ["Noto Sans Bold"],
          },
          paint: {
            "text-color": "#eef8fb",
            "text-halo-color": "rgba(6,12,16,0.9)", "text-halo-width": 1,
          },
        });

        // An individual case is a ring around a core — the signature mark of this
        // whole system, reused at larger scale for a cluster (ring+count) and again
        // for the selection (ring alone, in brass). The ring is deliberately the
        // INTERACTIVE layer (a 6px-radius hit target is far more forgiving than a
        // 2px dot) while the core is what the eye actually resolves as "the point".
        m.addLayer({
          id: "fir-pts-ring", type: "circle", source: "firs",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": CASE_RING_R,
            "circle-color": MAP_POINT, "circle-opacity": 0.14,
            "circle-stroke-width": 1.3, "circle-stroke-color": rgba(MAP_POINT, 0.85),
          },
        });
        m.addLayer({
          id: "fir-pts-core", type: "circle", source: "firs",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": CASE_CORE_R,
            "circle-color": "#d8f5fc", "circle-opacity": 0.98,
            "circle-stroke-width": 0.6, "circle-stroke-color": rgba("#04262e", 0.7),
          },
        });

        // The selected case outranks every other mark on the map: a soft outer halo
        // plus a crisp inner ring, both in the console's one reserved accent colour
        // (brass — the same colour a focus chip or an active tab already wears
        // everywhere else in Veritas), so "which case is selected" has an answer on
        // the map for the first time, using a vocabulary the rest of the console
        // already taught the officer rather than a new one invented here. Filters
        // start closed (matching nothing) — the separate activeEvidenceId effect
        // below keeps them current without ever re-running this draw/fitBounds.
        m.addLayer({
          id: "fir-pts-selected-halo", type: "circle", source: "firs",
          filter: ["==", ["get", "fir_id"], "__none__"],
          paint: {
            "circle-radius": SELECT_HALO_R, "circle-color": "rgba(0,0,0,0)",
            "circle-stroke-width": 1, "circle-stroke-color": rgba(ACCENT, 0.38),
          },
        });
        m.addLayer({
          id: "fir-pts-selected", type: "circle", source: "firs",
          filter: ["==", ["get", "fir_id"], "__none__"],
          paint: {
            "circle-radius": SELECT_RING_R, "circle-color": "rgba(0,0,0,0)",
            "circle-stroke-width": 2.25, "circle-stroke-color": ACCENT,
          },
        });
      }

      const all = [
        ...polys.flatMap((h) => h.polygon),
        ...pts.map((p) => [p.lng, p.lat] as [number, number]),
      ];
      if (all.length) {
        const b = all.reduce(
          (acc, c) => acc.extend(c as [number, number]),
          new maplibregl.LngLatBounds(all[0] as any, all[0] as any),
        );
        // Capped well short of MapLibre's own max: a tight cluster (a handful of
        // FIRs in one taluk) used to fit-zoom in so far that every neighbouring
        // district dot and label fell outside the viewport. 9 keeps a ~150-250km
        // window around any result — several neighbouring districts stay in frame
        // no matter how tight the underlying points are.
        m.fitBounds(b, { padding: 70, duration: 900, maxZoom: 9 });
      }
    };

    m.isStyleLoaded() ? draw() : m.once("load", draw);
  }, [data]);

  // Selection-ring update, deliberately separate from the draw effect above: this
  // fires whenever the officer selects a citation (on the map or anywhere else that
  // shares the same evidence rail), and must NOT re-run fitBounds — panning the map
  // every time someone clicks an evidence card would fight whatever they were just
  // looking at.
  useEffect(() => {
    const m = map.current;
    if (!m || !m.getLayer("fir-pts-selected")) return;
    const fid = activeEvidenceId?.startsWith("fir:") ? activeEvidenceId.slice(4) : "__none__";
    const filter: maplibregl.FilterSpecification = ["==", ["get", "fir_id"], fid];
    m.setFilter("fir-pts-selected", filter);
    m.setFilter("fir-pts-selected-halo", filter);
  }, [activeEvidenceId, data]);

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <div ref={ref} style={{ height: "100%", width: "100%", borderRadius: 14 }} />
      <div className="map-legend">
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--case"><i /></span>
          <span>Case — click to select</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--cluster">N</span>
          <span>Cluster — click to explore</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--selected"><i /></span>
          <span>Selected case</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-ramp" />
          <span>Hotspot density</span>
        </div>
      </div>
    </div>
  );
}

/** GeoJSON polygons must be explicitly closed; a convex hull ring is not. */
function closeRing(ring: [number, number][]): [number, number][] {
  if (ring.length < 3) return ring;
  const [f] = ring;
  const l = ring[ring.length - 1];
  return f[0] === l[0] && f[1] === l[1] ? ring : [...ring, f];
}
