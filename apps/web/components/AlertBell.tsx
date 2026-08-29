"use client";
import { useEffect, useState } from "react";
import { loadToken, streamAlerts } from "@/lib/api";
import type { AnomalyAlert } from "@/lib/types";

const MAX_KEPT = 12;

/** Live district-anomaly alerts (Isolation Forest spikes).
 *
 *  These are decision support, never an automated trigger, so they are
 *  something to read — not something that grabs the screen. The old version
 *  stacked toasts into the evidence column, where they covered the records an
 *  officer was reading. Now they collect behind a counter in the global bar and
 *  open as a list, on demand: the notification surface and the evidence surface
 *  no longer compete for the same pixels.
 *
 *  One component owns both the trigger and the panel because there is exactly
 *  one alert stream, and two components would mean two connections. */
export default function AlertBell() {
  const [alerts, setAlerts] = useState<AnomalyAlert[]>([]);
  const [seen, setSeen] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let stop: (() => void) | null = null;
    let retry: ReturnType<typeof setTimeout>;
    let stopped = false;

    const connect = () => {
      if (!loadToken()) return;   // unverified session — the feed is record-derived
      stop = streamAlerts(
        (a: AnomalyAlert) => setAlerts((all) => [a, ...all].slice(0, MAX_KEPT)),
        // A backend restart must not silently end alerting for the rest of the
        // session — reconnect rather than leaving the feed dead.
        () => { if (!stopped) retry = setTimeout(connect, 5000); },
      );
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); stop?.(); };
  }, []);

  const unread = Math.max(0, alerts.length - seen);

  const toggle = () => {
    setOpen((v) => {
      if (!v) setSeen(alerts.length);
      return !v;
    });
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        className="btn btn-quiet btn-sm"
        onClick={toggle}
        aria-expanded={open}
        title="District anomaly alerts"
      >
        Alerts
        {unread > 0 && (
          <span className="pill pill-amber" style={{ padding: "0 5px" }}>{unread}</span>
        )}
      </button>

      {open && (
        <>
          <div className="scrim" style={{ background: "transparent", zIndex: 54 }} onClick={() => setOpen(false)} />
          <div className="syspop" style={{ width: 320, zIndex: 56, padding: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
              <span className="label">District anomalies</span>
              <span className="prov prov-model" style={{ marginLeft: "auto" }}>Model</span>
            </div>
            <div style={{ maxHeight: 320, overflowY: "auto" }} className="scroll">
              {!alerts.length && (
                <div className="meta" style={{ padding: "16px 12px" }}>
                  No anomalies since you signed in. This feed reports districts whose
                  case volume departs from their own recent baseline.
                </div>
              )}
              {alerts.map((a) => (
                <div key={a.alert_id} className={`alert sev-${a.severity}`}
                  style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)", boxShadow: "none", background: "none" }}>
                  <span className="alert-bar" />
                  <div className="alert-main">
                    <div className="alert-head">
                      <span className="alert-title mono">{a.district_code}</span>
                      <span className={`pill pill-${a.severity === "high" ? "red" : a.severity === "medium" ? "amber" : "ok"}`}>
                        {a.severity}
                      </span>
                    </div>
                    <div className="alert-body">
                      {a.metric}: <b style={{ color: "var(--t-2)" }}>{a.observed.toFixed(1)}</b> against an
                      expected {a.expected.toFixed(1)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="meta" style={{ padding: "8px 12px", borderTop: "1px solid var(--line)", color: "var(--t-4)" }}>
              Decision support. Nothing here triggers an action on its own.
            </div>
          </div>
        </>
      )}
    </div>
  );
}
