"use client";
import { useEffect, useState } from "react";
import { loadToken, streamAlerts } from "@/lib/api";
import type { AnomalyAlert } from "@/lib/types";

const TTL_MS = 12_000;
const MAX_VISIBLE = 3;   // a stack taller than this is wallpaper, not an alert
const RETRY_MS = 5000;

/** Live district-anomaly alerts (Isolation Forest spikes) — decision-support only,
 * never an automated trigger, so this is a toast to read, not an action to take. */
export default function AlertToasts() {
  const [alerts, setAlerts] = useState<AnomalyAlert[]>([]);

  useEffect(() => {
    let stop: (() => void) | null = null;
    let retryTimer: ReturnType<typeof setTimeout>;
    let stopped = false;

    const connect = () => {
      if (!loadToken()) return;   // unverified session — the feed is record-derived
      stop = streamAlerts(
        (a: AnomalyAlert) => {
          setAlerts((all) => [...all, a].slice(-MAX_VISIBLE));
          setTimeout(() => setAlerts((all) => all.filter((x) => x.alert_id !== a.alert_id)), TTL_MS);
        },
        // A backend restart or network blip must not silently end alerting for
        // the rest of the session — reconnect rather than leaving the feed dead.
        () => { if (!stopped) retryTimer = setTimeout(connect, RETRY_MS); },
      );
    };
    connect();

    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      stop?.();
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
