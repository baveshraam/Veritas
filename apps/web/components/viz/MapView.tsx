"use client";
import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { ramp, rgba, ACCENT, MAP_BG } from "./palette";

type Hotspot = { polygon: [number, number][]; intensity: number; crime_count: number };
type Point = { lat: number; lng: number; fir_id: string };

// Karnataka's 31 real districts — code, name, and the same real centroid the
// generator's own geo sampling uses (data/data/seed/derived/district_centroids.csv),
// duplicated here rather than fetched, because it is static reference data an
// officer needs to orient a hotspot against, not a live query result. This is the
// UI-24 fix: the map previously had no geographic reference at all — no district
// outlines, scale, or labels — so it read as an abstract scatter plot. True district
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

/**
 * Hotspot map. The basemap is a plain dark canvas rather than a tile service —
 * the architecture requires self-hosted tiles (FIR locations must not be sent to a
 * third-party tile provider as part of a request URL), and no tile server is
 * running here. Point a MapLibre style at your own tile server via
 * NEXT_PUBLIC_MAP_STYLE and this picks it up.
 */
export default function MapView({ data }: { data: { polygons: Hotspot[]; fir_points: Point[] } }) {
  const ref = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!ref.current || map.current) return;
    const style = process.env.NEXT_PUBLIC_MAP_STYLE;

    map.current = new maplibregl.Map({
      container: ref.current,
      style: style ?? {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": MAP_BG } }],
      },
      center: [76.6, 14.5],
      zoom: 5.6,
      attributionControl: false,
    });
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    // Native MapLibre feature, not a new dependency: a real distance scale so an
    // officer can judge how far apart two points on the map actually are.
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
      // A small dot at every real district centre — the vector layer handles this
      // fine. The NAME next to it is drawn as an HTML marker, not a symbol-layer
      // text-field: a `text-field` layer needs MapLibre's `glyphs` PBF service to
      // rasterise text, which is exactly the kind of third-party request this map
      // was built to avoid (see the module docstring). A DOM marker uses the
      // console's own font stack — no glyph server, no new dependency.
      m.addLayer({
        id: "district-dot", type: "circle", source: "districts",
        paint: { "circle-radius": 2.5, "circle-color": rgba("#ffffff", 0.35) },
      });
      for (const d of DISTRICTS) {
        const el = document.createElement("div");
        el.textContent = d.name;
        el.style.cssText =
          "font-size:10px;color:rgba(255,255,255,0.55);white-space:nowrap;" +
          "transform:translateY(4px);pointer-events:none;font-family:inherit;";
        new maplibregl.Marker({ element: el, anchor: "top" })
          .setLngLat([d.lng, d.lat]).addTo(m);
      }
    };
    map.current.isStyleLoaded() ? addDistricts() : map.current.once("load", addDistricts);

    return () => { map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const draw = () => {
      for (const id of ["hot-fill", "hot-line", "fir-pts"]) {
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
        m.addLayer({
          id: "hot-fill", type: "fill", source: "hotspots",
          paint: { "fill-color": ["get", "color"], "fill-opacity": 0.26 },
        });
        m.addLayer({
          id: "hot-line", type: "line", source: "hotspots",
          paint: { "line-color": ["get", "color"], "line-width": 1.6, "line-opacity": 0.85 },
        });
      }

      const pts = data.fir_points ?? [];
      if (pts.length) {
        m.addSource("firs", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: pts.map((p) => ({
              type: "Feature" as const, properties: {},
              geometry: { type: "Point" as const, coordinates: [p.lng, p.lat] },
            })),
          },
        });
        m.addLayer({
          id: "fir-pts", type: "circle", source: "firs",
          paint: {
            "circle-radius": 3,
            "circle-color": ACCENT,
            "circle-opacity": 0.75,
            "circle-stroke-width": 0.5,
            "circle-stroke-color": rgba("#ffffff", 0.35),
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
        m.fitBounds(b, { padding: 70, duration: 900, maxZoom: 11 });
      }
    };

    m.isStyleLoaded() ? draw() : m.once("load", draw);
  }, [data]);

  return <div ref={ref} style={{ height: "100%", width: "100%", borderRadius: 14 }} />;
}

/** GeoJSON polygons must be explicitly closed; a convex hull ring is not. */
function closeRing(ring: [number, number][]): [number, number][] {
  if (ring.length < 3) return ring;
  const [f] = ring;
  const l = ring[ring.length - 1];
  return f[0] === l[0] && f[1] === l[1] ? ring : [...ring, f];
}
