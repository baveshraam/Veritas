"use client";
import { useEffect, useState } from "react";
import { deleteBoardItem, getBoard, updateBoardItem } from "@/lib/api";
import type { BoardItem, BoardItemType, CaseBoard } from "@/lib/types";
import type { Provenance } from "@/lib/evidence";
import { PROV_LABEL } from "@/lib/evidence";

/** The persistent per-case investigation board.
 *
 *  The one rule this surface exists to enforce: an investigator's note must
 *  never be able to look like a database fact, and a finding Veritas derived
 *  must never look like something written in the FIR. Each item therefore
 *  carries the same provenance rail and glyph the evidence column uses, so the
 *  distinction is the same distinction everywhere in the console rather than a
 *  word in a badge here.
 *
 *  A dismissed lead is never deleted. It stays on the board, marked closed —
 *  "we looked at this and ruled it out" is a finding, and losing it would make
 *  the board a worse record of the investigation than the officer's notebook. */

const PROV_OF: Record<BoardItemType, Provenance> = {
  evidence: "record",
  person: "record",
  finding: "derived",
  lead: "human",
  question: "human",
  note: "human",
};

const KIND_LABEL: Record<BoardItemType, string> = {
  finding: "Derived finding",
  evidence: "Pinned record",
  person: "Person of interest",
  lead: "Investigative lead",
  question: "Open question",
  note: "Investigator note",
};

const SECTIONS: { title: string; hint: string; types: BoardItemType[] }[] = [
  { title: "Established", hint: "What this investigation has settled",
    types: ["finding", "evidence", "person"] },
  { title: "Leads", hint: "Lines of enquiry, open and closed", types: ["lead"] },
  { title: "Open questions", hint: "Still unanswered", types: ["question"] },
  { title: "Investigator notes", hint: "Written by an officer, not by the records", types: ["note"] },
];

