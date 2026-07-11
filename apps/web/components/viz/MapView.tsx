"use client";
import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { ramp, rgba, ACCENT } from "./palette";

type Hotspot = { polygon: [number, number][]; intensity: number; crime_count: number };
type Point = { lat: number; lng: number; fir_id: string };

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
        layers: [{ id: "bg", type: "background", paint: { "background-color": "#e7ecf5" } }],
      },
      center: [76.6, 14.5],
      zoom: 5.6,
      attributionControl: false,
    });
    map.current.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
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
