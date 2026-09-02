"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import WhyChain from "../WhyChain";
import { caseIdOf } from "@/lib/evidence";
import { useT } from "@/lib/i18n";
import "maplibre-gl/dist/maplibre-gl.css";
import { ACCENT, MAP_POINT, ramp, rgba } from "./palette";

type Hotspot = { polygon: [number, number][]; intensity: number; crime_count: number };
type Point = {
  lat: number; lng: number; fir_id: string;
  crime_no?: string | null; filed?: string | null;
  crime_type?: string | null; district?: string | null;
};

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
// "positron" over "liberty"/"dark": a v1 pass tried "liberty" (too saturated — bright
// cream/yellow roads competed with every overlay colour) and then "dark" (unified with
// the console's own ink chrome, but read as a second dark instrument stacked on the
// first, and this product's own design review called for the map to go back to a
// LIGHT analytical basemap). "positron" is CartoDB's classic muted-cartography style —
// background rgb(242,243,240), park fill rgb(230,233,229) — confirmed directly, not
// assumed: low-saturation land, pale water, subdued grey labels, the register used by
// analytics tools specifically because it gets out of the way of data drawn on top of
// it. "bright" (OpenFreeMap's other light option) is closer to liberty's saturation and
// was rejected for the same reason liberty was.
const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/positron";

const CASE_R = 4.5;
const SELECT_RING_R = CASE_R + 4.5;
const SELECT_HALO_R = CASE_R + 8;

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
 * geography (the light basemap) -> hotspot density (soft, ambient) -> clusters
 * (aggregate badges) -> individual cases (compact glyphs) -> the selected case (the
 * one thing that should out-rank everything else on screen). A case is a small
 * navy glyph with a white keyline; a cluster is the same navy, larger, carrying a
 * count instead of a dot; the selection is brass — the console's one reserved
 * "active" colour, lifted off the pale basemap with a soft dark shadow ring rather
 * than invented as a fourth hue.
 */
