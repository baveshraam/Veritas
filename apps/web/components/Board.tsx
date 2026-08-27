"use client";
import { useEffect, useState } from "react";
import { deleteBoardItem, getBoard, updateBoardItem } from "@/lib/api";
import type { BoardItem, BoardItemType, CaseBoard } from "@/lib/types";

const SECTIONS: { key: BoardItemType; label: string; hint: string }[] = [
  { key: "finding", label: "Established findings", hint: "derived" },
  { key: "evidence", label: "Pinned evidence", hint: "record" },
  { key: "person", label: "People in this investigation", hint: "record" },
  { key: "lead", label: "Leads", hint: "" },
  { key: "question", label: "Open questions", hint: "" },
  { key: "note", label: "Investigator notes", hint: "human" },
];

const KIND_LABEL: Record<BoardItemType, string> = {
  finding: "derived finding", evidence: "pinned record", person: "pinned record",
  lead: "investigative lead", question: "open question", note: "investigator note",
};

/** The persistent per-case investigation board — pinned evidence, derived findings,
 *  people, leads, questions and the officer's own notes, kept visibly distinct
 *  (§ "never present an investigator note as a database fact"). Lives inside the
 *  same overlay Copilot already opens (see Copilot.tsx's tab switcher) rather than
 *  as a separate route, so opening a case never means choosing between "the brief"
 *  and "the board" as different destinations. */
export default function Board({
  firId, onAsk, refreshToken,
}: { firId: string; onAsk: (q: string) => void; refreshToken: number }) {
  const [board, setBoard] = useState<CaseBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [draftNote, setDraftNote] = useState("");
  const [draftLead, setDraftLead] = useState("");

  const load = () => getBoard(firId).then(setBoard).catch((e) => setError(e.message));

  useEffect(() => { setError(null); load(); }, [firId, refreshToken]);

  const setLeadStatus = async (item: BoardItem, status: string) => {
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

  if (error && !board) return <div className="msg-a refusal">{error}</div>;
  if (!board) return <div className="spinner" style={{ margin: "20px auto" }} />;

  return (
    <>
      <div className="board-summary">
        <span className="chip chip-low">
          {board.total} item{board.total === 1 ? "" : "s"} on this board
        </span>
        {error && <span className="dim" style={{ color: "var(--sev-high)" }}>{error}</span>}
      </div>

      {board.total === 0 && (
        <p className="dim">
          Nothing pinned, noted or saved as a lead yet. Ask a question, then say
          &ldquo;pin this&rdquo;, &ldquo;save this as a lead&rdquo;, or use the form below.
        </p>
      )}

      {SECTIONS.map(({ key, label }) => {
        const items = board.by_type[key] || [];
        if (!items.length) return null;
        return (
          <section key={key} className="copilot-section">
            <h3>{label}</h3>
            {items.map((it) => (
              <div key={it.item_id} className="board-item">
                <div className="board-item-head">
                  <span className={`board-kind board-kind-${it.item_type}`}>
                    {KIND_LABEL[it.item_type]}
                  </span>
                  {it.item_type === "lead" && it.status && (
                    <span className={`chip-stat ${it.status === "open" ? "open" : ""}`}>
                      {it.status}
                    </span>
                  )}
                  {it.confidence != null && (
                    <span className="dim board-confidence">
                      {(it.confidence * 100).toFixed(0)}% evidence strength
                    </span>
                  )}
                </div>
                <div className="board-item-body">{it.content}</div>
                {it.reason && <div className="dim board-reason">Reason: {it.reason}</div>}
                <div className="board-item-actions">
                  {it.item_type === "lead" && it.status === "open" && (
                    <>
                      <button className="btn btn-sm" disabled={busy === it.item_id}
                        onClick={() => setLeadStatus(it, "pursued")}>Mark pursued</button>
                      <button className="btn btn-sm" disabled={busy === it.item_id}
                        onClick={() => setLeadStatus(it, "dismissed")}>Dismiss</button>
                    </>
                  )}
                  {it.item_type === "lead" && it.status !== "open" && (
                    <button className="btn btn-sm" disabled={busy === it.item_id}
                      onClick={() => setLeadStatus(it, "open")}>Reopen</button>
                  )}
                  {it.item_type === "question" && it.status !== "resolved" && (
                    <button className="btn btn-sm" disabled={busy === it.item_id}
                      onClick={() => setLeadStatus(it, "resolved")}>Mark resolved</button>
                  )}
                  {it.item_type !== "lead" && (
                    <button className="btn btn-sm" disabled={busy === it.item_id}
                      onClick={() => remove(it)}>Remove</button>
                  )}
                </div>
              </div>
            ))}
          </section>
        );
      })}

      <section className="copilot-section">
        <h3>Add to this board</h3>
        <div className="board-add-row">
          <input className="search" placeholder="Add a note…" value={draftNote}
            onChange={(e) => setDraftNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitNote()} />
          <button className="btn btn-sm" disabled={!draftNote.trim()} onClick={submitNote}>
            Add note
          </button>
        </div>
        <div className="board-add-row">
          <input className="search" placeholder="Save a new lead…" value={draftLead}
            onChange={(e) => setDraftLead(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitLead()} />
          <button className="btn btn-sm" disabled={!draftLead.trim()} onClick={submitLead}>
            Save lead
          </button>
        </div>
        <p className="dim" style={{ marginTop: 8 }}>
          Pin evidence from the Evidence rail, or say &ldquo;add this person to the
          investigation&rdquo; after asking about someone.
        </p>
      </section>
    </>
  );
}
