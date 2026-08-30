"use client";
import { useEffect, useState } from "react";
import { getPerson } from "@/lib/api";
import { plural } from "@/lib/metrics";
import type { PersonDetail } from "@/lib/types";

/* ============================================================================
 * PERSON OVERVIEW
 *
 * Identity resolution — reconstructing a person across cases the organizers'
 * ER cannot itself relate — is the platform's own load-bearing centrepiece
 * (CLAUDE.md §0). Asking about a person nonetheless pulled Overview back to
 * the 10,000-case register: priors, network, financial and timeline all
 * worked individually, one question at a time, but there was never a single
 * "here is everything on this person" screen the way CaseOverview.tsx is one
 * for a case. This is that screen, built the same way: everything here comes
 * from an endpoint the console already calls (GET /person/:id), and nothing
 * is computed here that the platform does not already compute.
 * ========================================================================== */

function fmt(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d);
  return isNaN(t.getTime()) ? d.slice(0, 10)
    : t.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function PersonOverview({
  personId, name, onAsk,
}: {
  personId: string;
  name?: string;
  onAsk: (q: string) => void;
}) {
  const [p, setP] = useState<PersonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setP(null); setError(null);
    getPerson(personId).then((r) => live && setP(r)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [personId]);

  if (error) {
    return (
      <div className="empty">
        <span className="empty-mark" aria-hidden>!</span>
        <h3>This person could not be opened</h3>
        <p>{error}</p>
      </div>
    );
  }
  if (!p) return <div className="empty"><span className="spinner" /><p>Opening the identity…</p></div>;

  const displayName = p.name_en ?? name ?? "Name withheld at your rank";
  const cases = [...(p.cases ?? [])].sort((a, b) => (b.date_filed ?? "").localeCompare(a.date_filed ?? ""));

  return (
    <div className="overview">
      <section className="ov-block">
        <div className="ov-head">
          <span className="label">Who this is</span>
          <span className="prov prov-derived">Derived</span>
        </div>
        <div className="ov-person-main">
          <span className="ov-person-name" style={{ fontSize: 16 }}>{displayName}</span>
          {p.name_kn && p.name_kn !== displayName && (
            <span className="meta">{p.name_kn}</span>
          )}
        </div>
        <p className="ov-narrative">
          Identity reconstructed across case records by probabilistic record linkage —
          the organizers&apos; schema has no person, only per-case accused rows; this is
          the platform inferring that the same individual appears more than once.
        </p>
        <div className="ov-facts">
          <div><span className="ov-fact-l">Cases</span><span className="ov-fact-v">{plural(cases.length, "case")}</span></div>
          {p.criminal_history && (
            <div><span className="ov-fact-l">Record</span><span className="ov-fact-v">
              <span className="pill pill-open">Habitual offender</span>
            </span></div>
          )}
          {p.gang_affiliation && (
            <div><span className="ov-fact-l">Network</span><span className="ov-fact-v">
              {String(p.gang_affiliation).toLowerCase()}
            </span></div>
          )}
        </div>
      </section>

      <section className="ov-block">
        <div className="ov-head">
          <span className="label">Cases naming this person</span>
          <span className="ov-count">{plural(cases.length, "case")}</span>
        </div>
        {cases.length === 0 && <p className="dim">No cases on record within your access scope.</p>}
        {cases.map((c) => (
          <div className="ov-lead rail-record" key={c.fir_id}>
            <button className="btn btn-sm btn-quiet" style={{ marginRight: 8 }}
              onClick={() => onAsk(`What is the status of FIR ${c.fir_number}?`)}>
              {c.fir_number}
            </button>
            <span className="meta">{fmt(c.date_filed)} · PS {c.ps_code}</span>
          </div>
        ))}
      </section>

      <section className="ov-block">
        <div className="ov-head"><span className="label">Ask Veritas about this person</span></div>
        <div className="suggests">
          {[
            `Does ${displayName} have priors?`,
            `Who are the associates of ${displayName}?`,
            `Where did ${displayName}'s money go?`,
            `Show me the timeline for ${displayName}`,
          ].map((q) => (
            <button key={q} className="suggest" onClick={() => onAsk(q)}>{q}</button>
          ))}
        </div>
      </section>
    </div>
  );
}
