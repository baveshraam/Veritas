"use client";
import { useEffect, useState } from "react";
import { loadToken, streamAlerts } from "@/lib/api";
import { districtName } from "@/lib/districts";
import { useT } from "@/lib/i18n";
import { anomalyReading } from "@/lib/metrics";
import type { AdvisoryAlert, AnomalyAlert, SeriesAlert } from "@/lib/types";

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
  const t = useT();
  const [alerts, setAlerts] = useState<AnomalyAlert[]>([]);
  const [series, setSeries] = useState<SeriesAlert[]>([]);
  const [advisories, setAdvisories] = useState<AdvisoryAlert[]>([]);
  const [seen, setSeen] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let stop: (() => void) | null = null;
    let retry: ReturnType<typeof setTimeout>;
    let stopped = false;

    const connect = () => {
      if (!loadToken()) return;   // unverified session — the feed is record-derived
      stop = streamAlerts(
        (item: AnomalyAlert | SeriesAlert | AdvisoryAlert, kind) => {
          if (kind === "series") {
            setSeries((all) => [item as SeriesAlert, ...all].slice(0, MAX_KEPT));
          } else if (kind === "advisory") {
            setAdvisories((all) => [item as AdvisoryAlert, ...all].slice(0, MAX_KEPT));
          } else {
            setAlerts((all) => [item as AnomalyAlert, ...all].slice(0, MAX_KEPT));
          }
        },
        // A backend restart must not silently end alerting for the rest of the
        // session — reconnect rather than leaving the feed dead.
        () => { if (!stopped) retry = setTimeout(connect, 5000); },
      );
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); stop?.(); };
  }, []);

  const total = alerts.length + series.length + advisories.length;
  const unread = Math.max(0, total - seen);

  const toggle = () => {
    setOpen((v) => {
      if (!v) setSeen(total);
      return !v;
    });
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        className="btn btn-quiet btn-sm"
        onClick={toggle}
        aria-expanded={open}
        title={t("District anomaly alerts")}
      >
        {t("Alerts")}
        {unread > 0 && (
          <span className="pill pill-amber" style={{ padding: "0 5px" }}>{unread}</span>
        )}
      </button>

      {open && (
        <>
          <div className="scrim" style={{ background: "transparent", zIndex: 54 }} onClick={() => setOpen(false)} />
          <div className="syspop" style={{ width: 320, zIndex: 56, padding: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
              <span className="label">{t("District anomalies")}</span>
              <span className="prov prov-model" style={{ marginLeft: "auto" }}>{t("Model")}</span>
            </div>
            <div style={{ maxHeight: 320, overflowY: "auto" }} className="scroll">
              {!alerts.length && (
                <div className="meta" style={{ padding: "16px 12px" }}>
                  {t("No anomalies since you signed in. This feed reports districts whose case volume departs from their own recent baseline.")}
                </div>
              )}
              {alerts.map((a) => {
                const r = anomalyReading(a.observed, a.expected);
                return (
                  <div key={a.alert_id} className={`alert sev-${a.severity}`}
                    style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)", boxShadow: "none", background: "none" }}>
                    <span className="alert-bar" />
                    <div className="alert-main">
                      <div className="alert-head">
                        <span className="alert-title">{districtName(a.district_code)}</span>
                        <span className={`pill pill-${a.severity === "high" ? "red" : a.severity === "medium" ? "amber" : "ok"}`}>
                          {a.severity}
                        </span>
                      </div>
                      <div className="alert-body">
                        <b style={{ color: "var(--t-2)" }}>{t(r.headline)}</b>
                        <div className="meta">{t(r.measure)}</div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
              <span className="label">{t("Cross-station patterns")}</span>
              <span className="prov prov-derived" style={{ marginLeft: "auto" }}>{t("Derived")}</span>
            </div>
            <div style={{ maxHeight: 240, overflowY: "auto" }} className="scroll">
              {!series.length && (
                <div className="meta" style={{ padding: "16px 12px" }}>
                  {t("No cross-station pattern found in recently filed cases. This checks for a shared distinctive method across different stations with no common suspect yet.")}
                </div>
              )}
              {series.map((s) => {
                const named = s.members.find((m) => m.fir_number);
                const why = named?.matched_features.find((f) => f.startsWith("matching modus operandi"))
                  ?? named?.matched_features[0];
                return (
                  <div key={s.anchor_fir_id} className="alert"
                    style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)", boxShadow: "none", background: "none" }}>
                    <span className="alert-bar" />
                    <div className="alert-main">
                      <div className="alert-head">
                        <span className="alert-title">
                          {t("FIR")} {s.anchor_fir_id} + {s.members.length} {t("more")}
                        </span>
                        <span className="pill pill-amber">{s.stations.length} {t("stations")}</span>
                      </div>
                      <div className="alert-body">
                        <b style={{ color: "var(--t-2)" }}>
                          {t("Spans")} {s.districts.length} {t("district(s)")}: {s.districts.join(", ")}
                        </b>
                        {why && <div className="meta">{t("Matches because")}: {why}</div>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderTop: "1px solid var(--line)", borderBottom: "1px solid var(--line)" }}>
              <span className="label">{t("Prevention advisories")}</span>
              <span className="prov prov-derived" style={{ marginLeft: "auto" }}>{t("Derived")}</span>
            </div>
            <div style={{ maxHeight: 240, overflowY: "auto" }} className="scroll">
              {!advisories.length && (
                <div className="meta" style={{ padding: "16px 12px" }}>
                  {t("No district currently combines a real hotspot with a rising forecast. This fuses hotspot detection, trend forecasting, and cross-station series linkage — nothing here is a new source of data on its own.")}
                </div>
              )}
              {advisories.map((a) => (
                <div key={a.district_code} className="alert"
                  style={{ borderRadius: 0, border: 0, borderBottom: "1px solid var(--line)", boxShadow: "none", background: "none" }}>
                  <span className="alert-bar" />
                  <div className="alert-main">
                    <div className="alert-head">
                      <span className="alert-title">{a.district}</span>
                      <span className="pill pill-amber">{t("Advisory")}</span>
                    </div>
                    <div className="alert-body">
                      <b style={{ color: "var(--t-2)" }}>{t(a.headline)}</b>
                      {a.disclosures.map((d, i) => (
                        <div key={i} className="meta">{t(d)}</div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="meta" style={{ padding: "8px 12px", borderTop: "1px solid var(--line)", color: "var(--t-4)" }}>
              {t("Decision support. Nothing here triggers an action on its own.")}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
