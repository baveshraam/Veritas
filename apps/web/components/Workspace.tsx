"use client";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import CaseExplorer from "./CaseExplorer";
import CaseOverview from "./CaseOverview";
import PersonOverview from "./PersonOverview";
import Board from "./Board";
import {
  getAreaProfile, getCaseTimeline, getCommunity, getFir, getForecastSeries, getHotspots,
  getOffenders, getStatistics, getWatchlist, getWorkload,
} from "@/lib/api";
import type { OffenderRow as ApiOffenderRow } from "@/lib/api";
import { AreaView, CommunityView, WatchlistView, WorkloadView } from "./AnalyticsViews";
import { useAnalytics } from "@/lib/useAnalytics";
import { PROV_LABEL, provenanceOf } from "@/lib/evidence";
import { useT } from "@/lib/i18n";
import { densityReading, forecastReading, plural, rupees, type Reading } from "@/lib/metrics";
import { readNetwork } from "@/lib/network";
import type { EvidenceItem, SessionFocusView, TimelineResult, Visualization } from "@/lib/types";
import type { WorkspaceView } from "./InvestigationHeader";

/** A flat readout of the evidence items an answer produced, for the views (Offenders,
 *  Statistics) that are pure ranked/aggregated text — the engine gives no chart for
 *  these, and the ranked rows ARE the finding. Reuses the evidence rail styling so a
 *  record and a derived note still read apart here the way they do everywhere else. */
function EvidenceList({ items }: { items: EvidenceItem[] }) {
  const t = useT();
  return (
    <div className="col-body ev-list" style={{ padding: "12px 16px" }}>
      {items.map((e, i) => {
        const p = provenanceOf(e);
        return (
          <div key={e.evidence_id} className={`ev rail-${p}`}>
            <div className="ev-head">
              <span className="ev-idx">{i + 1}</span>
              <span className={`prov prov-${p}`}>{t(PROV_LABEL[p])}</span>
            </div>
            <div className="ev-body">{e.content}</div>
          </div>
        );
      })}
    </div>
  );
}

type OffenderRow = { id: string; name: string; cases: number; habitual: boolean; community: string | null };

// The engine gives each offender as one authoritative sentence ("named as
// accused on 7 case(s) matching…, recorded as a habitual offender, network
// community 3."), not a JSON row — this reads the same fields a table needs
// back out of it rather than asking the backend for a second, parallel shape.
function parseOffender(e: EvidenceItem): OffenderRow {
  const name = /^\d+\.\s*(.+?)\s+—\s+named as accused/i.exec(e.content)?.[1] ?? e.content;
  const cases = Number(/named as accused on (\d+)\s*case/i.exec(e.content)?.[1] ?? 0);
  return {
    id: e.evidence_id.replace(/^offender:/, ""),
    name,
    cases,
    habitual: /habitual offender/i.test(e.content),
    community: /network community (\d+)/i.exec(e.content)?.[1] ?? null,
  };
}

/** The Offenders / Repeat Offenders ranking as an actual table — rank, who,
 *  what's recorded about them, how many cases name them — instead of the same
 *  facts read out as full sentences one after another. Every column is a real
 *  recorded fact (case count, habitual flag, community) with nothing invented
 *  to fill a column the record layer doesn't have (age, area, an offence
 *  profile, a risk score) — CLAUDE.md §6/§8: a model estimate must never be
 *  able to look like a record, and this view is a record view. */
