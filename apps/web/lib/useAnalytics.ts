"use client";
import { useEffect, useRef, useState } from "react";

/** Load one analytical tab's data directly from the records, once, when the tab is
 *  first opened.
 *
 *  This replaces the console's old approach of firing a canned English question at
 *  the conversational engine to fill a tab. That was wrong in a way worth naming,
 *  because it is not obvious from either side on its own: a chat turn's evidence is
 *  the LAST turn's evidence, so a second tab's preload destroyed the first tab's
 *  contents — and the guard that stopped the preload re-firing then left the
 *  revisited tab empty forever. The fix is not a better guard. A tab is not a
 *  question, and it should not have to ask one.
 *
 *  `key` is what identifies the request (usually the scope: a district, a community
 *  id). The data is kept for the life of the session and only re-fetched when that
 *  key changes, so switching tabs is free and switching back is instant. `enabled`
 *  keeps the request from firing at all until the officer actually opens the tab —
 *  every one of these is a real scan of the case set, and loading seven of them on
 *  sign-in to show one would be paying for six nobody asked for.
 */
export function useAnalytics<T>(enabled: boolean, key: string, load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // The key we have already started loading. A ref, not state: putting it in the
  // dependency array would re-run this effect the moment the fetch starts, and the
  // cleanup from that re-run would discard the response that was already in flight.
  const loaded = useRef("");
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled || loaded.current === key) return;
    loaded.current = key;
    let live = true;
    setData(null);
    setError(null);
    setLoading(true);
    loadRef.current()
      .then((d) => { if (live) { setData(d); setLoading(false); } })
      .catch((e) => {
        if (!live) return;
        setError(e?.message ?? "This analysis could not be loaded");
        setLoading(false);
        // Clear the marker so revisiting the tab retries rather than showing the
        // same failure forever — a transient 401 during token refresh should not
        // permanently blank a view.
        loaded.current = "";
      });
    return () => { live = false; };
  }, [enabled, key]);

  return { data, error, loading };
}
