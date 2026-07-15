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
    alerts, auth_routes, chat, copilot, export, jobs, records,
)

app = FastAPI(
    title="Veritas — KSP Crime Intelligence Platform",
    version="0.1.0",
    description="Evidence-grounded investigative AI. Every answer traces to a record.",
)


_model_fetch_kicked = False


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

    global _model_fetch_kicked
    if not _model_fetch_kicked and os.getenv("VERITAS_MODELS_FOLDER_ID"):
        _model_fetch_kicked = True
        import threading

        from data.nlp.model_fetch import ensure_models

        threading.Thread(target=ensure_models, name="model-fetch", daemon=True).start()

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
app.include_router(copilot.router, tags=["copilot"])
app.include_router(export.router, tags=["export"])
app.include_router(alerts.router, tags=["alerts"])
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
    return status
