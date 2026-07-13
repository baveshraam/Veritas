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
"""
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, status

router = APIRouter()
log = logging.getLogger(__name__)


def _authorise(token: str | None) -> None:
    expected = os.getenv("VERITAS_JOB_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "VERITAS_JOB_TOKEN is not set; the job endpoint is disabled")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad job token")


@router.post("/jobs/refresh")
async def refresh(x_veritas_job_token: str | None = Header(default=None)):
    """Recompute the derived layers. Idempotent, and safe to run while the API serves."""
    _authorise(x_veritas_job_token)

    from data.gds import run_all as run_gds
    from data.graph import publish_graph

    out: dict = {}

    # Graph metrics first: the community/PageRank values every network answer cites.
    out["gds"] = run_gds()

    # Then the Stratus blob, so a cold container reads one object instead of paging the
    # whole edge list back through ZCQL's 300-row cap.
    out["stratus_graph"] = publish_graph()

    log.info("scheduled refresh complete: %s", out)
    return out


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
