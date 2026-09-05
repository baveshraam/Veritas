"""`data.cache` must reflect the CURRENT Catalyst SDK binding on every call, not
whichever one happened to exist the first time it ran.

Real live bug: `_segment()` independently called `zcatalyst_sdk.initialize()` and
memoized the result forever (`@lru_cache(maxsize=1)`). The SDK's context is
thread-scoped (CLAUDE.md's "per-request headers, not environment variables" gotcha),
so `/jobs/refresh`'s background thread — which explicitly rebinds `ds._sdk_app` for
exactly this reason, the same way it already does for Data Store queries — had no
effect on the cache: whatever thread called `_segment()` FIRST in the process's
lifetime locked in that thread's (possibly now-stale) client for every future caller,
on every thread, for the rest of the container's life. A background step's cache
write then silently no-opped (`put`'s own `except Exception` swallows a client that
can't authenticate), which is why the fused advisory (STRATEGIC_RESET Part 9, Item 2)
and the Aequitas audit (Item 1) never populated `/health` despite the refresh job
completing live.
"""
from data import cache


class _FakeSegment:
    def __init__(self, store: dict):
        self._store = store

    def get(self, key):
        return self._store.get(key)

    def put(self, key, value, expiry=None):
        self._store[key] = value

    def delete(self, key):
        self._store.pop(key, None)


class _FakeApp:
    def __init__(self, segment):
        self._segment = segment

    def cache(self):
        return self

    def segment(self, name):
        return self._segment


def test_segment_is_not_memoized_across_calls(monkeypatch):
    """The exact live failure: a background thread rebinds `ds.catalyst_app()` to a
    fresh app instance, and `data.cache` must pick that up on its very next call —
    not keep answering with whatever the first-ever caller got."""
    from data import ds

    first = _FakeApp(_FakeSegment({}))
    monkeypatch.setattr(ds, "catalyst_app", lambda: first)
    assert cache._segment() is first._segment

    second = _FakeApp(_FakeSegment({}))
    monkeypatch.setattr(ds, "catalyst_app", lambda: second)
    assert cache._segment() is second._segment, (
        "a rebound app object (the background-thread case) must be reflected "
        "immediately — memoizing the first segment forever silently strands "
        "every later cache write on a stale, likely-unauthenticated client")


def test_a_write_after_rebinding_reads_back_correctly(monkeypatch):
    """End-to-end: write happens on the ORIGINAL binding, a background thread
    rebinds, and a read must still see what the write actually stored — proving
    both go through the same live segment, not two different frozen ones."""
    from data import ds

    store: dict = {}
    app = _FakeApp(_FakeSegment(store))
    monkeypatch.setattr(ds, "catalyst_app", lambda: app)

    cache.put("k", {"flagged": True})
    assert cache.get("k") == {"flagged": True}

    # Simulate the background thread's rebind to a NEW app instance pointed at
    # the SAME real Catalyst segment (a fresh SDK client, not a fresh backing store).
    monkeypatch.setattr(ds, "catalyst_app", lambda: _FakeApp(_FakeSegment(store)))
    assert cache.get("k") == {"flagged": True}


def test_falls_back_to_the_local_dict_when_catalyst_is_unavailable(monkeypatch):
    """Local dev/tests (sqlite backend, no zcatalyst_sdk installed) must keep
    working exactly as before — `_segment()` returning None is not itself the bug."""
    from data import ds

    def _boom():
        raise ImportError("zcatalyst_sdk not installed")
    monkeypatch.setattr(ds, "catalyst_app", _boom)

    assert cache._segment() is None
    cache.put("local-key", "value")
    assert cache.get("local-key") == "value"
