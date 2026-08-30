"use client";
import { useCallback, useEffect, useState } from "react";
import { listOfficers, login, setToken } from "@/lib/api";
import type { Officer } from "@/lib/types";

/** Rank selection is the point of this screen, not a formality: the whole
 *  console behaves differently per rank — an IO cannot see another station's
 *  case, and victim identity is masked below DSP — so signing in at each rank is
 *  how that is demonstrated rather than asserted.
 *
 *  Two requirements, and the first version of this fix met one by breaking the
 *  other. It must never hang, and it must never lie about why it is waiting. */

/** The console used to convert SLOW into FAILED: a timer flipped the gate to
 *  demonstration mode while the roster request was still in flight. On a cold
 *  container the first request hydrates the whole read mirror before anything
 *  can answer, so a pending roster is the normal cold-start state, not a
 *  failure — and calling it a timeout is a false statement about the system.
 *
 *  So the request is left to run. After this, the screen SAYS it is slow and
 *  offers the fallback as a choice; it no longer takes that choice on the
 *  officer's behalf. Only an actual rejection is reported as a failure. */
const SLOW_AFTER_MS = 8000;

/** Shown only when the roster cannot be reached, so the console is still
 *  explorable. These carry no badge number: they are labels, not credentials,
 *  and the API refuses every scoped endpoint without a token. */
/** Top-down operational hierarchy: state scope, then district, then station. */
const RANK_ORDER = ["IG", "SCRB_Analyst", "SP", "DSP", "SHO", "IO"];
const FALLBACK_ROLES = RANK_ORDER;
const byRank = (a: { role: string }, b: { role: string }) =>
  RANK_ORDER.indexOf(a.role) - RANK_ORDER.indexOf(b.role);

/** What each rank actually sees, in the officer's own words. A rank is not a
 *  label on this screen, it is the scope of every answer that follows, so it is
 *  worth one line each rather than an acronym to be recognised or guessed.
 *
 *  can_view_fir (packages/policy/policy/rules.py) only restricts ONE role —
 *  IO, to their own station; every other role is deliberately cross-PS
 *  (test_non_io_roles_are_cross_ps asserts this, so it is a real design
 *  decision, not an oversight to "fix" by changing the policy). This copy
 *  used to claim a district tier for DSP/SP and a station tier for SHO that
 *  the code has never enforced — SHO, DSP, SP, SCRB_Analyst and IG all see
 *  every case in the state; what actually varies below IG is mask_person_
 *  fields (SHO ranks with IO — identity withheld) and max_traversal_depth
 *  (SHO ranks with IO — capped at 2 hops instead of 4). */
const ROLE_NOTE: Record<string, string> = {
  IO: "Investigating officer: cases at your own station",
  SHO: "Station house officer: every case, identity withheld",
  DSP: "Deputy superintendent: every case in the state",
  SP: "Superintendent: every case in the state",
  IG: "Inspector general: every case in the state",
  SCRB_Analyst: "State crime-records analyst: every case in the state",
};

const roleLabel = (r: string) => r.replace(/_/g, " ");

type State =
  | { s: "loading" }
  | { s: "slow" }
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
    const timer = setTimeout(() => { if (!settled) setState({ s: "slow" }); }, SLOW_AFTER_MS);

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
        // fetch() rejects with a bare "Failed to fetch" for DNS, CORS and
        // offline alike. That is a browser internal, not something to show.
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

  /** Entering demonstration mode must DROP any stored bearer token.
   *
   *  It did not, and loadToken() reads localStorage — so a token left by an
   *  earlier sign-in kept authorising every request while the screen showed a
   *  different, "unverified" rank. The console then displayed one rank and the
   *  API answered at another. Unverified has to mean unauthenticated. */
  const enterUnverified = (role: string) => {
    setToken(null);
    onIn({ badge_no: "", name: "Demonstration", role, ps_code: "N/A" } as Officer);
  };

  const signIn = useCallback(async (o: Officer) => {
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
  }, [onIn]);

  /** `?as=DSP` signs straight in at that rank once the roster arrives. The most
   *  reviewable property of this console is that the same question answers
   *  differently per rank, and comparing two ranks means two windows — this
   *  makes each one a link. It selects from the signed roster; it does not mint
   *  an identity. */
  useEffect(() => {
    if (state.s !== "ready" || busy) return;
    const want = new URLSearchParams(window.location.search).get("as");
    if (!want) return;
    const match = state.officers.find((o) => o.role.toLowerCase() === want.toLowerCase());
    if (match) signIn(match);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const waiting = state.s === "loading" || state.s === "slow";
  const fallback = state.s === "failed" || state.s === "slow";

  return (
    <div className="gate">
      <div className="gate-card">
        <div className="gate-head">
          <h1 className="mark-name">VERITAS</h1>
          <div className="gate-tag">Karnataka State Police · Crime Intelligence</div>
          <p className="gate-thesis">
            Ask in English or Kannada. Every claim in the answer carries the record it
            came from. Where the records don&apos;t support one, the console says so
            instead of guessing.
          </p>
        </div>

        <div className="gate-body">
          <span className="label">{fallback ? "Continue as" : "Select your operational role"}</span>

          {waiting && (
            <div className="gate-wait">
              <span className="spinner" />
              {state.s === "slow"
                ? "Still loading the duty roster — the service is warming up."
                : "Loading the duty roster…"}
            </div>
          )}

          {state.s === "ready" && [...state.officers].sort(byRank).map((o) => (
            <button key={o.badge_no} className="officer-row" onClick={() => signIn(o)}
              disabled={busy !== null}>
              <span className="officer-rank">{roleLabel(o.role)}</span>
              <span className="who">
                {o.name}
                <span className="who-note">{ROLE_NOTE[o.role] ?? "Scoped access"}</span>
              </span>
              <span className="ps">
                {busy === o.badge_no ? <span className="spinner" style={{ width: 11, height: 11 }} /> : `PS ${o.ps_code}`}
              </span>
            </button>
          ))}

          {/* Roster unreachable. Rank still selects, so the console opens and the
              case register, visualizations and reasoning trace stay reviewable;
              only the record-scoped calls refuse. */}
          {fallback && FALLBACK_ROLES.map((role) => (
            <button key={role} className="officer-row" onClick={() => enterUnverified(role)}>
              <span className="officer-rank">{roleLabel(role)}</span>
              <span className="who">
                Demonstration
                <span className="who-note">{ROLE_NOTE[role] ?? "Scoped access"}</span>
              </span>
              <span className="ps">unverified</span>
            </button>
          ))}

          {err && <div className="failure" style={{ marginTop: 12 }}><b>{err}</b></div>}

          {fallback && (
            <div className="gate-note">
              {state.s === "slow"
                ? "The duty roster is taking longer than usual. Keep waiting, or continue on an unverified rank."
                : `The duty roster could not be loaded: ${state.why}.`}{" "}
              The ranks above are unverified: continuing on one signs you out, so every
              record-scoped answer will be refused until the roster loads.
              <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={loadRoster}>
                {state.s === "slow" ? "Start over" : "Try again"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
