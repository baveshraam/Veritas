"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { listCases } from "@/lib/api";
import type { CaseRow, SessionFocusView } from "@/lib/types";

type Row =
  | { kind: "case"; id: string; title: string; sub: string; run: () => void }
  | { kind: "action"; id: string; title: string; sub: string; run: () => void };

/** ⌘K — one entry point to every case and every action.
 *
 *  Search is over the case register (the same `/cases` endpoint the register
 *  uses, so it is scoped by rank exactly as the register is) plus the actions
 *  this console genuinely performs. Nothing here is a shortcut to a capability
 *  that does not exist. */
export default function CommandPalette({
  open, onClose, onAsk, onCopilot, onBoard, onExport, canExport, onLanguage, language, focus,
}: {
  open: boolean;
  onClose: () => void;
  onAsk: (q: string) => void;
  onCopilot: (firId: string) => void;
  onBoard: (firId: string) => void;
  onExport: () => void;
  canExport: boolean;
  onLanguage: (l: "en" | "kn") => void;
  language: "en" | "kn";
  focus?: SessionFocusView;
}) {
  const [q, setQ] = useState("");
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) { setQ(""); setSel(0); setCases([]); setTimeout(() => inputRef.current?.focus(), 10); }
  }, [open]);

  useEffect(() => {
    if (!open || q.trim().length < 2) { setCases([]); return; }
    const t = setTimeout(() => {
      listCases({ q: q.trim() }).then((i) => setCases(i.cases.slice(0, 6))).catch(() => setCases([]));
    }, 180);
    return () => clearTimeout(t);
  }, [q, open]);

  const firId = focus?.case?.fir_id;
  const person = focus?.person?.name;

  const rows = useMemo<Row[]>(() => {
    const go = (fn: () => void) => () => { fn(); onClose(); };
    const caseRows: Row[] = cases.map((c) => ({
      kind: "case" as const,
      id: c.fir_id,
      title: c.fir_number,
      sub: `${c.crime_type} · ${c.district}`,
      run: go(() => onAsk(`What is the status of FIR ${c.fir_number}?`)),
    }));

    const actions: Row[] = [
      { kind: "action", id: "hotspots", title: "Show crime hotspots", sub: "Geography", run: go(() => onAsk("Show me crime hotspots")) },
      { kind: "action", id: "trend", title: "Show crime trends", sub: "Forecast", run: go(() => onAsk("What are the crime trends?")) },
      ...(person ? [
        { kind: "action" as const, id: "assoc", title: `Show the network around ${person}`, sub: "Network",
          run: go(() => onAsk(`Who are the associates of ${person}?`)) },
        { kind: "action" as const, id: "priors", title: `Check whether ${person} has priors`, sub: "Person history",
          run: go(() => onAsk(`Does ${person} have priors?`)) },
      ] : []),
      ...(firId ? [
        { kind: "action" as const, id: "board", title: "Open this case's investigation board", sub: "Board",
          run: go(() => onBoard(firId)) },
        { kind: "action" as const, id: "brief", title: "Open this case's briefing", sub: "Briefing",
          run: go(() => onCopilot(firId)) },
        { kind: "action" as const, id: "next", title: "What should I investigate next?", sub: "Next steps",
          run: go(() => onAsk("What should I investigate next?")) },
      ] : []),
      { kind: "action", id: "lang", title: language === "en" ? "Answer in Kannada" : "Answer in English",
        sub: "Language", run: go(() => onLanguage(language === "en" ? "kn" : "en")) },
      ...(canExport ? [{ kind: "action" as const, id: "export", title: "Export this session", sub: "PDF", run: go(onExport) }] : []),
    ];

    const needle = q.trim().toLowerCase();
    const matched = needle
      ? actions.filter((a) => a.title.toLowerCase().includes(needle) || a.sub.toLowerCase().includes(needle))
      : actions;

    return [...caseRows, ...matched];
  }, [cases, q, firId, person, language, canExport, onAsk, onBoard, onCopilot, onExport, onLanguage, onClose]);

  useEffect(() => { setSel((s) => Math.min(s, Math.max(0, rows.length - 1))); }, [rows.length]);

  if (!open) return null;

  const key = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { onClose(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => (s + 1) % Math.max(1, rows.length)); }
    if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => (s - 1 + rows.length) % Math.max(1, rows.length)); }
    if (e.key === "Enter") {
      e.preventDefault();
      if (rows[sel]) rows[sel].run();
      else if (q.trim()) { onAsk(q.trim()); onClose(); }
    }
  };

  const firstAction = rows.findIndex((r) => r.kind === "action");

  return (
    <div className="palette-scrim" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <input
          ref={inputRef}
          className="palette-input"
          value={q}
          placeholder="Search cases and actions, or type a question…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={key}
          aria-label="Search cases and actions"
        />
        <div className="palette-list">
          {rows.length === 0 && (
            <div className="palette-empty">
              Nothing matches. Press Enter to ask &ldquo;{q.trim()}&rdquo; as a question.
            </div>
          )}
          {rows.map((r, i) => (
            <div key={r.kind + r.id}>
              {i === 0 && r.kind === "case" && <div className="palette-group label">Cases</div>}
              {i === firstAction && <div className="palette-group label">Actions</div>}
              <button
                className={`palette-item ${i === sel ? "on" : ""}`}
                onMouseEnter={() => setSel(i)}
                onClick={r.run}
              >
                <span className={r.kind === "case" ? "mono" : ""} style={r.kind === "case" ? { color: "var(--t-1)" } : undefined}>
                  {r.title}
                </span>
                <span className="palette-item-sub">{r.sub}</span>
              </button>
            </div>
          ))}
        </div>
        <div className="palette-foot">
          <span><kbd>↑↓</kbd>navigate</span>
          <span><kbd>⏎</kbd>open</span>
          <span><kbd>esc</kbd>close</span>
        </div>
      </div>
    </div>
  );
}
