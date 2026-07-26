import type {
  CaseIndex, CopilotBrief, EvidenceItem, FinalEvent, Officer, TraceEntry,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_BASE = BASE.replace(/^http/, "ws");

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
  input: { query?: string; audio?: string; respondWithVoice?: boolean },
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

export async function getCopilotBrief(firId: string): Promise<CopilotBrief> {
  const r = await fetch(`${BASE}/copilot/${firId}`, { headers: authHeaders() });
  if (!r.ok) throw new Error(r.status === 404 ? "FIR not found" : "Copilot brief failed");
  return r.json();
}

export async function exportPdf(sessionId: string): Promise<void> {
  const r = await fetch(`${BASE}/export/pdf`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!r.ok) throw new Error("Export failed");
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `veritas-${sessionId.slice(0, 8)}.${blob.type.includes("pdf") ? "pdf" : "html"}`;
  a.click();
  URL.revokeObjectURL(url);
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
