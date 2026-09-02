"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { searchRecords } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type { SearchHit, SessionFocusView } from "@/lib/types";

type Row = {
  kind: "case" | "person" | "action";
  id: string;
  /** What the row IS, in the officer's language. */
  title: string;
  /** Where or what kind — the second line of meaning. */
  where?: string;
  /** The identifier, set in mono and placed last. A register is searched by
   *  crime and place far more often than by an 18-digit number, and leading
   *  with the number makes every row look identical at a glance. */
  ident?: string;
  sub: string;
  /** Which fields actually matched. A ranked list whose ordering cannot be
   *  explained is one an officer learns to distrust. */
  why?: string[];
  run: () => void;
};

/** ⌘K — one entry point to every case and every action.
 *
 *  Search runs through `GET /search` — ranked and typed, cases and people
 *  together, scoped by rank exactly as the register is. It replaces a filter that
 *  tested whether the WHOLE query appeared inside ONE field, so "theft mandya"
 *  matched nothing at all while the register held sixty-one of them; a person
 *  could not be found here at all, and neither could a section or a station.
 *
 *  Every hit says WHY it matched. Ranked results whose ordering cannot be
 *  explained are results an officer learns to scroll past.
 *
 *  The actions below are the ones this console genuinely performs. Nothing here
 *  is a shortcut to a capability that does not exist. */
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
  const t = useT();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) { setQ(""); setSel(0); setHits([]); setTimeout(() => inputRef.current?.focus(), 10); }
  }, [open]);

  useEffect(() => {
    if (!open || q.trim().length < 2) { setHits([]); setSearching(false); return; }
    setSearching(true);
    // A stale response must never overwrite a fresher one: typing "mandya" fires
    // six requests and they do not necessarily come back in order.
    let live = true;
    const t = setTimeout(() => {
      searchRecords(q.trim(), 8)
        .then((h) => { if (live) { setHits(h); setSearching(false); } })
        .catch(() => { if (live) { setHits([]); setSearching(false); } });
    }, 160);
    return () => { live = false; clearTimeout(t); };
  }, [q, open]);

  const firId = focus?.case?.fir_id;
  const person = focus?.person?.name;

  const rows = useMemo<Row[]>(() => {
    const go = (fn: () => void) => () => { fn(); onClose(); };
    const hitRows: Row[] = hits.map((h) => ({
      kind: h.kind,
      id: h.id,
      title: h.title,
      where: h.subtitle,
      ident: h.ident,
      why: h.why,
      sub: h.kind === "person" ? t("Person") : t("Case"),
      // Opening a hit asks the question that hit answers — a case by its number,
      // a person by their history — rather than dumping the row somewhere.
      run: go(() => onAsk(h.kind === "person"
        ? `Does ${h.title} have priors?`
        : `What is the status of FIR ${h.ident}?`)),
    }));

    const actions: Row[] = [
      { kind: "action", id: "hotspots", title: t("Show crime hotspots"), sub: t("Geography"), run: go(() => onAsk("Show me crime hotspots")) },
      { kind: "action", id: "trend", title: t("Show crime trends"), sub: t("Forecast"), run: go(() => onAsk("What are the crime trends?")) },
      ...(person ? [
        { kind: "action" as const, id: "assoc", title: t("Show the network around {name}", { name: person }), sub: t("Network"),
          run: go(() => onAsk(`Who are the associates of ${person}?`)) },
        { kind: "action" as const, id: "priors", title: t("Check whether {name} has priors", { name: person }), sub: t("Person history"),
          run: go(() => onAsk(`Does ${person} have priors?`)) },
      ] : []),
      ...(firId ? [
        { kind: "action" as const, id: "board", title: t("Open this case's investigation board"), sub: t("Board"),
          run: go(() => onBoard(firId)) },
        { kind: "action" as const, id: "brief", title: t("Open this case's briefing"), sub: t("Briefing"),
          run: go(() => onCopilot(firId)) },
        { kind: "action" as const, id: "next", title: t("What should I investigate next?"), sub: t("Next steps"),
          run: go(() => onAsk("What should I investigate next?")) },
      ] : []),
      { kind: "action", id: "lang", title: t(language === "en" ? "Answer in Kannada" : "Answer in English"),
        sub: t("Language"), run: go(() => onLanguage(language === "en" ? "kn" : "en")) },
      ...(canExport ? [{ kind: "action" as const, id: "export", title: t("Export this session"), sub: t("PDF"), run: go(onExport) }] : []),
    ];

    const needle = q.trim().toLowerCase();
    const matched = needle
      ? actions.filter((a) => a.title.toLowerCase().includes(needle) || a.sub.toLowerCase().includes(needle))
      : actions;

    return [...hitRows, ...matched];
  }, [hits, q, firId, person, language, canExport, onAsk, onBoard, onCopilot, onExport, onLanguage, onClose, t]);

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
      <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t("Command palette")}>
        <input
          ref={inputRef}
          className="palette-input"
          value={q}
          placeholder={t("FIR number, crime, district, station, section, MO, or a name…")}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={key}
          aria-label={t("Search records and actions")}
        />
        <div className="palette-list">
          {searching && rows.length === 0 && (
            <div className="palette-empty">{t("Searching the register…")}</div>
          )}
          {!searching && rows.length === 0 && (
            <div className="palette-empty">
              {t("No record matches every word of “{q}”. Press Enter to ask it as a question instead.", { q: q.trim() })}
            </div>
          )}
          {rows.map((r, i) => (
            <div key={r.kind + r.id}>
              {i === 0 && r.kind !== "action" && <div className="palette-group label">{t("Records")}</div>}
              {i === firstAction && <div className="palette-group label">{t("Actions")}</div>}
              <button
                className={`palette-item ${i === sel ? "on" : ""}`}
                onMouseEnter={() => setSel(i)}
                onClick={r.run}
              >
                <span className="palette-item-main">
                  <span className="palette-item-title">{r.title}</span>
                  <span className="palette-item-where">
                    {r.where}
                    {r.why && r.why.length > 0 && (
                      <>{r.where ? " · " : ""}
                        <span className="palette-why">{t("matched")} {r.why.join(", ")}</span>
                      </>
                    )}
                  </span>
                </span>
                {r.ident && <span className="mono palette-item-id">{r.ident}</span>}
                <span className="palette-item-sub">{r.sub}</span>
              </button>
            </div>
          ))}
        </div>
        <div className="palette-foot">
          <span><kbd>↑↓</kbd>{t("navigate")}</span>
          <span><kbd>⏎</kbd>{t("open")}</span>
          <span><kbd>esc</kbd>{t("close")}</span>
        </div>
      </div>
    </div>
  );
}
