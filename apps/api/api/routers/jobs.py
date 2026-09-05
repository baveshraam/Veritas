"""POST /jobs/refresh — the scheduled recompute, driven by Catalyst Cron.

Everything derived from the record layer goes stale the moment the record layer changes:
the graph metrics (PageRank / Louvain / betweenness), the Stratus graph blob a cold
container reads instead of paginating 136k edges, the AML flags, and (as of the series-
discovery pass) the cross-station pattern scan GET /alerts reads from cache rather than
recomputing per officer per poll. None of that is expensive enough to recompute per
request, and none of it is cheap enough to.

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
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, status

router = APIRouter()
log = logging.getLogger(__name__)

_refresh_lock = threading.Lock()
_refresh_running = False
_narrative_lock = threading.Lock()
_narrative_running = False

LAST_REFRESH_CACHE_KEY = "last_refresh_v1"


def _authorise(token: str | None) -> None:
    expected = os.getenv("VERITAS_JOB_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "VERITAS_JOB_TOKEN is not set; the job endpoint is disabled")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad job token")


def _reindex_with_progress() -> dict:
    """Same work as `data.embeddings.index_job.run_all`, but reports which of its
    two phases (query / embed-and-write) is in flight, by merging into whatever
    `LAST_REFRESH_CACHE_KEY` already holds rather than closing over `_run_refresh`'s
    local state — so this stays a standalone, independently testable step function
    like every other one in `steps` below.

    Live verification (2026-09-05): the async refresh reliably parked on
    "vector_index" with no forward motion until the container itself reset (its
    `model_weights`/`nllb_backend` health fields went back to fresh-boot values
    between two checks, with zero other requests in between) — this step, and only
    this step, is where it happens, every time it was tried. Embedding ~13,835
    documents through the ONNX model is CPU-bound and was previously untimed
    (this module's own docstring already flagged it as "the untimed remainder").
    Splitting "querying" from "embedding N documents" turns one opaque multi-minute
    step into two, so the next live run shows which phase a container reset
    actually happens in, rather than "vector_index" and nothing more.
    """
    from data import cache
    from data.embeddings.index_job import fir_documents, profile_documents
    from data.vectors import build_index

    def _report(stage: str) -> None:
        current = cache.get(LAST_REFRESH_CACHE_KEY) or {}
        cache.put(LAST_REFRESH_CACHE_KEY,
                 {**current, "vector_index_stage": stage,
                  "vector_index_stage_at": datetime.now(timezone.utc).isoformat()},
                 expiry_hours=SERIES_CACHE_TTL_HOURS)

    _report("querying records")
    firs, profiles = fir_documents(), profile_documents()
    # `build_index` embeds AND writes the blob in one call — no hook point inside
    # it — so this is the last observable phase boundary before either the next
    # step's own "current_step" write or the final "complete" write (whichever
    # this run reaches) shows this one finished.
    _report(f"embedding {len(firs) + len(profiles)} documents")
    n = build_index(firs + profiles)
    return {"fir_narrative": len(firs), "criminal_profile": len(profiles), "written": n}


def _run_refresh() -> dict:
    global _refresh_running
    from data.gds import run_all as run_gds
    from data.graph import publish_graph

    # Each step is isolated. These rebuild INDEPENDENT derived layers over the
    # same record layer — none is an input to the next — so one failing must not
    # cancel the rest. Under a single try/except the first raise silently skipped
    # everything after it, and that is not hypothetical: `publish_graph()` writes to
    # Stratus, whose bucket creation is scope-blocked on this org (CLAUDE.md §2,
    # OAUTH_SCOPE_MISMATCH — console-only). A blocked CACHE publish was therefore
    # able to cancel the AML detector sweep, which is a RECORD-layer rebuild, and the
    # Financial Watchlist stayed empty through a refresh that reported itself started
    # and finished. A failed step now names itself in the log and in `out`.
    steps = (
        # Graph metrics first: the community/PageRank values every network answer cites.
        ("gds", run_gds),
        # The Stratus blob, so a cold container reads one object instead of paging the
        # whole edge list back through ZCQL's 300-row cap. A miss costs latency, never
        # correctness — the sqlite mirror rebuilds the graph either way.
        ("stratus_graph", publish_graph),
        # The vector index, derived from the same record layer. Rebuilding it here is
        # what makes the deployment self-healing: an index that is missing or stale is
        # the one failure a citation-grounded system hides rather than reports —
        # retrieval simply returns nothing, confidently.
        ("vector_index", _reindex_with_progress),
        # The AML detectors. `vx_txn.FlaggedSuspicious` is a detector OUTPUT, never
        # written by the generator (data/generator/financial.py asserts that), so on a
        # freshly seeded dataset it is false on every row until something runs the
        # models — which nothing did. The Financial Watchlist therefore reported "no
        # transaction is flagged by either detector" forever, and that answer was
        # indistinguishable from a genuine all-clear.
        ("aml", _rerun_detectors),
        # Cross-station series discovery (rag_agent.series_detection) — a genuinely
        # proactive scan, not a per-query answer. Deliberately NOT run on /alerts'
        # own 30-second poll: it calls similar_cases_for (a real hybrid vector
        # search) per recently-filed case, and every connected officer's SSE stream
        # runs its own independent poll loop — recomputing that every 30 seconds per
        # officer is real, avoidable compute. This step runs it once per refresh
        # cycle (the same 6h Cron cadence as everything else derived from the record
        # layer) and caches the result; /alerts reads the cache, it never recomputes.
        # Placed after vector_index above so it searches against fresh embeddings.
        ("series_scan", _scan_series),
        # Aequitas bias audit (STRATEGIC_RESET Part 9, Item 1). Was a script nobody
        # scheduled — `fairness_run_audit.py` existed and worked, but an unscheduled
        # mitigation is a claim, not a verifiable safeguard. Runs last: it audits the
        # risk/recidivism models themselves, not anything the steps above produce.
        ("fairness", _run_fairness),
        # The fused proactive-prevention advisory (STRATEGIC_RESET Part 9, Item 2).
        # Placed last because it reads the two caches the steps above just wrote
        # (series_scan, fairness) to attach their results as disclosures.
        ("advisory", _run_advisory),
    )
    out: dict = {}
    from data import cache
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        for name, step in steps:
            # Written BEFORE the step runs, not just after the whole job finishes.
            # Live verification (2026-09-05) found the async path can run for many
            # minutes with `/health`'s `last_refresh` staying null the entire time —
            # indistinguishable, from outside AppSail's no-runtime-logs constraint,
            # between "still working", "stuck on one step", and "the container was
            # recycled mid-run and the thread died with it". This makes the CURRENT
            # step and when it started observable without waiting for completion.
            cache.put(LAST_REFRESH_CACHE_KEY,
                     {**out, "status": "running", "current_step": name,
                      "started_at": started_at,
                      "step_started_at": datetime.now(timezone.utc).isoformat()},
                     expiry_hours=SERIES_CACHE_TTL_HOURS)
            try:
                out[name] = step()
            except Exception as exc:
                # A background thread's exception has nowhere else to go — log it with
                # the traceback, or a failed step looks identical to a slow one from
                # the outside.
                log.exception("scheduled refresh step %r failed", name)
                out[name] = f"failed: {type(exc).__name__}: {exc}"[:300]
        log.info("scheduled refresh complete: %s", out)
        return out
    finally:
        with _refresh_lock:
            _refresh_running = False
        # AppSail exposes bundle-creator logs and no runtime logs, so the log line
        # above is invisible from outside — and `sync=true`'s own response is no
        # longer a reliable way to see it either, now that the full step list
        # (with fairness + advisory added) can run past AppSail's own request
        # execution ceiling (measured live: ~35s) even though the async path this
        # `finally` always runs on has no such limit. Cached here so a human can
        # read the last real outcome from `/health` without either.
        cache.put(LAST_REFRESH_CACHE_KEY,
                 {**out, "status": "complete", "started_at": started_at,
                  "at": datetime.now(timezone.utc).isoformat()},
                 expiry_hours=SERIES_CACHE_TTL_HOURS)


SERIES_CACHE_KEY = "series_scan_v1"
SERIES_CACHE_TTL_HOURS = 24     # a bit longer than the 6h refresh cadence, so a
                                # missed/slow refresh cycle doesn't blank the feed


def _scan_series() -> dict:
    """Cache the result so GET /alerts can read it cheaply on every poll instead of
    re-running a real vector search per recently-filed case for every connected
    officer every 30 seconds — see the step's own comment in _run_refresh above."""
    from data import cache
    from rag_agent.series_detection import scan_for_new_series

    results = scan_for_new_series()
    cache.put(SERIES_CACHE_KEY, [r.model_dump(mode="json") for r in results],
             expiry_hours=SERIES_CACHE_TTL_HOURS)
    return {"candidates": len(results)}


FAIRNESS_CACHE_KEY = "fairness_audit_v1"
FAIRNESS_CACHE_TTL_HOURS = 24   # same reasoning as SERIES_CACHE_TTL_HOURS above


def _run_fairness() -> dict:
    """Aequitas disparate-impact audit over both risk models, cached for `/health` and
    the console's System panel to read cheaply instead of retraining/re-scoring on
    every request. Geographic + gender subgroups only — never caste/religion, which
    are stored for schema conformance but never reach a model (CLAUDE.md §6/§9)."""
    from data import cache
    from ml_models.serving import run_fairness_audit

    reports = {m: run_fairness_audit(m).model_dump(mode="json")
              for m in ("score_risk", "predict_recidivism")}
    flagged = any(r["disparate_impact_flagged"] for r in reports.values())
    cache.put(FAIRNESS_CACHE_KEY, {"reports": reports, "flagged": flagged},
             expiry_hours=FAIRNESS_CACHE_TTL_HOURS)
    return {"flagged": flagged}


ADVISORY_CACHE_KEY = "advisory_v1"
ADVISORY_CACHE_TTL_HOURS = 24   # same cadence reasoning as SERIES_CACHE_TTL_HOURS above


def _run_advisory() -> dict:
    """One fused hotspot+forecast+series-linkage read per district, cached for
    GET /alerts to push cheaply (STRATEGIC_RESET Part 9, Item 2) instead of running
    KDE/DBSCAN and Prophet per officer per poll."""
    from data import cache
    from data.districts import all_districts
    from rag_agent.agents.prediction_agent import advisory_for

    series = cache.get(SERIES_CACHE_KEY) or []
    fairness = cache.get(FAIRNESS_CACHE_KEY)
    flagged = bool(fairness and fairness.get("flagged"))

    advisories = [a for d in all_districts()
                 if (a := advisory_for(d.code, series_candidates=series,
                                       fairness_flagged=flagged)) is not None]
    cache.put(ADVISORY_CACHE_KEY, advisories, expiry_hours=ADVISORY_CACHE_TTL_HOURS)
    return {"advisories": len(advisories)}


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
async def refresh(sync: bool = False,
                  x_veritas_job_token: str | None = Header(default=None)):
    """Kick off the recompute and return immediately. Idempotent, and safe to run while
    the API serves — but not safe to run twice at once against the same rows, so a
    second trigger while one is still in flight is reported rather than started.

    `sync=true` waits and returns the per-step summary instead. Cron must never use it —
    the recompute takes minutes and Cron abandons the request long before that, which is
    exactly the failure BUG-027 fixed for /jobs/audit-verify. It exists because on this
    platform a background thread's log is not reachable: AppSail exposes bundle-creator
    logs and no runtime logs, so a step that fails inside the thread is invisible from
    outside, and "started" is the only thing the caller ever learns. That is how a
    blocked Stratus publish silently cancelled the AML sweep for a whole deployment.
    An operator running this by hand can now see which step failed and why.
    """
    _authorise(x_veritas_job_token)

    global _refresh_running
    with _refresh_lock:
        if _refresh_running:
            return {"status": "already_running"}
        _refresh_running = True

    from data import ds

    if sync:
        # Already inside the lock's protection (set above), so this cannot race a
        # background run. Runs on the request's OWN thread, which the middleware has
        # already bound to the Catalyst context — so there is nothing to capture, and
        # asking for the SDK app here would import zcatalyst_sdk on the sqlite backend
        # where it is deliberately absent.
        return {"status": "complete", "steps": _run_refresh()}

    # Capture the current request's Catalyst context for the background thread — it has
    # no request of its own to bind. Guarded exactly like bind_catalyst_request: on the
    # sqlite backend (local dev, tests) there is no SDK context to capture, and calling
    # catalyst_app() unconditionally would import zcatalyst_sdk where it is deliberately
    # absent.
    app = ds.catalyst_app() if ds.backend() == "catalyst" else None

    def _work() -> None:
        if app is not None:
            ds.bind_app(app)
        _run_refresh()

    threading.Thread(target=_work, name="jobs-refresh", daemon=True).start()
    return {"status": "started"}


def _run_narrative_backfill() -> None:
    """BUG-023's live fix: recompute `CaseMaster.BriefFacts` in place (no case added,
    removed, or renumbered; no accused/identity/financial/graph row touched — see
    `narrative_backfill`'s own docstring for why a full regeneration is not needed
    here), then rebuild the vector index the new text feeds.

    Runs the BNS section backfill FIRST: the narrative's "Offences registered under
    section X" line reads straight out of ActSectionAssociation, so recomputing the
    narrative against not-yet-corrected sections would faithfully re-cite the wrong
    ones. Same isolation discipline as /jobs/refresh's own step list — one failing
    must not silently skip the rest."""
    global _narrative_running
    from data.embeddings.index_job import run_all as reindex
    from data.generator.narrative_backfill import backfill_narratives
    from data.generator.section_backfill import backfill_act_sections

    out: dict = {}
    try:
        out["sections"] = backfill_act_sections()
    except Exception as exc:
        log.exception("section backfill failed")
        out["sections"] = f"failed: {type(exc).__name__}"
    try:
        out["narratives"] = backfill_narratives()
        out["reindex"] = reindex()
    except Exception as exc:
        log.exception("narrative backfill failed")
        out["narratives"] = f"failed: {type(exc).__name__}"
    finally:
        log.info("narrative/section backfill complete: %s", out)
        with _narrative_lock:
            _narrative_running = False


@router.post("/jobs/regenerate_narratives")
async def regenerate_narratives(x_veritas_job_token: str | None = Header(default=None)):
    """One-time (or repeatable) fix for BUG-023 (narrative diversity) and the BNS
    section-currency fix, run where the SDK actually works — inside AppSail's request
    context — because the same operation cannot be driven from a developer machine:
    the Data Store SDK authenticates from per-request Catalyst headers, which only
    exist inside a real AppSail request (see `data.ds.bind_catalyst_request`), not
    from a bare local script."""
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
            ds.bind_app(app)
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
            ds.bind_app(app)
        _run_audit_verify()

    threading.Thread(target=_work, name="jobs-audit-verify", daemon=True).start()
    return {"status": "started"}
