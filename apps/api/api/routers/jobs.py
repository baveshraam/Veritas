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
        log.info("scheduled refresh complete: %s", out)
    except Exception:
        # A background thread's exception has nowhere else to go — log it with the
        # traceback, or a failed refresh looks identical to a slow one from the outside.
        log.exception("scheduled refresh failed")
    finally:
        with _refresh_lock:
            _refresh_running = False


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


@router.get("/jobs/audit-verify")
async def audit_verify(x_veritas_job_token: str | None = Header(default=None)):
    """Re-derive the whole audit hash chain and report whether it is intact.

    This is the thing that replaces Postgres's `RULE ... DO INSTEAD NOTHING`. Data Store has
    no rules and no triggers, so the log cannot be made physically immutable — instead every
    row hashes the one before it, and this is the check that says nobody has edited or
    removed one. Scheduled, so tampering is noticed rather than merely detectable.
    """
    _authorise(x_veritas_job_token)
    from data.audit import verify_chain

    intact, first_bad = verify_chain()
    if not intact:
        log.error("AUDIT CHAIN BROKEN at AuditID %s", first_bad)
    return {"intact": intact, "first_bad_audit_id": first_bad}
