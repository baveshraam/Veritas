"use client";
import { useState } from "react";
import { listSessions, loadSession } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { SessionSummary, Turn } from "@/lib/types";

type State =
  | { s: "idle" }
  | { s: "loading" }
  | { s: "ready"; sessions: SessionSummary[] }
  | { s: "failed" };

/** Chat history, pooled by rank+station rather than by whichever officer is
 *  signed in right now — see lib/types.ts's Officer. Loaded lazily, only when
 *  the panel is actually opened, the same pattern AlertBell already uses for
 *  its own popover. */
export default function SessionHistory({
  onLoad,
}: {
  onLoad: (turns: Turn[], sessionId: string) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State>({ s: "idle" });
  const [picking, setPicking] = useState<string | null>(null);

  const toggle = () => {
    setOpen((v) => !v);
    if (state.s === "idle") {
      setState({ s: "loading" });
      listSessions()
        .then((sessions) => setState({ s: "ready", sessions }))
        .catch(() => setState({ s: "failed" }));
    }
  };

  const pick = async (s: SessionSummary) => {
    setPicking(s.session_id);
    try {
      const turns = await loadSession(s.session_id);
      onLoad(turns, s.session_id);
      setOpen(false);
    } catch {
      setState({ s: "failed" });
    } finally {
      setPicking(null);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button className="btn btn-sm history-trigger" onClick={toggle} aria-expanded={open}
        title={t("Previous questions asked at your rank and station")}>
        <span aria-hidden style={{ fontSize: 14 }}>🕘</span>
        {t("History")}
      </button>

      {open && (
        <>
          <div className="scrim" style={{ background: "transparent", zIndex: 54 }} onClick={() => setOpen(false)} />
          <div className="syspop" style={{ width: 300, zIndex: 56, padding: 0 }}>
            <div style={{ padding: "10px 12px", borderBottom: "1px solid var(--line)" }}>
              <span className="label">{t("Chat history")}</span>
            </div>
            <div style={{ maxHeight: 320, overflowY: "auto" }} className="scroll">
              {state.s === "loading" && <div className="meta" style={{ padding: "14px 12px" }}>{t("Loading…")}</div>}
              {state.s === "failed" && <div className="meta" style={{ padding: "14px 12px" }}>{t("Could not load chat history.")}</div>}
              {state.s === "ready" && state.sessions.length === 0 && (
                <div className="meta" style={{ padding: "14px 12px" }}>
                  {t("No previous questions from your rank and station yet.")}
                </div>
              )}
              {state.s === "ready" && state.sessions.map((s) => (
                <button key={s.session_id} onClick={() => pick(s)} disabled={picking !== null}
                  style={{
                    display: "block", width: "100%", textAlign: "left", background: "none",
                    border: 0, borderBottom: "1px solid var(--line)", padding: "9px 12px",
                    cursor: "pointer", color: "var(--t-2)", font: "inherit",
                  }}>
                  <div style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {picking === s.session_id ? t("Loading…") : s.label}
                  </div>
                  <div className="meta" style={{ marginTop: 2 }}>
                    {new Date(s.updated_at).toLocaleString()}
                  </div>
                </button>
              ))}
            </div>
            <div className="meta" style={{ padding: "8px 12px", borderTop: "1px solid var(--line)", color: "var(--t-4)" }}>
              {t("Shared by rank and station, not by who is signed in.")}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