export default function MapView({
  data, onSelect, activeEvidenceId, onAsk, sessionId,
}: {
  data: { polygons: Hotspot[]; fir_points: Point[] };
  onSelect?: (id: string) => void;
  activeEvidenceId?: string | null;
  /** A selected case is an investigation entry point, not just a highlight —
   *  these are the questions the engine can actually answer about it. */
  onAsk?: (q: string) => void;
  sessionId?: string;
}) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [showHotspots, setShowHotspots] = useState(true);
  const [why, setWhy] = useState(false);
  // Latest callback without re-registering the click handler on every render —
  // interactions are wired up ONCE (see addInteractions below).
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  // Same reason: the popup handlers below are wired up once, in a useEffect
  // that never re-runs, so they must read the CURRENT translator through a
  // ref rather than closing over the one captured at mount.
  const tRef = useRef(t);
  tRef.current = t;

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
      // muted, present for orientation only. Investigative marks are drawn in later
      // draw() calls and layer on top, so they always read as the foreground. On a
      // light basemap a dark dot (not white — white would nearly vanish on pale
      // land) with a white keyline keeps it legible without competing for attention.
      m.addLayer({
        id: "district-dot", type: "circle", source: "districts",
        paint: {
          "circle-radius": 2,
          "circle-color": rgba("#4a5568", 0.55),
          "circle-stroke-width": 1,
          "circle-stroke-color": rgba("#ffffff", 0.9),
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
        closeButton: false, closeOnClick: false, offset: 12, className: "veritas-map-popup",
      });
      const show = (e: maplibregl.MapLayerMouseEvent, html: string) => {
        m.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML(html).addTo(m);
      };
      const hide = () => { m.getCanvas().style.cursor = ""; popup.remove(); };

      m.on("mouseenter", "fir-pts", (e) => {
        const p = e.features?.[0]?.properties ?? {};
        const crimeNo = p.crime_no ? `FIR ${escapeHtml(String(p.crime_no))}` : `Case ${escapeHtml(String(p.fir_id))}`;
        const metaBits = [p.crime_type, p.district].filter(Boolean).map(String).map(escapeHtml);
        const meta = metaBits.length
          ? `<div class="veritas-map-popup-sub">${metaBits.join(" · ")}</div>` : "";
        const filed = p.filed
          ? `<div class="veritas-map-popup-sub">${escapeHtml(tRef.current("Filed {date}", { date: fmtDate(p.filed) }))}</div>` : "";
        show(e, `<div class="veritas-map-popup-title mono">${crimeNo}</div>${meta}${filed}` +
          `<div class="veritas-map-popup-hint">${escapeHtml(tRef.current("Click to select"))}</div>`);
      });
      m.on("mouseleave", "fir-pts", hide);
      m.on("click", "fir-pts", (e) => {
        const fid = e.features?.[0]?.properties?.fir_id;
        if (fid != null) onSelectRef.current?.(`fir:${fid}`);
      });

      m.on("mouseenter", "clusters", (e) => {
        const n = e.features?.[0]?.properties?.point_count;
        show(e, `<div class="veritas-map-popup-title">${escapeHtml(tRef.current("{n} case(s) here", { n }))}</div>` +
          `<div class="veritas-map-popup-hint">${escapeHtml(tRef.current("Click to zoom in"))}</div>`);
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
        "hot-fill", "hot-line", "clusters", "cluster-ring", "cluster-count",
        "fir-pts", "fir-pts-selected-halo", "fir-pts-selected",
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
        // Hotspot density is analytical CONTEXT, not a record — a restrained warm
        // translucent surface that stays low enough for the basemap's own roads and
        // place names to read through it, and never resembles a case marker (cases
        // are navy/cool; a hotspot is always somewhere on the green->amber->red
        // severity ramp — hue alone keeps the two unmistakable from each other).
        m.addLayer({
          id: "hot-fill", type: "fill", source: "hotspots",
          paint: { "fill-color": ["get", "color"], "fill-opacity": 0.22 },
        });
        m.addLayer({
          id: "hot-line", type: "line", source: "hotspots",
          paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.8 },
        });
      }

      const pts = data.fir_points ?? [];
      if (pts.length) {
        // Clustering (native MapLibre/GL-JS GeoJSON source option, not a new
        // dependency): the failure mode this fixes is a dense area — dozens of FIRs
        // in one taluk — rendering as an indistinct smear with no way to tell "12
        // cases here" from "40". Below `clusterMaxZoom` the source aggregates nearby
        // points into a cluster feature carrying `point_count`; zooming in (or
        // clicking a cluster) breaks it apart into sub-clusters or real, individually
        // selectable points — progressive disclosure: broad scale shows aggregate
        // density, close scale reveals individual cases, never both at once.
        m.addSource("firs", {
          type: "geojson",
          cluster: true,
          clusterMaxZoom: 12,
          clusterRadius: 50,
          data: {
            type: "FeatureCollection",
            features: pts.map((p) => ({
              type: "Feature" as const,
              properties: {
                fir_id: p.fir_id, crime_no: p.crime_no ?? null, filed: p.filed ?? null,
                crime_type: p.crime_type ?? null, district: p.district ?? null,
              },
              geometry: { type: "Point" as const, coordinates: [p.lng, p.lat] },
            })),
          },
        });

        // A cluster is a solid navy badge with a white ring for separation from the
        // basemap — NOT a translucent bubble (that technique read as "glass" against
        // the dark v1 basemap; against light cartography a low-opacity fill reads as
        // a grey smudge instead). Radius steps with count, restrained at the top end
        // — a 500-case cluster gets visibly bigger than a 5-case one, never
        // dominant — and the count label's own size steps with it too.
        m.addLayer({
          id: "clusters", type: "circle", source: "firs",
          filter: ["has", "point_count"],
          paint: {
            "circle-radius": ["step", ["get", "point_count"], 11, 10, 14, 50, 17, 200, 20],
            "circle-color": MAP_POINT(),
          },
        });
        m.addLayer({
          id: "cluster-ring", type: "circle", source: "firs",
          filter: ["has", "point_count"],
          paint: {
            "circle-radius": ["step", ["get", "point_count"], 11, 10, 14, 50, 17, 200, 20],
            "circle-color": "rgba(0,0,0,0)",
            "circle-stroke-width": 2, "circle-stroke-color": "#ffffff",
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
          paint: { "text-color": "#ffffff" },
        });

        // An individual case: a compact navy glyph with a white keyline — the
        // keyline is what separates it cleanly from a road or a label underneath
        // rather than a generic filled dot melting into the basemap. One layer,
        // deliberately: hundreds of these have to sit on the map at once without
        // reading as visual noise, and the case mark's whole job here is to be
        // quiet until it's the thing being inspected or selected. A gentle zoom
        // interpolation (smaller/fainter just as clusters start breaking apart,
        // full size once you're clearly at case-inspection scale) makes that
        // transition a reveal rather than a hard pop-in.
        m.addLayer({
          id: "fir-pts", type: "circle", source: "firs",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, CASE_R * 0.6, 13, CASE_R],
            "circle-color": MAP_POINT(),
            "circle-opacity": ["interpolate", ["linear"], ["zoom"], 10, 0.55, 13, 1],
            "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff",
          },
        });

        // The selected case outranks every other mark on the map: a crisp brass
        // ring (the console's one reserved "active" colour, already worn by a
        // focus chip or an active tab everywhere else in Veritas) lifted off the
        // pale basemap by a soft dark shadow ring behind it — brass alone reads
        // weaker on paper-toned cartography than it does on dark chrome, so the
        // shadow is what guarantees it still wins the eye inside a dense cluster
        // of navy glyphs. Filters start closed (matching nothing); the separate
        // activeEvidenceId effect below keeps them current without ever
        // re-running this draw/fitBounds.
        m.addLayer({
          id: "fir-pts-selected-halo", type: "circle", source: "firs",
          filter: ["==", ["get", "fir_id"], "__none__"],
          paint: {
            "circle-radius": SELECT_HALO_R, "circle-color": "rgba(0,0,0,0)",
            "circle-stroke-width": 3, "circle-stroke-color": rgba("#1a2430", 0.22),
          },
        });
        m.addLayer({
          id: "fir-pts-selected", type: "circle", source: "firs",
          filter: ["==", ["get", "fir_id"], "__none__"],
          paint: {
            "circle-radius": SELECT_RING_R, "circle-color": "rgba(0,0,0,0)",
            "circle-stroke-width": 2.5, "circle-stroke-color": ACCENT(),
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
    // Either evidence_id shape names the same case — `fir:1194` from the structured
    // layer, `vec:fir_narrative:1194` from semantic search. Reading only the first
    // meant that on a hotspot answer, where every cited case arrives from semantic
    // search, selecting a case lit up no point at all.
    const fid = caseIdOf(activeEvidenceId) ?? "__none__";
    const filter: maplibregl.FilterSpecification = ["==", ["get", "fir_id"], fid];
    m.setFilter("fir-pts-selected", filter);
    m.setFilter("fir-pts-selected-halo", filter);
  }, [activeEvidenceId, data]);

  // Layer visibility. The two things on this map are different KINDS of claim —
  // a case is a record, a hotspot region is model output — so being able to see
  // one without the other is not a convenience, it is how an officer checks
  // whether the density surface is actually sitting on the cases it claims to.
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      for (const id of ["hot-fill", "hot-line"]) {
        if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", showHotspots ? "visible" : "none");
      }
    };
    m.isStyleLoaded() ? apply() : m.once("idle", apply);
  }, [showHotspots, data]);

  const hasHotspots = (data.polygons ?? []).length > 0;

  // The case behind the current selection, if the selection is one of the points
  // on this map. A click already highlighted the evidence card; this is what turns
  // that highlight into somewhere to go next.
  const selectedFir = caseIdOf(activeEvidenceId);
  const selectedPoint = selectedFir
    ? (data.fir_points ?? []).find((p) => String(p.fir_id) === selectedFir) ?? null
    : null;
  // Collapse the chain whenever the selection moves — a chain left open from the
  // previous case would be read as this one's.
  useEffect(() => setWhy(false), [activeEvidenceId]);

  return (
    <div className="map-shell">
      <div ref={ref} className="map-canvas" />

      {selectedPoint && (
        <div className="map-probe probe">
          <div className="probe-head">
            <span className="probe-what mono">{selectedPoint.crime_no ?? `FIR ${selectedPoint.fir_id}`}</span>
            <span className="prov prov-record" style={{ marginLeft: "auto" }}>{t("Record")}</span>
          </div>
          <div className="meta">
            {[selectedPoint.crime_type, selectedPoint.district,
              selectedPoint.filed ? t("filed {date}", { date: fmtDate(selectedPoint.filed) }) : null]
              .filter(Boolean).join(" · ")}
            <br />
            {t("Plotted here because the case file records these coordinates.")}
          </div>

          {why && (
            <div className="probe-body">
              <WhyChain evidenceId={`fir:${selectedPoint.fir_id}`} sessionId={sessionId}
                onAsk={onAsk} />
            </div>
          )}

          <div className="probe-acts">
            <button className="btn btn-sm" onClick={() => setWhy((v) => !v)} aria-expanded={why}>
              {t(why ? "Hide chain" : "Why is this here?")}
            </button>
            {onAsk && (
              <>
                <button className="btn btn-sm"
                  onClick={() => onAsk(`What is the status of FIR ${selectedPoint.crime_no ?? selectedPoint.fir_id}?`)}>
                  {t("What happened here?")}
                </button>
                <button className="btn btn-sm" onClick={() => onAsk("Who are all involved?")}>
                  {t("Who was involved?")}
                </button>
                <button className="btn btn-sm" onClick={() => onAsk("Show me the timeline.")}>
                  {t("Timeline")}
                </button>
                <button className="btn btn-sm" onClick={() => onAsk("Find similar cases.")}>
                  {t("Related cases")}
                </button>
                <button className="btn btn-sm"
                  onClick={() => onAsk("Pin this to the case board")}>
                  {t("Add to board")}
                </button>
              </>
            )}
            <button className="btn btn-sm btn-quiet" onClick={() => onSelect?.("")}>{t("Clear")}</button>
          </div>
        </div>
      )}

      {hasHotspots && (
        <div style={{ position: "absolute", left: 10, top: 10, zIndex: 2 }}>
          <button
            className="btn btn-sm"
            onClick={() => setShowHotspots((v) => !v)}
            aria-pressed={showHotspots}
            style={{ background: "var(--float)" }}
          >
            {t(showHotspots ? "Hide density" : "Show density")}
          </button>
        </div>
      )}

      <div className="map-legend">
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--case" />
          <span>{t("Case")}</span>
          <span className="prov prov-record" style={{ marginLeft: "auto" }}>{t("Record")}</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--cluster">N</span>
          <span>{t("Cases here — click to expand")}</span>
        </div>
        <div className="map-legend-row">
          <span className="map-legend-mark map-legend-mark--selected"><i /></span>
          <span>{t("Selected")}</span>
        </div>
        {hasHotspots && (
          <div className="map-legend-row">
            <span className="map-legend-ramp" />
            <span>{t("Hotspot density")}</span>
            <span className="prov prov-model" style={{ marginLeft: "auto" }}>{t("Model")}</span>
          </div>
        )}
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
