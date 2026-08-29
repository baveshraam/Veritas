"use client";
import { useEffect, useRef, useState } from "react";
import AlertBell from "./AlertBell";
import { getHealth, type Health } from "@/lib/api";
import type { Officer } from "@/lib/types";

/** Global chrome: identity, search, console-wide actions.
 *
 *  What is NOT here any more: the record counts. "10,000 FIRs · 16,918 nodes ·
 *  13,835 indexed" is a true and useful fact — about the deployment, not about
 *  the investigation — and it was occupying the most valuable strip on the
 *  screen. It moved behind the system indicator, one click away, where an
 *  operator can still check it and an investigator is never asked to read it. */
export default function TopBar({
  officer, language, onLanguage, voiceOut, onVoiceOut,
  onSearch, onExport, canExport, exportNote, onSignOut,
}: {
  officer: Officer;
  language: "en" | "kn";
  onLanguage: (l: "en" | "kn") => void;
  voiceOut: boolean;
  onVoiceOut: (v: boolean) => void;
  onSearch: () => void;
  onExport: () => void;
  canExport: boolean;
  exportNote?: string | null;
  onSignOut: () => void;
}) {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  const [openSys, setOpenSys] = useState(false);
  const sysRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setDown(true));
  }, []);

  useEffect(() => {
    if (!openSys) return;
    const away = (e: MouseEvent) => {
      if (!sysRef.current?.contains(e.target as Node)) setOpenSys(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [openSys]);

  const n = (v: number) => v.toLocaleString("en-IN");
  const state = down ? "is-down" : health ? "" : "is-wait";

  return (
    <header className="topbar">
      <div className="mark">
        <h1 className="mark-name">VERITAS</h1>
        <span className="mark-sub">Crime Intelligence</span>
      </div>

      <button className="omni" onClick={onSearch} aria-label="Search records and actions">
        <span aria-hidden>⌕</span>
        <span className="omni-text">Search cases, people, districts, actions…</span>
        <span className="omni-hint">⌘K</span>
      </button>

      <div className="spacer" />

      <div className="seg" role="group" aria-label="Answer language">
        <button className={language === "en" ? "on" : ""} onClick={() => onLanguage("en")}
          aria-pressed={language === "en"}>EN</button>
        <button className={language === "kn" ? "on" : ""} onClick={() => onLanguage("kn")}
          aria-pressed={language === "kn"}>ಕನ್ನಡ</button>
      </div>

      <button className={`btn btn-quiet btn-sm ${voiceOut ? "on" : ""}`}
        onClick={() => onVoiceOut(!voiceOut)}
        aria-pressed={voiceOut}
        title="Read answers aloud">
        {voiceOut ? "Voice on" : "Voice off"}
      </button>

      <AlertBell />

      <button className="btn btn-quiet btn-sm" onClick={onExport} disabled={!canExport}
        title="Save this session as a PDF">
        Export
      </button>
      {exportNote && (
        <span role="status" className="meta" style={{ maxWidth: 230, color: "var(--amber)" }}>
          {exportNote}
        </span>
      )}

      <div ref={sysRef} style={{ position: "relative" }}>
        <button className={`sysdot ${state}`} onClick={() => setOpenSys((v) => !v)}
          aria-expanded={openSys}
          title={down ? "The API is unreachable" : "System status"}>
          <i aria-hidden />
          {down ? "Offline" : health ? "Live" : "Connecting"}
        </button>
        {openSys && (
          <div className="syspop">
            <div className="label" style={{ marginBottom: 6 }}>Records loaded</div>
            {health ? (
              <>
                <div className="syspop-row"><span>Case records</span><b>{n(health.firs)}</b></div>
                <div className="syspop-row"><span>Graph nodes</span><b>{n(health.graph_nodes)}</b></div>
                <div className="syspop-row"><span>Graph edges</span><b>{n(health.graph_edges)}</b></div>
                <div className="syspop-row"><span>Indexed documents</span><b>{n(health.indexed_documents)}</b></div>
                <div className="syspop-row"><span>Record store</span><b>{health.datastore}</b></div>
                <div className="syspop-row"><span>Language model</span><b>{health.llm}</b></div>
              </>
            ) : (
              <div className="meta">
                {down ? "The Veritas API did not respond." : "Checking the record store…"}
              </div>
            )}
            <div className="meta" style={{ marginTop: 8, color: "var(--t-4)" }}>
              Every answer is drawn from this set. Nothing outside it can be cited.
            </div>
          </div>
        )}
      </div>

      <div className="officer">
        <span className="officer-rank">{officer.role}</span>
        <span className="officer-name">{officer.name}</span>
        <span className="officer-ps">{officer.ps_code === "—" ? "unverified" : `PS ${officer.ps_code}`}</span>
      </div>
      <button className="btn btn-quiet btn-sm" onClick={onSignOut} title="Sign in at another rank">
        Switch
      </button>
    </header>
  );
}
