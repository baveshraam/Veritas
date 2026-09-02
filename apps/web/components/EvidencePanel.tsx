"use client";
import { band, CONF_NAME, PROV_LABEL, provenanceOf, showsPercent, summarise } from "@/lib/evidence";
import { useT } from "@/lib/i18n";
import { matchReading } from "@/lib/metrics";
import type { EvidenceItem } from "@/lib/types";

/** The evidence column.
 *
 *  It used to be nine identical cards, every one of them stamped "100% evidence
 *  strength" in the same green. That reads as a system proving how much data it
 *  has, not as a set of sources an officer can check — and it made the strongest
 *  record indistinguishable from the weakest.
 *
 *  So the column now leads with a summary of the evidence AS A SET (how many
 *  authoritative records, how many corroborating findings, how many model
 *  outputs), and the sources themselves are compact rows. The full record, its
 *  provenance and the query that produced it live in the inspector, one click
 *  away — a citation you cannot inspect is a citation you cannot check, but the
 *  inspection does not have to be permanently on screen to be available. */
export default function EvidencePanel({
  evidence, active, onOpen,
}: {
  evidence: EvidenceItem[];
  active: string | null;
  onOpen: (id: string) => void;
}) {
  const t = useT();
  if (!evidence.length) {
    return (
      <section className="col col-evidence" aria-label="Evidence">
        <div className="col-head"><span className="label">{t("Evidence")}</span></div>
        <div className="col-body">
          {/* Deliberately small. An empty panel that fills a fifth of the screen
              is a fifth of the screen spent saying nothing. */}
          <div className="evidence-idle">
            <b>{t("Nothing cited yet")}</b>
            {t("Every claim an answer makes appears here as the record it rests on — with what kind of source it is, and how well it supports the claim.")}
          </div>
        </div>
      </section>
    );
  }

  const s = summarise(evidence);

  return (
    <section className="col col-evidence" aria-label="Evidence">
      <div className="col-head">
        <span className="label">{t("Evidence")}</span>
        <div className="col-head-right">
          <span className="meta">{s.total} {t(s.total === 1 ? "source" : "sources")}</span>
        </div>
      </div>

      <div className="evidence-summary">
        <div className="support-head">
          <span className="label">{t("Support")}</span>
          <span className={`support-verdict is-${s.band}`}>{t(s.verdict)}</span>
        </div>
        <div className={`support-bar support-verdict is-${s.band}`}>
          {[0, 1, 2, 3].map((i) => <i key={i} className={i < s.steps ? "on" : ""} />)}
        </div>
        <div className="evidence-breakdown">
          {s.authoritative > 0 && (
            <div className="evidence-breakdown-row" title={t("Stated directly in the case records")}>
              <span className="prov prov-record">{t(PROV_LABEL.record)}</span>
              <span>{t("authoritative records")}</span>
              <span className="mono">{s.authoritative}</span>
            </div>
          )}
          {s.corroborating > 0 && (
            <div className="evidence-breakdown-row" title={t("Inferred by Veritas from the records")}>
              <span className="prov prov-derived">{t(PROV_LABEL.derived)}</span>
              <span>{t("corroborating findings")}</span>
              <span className="mono">{s.corroborating}</span>
            </div>
          )}
          {s.modelled > 0 && (
            <div className="evidence-breakdown-row" title={t("Computed by a model — decision support")}>
              <span className="prov prov-model">{t(PROV_LABEL.model)}</span>
              <span>{t("model outputs")}</span>
              <span className="mono">{s.modelled}</span>
            </div>
          )}
        </div>
      </div>

      <div className="col-body ev-list">
        {evidence.map((e, i) => {
          const p = provenanceOf(e);
          const b = band(e.confidence);
          return (
            <button
              key={e.evidence_id}
              // The evidence thread anchors its line on this id. Keep it.
              id={`ev-${e.evidence_id}`}
              className={`ev rail-${p} ${active === e.evidence_id ? "on" : ""}`}
              onClick={() => onOpen(e.evidence_id)}
              aria-label={t("Source {i}, {label}", { i: i + 1, label: t(PROV_LABEL[p]) })}
            >
              <div className="ev-head">
                <span className="ev-idx">{i + 1}</span>
                <span className={`prov prov-${p}`}>{t(PROV_LABEL[p])}</span>
                <span className="mono" style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--t-4)" }}>
                  {e.source_id}
                </span>
              </div>
              <div className="ev-body">{e.content}</div>
              <div className="ev-foot">
                {/* What this source IS, then how it was measured. A bare "66%"
                    under a bare "Text match" asks the officer to decide what a
                    percentage of wording similarity is worth. */}
                <span className="meta">
                  {e.confidence_kind === "similarity"
                    ? t(matchReading(e.confidence).headline)
                    : t(CONF_NAME[e.confidence_kind])}
                </span>
                {showsPercent(e.confidence_kind) && (
                  <span className={`ev-strength support-verdict is-${b}`}>
                    <i><b style={{ width: `${Math.round(e.confidence * 100)}%` }} /></i>
                    {(e.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
