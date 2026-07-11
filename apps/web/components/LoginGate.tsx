"use client";
import { useEffect, useState } from "react";
import { listOfficers, login } from "@/lib/api";
import type { Officer } from "@/lib/types";

/** Role selection is the point of this screen, not a formality: the whole console
 *  behaves differently per rank (an IO cannot see another station's FIR, and victim
 *  identity is masked below DSP), so being able to sign in as each role is how that
 *  is demonstrated rather than asserted. */
export default function LoginGate({ onIn }: { onIn: (o: Officer) => void }) {
  const [officers, setOfficers] = useState<Officer[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    listOfficers().then(setOfficers).catch((e) => setErr(e.message));
  }, []);

  const signIn = async (o: Officer) => {
    setBusy(o.badge_no);
    try {
      await login(o.badge_no);
      onIn(o);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gate">
      <div className="gate-card glass">
        <h1>VERITAS</h1>
        <p className="tag">Karnataka State Police · Crime Intelligence Platform</p>

        {err && (
          <div className="msg-a refusal" style={{ marginBottom: 16, fontSize: 12 }}>
            {err}
            <div style={{ color: "var(--text-faint)", marginTop: 6 }}>
              Start the API: <code>uvicorn api.main:app --port 8000</code>
            </div>
          </div>
        )}

        <div className="pane-title" style={{ marginBottom: 10 }}>Sign in as</div>
        {officers.map((o) => (
          <button key={o.badge_no} className="officer-row" onClick={() => signIn(o)}>
            <span>
              <span className="role">{o.role}</span>
              <span className="meta"> · {o.name}</span>
            </span>
            <span className="meta">
              {busy === o.badge_no ? <span className="spinner" /> : o.ps_code}
            </span>
          </button>
        ))}
        {!officers.length && !err && (
          <div className="meta" style={{ color: "var(--text-faint)" }}>Loading officers…</div>
        )}
      </div>
    </div>
  );
}
