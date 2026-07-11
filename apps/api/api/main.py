"""Veritas backend — the one deployable service.

Auth, policy enforcement on structured responses, transport (SSE/WebSocket), and
persistence orchestration. It hosts packages/rag_agent and packages/ml_models as
imports; it contains no reasoning, retrieval, or ML logic of its own.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import alerts, auth_routes, chat, copilot, export, records

app = FastAPI(
    title="Veritas — KSP Crime Intelligence Platform",
    version="0.1.0",
    description="Evidence-grounded investigative AI. Every answer traces to a record.",
)

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


@app.get("/health")
async def health() -> dict:
    """Reports what is actually reachable, not just that the process is alive."""
    from rag_agent.llm import available as llm_available

    status = {"api": "ok", "llm": "gemini" if llm_available() else "deterministic"}
    try:
        from data.db import get_session
        from sqlalchemy import text
        with get_session() as s:
            status["postgres"] = "ok"
            status["firs"] = s.execute(text("SELECT count(*) FROM fir")).scalar()
    except Exception as e:
        status["postgres"] = f"unavailable: {type(e).__name__}"
    try:
        from data.graph import get_driver
        get_driver().verify_connectivity()
        status["neo4j"] = "ok"
    except Exception as e:
        status["neo4j"] = f"unavailable: {type(e).__name__}"
    return status