function OffenderTable({ items, onAsk }: { items: EvidenceItem[]; onAsk: (q: string) => void }) {
  const t = useT();
  const rows = items.map(parseOffender);
  return (
    <div className="off-table">
      <div className="off-row off-head" aria-hidden>
        <span>#</span><span>{t("Offender")}</span><span>{t("Recorded as")}</span><span>{t("Community")}</span><span>{t("Cases")}</span><span />
      </div>
      <div className="off-body">
        {rows.map((r, i) => (
          <div key={r.id} className="off-row">
            <span className="off-rank">{i + 1}</span>
            <div className="off-who">
              <div className="off-name">{r.name}</div>
              <div className="off-id mono">{t("Person {id}", { id: r.id })}</div>
            </div>
            <div className="off-badges">
              <span className="pill pill-red">{t("Accused")}</span>
              {r.habitual && <span className="pill pill-amber">{t("Habitual")}</span>}
            </div>
            <span className="off-community">{r.community ? t("Community {n}", { n: r.community }) : "—"}</span>
            <span className="off-cases mono">{r.cases}</span>
            <button className="btn btn-sm off-ask" onClick={() => onAsk(`Does ${r.name} have priors?`)}>
              {t("Priors")}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

/** The same ranking table as `OffenderTable`, but fed the STRUCTURED rows the
 *  /analytics endpoint returns rather than the sentences a chat answer produces.
 *
 *  Two renderers rather than one because the two paths genuinely carry different
 *  things: a chat answer's rows are evidence items with citation ids the console
 *  threads back to the copilot, and the tab's own rows are plain records with no
 *  turn behind them. Parsing the structured rows back into sentences so one
 *  component could take both would be inventing prose to throw it away again.
 *  Every column is still a recorded fact — case count, habitual flag, community —
 *  and none of them is a risk score. */
function OffenderRows({ rows, onAsk }: { rows: ApiOffenderRow[]; onAsk: (q: string) => void }) {
  const t = useT();
  return (
    <div className="off-table">
      <div className="off-row off-head" aria-hidden>
        <span>#</span><span>{t("Offender")}</span><span>{t("Recorded as")}</span><span>{t("Community")}</span><span>{t("Cases")}</span><span />
      </div>
      <div className="off-body">
        {rows.map((r, i) => (
          <div key={r.person_id} className="off-row">
            <span className="off-rank">{i + 1}</span>
            <div className="off-who">
              <div className="off-name">{r.name}</div>
              <div className="off-id mono">{t("Person {id}", { id: r.person_id })}</div>
            </div>
            <div className="off-badges">
              <span className="pill pill-red">{t("Accused")}</span>
              {r.habitual && <span className="pill pill-amber">{t("Habitual")}</span>}
            </div>
            <span className="off-community">{r.community !== null ? t("Community {n}", { n: r.community }) : "—"}</span>
            <span className="off-cases mono">{r.cases}</span>
            <button className="btn btn-sm off-ask" onClick={() => onAsk(`Does ${r.name} have priors?`)}>
              {t("Priors")}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// Charts and MapLibre touch window/canvas — keep them out of the server bundle.
const NetworkView = dynamic(() => import("./viz/NetworkView"), { ssr: false });
const SankeyView = dynamic(() => import("./viz/SankeyView"), { ssr: false });
const TrendView = dynamic(() => import("./viz/TrendView"), { ssr: false });
const MapView = dynamic(() => import("./viz/MapView"), { ssr: false });
const StatsDashboard = dynamic(() => import("./viz/StatsDashboard"), { ssr: false });
const TimelineView = dynamic(() => import("./viz/TimelineView"), { ssr: false });

/** A view that has nothing loaded yet. Never a dead end: it says what the view
 *  is for and hands over the exact question that fills it, so a judge or an
 *  officer reaches the analysis in one click instead of guessing a phrasing. */
function Prompt({
  mark, title, body, ask, question,
}: {
  mark: string; title: string; body: string;
  ask: (q: string) => void; question: string | null;
}) {
  const t = useT();
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden>{mark}</span>
      <h3>{t(title)}</h3>
      <p>{t(body)}</p>
      {question && (
        <button className="btn" onClick={() => ask(question)}>{t(question)}</button>
      )}
    </div>
  );
}

/** What a directly-loaded tab shows while its own request is in flight, or when that
 *  request failed. A failure has to say so: a view that silently keeps showing
 *  "Loading…" is indistinguishable from a view whose data is genuinely empty, and an
 *  officer cannot tell which one they are looking at. */
function Loading({ label }: { label: string }) {
  const t = useT();
  return <div className="empty"><span className="spinner" /><p>{t(label)}</p></div>;
}

function Failed({ error, retryHint }: { error: string; retryHint?: string }) {
  const t = useT();
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden>⚠</span>
      <h3>{t("This analysis could not be loaded")}</h3>
      <p>{error}</p>
      {retryHint && <p className="an-note">{t(retryHint)}</p>}
    </div>
  );
}

/** The primary workspace: one surface at a time, under a header that answers
 *  the questions a visualization cannot answer about itself — what this is,
 *  what it found, what KIND of claim that is, and what to do next.
 *
 *  The rule the header enforces (see lib/metrics.ts): the FINDING is the
 *  headline and the measurement sits under it. "Severe concentration" over
 *  "1.00"; "≈74 cases projected" over "2.5 mean FIRs/day". Nothing is hidden —
 *  a band is a reading of a number that is still printed beside it. */
export default function Workspace({
  view, viz, focus, evidence, onAsk, onPreload, onCopilot, onBoard, activeEvidence, onSelectEvidence,
  onPinEvidence, boardVersion, sessionId,
}: {
  view: WorkspaceView;
  viz: Visualization;
  focus?: SessionFocusView;
  evidence: EvidenceItem[];
  onAsk: (q: string) => void;
  /** Same as onAsk, but for a tab's own background preload — must never pull
   *  the workspace away from wherever the officer has since navigated. */
  onPreload: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  activeEvidence: string | null;
  onSelectEvidence: (id: string) => void;
  onPinEvidence: (id: string) => void;
  boardVersion: number;
  /** Passed down so a selected node / case / event can ask GET /explain why it is
   *  on screen, with the session's own operation and focus as context. */
  sessionId?: string;
}) {
  const t = useT();
  const kind = viz?.kind ?? "none";
  const d = viz?.data ?? {};
  const firId = focus?.case?.fir_id ?? null;
  const person = focus?.person?.name;

  // The Timeline view prefers the FULL case timeline over whatever a chat turn
  // happened to filter — the tab is a view of the case, not of the last answer.
  // Opening a case turns Overview into the case's own overview. The register
  // must not become unreachable for that (it is also in ⌘K) — this is the one
  // click back to it, and it resets whenever the case changes.
  const [showRegister, setShowRegister] = useState(false);
  useEffect(() => { setShowRegister(false); }, [firId, focus?.person?.person_id]);

  // Offenders/Repeat Offenders search — a name search over EVERY offender in the
  // officer's scope, not just the top-ranked page a chat question or the tab's own
  // default view shows. Debounced so typing doesn't fire a scan per keystroke.
  const [offenderQuery, setOffenderQuery] = useState("");
  const [offenderQueryLive, setOffenderQueryLive] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setOffenderQueryLive(offenderQuery.trim()), 300);
    return () => clearTimeout(id);
  }, [offenderQuery]);

  // Every analytical tab loads its own data DIRECTLY FROM THE RECORDS the moment it
  // is opened, and keeps it. It used to fill itself by firing a canned English
  // question at the conversational engine and reading the answer's evidence back
  // out, which was wrong three ways at once: a turn's evidence is the LAST turn's
  // evidence, so opening a second tab wiped the first; the guard that stopped the
  // preload re-firing then left the revisited tab loading forever; and the officer's
  // own transcript filled with questions nobody had asked. A tab is not a question.
  //
  // The conversational path is untouched and still WINS: where a chat answer has
  // produced this view's result — with its citations, its scope and its refusals —
  // that is what renders. The fetched data is the default the tab opens on, not a
  // replacement for asking.
  const offenderRows = evidence.filter((e) => e.evidence_id.startsWith("offender:"));
  const hasOffenderRanking = offenderRows.length > 0;
  const hasHabitualRanking = offenderRows.some((e) => /habitual offender/i.test(e.content));
  const chatStats = evidence.filter((e) => e.evidence_id.startsWith("stats:"));
  const hasGeography = kind === "map";
  const hasForecast = kind === "trend";
  const chatArea = evidence.filter((e) => e.evidence_id.startsWith("area:"));
  const chatCommunity = evidence.filter((e) => e.evidence_id.startsWith("community:"));
  const chatWatchlist = evidence.filter((e) => e.evidence_id.startsWith("watchlist:"));
  const chatWorkload = evidence.filter((e) => e.evidence_id.startsWith("workload:")
    || e.evidence_id.startsWith("stalled:"));

  // Network's own person to ask about: with a case open, that case's lead accused
  // wins — otherwise a person focus left over from a DIFFERENT question asked before
  // this case was opened would keep showing on this tab regardless of which case is
  // now open. Only with no case open does an explicit person focus apply. Fetched
  // once per case.
  const [caseLead, setCaseLead] = useState<string | null>(null);
  useEffect(() => {
    if (!firId) { setCaseLead(null); return; }
    let live = true;
    getFir(firId).then((f) => live && setCaseLead(f.accused?.[0]?.AccusedName ?? null))
      .catch(() => live && setCaseLead(null));
    return () => { live = false; };
  }, [firId]);
  const networkSubject = firId ? (caseLead ?? person) : person;

  // Network is the one analytical tab that stays on the conversational path: it is a
  // subject-scoped graph traversal with real citations and a policy depth cap, not a
  // readout of the case set, and there is nothing to show until a subject exists.
  // `onPreload` (never `onAsk`) so its completion cannot yank the workspace back here
  // after the officer has clicked away.
  const onPreloadRef = useRef(onPreload);
  onPreloadRef.current = onPreload;
  const netFired = useRef("");
  useEffect(() => {
    if (view !== "network" || kind === "network" || !networkSubject) return;
    const key = firId ?? networkSubject;
    if (netFired.current === key) return;
    netFired.current = key;
    onPreloadRef.current(`Who are the associates of ${networkSubject}?`);
  }, [view, kind, networkSubject, firId]);

  const stats = useAnalytics(view === "statistics", "all", () => getStatistics());
  // Offenders is every offender in scope, full stop — not a "most active" top-N. That
  // ranked-by-activity framing belongs to Repeat Offenders, which is genuinely a
  // ranking (habitual, by recorded case count). So Offenders always fetches the whole
  // scoped list, regardless of whether a chat answer's own (narrower, question-scoped)
  // ranking is sitting in evidence — a search or a fresh open should never show fewer
  // people than "everyone".
  const topOffenders = useAnalytics(view === "offenders",
    `all:${offenderQueryLive}`, () => getOffenders({ limit: 5000, q: offenderQueryLive || null }));
  const repeatOffenders = useAnalytics(view === "repeat_offenders" && !(hasHabitualRanking && !offenderQueryLive),
    `all:${offenderQueryLive}`, () => getOffenders({ limit: 20, habitual: true, q: offenderQueryLive || null }));
  const geo = useAnalytics(view === "geography" && !hasGeography, "default",
    () => getHotspots());
  const fc = useAnalytics(view === "forecast" && !hasForecast, "default",
    () => getForecastSeries());
  const area = useAnalytics(view === "area" && !chatArea.length, "default",
    () => getAreaProfile());
  // Keyed on the person in focus: opening this tab while investigating someone should
  // show THEIR community, and it must re-fetch when the subject changes.
  const community = useAnalytics(view === "community" && !chatCommunity.length,
    focus?.person?.person_id ?? "default",
    () => getCommunity({ personId: focus?.person?.person_id ?? null }));
  const watch = useAnalytics(view === "watchlist" && !chatWatchlist.length, "all",
    () => getWatchlist(50));
  const work = useAnalytics(view === "workload" && !chatWorkload.length, "all",
    () => getWorkload());


  const [caseTl, setCaseTl] = useState<TimelineResult | null>(null);
  const [tlError, setTlError] = useState<string | null>(null);
  useEffect(() => {
    if (view !== "timeline" || !firId || kind === "timeline") return;
    setCaseTl(null); setTlError(null);
    let live = true;
    getCaseTimeline(firId)
      .then((t) => live && setCaseTl(t))
      .catch((e) => live && setTlError(e.message));
    return () => { live = false; };
  }, [view, firId, kind]);

  let title = t("Case register");
  let sub = "";
  let lead: Reading | null = null;
  let prov: "record" | "derived" | "model" | null = null;
  let figs: { n: string; l: string }[] = [];
  let next: { label: string; q: string } | null = null;
  let body: React.ReactNode = null;
  let flush = false;
  let searchBar: React.ReactNode = null;

  if (view === "register") {
    title = t("Case register");
    sub = t("Every case your rank is cleared to see, independent of whichever case is open.");
    body = <CaseExplorer onAsk={onAsk} onCopilot={onCopilot} onBoard={onBoard} activeFir={firId} />;
    flush = true;
  }

  if (view === "forecast") {
    if (kind === "trend") {
      const s: [string, number, number, number][] = d.series ?? [];
      const f = forecastReading(s);
      title = t("{days}-day outlook", { days: f.days });
      sub = t("Projected case volume, with the daily range the model considers likely.");
      lead = f;
      prov = "model";
      figs = [{ n: String(f.days), l: t("days ahead") }];
      next = { label: t("Where are these concentrated?"), q: "Show me crime hotspots" };
      body = <TrendView data={d} />;
    } else if (fc.data?.series?.length) {
      // Loaded straight from the records (GET /analytics/forecast) — same Prophet +
      // MinT call the FORECAST intent makes, without needing a question first.
      const s: [string, number, number, number][] = fc.data.series;
      const f = forecastReading(s);
      title = t("{days}-day outlook", { days: f.days });
      sub = fc.data.district
        ? t("{d} — projected case volume, with the daily range the model considers likely.", { d: fc.data.district })
        : t("Projected case volume, with the daily range the model considers likely.");
      lead = f;
      prov = "model";
      figs = [{ n: String(f.days), l: t("days ahead") }];
      next = { label: t("Where are these concentrated?"), q: "Show me crime hotspots" };
      body = <TrendView data={{ series: s }} />;
    } else {
      title = t("Forecast");
      body = fc.error
        ? <Failed error={fc.error} />
        : <Loading label="Fitting the forecast to the recorded case history…" />;
    }
  }

  if (view === "offenders" || view === "repeat_offenders") {
    const habitual = view === "repeat_offenders";
    const rows = evidence.filter((e) => e.evidence_id.startsWith("offender:")
      && (habitual ? /habitual offender/i.test(e.content) : true));
    title = habitual ? t("Repeat offenders") : t("Offenders");
    sub = habitual
      ? t("Ranked by how many cases on record name them — a fact the identity layer makes possible, since the raw records have no cross-case person at all.")
      : t("Every person named as accused on a case within your access scope — the identity layer makes this list possible at all, since the raw records have no cross-case person.");
    // Repeat Offenders is a genuine ranking, and a chat answer's own (question-scoped)
    // ranking wins there when there is one and nobody is searching. Offenders is never
    // a ranking — it is everyone in scope — so it always shows the full fetched list;
    // a chat answer that named a handful of people is not "the offenders", it's a
    // narrower answer to a different question.
    const loaded = habitual ? repeatOffenders : topOffenders;
    const direct = loaded.data?.offenders ?? [];
    const searching = offenderQueryLive.length > 0;
    const useDirect = !habitual || searching || !rows.length;
    const n = useDirect ? direct.length : rows.length;
    searchBar = (
      <input
        className="offender-search"
        type="search"
        value={offenderQuery}
        onChange={(e) => setOffenderQuery(e.target.value)}
        placeholder={t("Search every offender in your scope by name…")}
        aria-label={t("Search offenders by name")}
      />
    );
    if (n) {
      lead = { headline: plural(n, "person", "people", t),
        measure: searching
          ? t("Matching “{q}”, within your access scope", { q: offenderQueryLive })
          : habitual
            ? t("Ranked by recorded case count, within your access scope")
            : t("Every offender on record, within your access scope") };
      prov = "record";
      figs = [{ n: String(n), l: searching ? t("matched") : habitual ? t("ranked") : t("listed") }];
      body = useDirect
        ? <OffenderRows rows={direct} onAsk={onAsk} />
        : <OffenderTable items={rows} onAsk={onAsk} />;
      flush = true;
    } else if (loaded.error) {
      body = <Failed error={loaded.error} />;
    } else if (loaded.loading || !loaded.data) {
      body = <Loading label="Counting the cases that name each person…" />;
    } else if (searching) {
      body = <Prompt mark="◈" title={t("No offender named “{q}” is on record in your scope", { q: offenderQueryLive })}
        body={t("The search covers every offender in your access scope, not only the ranked page — this name simply isn't in the records you can see.")}
        ask={onAsk} question={habitual ? "Who are the repeat offenders in Bengaluru Urban?" : "Who is the most active offender in Bengaluru Urban?"} />;
    } else {
      body = <Prompt mark="◈" title={habitual ? "No repeat offender is on record in your scope" : "No offender is on record in your scope"}
        body="Case count is a recorded fact, never a risk score — this never ranks by PageRank or a model output."
        ask={onAsk}
        question={habitual ? "Who are the repeat offenders in Bengaluru Urban?" : "Who is the most active offender in Bengaluru Urban?"} />;
    }
  }

  if (view === "statistics") {
    title = t("Case statistics");
    sub = t("The shape of the whole case set — volume over time, how cases end, and where they are recorded.");
    if (stats.data) {
      prov = "record";
      lead = {
        headline: t("{n} cases analysed", { n: stats.data.total.toLocaleString() }),
        measure: t("Every figure is a count of records within your access scope"),
      };
      figs = [
        { n: String(stats.data.district.length), l: t("districts") },
        { n: String(stats.data.station.length), l: t("stations") },
        { n: String(stats.data.crime_type.length), l: t("offence types") },
      ];
      body = (
        <div className="stat-scroll">
          {/* A chat answer about statistics keeps its own citations and its own
              scope, so it is shown AS an answer above the dashboard rather than
              being folded into it — the dashboard is statewide and the answer
              usually is not, and silently merging the two would caption one
              scope's number with another's. */}
          {chatStats.length > 0 && (
            <div className="stat-answer">
              <div className="stat-answer-h">{t("From your last question")}</div>
              <EvidenceList items={chatStats} />
            </div>
          )}
          <StatsDashboard data={stats.data} onAsk={onAsk} />
        </div>
      );
      flush = true;
    } else if (stats.error) {
      body = <Failed error={stats.error} />;
    } else {
      body = <Loading label="Counting the case set…" />;
    }
  }

  if (view === "area") {
    title = t("Area profile");
    sub = t("Recorded crime mix alongside real Census 2011 ground truth for the same district — shown side by side, never combined into one score.");
    if (chatArea.length) {
      prov = "record";
      figs = [{ n: String(chatArea.length), l: t("facts") }];
      body = <EvidenceList items={chatArea} />;
      flush = true;
    } else if (area.data?.district) {
      prov = "record";
      title = t("Area profile — {d}", { d: area.data.district });
      lead = { headline: t("{n} cases on record", { n: area.data.total.toLocaleString() }),
               measure: t("Recorded in this district, within your access scope") };
      figs = [{ n: String(area.data.mix.length), l: t("offence types") }];
      body = <AreaView data={area.data} onAsk={onAsk} />;
      flush = true;
    } else if (area.error) {
      body = <Failed error={area.error} />;
    } else if (area.loading || !area.data) {
      body = <Loading label="Profiling the district against the case set and Census 2011…" />;
    } else {
      body = <Prompt mark="◈" title="No area could be profiled"
        body="Name a district and Veritas profiles it: recorded offence mix next to real Census 2011 socioeconomic ground truth. No district finer than this exists in the data."
        ask={onAsk} question="Give me an area profile of Bengaluru Urban" />;
    }
  }

  if (view === "community") {
    const summary = chatCommunity.find((e) => e.evidence_id.startsWith("community:summary:"));
    const members = chatCommunity.filter((e) => e !== summary);
    title = t("Known associates group");
    sub = t("A Louvain community over co-offending — derived from shared cases, never a legal or gang designation.");
    if (members.length) {
      lead = { headline: plural(members.length, "known associate", undefined, t),
        measure: t("Ranked by network influence — not a risk score") };
      prov = "derived";
      figs = [{ n: String(members.length), l: t("members") }];
      body = <EvidenceList items={summary ? [summary, ...members] : members} />;
      flush = true;
    } else if (community.data?.members?.length) {
      const c = community.data;
      title = c.community_id !== null
        ? t("Community {n}", { n: c.community_id })
        : t("Known associates group");
      lead = { headline: plural(c.members.length, "known associate", undefined, t),
        measure: t("Ranked by network influence — not a risk score") };
      prov = "derived";
      figs = [
        { n: String(c.members.length), l: t("members") },
        ...(c.profile ? [{ n: String(c.profile.case_count), l: t("shared cases") }] : []),
      ];
      body = <CommunityView data={c} onAsk={onAsk} />;
      flush = true;
    } else if (community.error) {
      body = <Failed error={community.error} />;
    } else if (community.loading || !community.data) {
      body = <Loading label="Reading the co-offending communities off the graph…" />;
    } else {
      body = <Prompt mark="◇" title="No community is on record"
        body="Name a community number, or ask about a person already in focus, and Veritas shows who else the graph places alongside them."
        ask={onAsk} question="Who is in community 1?" />;
    }
  }

  if (view === "watchlist") {
    title = t("Financial watchlist");
    sub = t("Every transaction a detector has flagged, statewide — each labelled by which one: the rule-based detector is court-auditable, the GNN is an investigative lead only.");
    if (chatWatchlist.length) {
      prov = "model";
      figs = [{ n: String(chatWatchlist.length), l: t("flagged") }];
      body = <EvidenceList items={chatWatchlist} />;
      flush = true;
    } else if (watch.data?.transactions?.length) {
      prov = "model";
      lead = { headline: plural(watch.data.total, "flagged transaction", undefined, t),
               measure: t("Ranked by detector confidence") };
      figs = [
        { n: String(watch.data.rule), l: t("rule-based") },
        { n: String(watch.data.gnn), l: t("GNN") },
      ];
      body = <WatchlistView data={watch.data} onAsk={onAsk} />;
      flush = true;
    } else if (watch.error) {
      body = <Failed error={watch.error} />;
    } else if (watch.loading || !watch.data) {
      body = <Loading label="Reading the detectors flagged transactions…" />;
    } else {
      body = <Prompt mark="◈" title="Nothing is currently flagged"
        body="No transaction is flagged by either detector within your access scope. That is a checked absence, not a failed search."
        ask={onAsk} question={null} />;
    }
  }

  if (view === "workload") {
    title = t("Station workload");
    sub = t("Open caseload and how much of it has gone stale — untouched on the investigation board for over 30 days. Never allocates work; only says where to look.");
    if (chatWorkload.length) {
      prov = "derived";
      figs = [{ n: String(chatWorkload.filter((e) => e.evidence_id.startsWith("workload:")).length), l: t("stations") },
              { n: String(chatWorkload.filter((e) => e.evidence_id.startsWith("stalled:")).length), l: t("stalled cases") }];
      body = <EvidenceList items={chatWorkload} />;
      flush = true;
    } else if (work.data?.stations?.length) {
      prov = "derived";
      lead = { headline: plural(work.data.stalled, "stalled case", undefined, t),
               measure: `${t("{n} open across", { n: work.data.open_cases.toLocaleString() })} ${plural(work.data.stations.length, "station", undefined, t)}` };
      figs = [
        { n: String(work.data.stations.length), l: t("stations") },
        { n: String(work.data.open_cases), l: t("open cases") },
      ];
      body = <WorkloadView data={work.data} onAsk={onAsk} />;
      flush = true;
    } else if (work.error) {
      body = <Failed error={work.error} />;
    } else if (work.loading || !work.data) {
      body = <Loading label="Measuring each station open caseload…" />;
    } else {
      body = <Prompt mark="◈" title="No case is under investigation in your scope"
        body="Nothing is currently open, so there is no workload to measure. That is a checked absence, not a failed search."
        ask={onAsk} question={null} />;
    }
  }

  if (view === "overview") {
    if (firId && !showRegister) {
      // A case is open. The register is the right answer when nothing is; it is
      // the wrong one the moment something is, and it was what Overview showed.
      title = t("Case overview");
      sub = t("What this case is, who is in it, what is still open, and what changed most recently.");
      body = <CaseOverview firId={firId} onAsk={onAsk} onCopilot={onCopilot}
        refreshToken={boardVersion} />;
      next = { label: t("Case register"), q: "" };
      flush = true;
    } else if (focus?.person?.person_id && !showRegister) {
      // A person is the subject and no case is open — the identity-resolution
      // centrepiece (CLAUDE.md §0) otherwise had no home screen: priors, network,
      // financial and timeline all worked one question at a time, but Overview
      // fell back to the unfiltered case register regardless of who was asked
      // about.
      title = t("Person overview");
      sub = t("Who this is, the cases naming them, and what to ask next.");
      body = <PersonOverview personId={focus.person.person_id} name={person} onAsk={onAsk} />;
      next = { label: t("Case register"), q: "" };
      flush = true;
    } else {
      title = t("Case register");
      sub = firId
        ? t("Every case your rank is cleared to see. The case you are working stays open.")
        : t("Every case your rank is cleared to see. Open one to start an investigation.");
      if (firId) next = { label: t("Back to this case"), q: "" };
      body = <CaseExplorer onAsk={onAsk} onCopilot={onCopilot} onBoard={onBoard}
        activeFir={firId} />;
      flush = true;
    }
  }

  if (view === "geography") {
    // The map is PRELOADED. It used to appear only after a canned "Show me crime
    // hotspots" question had round-tripped through the conversational engine, which
    // meant an officer opening the tab watched a question they had not asked run in
    // the copilot column beside an empty canvas. The same KDE + DBSCAN call now comes
    // straight off GET /analytics/hotspots when the tab opens — and a chat answer,
    // which carries its own district scope and citations, still overrides it.
    const md = kind === "map" ? d : (geo.data ?? null);
    if (md) {
      const pts: any[] = md.fir_points ?? [];
      const polys: any[] = md.polygons ?? [];
      const districts = new Set(pts.map((p) => p.district).filter(Boolean));
      const peak = polys.length ? Math.max(...polys.map((h) => h.intensity ?? 0)) : 0;
      const biggest = polys.length ? Math.max(...polys.map((h) => h.crime_count ?? 0)) : 0;
      const main = [...districts][0];
      title = t("Crime concentration");
      sub = districts.size === 1 && main
        ? t("{main} — cases as recorded, with modelled hotspot density drawn over them.", { main })
        : t("{n} districts — cases as recorded, with modelled hotspot density drawn over them.", { n: districts.size });
      if (polys.length) {
        lead = densityReading(peak);
        prov = "model";
      }
      figs = [
        { n: String(pts.length), l: t("cases located") },
        ...(polys.length ? [
          { n: String(polys.length), l: t("hotspots") },
          { n: String(biggest), l: t("in the strongest") },
        ] : []),
      ];
      if (main) next = { label: t("Cases in {main}", { main }), q: `Show me theft cases in ${main}` };
      body = <MapView data={md} activeEvidenceId={activeEvidence} onSelect={onSelectEvidence}
               onAsk={onAsk} sessionId={sessionId} />;
      flush = true;
    } else if (geo.error) {
      title = t("Hotspot Map");
      body = <Failed error={geo.error} />;
    } else {
      title = t("Hotspot Map");
      body = <Loading label="Locating the recorded cases and fitting the density model…" />;
    }
  }

  const net = readNetwork(viz, evidence, person);

  if (view === "network") {
    if (kind === "network" && net) {
      title = t("People and connections");
      // The layering, stated where the graph is. The copilot says the same
      // thing beside the answer — an officer arriving by tab never read that.
      const front = t(net.basis === "record" ? "named in these records" : "who offended alongside them");
      const wider = net.extended.length
        ? t(", and {n} more reached through a chain of shared cases", { n: net.extended.length })
        : "";
      sub = net.direct.length
        ? `${plural(net.direct.length, "person", "people", t)} ${front}${wider}.`
        : t("People reconstructed from accused records by probabilistic linkage, connected by the cases they share.");
      lead = {
        headline: net.direct.length
          ? `${net.direct.length} ${t(net.basis === "record" ? "directly involved" : "direct co-offenders")}`
          : t("{n} in this network", { n: net.total }),
        measure: `${plural(net.edges, "connection", undefined, t)} · ${t("{n} people in view", { n: net.total })}`,
      };
      prov = net.basis === "record" ? "record" : "derived";
      figs = [
        { n: String(net.direct.length), l: net.basis === "record" ? t("named in record") : t("direct") },
        { n: String(net.extended.length), l: t("wider network") },
        ...(net.communities ? [{ n: String(net.communities), l: t("communities") }] : []),
      ];
      if (net.extended[0]) {
        next = { label: t("Examine {name}", { name: net.extended[0].name }), q: `Does ${net.extended[0].name} have priors?` };
      }
      body = <NetworkView data={d} onAsk={onAsk} subjectLabel={person} reading={net}
               sessionId={sessionId} />;
      flush = true;
    } else if (networkSubject) {
      // Auto-preload (above) is already asking this; this is only the frame
      // shown while that request is in flight.
      title = t("Network");
      body = <Prompt mark="◇" title="Loading network…" body="" ask={onAsk} question={null} />;
    } else {
      title = t("Network");
      body = <Prompt mark="◇" title="No network loaded"
        body="Open a case or name a person and Veritas traces who they offend with. Without a named subject there is nothing to traverse from, and picking one would be a guess."
        ask={onAsk} question={null} />;
    }
  }

  if (view === "financial") {
    if (kind === "sankey") {
      const links: any[] = d.links ?? [];
      const nodes: any[] = d.nodes ?? [];
      const traced = links.reduce((a, l) => a + (l.value ?? 0), 0);
      const sources = new Set(links.map((l) => l.source)).size;
      const dests = new Set(links.map((l) => l.target)).size;
      title = t("Financial trail");
      sub = t("Transfers between accounts owned by people in this investigation. Direction is preserved — money moves one way.");
      lead = {
        headline: t("{amount} traced", { amount: rupees(traced) }),
        measure: `${plural(sources, "source account", undefined, t)} · ${plural(dests, "destination account", undefined, t)}`,
      };
      prov = "record";
      figs = [
        { n: String(links.length), l: t("transfers") },
        { n: String(nodes.length), l: t("accounts") },
      ];
      body = <SankeyView data={d} />;
      flush = true;
    } else {
      // A trail that was LOOKED FOR and not found is a finding, and must not
      // render as "nothing has been asked yet". The engine says which happened.
      const searched = evidence.find((e) => e.evidence_id.startsWith("flow:none:"));
      title = t("Financial");
      if (searched) {
        lead = { headline: t("No outbound trail"), measure: t("Within your access scope") };
        prov = "record";
        sub = t("The accounts were traced. Nothing moved out of them in the records you can see.");
        body = <Prompt mark="◆" title="No outbound transfer trail"
          body={searched.content}
          ask={onAsk}
          question={person ? `Show me the timeline for ${person}` : null} />;
      } else if (firId) {
        body = <Prompt mark="◆" title="No money trail loaded"
          body="Financial analysis follows the accounts owned by people in this case. Ask about the money trail and Veritas traces the transfers, resolving the subject from this case."
          ask={onAsk}
          question="Trace the money trail for this case" />;
      } else {
        body = <Prompt mark="◆" title="No money trail loaded"
          body="Financial analysis follows a person's accounts. Pick a case from the register, or name a person, then ask about the money trail."
          ask={onAsk}
          question={null} />;
      }
    }
  }

  if (view === "timeline") {
    const data = kind === "timeline" ? d : caseTl;
    const events: any[] = data?.events ?? [];
    title = t("Investigation timeline");
    sub = t("One chronology across the case, the people accused in it, and money through their accounts.");
    if (events.length) {
      const derived = events.filter((e) => e.kind === "derived").length;
      lead = {
        headline: plural(events.length, "dated event", undefined, t),
        measure: t("{a} stated in the records · {b} linked by identity resolution",
          { a: events.length - derived, b: derived }),
      };
      prov = derived ? "derived" : "record";
      figs = [
        { n: String(events.length - derived), l: t("from records") },
        ...(derived ? [{ n: String(derived), l: t("derived") }] : []),
      ];
      body = <TimelineView data={data} activeEvidenceId={activeEvidence}
        onSelect={onSelectEvidence} onPin={onPinEvidence} />;
    } else if (tlError) {
      body = <Prompt mark="◷" title="Timeline unavailable" body={tlError} ask={onAsk} question={null} />;
    } else if (firId && !caseTl) {
      body = <div className="empty"><span className="spinner" /><p>{t("Building the case chronology…")}</p></div>;
    } else {
      body = <Prompt mark="◷" title="No timeline loaded"
        body="Open a case and its chronology appears here — its own dates, its accused persons' other cases, and any money that moved."
        ask={onAsk} question={firId ? null : "What happened in this case?"} />;
    }
  }

  if (view === "board") {
    title = t("Investigation board");
    sub = t("What this investigation has established, what is still open, and what you noted. It persists across sessions and officers.");
    body = firId
      ? <Board firId={firId} onAsk={onAsk} refreshToken={boardVersion} />
      : <Prompt mark="▣" title="No case open"
          body="The board belongs to a case. Open one from the register, or ask about a FIR, and its board becomes available here."
          ask={onAsk} question={null} />;
    flush = true;
  }

  const PROV_WORD = { record: t("Record"), derived: t("Derived"), model: t("Model") } as const;

  return (
    <section className="col col-workspace" aria-label="Workspace">
      <div className="workspace">
        <div className="analysis">
          <div className="analysis-id">
            <div className="analysis-title">{title}</div>
            {sub && <div className="analysis-sub">{sub}</div>}
          </div>

          {searchBar && <div className="analysis-search">{searchBar}</div>}

          {lead && (
            <div className="analysis-lead">
              {prov && <span className={`prov prov-${prov}`}>{PROV_WORD[prov]}</span>}
              <div className="analysis-lead-n">{t(lead.headline)}</div>
              <div className="analysis-lead-m">{t(lead.measure)}</div>
            </div>
          )}

          {figs.length > 0 && (
            <div className="analysis-figs">
              {figs.map((f) => (
                <div className="analysis-fig" key={f.l}>
                  <div className="analysis-fig-n">{f.n}</div>
                  <div className="analysis-fig-l">{f.l}</div>
                </div>
              ))}
            </div>
          )}

          {next && (
            <div className="analysis-acts">
              <button className="btn btn-sm"
                onClick={() => (next!.q ? onAsk(next!.q) : setShowRegister((v) => !v))}>
                {next.label}
              </button>
            </div>
          )}
        </div>
        <div className={`stage ${flush ? "flush" : ""}`}>
          <div className="stage-inner">
            <div className="viz-enter" key={`${view}:${kind}`} style={{ height: "100%" }}>
              {body}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
