"""POST /jobs/refresh — the scheduled recompute, driven by Catalyst Cron.

Everything derived from the record layer goes stale the moment the record layer changes:
the graph metrics (PageRank / Louvain / betweenness), the Stratus graph blob a cold
container reads instead of paginating 136k edges, and the AML flags. None of that is
expensive enough to recompute per request, and none of it is cheap enough to.

So it is a job. Catalyst's scheduler (Cron) is what runs it — a Cron entry cannot invoke an
AppSail container directly, but it can call a URL, so the job *is* an endpoint. It is not a
public one:

  * it is not behind `current_officer`, because a scheduler has no officer;
  * so it is behind a shared secret instead (`VERITAS_JOB_TOKEN`), and it refuses to run at
    all if that secret is unset. An unauthenticated endpoint that rewrites the graph is a
    remote denial-of-service with extra steps.

Runs in the background, not inline in the request. Measured live: at the dataset's real
size the request consistently 500'd around 15-16s. Timed the three GDS algorithms locally
against the actual co-offending-projection scale (~7,000 person nodes) at 8.23s — plausibly
not the dominant cost — with the Data Store write-back (no bulk UPDATE in ZCQL; thousands of
individual row writes) and the vector reindex (13,835+ documents) as the untimed remainder.
Whichever it is, none of them belongs inside a synchronous HTTP handler: Cron only needs the
trigger call to succeed, and every long-running thing already in this codebase (the AppSail
warm-up in `main.py`) runs the same way — kicked from a request, finishing after it returns.
"""
import hmac
import logging
import os
import threading

from fastapi import APIRouter, Header, HTTPException, status

router = APIRouter()
log = logging.getLogger(__name__)

_refresh_lock = threading.Lock()
_refresh_running = False
_narrative_lock = threading.Lock()
_narrative_running = False


def _authorise(token: str | None) -> None:
    expected = os.getenv("VERITAS_JOB_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "VERITAS_JOB_TOKEN is not set; the job endpoint is disabled")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad job token")


def _run_refresh() -> None:
    global _refresh_running
    from data.embeddings.index_job import run_all as reindex
    from data.gds import run_all as run_gds
    from data.graph import publish_graph

    try:
        out: dict = {}
        # Graph metrics first: the community/PageRank values every network answer cites.
        out["gds"] = run_gds()
        # Then the Stratus blob, so a cold container reads one object instead of paging the
        # whole edge list back through ZCQL's 300-row cap.
        out["stratus_graph"] = publish_graph()
        # And the vector index, which is derived from the same record layer. Rebuilding it
        # here is what makes the deployment self-healing: an index that is missing or stale
        # is the one failure a citation-grounded system hides rather than reports —
        # retrieval simply returns nothing, confidently.
        out["vector_index"] = reindex()
        # And the AML detectors. `vx_txn.FlaggedSuspicious` is a detector OUTPUT, never
        # written by the generator (data/generator/financial.py asserts that), so on a
        # freshly seeded dataset it is false on every row until something runs the
        # models — which nothing did. The Financial Watchlist therefore reported "no
        # transaction is flagged by either detector" forever, and that answer was
        # indistinguishable from a genuine all-clear. It belongs here for the same
        # reason the vector index does: a derived layer that is missing rather than
        # stale is the failure a citation-grounded system hides instead of reporting.
        out["aml"] = _rerun_detectors()
        log.info("scheduled refresh complete: %s", out)
    except Exception:
        # A background thread's exception has nowhere else to go — log it with the
        # traceback, or a failed refresh looks identical to a slow one from the outside.
        log.exception("scheduled refresh failed")
    finally:
        with _refresh_lock:
            _refresh_running = False


def _rerun_detectors() -> dict:
    """Both AML detectors over every account, flags rewritten from scratch.

    `clear_flags()` first, deliberately: a flag is derived, and a stale one points an
    investigator at a transaction the current model no longer considers suspicious.
    Per-account because that is the unit `flag_transactions` traces a pattern over —
    structuring is a shape in one account's own activity, and the GNN needs a subgraph
    to classify. Failures are counted, not raised: one unparseable account must not
    cost the whole sweep, and a silent partial run is worse than a reported one.
    """
    from data import ds
    from data.transactions import clear_flags
    from ml_models import serving

    clear_flags()
    accounts = [str(a["AccountID"]) for a in ds.query('SELECT "AccountID" FROM "vx_account"')]
    flags = failed = 0
    for a in accounts:
        try:
            flags += len(serving.flag_transactions(a))
        except Exception:
            failed += 1
    return {"accounts": len(accounts), "flagged": flags, "failed": failed}


