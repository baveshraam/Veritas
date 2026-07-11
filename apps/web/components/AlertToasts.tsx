"use client";
import { useEffect, useState } from "react";
import { WS_BASE } from "@/lib/api";
import type { AnomalyAlert } from "@/lib/types";

const TTL_MS = 12_000;

/** Live district-anomaly alerts (Isolation Forest spikes) — decision-support only,
 * never an automated trigger, so this is a toast to read, not an action to take. */
export default function AlertToasts() {
  const [alerts, setAlerts] = useState<AnomalyAlert[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout>;
    let stopped = false;

    const connect = () => {
      try {
        ws = new WebSocket(`${WS_BASE}/alerts`);
      } catch {
        return;                     // no WS support in this browser — alerts are an enhancement
      }
      ws.onmessage = (e) => {
        try {
          const a = JSON.parse(e.data) as AnomalyAlert;
          setAlerts((all) => [...all, a]);
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
