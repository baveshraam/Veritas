"""Veritas backend — the one deployable service.

Auth, policy enforcement on structured responses, transport (SSE/WebSocket), and
persistence orchestration. It hosts packages/rag_agent and packages/ml_models as
imports; it contains no reasoning, retrieval, or ML logic of its own.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# There are no API keys in the image. Inside AppSail the Catalyst SDK authenticates as the
# app itself, so the deployed service needs no secret at all. `.env` only carries the local
# pointers (project id, QuickML endpoint), and nothing else loads it — without this line a
# local uvicorn would not see them. override=False: an exported shell variable still wins.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

from .routers import (  # noqa: E402
    alerts, analytics, attach, auth_routes, board, chat, copilot, explain, export, jobs,
    records, search, sessions, timeline,
)

app = FastAPI(
    title="Veritas — KSP Crime Intelligence Platform",
    version="0.1.0",
    description="Evidence-grounded investigative AI. Every answer traces to a record.",
)


_warm_kicked = False


@app.middleware("http")
async def _catalyst_context(request: Request, call_next):
    """Capture AppSail's per-request Catalyst headers (X-ZC-*) into the SDK.

    The SDK has no env-var path in AppSail — its project context and admin credential
    ride on every gateway request. Data Store access and the File Store model fetch
    both depend on this. The model fetch (see data.nlp.model_fetch — the weights live
    outside the image because AppSail's bundle sandbox caps the image size) is kicked
    once, in the background, after the first request has provided a context; the lazy
    model loaders block on its lock if a query needs a model before it finishes."""
    from data import ds

    ds.bind_catalyst_request(request)

    global _warm_kicked
    if not _warm_kicked:
        _warm_kicked = True
        import threading

        # The SDK app is THREAD-LOCAL (ds._ctx). Capture the binding this request
        # just made, on this request's own thread, and re-pin it inside the warm
        # thread — the same handoff /jobs/refresh already does. Without it the warm
        # thread falls through to a bare `zcatalyst_sdk.initialize()`, which has no
        # headers in AppSail, so the File Store model fetch failed silently on every
        # cold start and every embedding-backed question 500'd (2026-09-06).
        warm_app = ds.catalyst_app_or_none()

        def _warm() -> None:
            if warm_app is not None:
                ds.bind_app(warm_app)
            # Mirror first (the Data Store reads every endpoint needs), models second.
            # Both are idempotent and both block their lazy loaders while running, so
            # a query that beats the warm-up waits instead of failing.
            #
            # This whole block used to be gated on VERITAS_MODELS_FOLDER_ID, which is
            # NOT set on the deployed app — so the mirror warm-up never ran in
            # production. The two have nothing to do with each other: the mirror is
            # the Data Store read path every endpoint needs, the model fetch is
            # optional weights. Only the second belongs behind that variable.
            try:
                ds._ensure_mirror()
            except Exception:
                pass                      # next query retries; failure detail is logged
            if os.getenv("VERITAS_MODELS_FOLDER_ID"):
                from data.nlp.model_fetch import ensure_models
                ensure_models()

            # BUG-016: profiled locally, a cold NLLB/whisper load is ~20s of weight
            # loading (not inference — the next call on the same warm process was
            # under 1.5s). Without this, that cost landed on whichever officer's query
            # happened to be first after a container start. Best-effort: a query must
            # never fail because warm-up is still in progress or failed.
            try:
                import importlib

                from data.nlp import speech
                # importlib, not `from data.nlp import translate`: data.nlp's __init__
                # re-exports the `translate` FUNCTION under the same name, shadowing
                # the submodule (see the /health handler above for the same trap).
                importlib.import_module("data.nlp.translate").warm()
                speech.warm()
            except Exception:
                pass

            # Same reasoning as the NLLB/whisper warm-up above, for QuickML's own
            # cold path: mint the OAuth access token now, off the request path,
            # rather than on whichever officer's Copilot request is first to need it.
            try:
                from rag_agent.llm import warm as _warm_llm
                _warm_llm()
            except Exception:
                pass

        threading.Thread(target=_warm, name="warm", daemon=True).start()

    return await call_next(request)

# The Command Console is a separate origin in dev; lock this down per-deployment.
_origins = [o for o in os.getenv(
    "VERITAS_CORS_ORIGINS", "http://localhost:3000").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router, tags=["auth"])
app.include_router(chat.router, tags=["chat"])
app.include_router(records.router, tags=["records"])
app.include_router(analytics.router, tags=["analytics"])
app.include_router(copilot.router, tags=["copilot"])
app.include_router(board.router, tags=["board"])
app.include_router(timeline.router, tags=["timeline"])
app.include_router(explain.router, tags=["explain"])
app.include_router(search.router, tags=["search"])
app.include_router(export.router, tags=["export"])
app.include_router(alerts.router, tags=["alerts"])
app.include_router(sessions.router, tags=["sessions"])
app.include_router(attach.router, tags=["attach"])
app.include_router(jobs.router, tags=["jobs"])       # driven by Catalyst Cron, not by a user


@app.get("/health")
async def health() -> dict:
    """Reports what is actually reachable, not just that the process is alive."""
    # llm_status() distinguishes "no key" from "key present but quota exhausted" —
    # reporting a bare model name for an unreachable endpoint is how you debug the
    # wrong thing.
    from rag_agent.llm import status as llm_status

    status = {"api": "ok", "llm": llm_status()}
    try:
        from data import ds
        status["datastore"] = ds.backend()
        status["firs"] = ds.scalar('SELECT COUNT("CaseMasterID") AS c FROM "CaseMaster"')
    except Exception as e:
        status["datastore"] = f"unavailable: {type(e).__name__}"
    try:
        from data.graph import load_graph
        g = load_graph()
        status["graph"] = "ok"
        status["graph_nodes"] = g.number_of_nodes()
        status["graph_edges"] = g.number_of_edges()
    except Exception as e:
        status["graph"] = f"unavailable: {type(e).__name__}"

    # The vector index lives in a Stratus object. If the bucket is missing, retrieval does
    # not fail — it silently returns nothing, which is the worst possible failure for a
    # citation-grounded system: confident, empty, and quiet. So it is reported.
    try:
        from data.vectors import load_index
        n = len(load_index()["source_id"])
        status["vector_index"] = "ok" if n else "EMPTY — retrieval will find nothing"
        status["indexed_documents"] = n
    except Exception as e:
        status["vector_index"] = f"unavailable: {type(e).__name__}"

    from data.cache import _segment
    status["cache"] = "catalyst" if _segment() is not None else "in-process"

    # Aequitas bias audit, run and cached by /jobs/refresh's own "fairness" step
    # (STRATEGIC_RESET Part 9, Item 1) — a mitigation nobody can check is a claim,
    # not a safeguard, so it gets a real status line here rather than living only in
    # a script's own stdout.
    try:
        from data.cache import get as cache_get
        fairness = cache_get(jobs.FAIRNESS_CACHE_KEY)
        if fairness is None:
            status["fairness"] = "not yet run"
        else:
            status["fairness"] = ("DISPARATE IMPACT FLAGGED" if fairness["flagged"]
                                  else "clear")
    except Exception as e:
        status["fairness"] = f"unavailable: {type(e).__name__}"

    # The last background /jobs/refresh's own per-step outcome, for the same reason
    # as `fairness` above — AppSail exposes no runtime logs, and `sync=true` is no
    # longer a reliable way to see this now that the full step list can outrun
    # AppSail's own request execution ceiling.
    try:
        from data.cache import get as cache_get
        status["last_refresh"] = cache_get(jobs.LAST_REFRESH_CACHE_KEY)
    except Exception as e:
        status["last_refresh"] = f"unavailable: {type(e).__name__}"

    # BUG-017: don't force a model load just to report on it — report what is
    # actually true of this container's state right now.
    #
    # importlib.import_module, not `from data.nlp import translate`: data.nlp's
    # __init__ re-exports the `translate` FUNCTION under the same name, which shadows
    # the submodule as a package attribute (the same trap test_nlp.py documents).
    try:
        import importlib
        model_fetch = importlib.import_module("data.nlp.model_fetch")
        translate_mod = importlib.import_module("data.nlp.translate")
        status["model_weights"] = model_fetch.status()
        status["nllb_backend"] = translate_mod.backend_status()
    except Exception as e:
        status["model_weights"] = f"unavailable: {type(e).__name__}"
        status["nllb_backend"] = f"unavailable: {type(e).__name__}"

    return status
