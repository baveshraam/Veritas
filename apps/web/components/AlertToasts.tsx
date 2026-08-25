"use client";
import { useEffect, useState } from "react";
import { loadToken, WS_BASE } from "@/lib/api";
import type { AnomalyAlert } from "@/lib/types";

const TTL_MS = 12_000;
const MAX_VISIBLE = 3;   // a stack taller than this is wallpaper, not an alert

/** Live district-anomaly alerts (Isolation Forest spikes) — decision-support only,
 * never an automated trigger, so this is a toast to read, not an action to take. */
export default function AlertToasts() {
  const [alerts, setAlerts] = useState<AnomalyAlert[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout>;
    let stopped = false;

    const connect = () => {
      const token = loadToken();
      if (!token) return;           // unverified session — the feed is record-derived
      try {
        ws = new WebSocket(`${WS_BASE}/alerts`);
      } catch {
        return;                     // no WS support in this browser — alerts are an enhancement
      }
      // The token goes in the first frame, not the URL: a bearer token in a WebSocket
      // URL is written into every access log the connection passes through.
      ws.onopen = () => ws?.send(token);
      ws.onmessage = (e) => {
        try {
          const a = JSON.parse(e.data) as AnomalyAlert;
          setAlerts((all) => [...all, a].slice(-MAX_VISIBLE));
          setTimeout(() => setAlerts((all) => all.filter((x) => x.alert_id !== a.alert_id)), TTL_MS);
        } catch {
          /* ignore malformed frames */
        }
      };
      // A backend restart or network blip must not silently end alerting for the
      // rest of the session — reconnect rather than leaving the feed dead.
      ws.onclose = () => {
        if (!stopped) retryTimer = setTimeout(connect, 5000);
      };
    };
    connect();

    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  if (!alerts.length) return null;

  return (
    <div className="toast-stack">
      {alerts.map((a) => (
        <div key={a.alert_id} className={`glass toast toast-${a.severity}`}>
          <div className="toast-head">
            <span className={`chip chip-${a.severity === "high" ? "high" : a.severity === "medium" ? "med" : "low"}`}>
              {a.severity}
            </span>
            <span>{a.district_code}</span>
          </div>
          <div className="toast-body">
            {a.metric}: {a.observed.toFixed(1)} vs expected {a.expected.toFixed(1)}
          </div>
        </div>
      ))}
    </div>
  );
}
