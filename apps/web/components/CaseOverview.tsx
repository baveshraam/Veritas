"use client";
import { useEffect, useState } from "react";
import { getBoard, getCaseTimeline, getFir, getPerson } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { CaseBoard, CaseDetail, TimelineResult } from "@/lib/types";

/* ============================================================================
 * CASE OVERVIEW — the hero screen.
 *
 * Overview used to be the case register, which is the right answer when nothing
 * is open and the wrong one the moment something is. An officer with a case in
 * front of them does not want a list of ten thousand other cases; they want the
 * five questions this screen answers, in this order:
 *
 *   What is this case?  ·  Who is in it?  ·  What is still open?
 *   What happened lately?  ·  What do I ask next?
 *
 * Everything here comes from endpoints the console already calls — /fir,
 * /board and /timeline/case. Nothing is a second copy of the record, and
 * nothing is computed here that the platform does not already compute.
 * ========================================================================== */

function fmt(d?: string | null): string {
  if (!d) return "—";
  const t = new Date(d);
  return isNaN(t.getTime()) ? d.slice(0, 10)
    : t.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

const OPEN_STATUS = "Under Investigation";

/** An accused as the FILE names them, plus the identity Veritas resolved when
 *  the two differ. Both are true; showing one without the other is what makes
 *  "Suma Nadkarni" and "Soom Nadkarni" read as two people. */
function Accused({
  name, age, personId, onAsk,
}: {
  name: string | null; age: number | null;
  personId: string | number | null; onAsk: (q: string) => void;
}) {
  const t = useT();
  const [canonical, setCanonical] = useState<string | null>(null);
  const [priors, setPriors] = useState<number | null>(null);

  useEffect(() => {
    if (personId == null) return;
    let live = true;
    getPerson(String(personId))
      .then((p) => {
        if (!live) return;
        setCanonical(p.name_en ?? null);
        setPriors(Math.max(0, (p.cases?.length ?? 1) - 1));
      })
      .catch(() => {});
    return () => { live = false; };
  }, [personId]);

  const filed = name ?? t("Name withheld at your rank");
  // The as-filed name usually carries a patronymic the canonical one drops, so
  // compare on the leading name part before calling them different.
  const differs = !!canonical && !!name && !filed.toLowerCase().startsWith(canonical.toLowerCase());

  return (
    <div className="ov-person">
      <div className="ov-person-main">
        <span className="ov-person-name">{filed}</span>
        {age ? <span className="meta">{age} {t("years")}</span> : null}
        <span className="prov prov-record">{t("Record")}</span>
      </div>
      {differs && (
        <div className="ov-person-alias">
          <span className="prov prov-derived">{t("Derived")}</span>
          {t("Recorded elsewhere as")} <b>{canonical}</b> {t("— the same person, matched across case files by identity resolution.")}
        </div>
      )}
      <div className="ov-person-foot">
        {priors != null && (
          <span className="meta">
            {/* NOT a fact from this FIR: the other cases are reached through the
                identity Fellegi-Sunter resolved, so the count is labelled as
                derived. A large number here is a real property of a common
                name in this dataset, and reporting it plainly is the point. */}
            <span className="prov prov-derived" style={{ marginRight: 6 }}>{t("Derived")}</span>
            {priors === 0
              ? t("No other case linked to this identity")
              : t("{n} other case linked to this identity", { n: priors })}
          </span>
        )}
        {name && (
          <button className="btn btn-sm" onClick={() => onAsk(`Does ${name} have priors?`)}>
            {t("Examine")}
          </button>
        )}
        {name && (
          <button className="btn btn-sm btn-quiet"
            onClick={() => onAsk(`Who are the associates of ${name}?`)}>
            {t("Associates")}
          </button>
        )}
      </div>
    </div>
  );
}

export default function CaseOverview({
  firId, onAsk, onCopilot, refreshToken,
}: {
  firId: string;
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  refreshToken: number;
}) {
  const t = useT();
  const [fir, setFir] = useState<CaseDetail | null>(null);
  const [board, setBoard] = useState<CaseBoard | null>(null);
  const [tl, setTl] = useState<TimelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setFir(null); setError(null);
    getFir(firId).then((f) => live && setFir(f)).catch((e) => live && setError(e.message));
    getCaseTimeline(firId).then((t) => live && setTl(t)).catch(() => {});
    return () => { live = false; };
  }, [firId]);

  useEffect(() => {
    let live = true;
    getBoard(firId).then((b) => live && setBoard(b)).catch(() => live && setBoard(null));
    return () => { live = false; };
  }, [firId, refreshToken]);

  if (error) {
    return (
      <div className="empty">
        <span className="empty-mark" aria-hidden>!</span>
        <h3>{t("This case could not be opened")}</h3>
        <p>{error}</p>
      </div>
    );
  }
  if (!fir) return <div className="empty"><span className="spinner" /><p>{t("Opening the case…")}</p></div>;

  const leads = (board?.by_type.lead ?? []).filter((l) => l.status === "open");
  const established = [
    ...(board?.by_type.finding ?? []),
    ...(board?.by_type.evidence ?? []),
    ...(board?.by_type.person ?? []),
  ];
  const questions = board?.by_type.question ?? [];
  const recent = [...(tl?.events ?? [])].slice(-4).reverse();
  const sections = (fir.sections ?? []).map((s) => `${s.ActID} ${s.SectionID}`);

  return (
    <div className="overview">
      <section className="ov-block">
        <div className="ov-head">
          <span className="label">{t("What happened")}</span>
          <span className="prov prov-record">{t("Record")}</span>
        </div>
        <p className="ov-narrative">{fir.narrative || fir.modus_operandi || t("No narrative on record.")}</p>
        <div className="ov-facts">
          <div><span className="ov-fact-l">{t("Filed")}</span><span className="ov-fact-v">{fmt(fir.date_filed)}</span></div>
          <div><span className="ov-fact-l">{t("Station")}</span><span className="ov-fact-v">{fir.ps_name ?? `PS ${fir.ps_code}`}</span></div>
          <div><span className="ov-fact-l">{t("District")}</span><span className="ov-fact-v">{fir.district}</span></div>
          <div><span className="ov-fact-l">{t("Sections")}</span><span className="ov-fact-v mono">{sections.join(" · ") || "—"}</span></div>
          <div>
            <span className="ov-fact-l">{t("Status")}</span>
            <span className="ov-fact-v">
              <span className={`pill ${fir.case_status === OPEN_STATUS ? "pill-open" : "pill-neutral"}`}>
                {t(fir.case_status)}
              </span>
            </span>
          </div>
          <div><span className="ov-fact-l">{t("FIR")}</span><span className="ov-fact-v mono">{fir.fir_number}</span></div>
        </div>
      </section>

      <div className="ov-cols">
        <section className="ov-block">
          <div className="ov-head">
            <span className="label">{t("People in this case")}</span>
            <span className="ov-count">{fir.accused?.length ?? 0} {t("accused")} · {fir.victims?.length ?? 0} {t(((fir.victims?.length ?? 0) === 1) ? "victim" : "victims")}</span>
          </div>
          {(fir.accused ?? []).map((a, i) => (
            <Accused key={i} name={a.AccusedName} age={a.AgeYear} personId={a.PersonUID} onAsk={onAsk} />
          ))}
          {!fir.accused?.length && <p className="dim">{t("No accused named on this FIR.")}</p>}
          {(fir.victims ?? []).length > 0 && (
            <div className="ov-victims">
              <span className="label">{t("Victims")}</span>
              {fir.victims.map((v, i) => (
                <div className="ov-victim" key={i}>
                  {v.VictimName ?? t("Name withheld at your rank")}
                  {v.AgeYear ? <span className="meta"> · {v.AgeYear} {t("years")}</span> : null}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="ov-block">
          <div className="ov-head">
            <span className="label">{t("Still open")}</span>
            <span className="ov-count">{leads.length} {t("lead(s)")}</span>
          </div>
          {leads.length === 0 && questions.length === 0 && (
            <p className="dim">
              {t("Nothing is on this case's board yet. Ask a question and pin what matters, or record a lead — it stays with the case for the next officer on it.")}
            </p>
          )}
          {leads.map((l) => (
            <div className="ov-lead rail-human" key={l.item_id}>{l.content}</div>
          ))}
          {questions.map((q) => (
            <div className="ov-lead rail-human" key={q.item_id}>
              <span className="label" style={{ marginRight: 7 }}>{t("Question")}</span>{q.content}
            </div>
          ))}
          {established.length > 0 && (
            <div className="ov-established">
              <span className="label">{t("Established")}</span>
              {t("{n} item(s) pinned to this case's board.", { n: established.length })}
            </div>
          )}
          <button className="btn btn-sm" style={{ marginTop: 10 }} onClick={() => onCopilot(firId)}>
            {t("Open the case briefing")}
          </button>
        </section>
      </div>

      {recent.length > 0 && (
        <section className="ov-block">
          <div className="ov-head">
            <span className="label">{t("Most recent developments")}</span>
            <span className="ov-count">{t("{n} dated events in all", { n: tl?.events.length ?? 0 })}</span>
          </div>
          {recent.map((e, i) => (
            <div className={`ov-event rail-${e.kind === "derived" ? "derived" : "record"}`} key={i}>
              <span className="ov-event-date mono">{fmt(e.date)}</span>
              <span className="ov-event-body">{e.description}</span>
            </div>
          ))}
        </section>
      )}

      <section className="ov-block">
        <div className="ov-head"><span className="label">{t("Ask Veritas about this case")}</span></div>
        <div className="suggests">
          {[
            "Who is involved in this case?",
            "What should I investigate next?",
            "Show me the timeline for this case",
            "Are there similar cases?",
          ].map((q) => (
            <button key={q} className="suggest" onClick={() => onAsk(q)}>{t(q)}</button>
          ))}
        </div>
      </section>
    </div>
  );
}
