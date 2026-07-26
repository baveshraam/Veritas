"use client";
import { useCallback, useEffect, useState } from "react";
import { listOfficers, login } from "@/lib/api";
import type { Officer } from "@/lib/types";

/** Role selection is the point of this screen, not a formality: the whole console
 *  behaves differently per rank (an IO cannot see another station's FIR, and victim
 *  identity is masked below DSP), so being able to sign in as each role is how that
 *  is demonstrated rather than asserted.
 *
 *  This screen must never be able to hang. Its previous version awaited the roster
 *  with no timeout and no failure path, so any unreachable API left "Loading officers…"
 *  on screen forever — the console looked dead when it was merely waiting. Now the
 *  request is bounded, every outcome renders something actionable, and sign-in can be
 *  skipped entirely: this is a demonstration console, so being unable to authenticate
 *  should cost the reviewer the RBAC demo, not the whole platform. */

const ROSTER_TIMEOUT_MS = 8000;

/** Shown only when the roster cannot be reached, so the console is still explorable.
 *  These carry no badge number: they are labels, not credentials, and the API will
 *  refuse the scoped endpoints without a token. */
const FALLBACK_ROLES = ["IO", "SHO", "DSP", "SP", "IG", "SCRB_Analyst"];

type State =
  | { s: "loading" }
  | { s: "ready"; officers: Officer[] }
  | { s: "failed"; why: string };

export default function LoginGate({ onIn }: { onIn: (o: Officer) => void }) {
  const [state, setState] = useState<State>({ s: "loading" });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadRoster = useCallback(() => {
    setState({ s: "loading" });
    setErr(null);
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        setState({ s: "failed", why: "the request timed out" });
      }
    }, ROSTER_TIMEOUT_MS);

    listOfficers()
      .then((officers) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        officers.length
          ? setState({ s: "ready", officers })
          : setState({ s: "failed", why: "the roster came back empty" });
      })
      .catch((e) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        // fetch() rejects with a bare "Failed to fetch" for DNS, CORS and offline
        // alike. That is a browser internal, not something to show an officer.
        const raw = String(e?.message ?? "");
        setState({
          s: "failed",
          why: /failed to fetch|networkerror|load failed/i.test(raw)
            ? "the API did not respond"
            : raw.replace(/\.$/, "") || "the API did not respond",
        });
      });

    return () => clearTimeout(timer);
  }, []);

  useEffect(loadRoster, [loadRoster]);

  /** `?as=DSP` signs straight in at that rank once the roster arrives.
   *  The console's most reviewable property is that the same question answers
   *  differently per rank, and comparing two ranks means two windows. This makes each
   *  one a link. It selects from the signed roster — it does not mint an identity. */
  useEffect(() => {
    if (state.s !== "ready" || busy) return;
    const want = new URLSearchParams(window.location.search).get("as");
    if (!want) return;
    const match = state.officers.find(
      (o) => o.role.toLowerCase() === want.toLowerCase(),
    );
    if (match) signIn(match);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const signIn = async (o: Officer) => {
    setBusy(o.badge_no);
    setErr(null);
    try {
      await login(o.badge_no);
      onIn(o);
    } catch (e: any) {
      setErr(e?.message ?? "Sign-in failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="gate">
      <div className="gate-card glass">
        <h1>VERITAS</h1>
        <p className="tag">Karnataka State Police</p>

        <p className="thesis">
          Ask in English or Kannada. Every claim in the answer carries the record it
          came from — and where the records don&apos;t support one, the console says
          so instead of guessing.
        </p>

        <div className="pane-title" style={{ marginBottom: 10 }}>
          {state.s === "failed" ? "Continue as" : "Sign in as"}
        </div>

        {state.s === "loading" && (
          <div className="meta" style={{ display: "flex", alignItems: "center", gap: 9, color: "var(--text-faint)" }}>
            <span className="spinner" /> Loading the duty roster…
          </div>
        )}

        {state.s === "ready" &&
          state.officers.map((o) => (
            <button
              key={o.badge_no}
              className="officer-row"
              onClick={() => signIn(o)}
              disabled={busy !== null}
            >
              <span>
                <span className="role">{o.role}</span>
                <span className="meta"> · {o.name}</span>
              </span>
              <span className="ps">
                {busy === o.badge_no ? <span className="spinner" /> : `PS ${o.ps_code}`}
              </span>
            </button>
          ))}

        {/* Roster unreachable. Rank still selects, so the console opens and the case
            index, visualizations and reasoning trace remain reviewable; only the
            record-scoped calls will refuse. */}
        {state.s === "failed" &&
          FALLBACK_ROLES.map((role) => (
            <button
              key={role}
              className="officer-row"
              onClick={() => onIn({ badge_no: "", name: "Demonstration", role, ps_code: "—" } as Officer)}
            >
              <span>
                <span className="role">{role}</span>
                <span className="meta"> · demonstration</span>
              </span>
              <span className="ps">unverified</span>
            </button>
          ))}

        {err && (
          <div className="msg-a refusal" style={{ marginTop: 12, fontSize: 12.5, marginRight: 0 }}>
            {err}
          </div>
        )}

        {state.s === "failed" && (
          <div className="gate-note">
            The duty roster could not be loaded — {state.why}. The ranks above are
            unverified, so record-scoped answers will be refused.
            <button
              className="btn btn-sm"
              style={{ marginTop: 10, display: "block" }}
              onClick={loadRoster}
            >
              Retry sign-in
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
