"use client";
import { influenceReading } from "@/lib/metrics";
import type { Connection, NetworkReading } from "@/lib/network";

/** The layer explanation, and the one defect it exists to close.
 *
 *  An answer would say "two people are accused in this FIR" while the graph
 *  beside it drew forty, and nothing on screen reconciled the two. An officer
 *  reading that reasonably concludes either that the answer is incomplete or
 *  that forty people are accused — and the second reading is an accusation this
 *  platform has no basis for making.
 *
 *  So the populations are stated separately and each is named for exactly what
 *  it is. The front group is either people the case file NAMES (a record fact)
 *  or people who have offended alongside the subject (a derived one) — never
 *  both under one caption, because those are different claims. Everyone else was
 *  reached through a chain of shared cases. The measurement stays on screen; it
 *  just stops being the headline. */
function Row({
  c, rank, subject, basis, onAsk,
}: {
  c: Connection; rank: number; subject: string | null;
  basis: NetworkReading["basis"]; onAsk?: (q: string) => void;
}) {
  const r = influenceReading(c.normalised, c.pagerank);
  const role = c.direct
    ? basis === "record"
      ? "Named in the case records"
      : `Offended alongside ${subject ?? "the subject"}`
    : `${r.headline} · ${c.hops} steps away`;
  return (
    <button
      className="entity-row conn"
      onClick={() => onAsk?.(`Does ${c.name} have priors?`)}
      title={`Examine ${c.name}`}
    >
      <span className="entity-rank">{rank}</span>
      <span className="conn-main">
        <span className="conn-name">{c.name}</span>
        <span className="conn-read">
          {role}
          <span className="conn-measure">{r.measure}</span>
        </span>
      </span>
    </button>
  );
}

export default function NetworkFinding({
  reading, onAsk, limit = 4,
}: { reading: NetworkReading; onAsk?: (q: string) => void; limit?: number }) {
  const { direct, extended, basis, subjectName } = reading;
  if (!direct.length && !extended.length) return null;

  const who = subjectName ?? "this investigation";
  const frontLabel = basis === "record" ? "Named in the records" : "Direct co-offenders";

  return (
    <div className="module">
      <div className="module-head">
        <span className="label">Who this network shows</span>
      </div>

      <p className="layer-note">
        {direct.length > 0 && (basis === "record" ? (
          <>
            <b>{direct.length}</b> {direct.length === 1 ? "person is" : "people are"} named
            directly in the records for this investigation.
          </>
        ) : (
          <>
            <b>{direct.length}</b> {direct.length === 1 ? "person has" : "people have"} offended
            alongside {who} on a shared case.
          </>
        ))}
        {extended.length > 0 && (
          <>
            {" "}
            <b>{extended.length}</b> further {extended.length === 1 ? "person is" : "people are"}{" "}
            reached through a chain of shared cases — connected, not accused here.
          </>
        )}
      </p>

      {direct.length > 0 && (
        <>
          <div className="module-head sub">
            <span className="label">{frontLabel}</span>
            <span className={`prov prov-${basis === "record" ? "record" : "derived"}`}
              title={basis === "record"
                ? "Stated in the case records"
                : "Inferred by Veritas from cases these people share"}>
              {basis === "record" ? "Record" : "Derived"}
            </span>
          </div>
          <div className="entity-list">
            {direct.slice(0, limit).map((c, i) => (
              <Row key={c.id} c={c} rank={i + 1} subject={subjectName} basis={basis} onAsk={onAsk} />
            ))}
          </div>
          {direct.length > limit && (
            <div className="meta conn-more">
              and {direct.length - limit} more — the Network view has all of them.
            </div>
          )}
        </>
      )}

      {extended.length > 0 && (
        <>
          <div className="module-head sub">
            <span className="label">Strongest wider connections</span>
            <span className="prov prov-derived" title="Inferred by Veritas from shared cases">Derived</span>
          </div>
          <div className="entity-list">
            {extended.slice(0, limit).map((c, i) => (
              <Row key={c.id} c={c} rank={i + 1} subject={subjectName} basis={basis} onAsk={onAsk} />
            ))}
          </div>
          {extended.length > limit && (
            <div className="meta conn-more">
              and {extended.length - limit} more in the Network view.
            </div>
          )}
        </>
      )}
    </div>
  );
}
