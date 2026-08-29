"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import Board from "./Board";
import { getCaseTimeline, getCopilotBrief } from "@/lib/api";
import type { CopilotBrief, TimelineResult } from "@/lib/types";

const TimelineView = dynamic(() => import("./viz/TimelineView"), { ssr: false });

/** The per-case deep dive: the Monday-morning briefing, the board and the
 *  chronology for ONE case — which may not be the case the conversation is
 *  currently about, which is exactly why it is an overlay and not the workspace.
 *  It floats over the console rather than replacing it, so an officer checking
 *  another case never loses the investigation underneath. */
export default function Copilot({
  firId, onClose, onAsk, onPin, turnsVersion, initialTab = "brief",
}: {
  firId: string;
  onClose: () => void;
  onAsk: (q: string) => void;
  onPin?: (evidenceId: string) => void;
  turnsVersion: number;
  initialTab?: "brief" | "board" | "timeline";
}) {
  const [tab, setTab] = useState<"brief" | "board" | "timeline">(initialTab);
  const [brief, setBrief] = useState<CopilotBrief | null>(null);
  const [tl, setTl] = useState<TimelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tlError, setTlError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => { setTab(initialTab); }, [firId, initialTab]);

  useEffect(() => {
    setBrief(null); setError(null);
    getCopilotBrief(firId).then(setBrief).catch((e) => setError(e.message));
  }, [firId]);

  useEffect(() => {
    if (tab !== "timeline") return;
    setTl(null); setTlError(null);
    getCaseTimeline(firId).then(setTl).catch((e) => setTlError(e.message));
  }, [firId, tab]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const copy = () => {
    if (!brief) return;
    navigator.clipboard.writeText(brief.draft_summary).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  };

  const TABS = [
    { k: "brief", label: "Briefing" },
    { k: "board", label: "Board" },
    { k: "timeline", label: "Timeline" },
  ] as const;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="overlay-panel" onClick={(e) => e.stopPropagation()} role="dialog"
        aria-label="Case briefing">
        <div className="overlay-head">
          <div className="overlay-title">
            Case <span className="mono" style={{ color: "var(--t-2)" }}>{firId}</span>
          </div>
          <nav className="overlay-tabs">
            {TABS.map((t) => (
              <button key={t.k} className={`inv-tab ${tab === t.k ? "on" : ""}`}
                onClick={() => setTab(t.k)}>{t.label}</button>
            ))}
          </nav>
          <button className="btn btn-sm" style={{ alignSelf: "center", marginBottom: 12 }}
            onClick={onClose}>Close</button>
        </div>

        <div className="overlay-body">
          {tab === "board" && (
            <div style={{ height: "100%" }}>
              <Board firId={firId} onAsk={onAsk} refreshToken={turnsVersion} />
            </div>
          )}

          {tab === "timeline" && (
            <div style={{ padding: 16, height: "100%" }}>
              {tlError && <div className="failure"><b>Timeline unavailable.</b> {tlError}</div>}
              {!tl && !tlError && <div className="empty"><span className="spinner" /><p>Building the chronology…</p></div>}
              {tl && <TimelineView data={tl} onPin={onPin} />}
            </div>
          )}

          {tab === "brief" && (
            <div style={{ padding: 18 }}>
              {error && <div className="failure"><b>The briefing could not be prepared.</b> {error}</div>}

              {!brief && !error && (
                <div className="empty" style={{ paddingTop: 50 }}>
                  <span className="spinner" />
                  <h3>Preparing the briefing</h3>
                  {/* The diary paragraph is the one Copilot output that calls the
                      reasoning model unconditionally, and the first such call on a
                      cold container pays real inference latency. Saying so is more
                      useful than a spinner that looks stuck. */}
                  <p>
                    The case-diary paragraph is written by the reasoning model. On a cold
                    start this takes up to 30 seconds.
                  </p>
                </div>
              )}

              {brief && (
                <>
                  <section className="section">
                    <div className="section-head">
                      <span className="label">Chronology</span>
                      <span className="prov prov-record" style={{ marginLeft: "auto" }}>Record</span>
                    </div>
                    {brief.timeline.length === 0 && <p className="dim">No dated events on record.</p>}
                    {brief.timeline.map((ev, i) => (
                      <div key={i} className="brief-row">
                        <span className="brief-date">{ev.date}</span>
                        <span className="brief-main">{ev.event}</span>
                      </div>
                    ))}
                  </section>

                  <section className="section">
                    <div className="section-head">
                      <span className="label">Cases with a similar method</span>
                      <span className="prov prov-derived" style={{ marginLeft: "auto" }}>Derived</span>
                    </div>
                    {brief.similar_cases.length === 0 && <p className="dim">No comparable case found.</p>}
                    {brief.similar_cases.map((c, i) => (
                      <div key={i} className="brief-row">
                        <span className="brief-date">{c.fir_number}</span>
                        <span className="brief-main">
                          <div>
                            {c.crime_type} · {c.district}
                            {c.outcome && <span className="pill pill-neutral" style={{ marginLeft: 8 }}>{c.outcome}</span>}
                          </div>
                          {/* WHY these two line up, not a bare embedding score. A raw
                              percentage cannot tell an officer whether it was the
                              method, the section or the district that matched. */}
                          <div className="brief-why">
                            {c.explanation}
                            {typeof c.similarity === "number" &&
                              ` · ${Math.round(c.similarity * 100)}% text match`}
                          </div>
                        </span>
                      </div>
                    ))}
                  </section>

                  <section className="section">
                    <div className="section-head">
                      <span className="label">Recommended next steps</span>
                      <span className="prov prov-derived" style={{ marginLeft: "auto" }}>Derived</span>
                    </div>
                    {brief.leads.length === 0 && <p className="dim">No lead could be drawn from the records.</p>}
                    <div className="lead-list">
                      {brief.leads.map((l, i) => <div className="lead-item" key={i}><span>{l}</span></div>)}
                    </div>
                  </section>

                  <section className="section" style={{ marginBottom: 0 }}>
                    <div className="section-head">
                      <span className="label">Draft case-diary entry</span>
                      <span className="prov prov-model" style={{ marginLeft: "auto" }}>Model</span>
                      <button className="btn btn-sm" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
                    </div>
                    <p className="brief-draft">{brief.draft_summary}</p>
                    <div className="meta" style={{ marginTop: 8 }}>
                      Written by the reasoning model from the records above. Read it before
                      it goes in the diary.
                    </div>
                  </section>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