function when(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

export default function Board({
  firId, onAsk, refreshToken,
}: { firId: string; onAsk: (q: string) => void; refreshToken: number }) {
  const [board, setBoard] = useState<CaseBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const [draftLead, setDraftLead] = useState("");

  const load = () => getBoard(firId).then(setBoard).catch((e) => setError(e.message));
  useEffect(() => { setError(null); load(); /* eslint-disable-next-line */ }, [firId, refreshToken]);

  const setStatus = async (item: BoardItem, status: string) => {
    setBusy(item.item_id);
    try { await updateBoardItem(firId, item.item_id, { status }); await load(); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(null); }
  };

  const remove = async (item: BoardItem) => {
    setBusy(item.item_id);
    try { await deleteBoardItem(firId, item.item_id); await load(); }
    catch (e: any) { setError(e.message); }
    finally { setBusy(null); }
  };

  const submitNote = () => {
    if (!draftNote.trim()) return;
    onAsk(`Add a note that ${draftNote.trim()}`);
    setDraftNote("");
  };
  const submitLead = () => {
    if (!draftLead.trim()) return;
    onAsk(`Save this as a lead: ${draftLead.trim()}`);
    setDraftLead("");
  };

  if (error && !board) {
    return (
      <div className="empty">
        <span className="empty-mark" aria-hidden>▣</span>
        <h3>This board is not available</h3>
        <p>{error}</p>
      </div>
    );
  }
  if (!board) return <div className="empty"><span className="spinner" /><p>Opening the board…</p></div>;

  const openLeads = (board.by_type.lead ?? []).filter((l) => l.status === "open").length;

  return (
    <div className="board">
      <div className="board-body">
        {error && <div className="failure" style={{ marginBottom: 12 }}><b>{error}</b></div>}

        {board.total === 0 && (
          <div className="empty" style={{ paddingTop: 40 }}>
            <span className="empty-mark" aria-hidden>▣</span>
            <h3>Nothing on this board yet</h3>
            <p>
              Ask a question about this case, then say &ldquo;pin this&rdquo; to keep the record,
              or write a note or a lead below. Everything you add stays with the case —
              across sessions, and for the next officer on it.
            </p>
          </div>
        )}

        {board.total > 0 && openLeads > 0 && (
          <div className="meta" style={{ marginBottom: 14 }}>
            {board.total} {board.total === 1 ? "item" : "items"} · {openLeads} open{" "}
            {openLeads === 1 ? "lead" : "leads"}
          </div>
        )}

        {SECTIONS.map((s) => {
          const items = s.types.flatMap((t) => board.by_type[t] ?? []);
          if (!items.length) return null;
          return (
            <section className="board-section" key={s.title}>
              <div className="board-section-head">
                <span className="label">{s.title}</span>
                <span className="board-section-n">{items.length}</span>
                <span className="meta" style={{ marginLeft: "auto", color: "var(--t-4)" }}>{s.hint}</span>
              </div>
              {items.map((it) => {
                const p = PROV_OF[it.item_type] ?? "human";
                const closed = it.item_type === "lead" && it.status && it.status !== "open";
                return (
                  <div key={it.item_id} className={`board-item rail-${p} ${closed ? "is-closed" : ""}`}>
                    <div className="board-item-head">
                      <span className={`prov prov-${p}`}>{PROV_LABEL[p]}</span>
                      <span className="meta">{KIND_LABEL[it.item_type]}</span>
                      {it.item_type === "lead" && it.status && (
                        <span className={`pill ${it.status === "open" ? "pill-open"
                          : it.status === "pursued" ? "pill-ok" : "pill-neutral"}`}>
                          {it.status}
                        </span>
                      )}
                      {it.item_type === "question" && it.status === "resolved" && (
                        <span className="pill pill-ok">resolved</span>
                      )}
                    </div>
                    <div className="board-item-body">{it.content}</div>
                    {it.reason && (
                      <div className="board-reason"><b>Reason:</b> {it.reason}</div>
                    )}
                    <div className="board-item-foot">
                      <span className="board-item-who">
                        {it.created_by ? `${it.created_by} · ` : ""}{when(it.created_at)}
                        {it.confidence != null && ` · ${(it.confidence * 100).toFixed(0)}% support at pinning`}
                      </span>
                      <div className="board-item-acts">
                        {it.item_type === "lead" && it.status === "open" && (
                          <>
                            <button className="btn btn-sm" disabled={busy === it.item_id}
                              onClick={() => setStatus(it, "pursued")}>Mark pursued</button>
                            <button className="btn btn-sm" disabled={busy === it.item_id}
                              onClick={() => setStatus(it, "dismissed")}>Dismiss</button>
                          </>
                        )}
                        {it.item_type === "lead" && it.status !== "open" && (
                          <button className="btn btn-sm" disabled={busy === it.item_id}
                            onClick={() => setStatus(it, "open")}>Reopen</button>
                        )}
                        {it.item_type === "question" && it.status !== "resolved" && (
                          <button className="btn btn-sm" disabled={busy === it.item_id}
                            onClick={() => setStatus(it, "resolved")}>Mark resolved</button>
                        )}
                        {/* A lead cannot be removed — retiring one is a status
                            change, so the board stays auditable. */}
                        {it.item_type !== "lead" && (
                          <button className="btn btn-sm btn-danger" disabled={busy === it.item_id}
                            onClick={() => remove(it)}>Remove</button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>

      <div className="board-compose">
        <div className="board-compose-row">
          <input className="field" placeholder="Write a note…" value={draftNote}
            aria-label="Write an investigator note"
            onChange={(e) => setDraftNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitNote()} />
          <button className="btn" disabled={!draftNote.trim()} onClick={submitNote}>Add note</button>
        </div>
        <div className="board-compose-row">
          <input className="field" placeholder="Record a lead…" value={draftLead}
            aria-label="Record an investigative lead"
            onChange={(e) => setDraftLead(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitLead()} />
          <button className="btn" disabled={!draftLead.trim()} onClick={submitLead}>Save lead</button>
        </div>
      </div>
    </div>
  );
}