@router.post("/jobs/refresh")
async def refresh(x_veritas_job_token: str | None = Header(default=None)):
    """Kick off the recompute and return immediately. Idempotent, and safe to run while
    the API serves — but not safe to run twice at once against the same rows, so a
    second trigger while one is still in flight is reported rather than started."""
    _authorise(x_veritas_job_token)

    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            return {"status": "already_running"}
        _refresh_running = True

    from data import ds

    # Capture the current request's Catalyst context for the background thread — it has
    # no request of its own to bind. Guarded exactly like bind_catalyst_request: on the
    # sqlite backend (local dev, tests) there is no SDK context to capture, and calling
    # catalyst_app() unconditionally would import zcatalyst_sdk where it is deliberately
    # absent.
    app = ds.catalyst_app() if ds.backend() == "catalyst" else None

    def _work() -> None:
        if app is not None:
            ds._sdk_app = app          # noqa: SLF001 — same pattern main.py's warm-up thread uses
        _run_refresh()

    threading.Thread(target=_work, name="jobs-refresh", daemon=True).start()
    return {"status": "started"}


def _run_narrative_backfill() -> None:
    """BUG-023's live fix: recompute `CaseMaster.BriefFacts` in place (no case added,
    removed, or renumbered; no accused/identity/financial/graph row touched — see
    `narrative_backfill`'s own docstring for why a full regeneration is not needed
    here), then rebuild the vector index the new text feeds."""
    global _narrative_running
    from data.embeddings.index_job import run_all as reindex
    from data.generator.narrative_backfill import backfill_narratives

    try:
        updated = backfill_narratives()
        indexed = reindex()
        log.info("narrative backfill complete: %s cases updated, reindex=%s", updated, indexed)
    except Exception:
        log.exception("narrative backfill failed")
    finally:
        with _narrative_lock:
            _narrative_running = False


@router.post("/jobs/regenerate_narratives")
async def regenerate_narratives(x_veritas_job_token: str | None = Header(default=None)):
    """One-time (or repeatable) fix for BUG-023, run where the SDK actually works —
    inside AppSail's request context — because the same operation cannot be driven
    from a developer machine: the Data Store SDK authenticates from per-request
    Catalyst headers, which only exist inside a real AppSail request (see
    `data.ds.bind_catalyst_request`), not from a bare local script."""
    _authorise(x_veritas_job_token)

    global _narrative_running
    with _narrative_lock:
        if _narrative_running:
            return {"status": "already_running"}
        _narrative_running = True

    from data import ds

    app = ds.catalyst_app() if ds.backend() == "catalyst" else None

    def _work() -> None:
        if app is not None:
            ds._sdk_app = app          # noqa: SLF001 — same pattern as /jobs/refresh
        _run_narrative_backfill()

    threading.Thread(target=_work, name="jobs-regenerate-narratives", daemon=True).start()
    return {"status": "started"}


_audit_lock = threading.Lock()
_audit_running = False


def _run_audit_verify() -> None:
    global _audit_running
    from data.audit import verify_chain

    try:
        intact, first_bad = verify_chain()
        if not intact:
            log.error("AUDIT CHAIN BROKEN at AuditID %s", first_bad)
        else:
            log.info("audit chain verified intact")
    except Exception:
        log.exception("scheduled audit verify failed")
    finally:
        with _audit_lock:
            _audit_running = False


@router.get("/jobs/audit-verify")
async def audit_verify(x_veritas_job_token: str | None = Header(default=None),
                        sync: bool = False):
    """Re-derive the whole audit hash chain and report whether it is intact.

    This is the thing that replaces Postgres's `RULE ... DO INSTEAD NOTHING`. Data Store has
    no rules and no triggers, so the log cannot be made physically immutable — instead every
    row hashes the one before it, and this is the check that says nobody has edited or
    removed one. Scheduled, so tampering is noticed rather than merely detectable.

    BUG-025 follow-up: Cron kept failing every scheduled fire even after its URL/token were
    corrected. Root cause — `verify_chain()`'s first `ds.query()` is exactly the call that pays
    the ~23s mirror-hydration cost on a cold container (BUG-001), synchronously, inside a
    request Cron abandons well before that. `/jobs/refresh` avoids this by never touching the
    data layer before responding; this endpoint now does the same, running the real check on a
    background thread and logging the result so a broken chain is still noticed. `sync=true`
    keeps the original blocking behaviour for a human running this by hand (a warm container
    answers in milliseconds) — the one caller that actually wants the real answer inline.
    """
    _authorise(x_veritas_job_token)

    if sync:
        from data.audit import verify_chain
        intact, first_bad = verify_chain()
        if not intact:
            log.error("AUDIT CHAIN BROKEN at AuditID %s", first_bad)
        return {"intact": intact, "first_bad_audit_id": first_bad}

    global _audit_running
    with _audit_lock:
        if _audit_running:
            return {"status": "already_running"}
        _audit_running = True

    from data import ds

    app = ds.catalyst_app() if ds.backend() == "catalyst" else None

    def _work() -> None:
        if app is not None:
            ds._sdk_app = app          # noqa: SLF001 — same pattern as /jobs/refresh
        _run_audit_verify()

    threading.Thread(target=_work, name="jobs-audit-verify", daemon=True).start()
    return {"status": "started"}
