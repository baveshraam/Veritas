"use client";
import { useT } from "@/lib/i18n";
import type { AreaProfile, CommunityProfile, Watchlist, Workload } from "@/lib/api";
import { influence as influenceColour } from "./viz/palette";

/** The structured renderings of the four record-readout tabs.
 *
 *  Each of these used to be a column of full English sentences, because the view was
 *  filled by an answer and an answer is prose. A ranked list read out one sentence at
 *  a time is a list an officer scrolls past: the value they are comparing on is buried
 *  mid-clause, in a different place in every row. These are the same facts, from the
 *  same policy-scoped queries, in the shape the comparison actually needs.
 *
 *  Nothing here invents a column the record layer does not have. Where a number is
 *  derived or modelled it says so on the row, using the console's own provenance
 *  vocabulary (globals.css `.prov-*`), because a model output must never be able to
 *  look like a record (CLAUDE.md §8). */

function rupees(n: number): string {
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/* ── Area profile ─────────────────────────────────────────────────────────── */

const CENSUS_ROWS: [string, string, (v: number) => string][] = [
  ["Population", "Population", (v) => v.toLocaleString("en-IN")],
  ["LiteracyRate", "Literacy", (v) => `${v.toFixed(1)}%`],
  ["UrbanRatio", "Urban households", (v) => `${Math.round(v * 100)}%`],
  ["PovertyIndex", "Poverty index", (v) => `${Math.round(v * 100)}%`],
  ["MarginalWorkerRate", "Marginal workers", (v) => `${Math.round(v * 100)}%`],
  ["YouthRatio", "Youth share", (v) => `${Math.round(v * 100)}%`],
];

export function AreaView({ data, onAsk }: { data: AreaProfile; onAsk: (q: string) => void }) {
  const t = useT();
  const top = data.mix[0]?.cases ?? 1;
  return (
    <div className="an-body">
      <div className="an-cols">
        <section className="an-block">
          <h4 className="an-h">
            <span className="prov prov-record">{t("Record")}</span>
            {t("Recorded offence mix")}
          </h4>
          <div className="an-bars">
            {data.mix.slice(0, 12).map((m) => (
              <div className="an-bar" key={m.name}>
                <span className="an-bar-l">{m.name}</span>
                <span className="an-bar-t"><i style={{ width: `${(m.cases / top) * 100}%` }} /></span>
                <span className="an-bar-n mono">{m.cases}</span>
              </div>
            ))}
          </div>
          <p className="an-note">
            {t("{n} case(s) on record in {d}, within your access scope.",
               { n: data.total.toLocaleString(), d: data.district ?? "" })}
          </p>
        </section>

        <section className="an-block">
          <h4 className="an-h">
            <span className="prov prov-record">{t("Record")}</span>
            {t("Census 2011 ground truth")}
          </h4>
          {data.census ? (
            <>
              <dl className="an-dl">
                {CENSUS_ROWS.filter(([k]) => data.census![k] != null).map(([k, label, fmt]) => (
                  <div className="an-dl-row" key={k}>
                    <dt>{t(label)}</dt>
                    <dd className="mono">{fmt(Number(data.census![k]))}</dd>
                  </div>
                ))}
              </dl>
              {/* The one sentence on this surface that has to be prose, because it
                  states what is deliberately NOT being claimed. Putting the crime
                  mix and the socioeconomics side by side without it would imply the
                  causal link this platform's own causal layer refuses to assert
                  without naming its confounders (CLAUDE.md §9). */}
              <p className="an-note">
                {t("Real, non-synthetic ground truth. Shown beside the crime mix, never combined with it — this is a fact about the district, not an explanation of its case count.")}
              </p>
            </>
          ) : (
            <p className="an-note">{t("No Census 2011 row is on record for this district.")}</p>
          )}
          <div className="an-acts">
            {data.district && (
              <>
                <button className="btn btn-sm" onClick={() => onAsk(`Show me crime hotspots in ${data.district}`)}>
                  {t("Hotspots here")}
                </button>
                <button className="btn btn-sm" onClick={() => onAsk(`Who is the most active offender in ${data.district}?`)}>
                  {t("Most active offender")}
                </button>
              </>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ── Community ────────────────────────────────────────────────────────────── */

export function CommunityView({ data, onAsk }: { data: CommunityProfile; onAsk: (q: string) => void }) {
  const t = useT();
  const peak = Math.max(...data.members.map((m) => m.influence), 1e-9);
  return (
    <div className="an-body">
      {data.defaulted && (
        <p className="an-note an-lead">
          {t("No person is in focus, so this is the largest community in the graph. Name a person or a community number to see a different one.")}
        </p>
      )}
      <div className="an-table an-table-comm">
        <div className="an-row an-head" aria-hidden>
          <span>#</span><span>{t("Known associate")}</span><span>{t("Network influence")}</span><span />
        </div>
        {data.members.map((m, i) => (
          <div className="an-row" key={m.person_id}>
            <span className="an-rank">{i + 1}</span>
            <div className="an-who">
              <div className="an-name">{m.name}</div>
              <div className="an-sub mono">{t("Person {id}", { id: m.person_id })}</div>
            </div>
            <span className="an-meter">
              <span className="an-bar-t">
                <i style={{ width: `${(m.influence / peak) * 100}%`,
                            background: influenceColour(m.influence / peak) }} />
              </span>
              <b className="mono">{m.influence.toFixed(4)}</b>
            </span>
            <button className="btn btn-sm" onClick={() => onAsk(`Does ${m.name} have priors?`)}>
              {t("Priors")}
            </button>
          </div>
        ))}
      </div>
      <p className="an-note">
        <span className="prov prov-derived">{t("Derived")}</span>{" "}
        {t("Membership is a Louvain community over co-offending — derived from shared cases, never a legal or gang designation. Influence is a graph-position fact, not a threat score.")}
        {data.profile && data.profile.case_count > 0 && " " +
          t("{n} distinct case(s) behind this group{c}.", {
            n: data.profile.case_count,
            c: data.profile.top_crime_type ? `, most often ${data.profile.top_crime_type}` : "",
          })}
      </p>
    </div>
  );
}

/* ── Financial watchlist ──────────────────────────────────────────────────── */

export function WatchlistView({ data, onAsk }: { data: Watchlist; onAsk: (q: string) => void }) {
  const t = useT();
  return (
    <div className="an-body">
      <div className="an-table an-table-watch">
        <div className="an-row an-head" aria-hidden>
          <span>{t("Transaction")}</span><span>{t("From → to")}</span><span>{t("Amount")}</span>
          <span>{t("Flagged as")}</span><span>{t("Detector")}</span><span>{t("Confidence")}</span><span />
        </div>
        {data.transactions.map((x) => (
          <div className={`an-row rail-${x.detector === "rule" ? "record" : "model"}`} key={x.txn_id}>
            <span className="mono an-sub">{x.txn_id}</span>
            <span className="mono an-sub">{x.src} → {x.dst}</span>
            <span className="mono">{rupees(x.amount)}</span>
            <span>{x.flag_type}</span>
            {/* The one distinction that makes this list trustworthy rather than
                merely alarming: the rule is auditable line by line in court, the
                GNN is an investigative lead. Never collapsed into "flagged". */}
            <span className={`pill ${x.detector === "rule" ? "pill-pri" : "pill-violet"}`}>
              {x.detector === "rule" ? t("Rule · auditable") : t("GNN · lead only")}
            </span>
            <span className="mono">{Math.round(x.confidence * 100)}%</span>
            <span>
              {x.fir_id && (
                <button className="btn btn-sm" onClick={() => onAsk(`What is case ${x.fir_id}?`)}>
                  {t("Case")}
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="an-note">
        {t("{r} from the rule-based structuring detector (court-auditable), {g} from the GNN pattern detector (an investigative lead, not a court-ready finding).",
           { r: data.rule, g: data.gnn })}
      </p>
    </div>
  );
}

/* ── Station workload ─────────────────────────────────────────────────────── */

export function WorkloadView({ data, onAsk }: { data: Workload; onAsk: (q: string) => void }) {
  const t = useT();
  const peak = Math.max(...data.stations.map((s) => s.open_cases), 1);
  return (
    <div className="an-body">
      <div className="an-table an-table-work">
        <div className="an-row an-head" aria-hidden>
          <span>#</span><span>{t("Station")}</span><span>{t("Open caseload")}</span>
          <span>{t("Average age")}</span><span>{t("Stalled")}</span><span />
        </div>
        {data.stations.map((s, i) => (
          <div className="an-row" key={s.ps_code}>
            <span className="an-rank">{i + 1}</span>
            <div className="an-who">
              <div className="an-name">{s.station}</div>
              <div className="an-sub mono">{t("PS {code}", { code: s.ps_code })}</div>
            </div>
            <span className="an-meter">
              <span className="an-bar-t"><i style={{ width: `${(s.open_cases / peak) * 100}%` }} /></span>
              <b className="mono">{s.open_cases}</b>
            </span>
            <span className="mono">{t("{d} days", { d: s.avg_age_days })}</span>
            <span>
              {s.stalled_count > 0
                ? <span className="pill pill-amber">{t("{n} stalled", { n: s.stalled_count })}</span>
                : <span className="pill pill-ok">{t("none stalled")}</span>}
            </span>
            <span>
              {s.stalled_ids[0] && (
                <button className="btn btn-sm" onClick={() => onAsk(`What is case ${s.stalled_ids[0]}?`)}>
                  {t("Oldest")}
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="an-note">
        <span className="prov prov-derived">{t("Derived")}</span>{" "}
        {t("STALLED means open more than {n} days with no investigation-board activity recorded — nobody has pinned evidence, added a lead or left a note. This says where to look; it never allocates work.",
           { n: data.stale_days })}
      </p>
    </div>
  );
}
