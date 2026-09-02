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
 *
 *  THE PART THAT IS EASY TO GET WRONG, and which this got wrong first: there is no
 *  cleanup that cancels the in-flight request. The obvious `let live = true; return
 *  () => { live = false; }` reintroduces the exact bug this hook exists to remove.
 *  `enabled` flips to false the moment the officer clicks another tab, which re-runs
 *  the effect and fires that cleanup — so the response, when it arrives, is thrown
 *  away, while the "already started" marker stays set and blocks any re-fetch. The
 *  tab then spins forever on every later visit. Found live on Forecast, whose Prophet
 *  fit is slow enough to still be in flight when someone clicks away.
 *
 *  A result is therefore accepted whenever it still matches the key that asked for
 *  it. That is the condition that actually matters — a stale ANSWER is one for a
 *  scope nobody is looking at any more, not one that arrived while the officer was
 *  glancing at another tab. The hook lives in Workspace, which stays mounted across
 *  tab changes, so there is no unmounted-setState hazard here either.
 */
export function useAnalytics<T>(enabled: boolean, key: string, load: () => Promise<T>) {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>(
    { key: "", data: null, error: null },
  );
  const [loading, setLoading] = useState(false);
  // The key we have already STARTED loading — a ref, not state, because putting it in
  // the dependency array would re-run this effect the moment the fetch begins.
  const started = useRef("");
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled || started.current === key) return;
    started.current = key;
    setLoading(true);
    loadRef.current()
      .then((d) => {
        if (started.current !== key) return;   // the scope moved on; this answer is stale
        setState({ key, data: d, error: null });
        setLoading(false);
      })
      .catch((e) => {
        if (started.current !== key) return;
        setState({ key, data: null, error: e?.message ?? "This analysis could not be loaded" });
        setLoading(false);
        // Clear the marker so revisiting the tab retries rather than showing the same
        // failure forever — a transient 401 during token refresh should not
        // permanently blank a view.
        started.current = "";
      });
  }, [enabled, key]);

  // Only ever hand back data that belongs to the key being asked about now.
  const fresh = state.key === key;
  return {
    data: fresh ? state.data : null,
    error: fresh ? state.error : null,
    loading: loading && !fresh,
  };
}
