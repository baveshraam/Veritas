import type {
  BoardItem, BoardItemType, CaseBoard, CaseDetail, CaseIndex, CopilotBrief, Derivation,
  EvidenceItem, FinalEvent, Officer, PersonDetail, SearchHit, SessionSummary, TimelineEvent,
  TimelineResult, TraceEntry, Turn,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let token: string | null = null;
export function setToken(t: string | null) {
  token = t;
  if (typeof window !== "undefined") {
    t ? localStorage.setItem("veritas_token", t) : localStorage.removeItem("veritas_token");
  }
}
export function loadToken(): string | null {
  if (token) return token;
  if (typeof window !== "undefined") token = localStorage.getItem("veritas_token");
  return token;
}

function authHeaders(): Record<string, string> {
  const t = loadToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export async function listOfficers(): Promise<Officer[]> {
  const r = await fetch(`${BASE}/auth/officers`);
  if (!r.ok) throw new Error("Cannot reach the Veritas API");
  return r.json();
}

export type Health = {
  api: string; llm: string; datastore: string; firs: number;
  graph_nodes: number; graph_edges: number; indexed_documents: number;
};

/** Powers the status readout in the command bar. What is loaded is a fact about the
 *  answers this console can give, so it belongs on screen rather than in a log. */
export async function getHealth(): Promise<Health> {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error("unhealthy");
  return r.json();
}

export async function login(badge_no: string): Promise<{ officer: Officer }> {
  const r = await fetch(`${BASE}/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ badge_no }),
  });
  if (!r.ok) throw new Error("Sign-in failed");
  const data = await r.json();
  setToken(data.access_token);
  return data;
}

/**
 * POST /chat and parse the SSE stream.
 *
 * Uses fetch + a manual SSE reader rather than EventSource, because EventSource
 * cannot send an Authorization header or a POST body — and officer identity comes
 * from the bearer token, never from the URL.
 */
export async function streamChat(
  sessionId: string,
  input: { query?: string; audio?: string; respondWithVoice?: boolean; activeEvidenceId?: string | null },
  language: "en" | "kn",
  onTrace: (t: TraceEntry) => void,
  onFinal: (f: FinalEvent) => void,
  onAudio?: (base64: string) => void,
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({
      session_id: sessionId,
      language,
      ...(input.audio
        ? { audio: input.audio, respond_with_voice: !!input.respondWithVoice }
        : { query: input.query }),
      // Which evidence card was selected when the officer said "pin this" — lets
      // BOARD_PIN_EVIDENCE pin exactly what was in view instead of guessing at the
      // previous turn's top citation.
      ...(input.activeEvidenceId ? { active_evidence_id: input.activeEvidenceId } : {}),
    }),
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed (${res.status})`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    // Normalise CRLF first. sse-starlette terminates frames with "\r\n\r\n", so
    // splitting on "\n\n" matches nothing, every frame stays buffered, and the
    // stream ends having emitted no events at all — a silently empty answer.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    // A frame can arrive split across chunks: consume only complete ones and keep
    // the remainder buffered.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let evt: any;
      try {
        evt = JSON.parse(payload);
      } catch {
        continue;                       // keep-alive / non-JSON frame
      }
      if (evt.type === "trace") onTrace(evt as TraceEntry);
      else if (evt.type === "final") onFinal(evt as FinalEvent);
      else if (evt.type === "audio") onAudio?.(evt.data as string);
      // The engine failed. Surface it: an ignored error event leaves the console
      // spinning on keep-alive pings with no answer and no explanation.
      // The API sends `detail` (the exception type and message) alongside `message`.
      // Dropping it left the console reporting only that something failed, which is
      // the one thing the officer could already see.
      else if (evt.type === "error")
        throw new Error([evt.message ?? "Investigation failed", evt.detail].filter(Boolean).join(" — "));
    }
  }
}

/**
 * GET /alerts and parse the SSE stream of district anomaly alerts.
 *
 * Same fetch + manual SSE reader as streamChat, for the same reason: neither
 * EventSource nor WebSocket can set an Authorization header, and — for
 * WebSocket specifically — live checks against the deployed AppSail gateway
 * (BUG-005) found it does not appear to proxy WebSocket upgrades to a
 * custom-runtime app at all. This transport is the one already proven live
 * for /chat on this exact deployment.
 *
 * Returns an abort function; call it on unmount to stop the stream.
 */
export function streamAlerts(
  onAlert: (a: any, kind: "alert" | "series") => void,
  onError?: () => void,
): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/alerts`, { headers: authHeaders(), signal: controller.signal });
      if (!res.ok || !res.body) throw new Error(`Alerts stream failed (${res.status})`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const lines = frame.split("\n");
          const eventLine = lines.find((l) => l.startsWith("event:"));
          const dataLine = lines.find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          const payload = dataLine.slice(5).trim();
          if (!payload) continue;
          // Two event kinds share this one stream: district-anomaly alerts (the
          // original feed) and cross-station series discoveries. Untyped frames
          // (SSE's own keep-alive comments, or an older server) default to "alert"
          // so existing behaviour is unchanged if the event: line is ever absent.
          const kind = eventLine?.slice(6).trim() === "series" ? "series" : "alert";
          try {
            onAlert(JSON.parse(payload), kind);
          } catch {
            /* keep-alive / non-JSON frame */
          }
        }
      }
    } catch (e) {
      if ((e as any)?.name !== "AbortError") onError?.();
    }
  })();

  return () => controller.abort();
}

export async function listCases(
  filter: { q?: string; crime_type?: string; case_status?: string },
): Promise<CaseIndex> {
  const qs = new URLSearchParams(
    Object.entries(filter).filter(([, v]) => v) as [string, string][],
  );
  const r = await fetch(`${BASE}/cases?${qs}`, { headers: authHeaders() });
  if (!r.ok) throw new Error("Cannot load the case index");
  return r.json();
}

/** One case, in full: its own columns plus the accused, the victims and the IPC
 *  sections — all already masked by rank server-side. The Overview reads this;
 *  nothing here is a second copy of the record. */
export async function getFir(firId: string): Promise<CaseDetail> {
  const r = await fetch(`${BASE}/fir/${firId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(
    r.status === 404 ? "This case is not in the records"
    : r.status === 403 ? "This case was filed at another police station"
    : "The case record could not be loaded");
  return r.json();
}

/** One reconstructed person. The Overview reads this only to answer a question
 *  the case file cannot: the file records "Suma Nadkarni D/o Eshwar" while every
 *  derived surface calls the same PersonUID "Soom Nadkarni". Both are true — one
 *  is as-filed, one is the identity Fellegi-Sunter resolved — and showing them
 *  apart with nothing linking them is how an officer concludes there are two
 *  people. */
export async function getPerson(personId: string): Promise<PersonDetail> {
  const r = await fetch(`${BASE}/person/${personId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error("Person not found");
  return r.json();
}

export async function getCopilotBrief(firId: string): Promise<CopilotBrief> {
  const r = await fetch(`${BASE}/copilot/${firId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(r.status === 404 ? "FIR not found" : "Copilot brief failed");
  return r.json();
}

/** The persistent per-case investigation board. Reads and precise per-item actions
 *  (a lead's status button, a delete) go through these — free-text board commands
 *  ("pin this", "add a note that…") go through /chat instead, so both paths share
 *  exactly one server-side implementation (rag_agent.board). */
export async function getBoard(firId: string): Promise<CaseBoard> {
  const r = await fetch(`${BASE}/board/${firId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(
    r.status === 404 ? "Case not found"
    : r.status === 403 ? "This case's board is outside your access scope"
    : "Board unavailable");
  return r.json();
}

export async function createBoardItem(firId: string, body: {
  item_type: BoardItemType; content: string; ref_type?: string | null; ref_id?: string | null;
  confidence?: number | null; status?: string | null;
}): Promise<BoardItem> {
  const r = await fetch(`${BASE}/board/${firId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("Could not add to the board");
  return r.json();
}

export async function updateBoardItem(firId: string, itemId: string, body: {
  status?: string | null; reason?: string | null; content?: string | null;
}): Promise<BoardItem> {
  const r = await fetch(`${BASE}/board/${firId}/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("Could not update that board item");
  return r.json();
}

/** The cross-entity timeline (docs/INDUSTRY_GAP_ANALYSIS.md §7 item 3), reachable
 *  directly (this) as well as via /chat's TIMELINE/TIMELINE_CONNECTION intents —
 *  the Copilot overlay's Timeline tab always wants the FULL case timeline, not
 *  whatever a chat turn happened to filter. */
export async function getCaseTimeline(firId: string): Promise<TimelineResult> {
  const r = await fetch(`${BASE}/timeline/case/${firId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(
    r.status === 404 ? "Case not found"
    : r.status === 403 ? "This case's timeline is outside your access scope"
    : "Timeline unavailable");
  return r.json();
}

export async function getPersonTimeline(personId: string): Promise<TimelineResult> {
  const r = await fetch(`${BASE}/timeline/person/${personId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(r.status === 404 ? "Person not found" : "Timeline unavailable");
  return r.json();
}

/** The exact evidence_id a chat-driven timeline event was cited under
 *  (rag_agent/orchestrator.py:_timeline_evidence) — reconstructed client-side so a
 *  click on an event card can select/pin it through the same EvidenceRail
 *  mechanism every other evidence item already uses, with no server round trip. */
export function timelineEvidenceId(e: TimelineEvent): string {
  return `timeline:${e.event_type}:${e.entity_id}:${e.date}`;
}

/** The one search box — GET /search.
 *
 *  Distinct from `listCases({q})`, which filters the browsable register. This is
 *  ranked and typed: cases and people together, each hit carrying the fields that
 *  actually matched it. The register's own `q` matched the WHOLE query inside ONE
 *  field, so "theft mandya" found nothing at all. */
export async function searchRecords(q: string, limit = 20): Promise<SearchHit[]> {
  const r = await fetch(`${BASE}/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    { headers: authHeaders() });
  if (!r.ok) throw new Error("Search is unavailable");
  return (await r.json()).hits as SearchHit[];
}

/** "Why is this here?" for one result — GET /explain.
 *
 *  The REST half of the same question the copilot answers when it is typed
 *  ("why is this person connected?"). Both call rag_agent.provenance.explain, so a
 *  result explained by clicking and the same result explained by asking are one
 *  explanation shown twice.
 *
 *  `sessionId` is what lets the server say why THIS case, of ten thousand, is on
 *  screen — the same FIR is there for a different reason depending on whether it was
 *  looked up by number, matched a filter, or was ranked as similar to another case. */
export async function explainEvidence(
  evidenceId: string, sessionId?: string,
): Promise<Derivation> {
  const q = new URLSearchParams({ evidence_id: evidenceId });
  if (sessionId) q.set("session_id", sessionId);
  const r = await fetch(`${BASE}/explain?${q}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(
    r.status === 403 ? "That result is outside your access scope"
    : "Could not reconstruct where this came from");
  return r.json();
}

export async function deleteBoardItem(firId: string, itemId: string): Promise<void> {
  const r = await fetch(`${BASE}/board/${firId}/items/${itemId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!r.ok) throw new Error("Could not remove that board item");
}

/** Returns whether a real PDF was produced — a 200 with an HTML body (the
 *  SmartBrowz/local-renderer fallback, see BUG-018) is not a failure the caller
 *  should swallow silently, since "Export PDF" said PDF. */
export async function exportPdf(sessionId: string): Promise<boolean> {
  const r = await fetch(`${BASE}/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!r.ok) throw new Error("Export failed");
  const blob = await r.blob();
  const isPdf = blob.type.includes("pdf");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `veritas-${sessionId.slice(0, 8)}.${isPdf ? "pdf" : "html"}`;
  a.click();
  URL.revokeObjectURL(url);
  return isPdf;
}

/** GET /sessions — chat history, pooled by rank+station rather than by the
 *  individual officer signed in right now (see lib/types.ts's Officer). */
export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${BASE}/sessions`, { headers: authHeaders() });
  if (!r.ok) throw new Error("Could not load chat history");
  return r.json();
}

/** GET /sessions/{id} — the full turn history of one past session, reconstructed
 *  into the same `Turn[]` shape the console renders live. Whether a turn was a
 *  refusal isn't persisted server-side, so a reloaded turn always renders as a
 *  plain finding rather than reconstructing that exact banner. */
export async function loadSession(sessionId: string): Promise<Turn[]> {
  const r = await fetch(`${BASE}/sessions/${sessionId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(
    r.status === 403 ? "That session belongs to a different rank or station"
    : r.status === 404 ? "That session no longer exists"
    : "Could not load that session");
  const turns: any[] = await r.json();
  return turns.map((t) => ({
    id: `${sessionId}-${t.turn_index}`,
    query: t.query,
    answer: t.final_answer,
    streaming: false,
    refused: false,
    trace: t.agent_trace ?? [],
    citations: t.citations ?? [],
    evidence: (t.evidence_items ?? []).filter((e: any) => e.content),
    visualization: t.visualization?.kind ? t.visualization : { kind: "none", data: {} },
  }));
}

export async function attachFile(file: File): Promise<{ filename: string; text: string; truncated: boolean }> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`${BASE}/attach`, { method: "POST", headers: authHeaders(), body: form });
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail ?? "Could not read this file");
  return r.json();
}

/** How well corroborated a piece of evidence is.
 *
 *  This used to route confidence through the SEVERITY ramp, which inverted its
 *  meaning on screen: a 100%-confidence record — the strongest thing the retrieval
 *  found — rendered in the same crimson used for a high-risk hotspot, so the best
 *  evidence looked like the most alarming. Confidence is its own dimension and reads
 *  the intuitive way now: strong is green, weak is red. */
export function confidenceBand(confidence: number): "strong" | "fair" | "weak" {
  if (confidence >= 0.75) return "strong";
  if (confidence >= 0.45) return "fair";
  return "weak";
}

/** What the chip should say, and whether the number even belongs on it.
 *  "support": a real evidential-strength band ("87% strong"). "similarity": labeled
 *  as text similarity, never as trust in the claim (BUG-011). "model_estimate": the
 *  model's own reported number already appears in the evidence body — showing a
 *  second, different-meaning percentage here would just be a second unlabeled
 *  number, so this kind gets a plain tag instead of a percentage. */
export function confidenceLabel(kind: EvidenceItem["confidence_kind"]): string {
  if (kind === "similarity") return "text similarity";
  if (kind === "model_estimate") return "model output";
  return "evidence strength";
}

export function evidenceFor(e: EvidenceItem): string {
  return e.source_type.replace(/_/g, " ").toLowerCase();
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve((r.result as string).split(",")[1]);
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

/** Decodes base64 speech audio and plays it. Errors are swallowed — voice
 * playback is an enhancement, never something a turn can fail on. */
export function playBase64Audio(base64: string): void {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play().catch(() => URL.revokeObjectURL(url));
}

/* ── /analytics ───────────────────────────────────────────────────────────────
 *
 * The workspace's analytical tabs, read straight from the records rather than
 * synthesised by the conversational engine. These are the same policy-scoped
 * queries /chat runs for the same questions; what changes is only that a TAB no
 * longer has to ask a QUESTION to fill itself. See apps/api/api/routers/analytics.py
 * for why that distinction is worth a second surface.
 *
 * The chat path is unaffected: a typed question still produces its own answer,
 * its own citations and its own visualization, and still wins over the tab's
 * default whenever it has produced one (Workspace.tsx). */

export type Counted = { name: string; cases: number };

export type Statistics = {
  total: number;
  scope: { district: string | null; crime_type: string | null };
  status: Counted[]; crime_type: Counted[]; district: Counted[];
  station: Counted[]; monthly: Counted[];
  conviction: { convicted: number; decided: number; rate: number | null };
};

export type OffenderRow = {
  person_id: string; name: string; cases: number;
  habitual: boolean; community: number | null;
};

export type HotspotPayload = {
  district: string | null; district_code: string | null;
  polygons: any[]; fir_points: any[];
};

export type AreaProfile = {
  district: string | null; total: number; mix: Counted[]; status: Counted[];
  census: Record<string, number> | null;
};

export type CommunityProfile = {
  community_id: number | null; defaulted?: boolean;
  profile: { case_count: number; top_crime_type: string | null } | null;
  members: { person_id: string; name: string; influence: number }[];
};

export type WatchlistRow = {
  txn_id: string; src: string; dst: string; amount: number; date: string | null;
  fir_id: string | null; flag_type: string; detector: "rule" | "gnn"; confidence: number;
};

export type Watchlist = {
  total: number; rule: number; gnn: number; transactions: WatchlistRow[];
};

export type StationRow = {
  ps_code: string; station: string; open_cases: number;
  avg_age_days: number; stalled_count: number; stalled_ids: string[];
};

export type Workload = {
  stale_days: number; open_cases: number; stalled: number; stations: StationRow[];
};

async function analytics<T>(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
  }
  const r = await fetch(`${BASE}/analytics/${path}${qs.toString() ? `?${qs}` : ""}`,
                        { headers: authHeaders() });
  // One message per failure mode an officer can act on. A 401 here means the
  // rank was entered without a verified badge (LoginGate) — saying "unavailable"
  // would read as the platform being down.
  if (!r.ok) throw new Error(
    r.status === 401 ? "Sign in with a verified badge to load this analysis"
    : r.status === 403 ? "Your rank is not cleared for this analysis"
    : "This analysis could not be loaded from the records");
  return r.json();
}

export const getStatistics = (district?: string | null, crimeType?: string | null) =>
  analytics<Statistics>("statistics", { district, crime_type: crimeType });

export const getOffenders = (opts: { district?: string | null; habitual?: boolean; limit?: number; q?: string | null } = {}) =>
  analytics<{ offenders: OffenderRow[] }>("offenders",
    { district: opts.district, habitual: opts.habitual, limit: opts.q ? Math.max(opts.limit ?? 20, 50) : (opts.limit ?? 20), q: opts.q });

export const getHotspots = (district?: string | null) =>
  analytics<HotspotPayload>("hotspots", { district });

export const getForecastSeries = (district?: string | null, horizon = 30) =>
  analytics<{ district: string | null; reconciled: boolean; series: [string, number, number, number][] }>(
    "forecast", { district, horizon });

export const getAreaProfile = (district?: string | null) =>
  analytics<AreaProfile>("area", { district });

export const getCommunity = (opts: { id?: number | null; personId?: string | null } = {}) =>
  analytics<CommunityProfile>("community", { id: opts.id, person_id: opts.personId });

export const getWatchlist = (limit = 25) => analytics<Watchlist>("watchlist", { limit });

export const getWorkload = () => analytics<Workload>("workload");
