"use client";
import { useEffect, useRef, useState } from "react";
import AlertBell from "./AlertBell";
import { getHealth, type Health } from "@/lib/api";
import { useT } from "@/lib/i18n";
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
  const t = useT();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  const [openSys, setOpenSys] = useState(false);
  const sysRef = useRef<HTMLDivElement>(null);

  /* Light is the default and the one this console is designed in; dark is a
   * preference some officers work a night shift in, so it is offered where the
   * other system-level settings are rather than given a button in the chrome. */
  const [theme, setTheme] = useState<"light" | "dark">("light");
  useEffect(() => {
    const saved = localStorage.getItem("veritas-theme");
    if (saved === "dark") setTheme("dark");
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("veritas-theme", theme);
  }, [theme]);

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
        <div className="mark-row">
          <h1 className="mark-name">VERITAS</h1>
          <span className="mark-sub">Crime Intelligence</span>
        </div>
      </div>

      <button className="omni" onClick={onSearch} aria-label={t("Search records and actions")}>
        <span aria-hidden>⌕</span>
        <span className="omni-text">{t("Search cases, people, districts, actions…")}</span>
        <span className="omni-hint">⌘K</span>
      </button>

      <div className="spacer" />

      <div className="seg" role="group" aria-label={t("Appearance")}>
        <button className={theme === "light" ? "on" : ""} onClick={() => setTheme("light")}
          aria-pressed={theme === "light"} title={t("Light appearance")}>{t("Light")}</button>
        <button className={theme === "dark" ? "on" : ""} onClick={() => setTheme("dark")}
          aria-pressed={theme === "dark"} title={t("Dark appearance")}>{t("Dark")}</button>
      </div>

      <div className="seg" role="group" aria-label={t("Answer language")}>
        <button className={language === "en" ? "on" : ""} onClick={() => onLanguage("en")}
          aria-pressed={language === "en"}>EN</button>
        <button className={language === "kn" ? "on" : ""} onClick={() => onLanguage("kn")}
          aria-pressed={language === "kn"}>ಕನ್ನಡ</button>
      </div>

      <button className={`btn btn-quiet btn-sm ${voiceOut ? "on" : ""}`}
        onClick={() => onVoiceOut(!voiceOut)}
        aria-pressed={voiceOut}
        title={t("Read answers aloud")}>
        {voiceOut ? t("Voice on") : t("Voice off")}
      </button>

      <AlertBell />

      <button className="btn btn-quiet btn-sm" onClick={onExport} disabled={!canExport}
        title={t("Save this session as a PDF")}>
        {t("Export")}
      </button>
      {exportNote && (
        <div role="status" className="toast">
          {exportNote}
        </div>
      )}

      <div ref={sysRef} style={{ position: "relative" }}>
        <button className={`sysdot ${state}`} onClick={() => setOpenSys((v) => !v)}
          aria-expanded={openSys}
          title={down ? t("The API is unreachable") : t("System status")}>
          <i aria-hidden />
          {down ? t("Offline") : health ? t("Live") : t("Connecting")}
        </button>
        {openSys && (
          <div className="syspop">
            <div className="label" style={{ marginBottom: 6 }}>{t("Records loaded")}</div>
            {health ? (
              <>
                <div className="syspop-row"><span>{t("Case records")}</span><b>{n(health.firs)}</b></div>
                <div className="syspop-row"><span>{t("Graph nodes")}</span><b>{n(health.graph_nodes)}</b></div>
                <div className="syspop-row"><span>{t("Graph edges")}</span><b>{n(health.graph_edges)}</b></div>
                <div className="syspop-row"><span>{t("Indexed documents")}</span><b>{n(health.indexed_documents)}</b></div>
                <div className="syspop-row"><span>{t("Record store")}</span><b>{health.datastore}</b></div>
                <div className="syspop-row"><span>{t("Language model")}</span><b>{health.llm}</b></div>
                {health.fairness && (
                  <div className="syspop-row"><span>{t("Fairness audit")}</span><b>{health.fairness}</b></div>
                )}
              </>
            ) : (
              <div className="meta">
                {down ? t("The Veritas API did not respond.") : t("Checking the record store…")}
              </div>
            )}
            <div className="meta" style={{ marginTop: 8, color: "var(--t-4)" }}>
              {t("Every answer is drawn from this set. Nothing outside it can be cited.")}
            </div>
          </div>
        )}
      </div>

      <div className="officer">
        <span className="officer-rank">{officer.role}</span>
        <span className="officer-ps">{officer.badge_no ? `PS ${officer.ps_code}` : t("unverified")}</span>
      </div>
      <button className="btn btn-quiet btn-sm" onClick={onSignOut} title={t("Sign in at another rank")}>
        {t("Switch")}
      </button>
    </header>
  );
}
