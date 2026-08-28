"""POST /chat — SSE stream of the reasoning trace, then the grounded answer.

Envelope (canonical; apps/web builds against exactly this):
    { type: "trace", step, detail, duration_ms, confidence }
    { type: "final", final_answer, citations, evidence_items, visualization }
    { type: "audio", data: <base64> }        # only when respond_with_voice

Trace events stream as the engine produces them, which is the point: the officer
watches the system reason rather than staring at a spinner, and the trace is the
explainability surface, not a debug log.

officer_id / officer_role come from the JWT. If the body carries them, they are
ignored — see auth/jwt_auth.py.
"""
import asyncio
import base64
import json
import logging
from typing import Literal, Optional

from data import SessionFocus, get_session_focus, write_conversation_turn
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from rag_agent import InvestigationState, run_investigation
from sse_starlette.sse import EventSourceResponse

from ..audit import record

log = logging.getLogger(__name__)
from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    language: Literal["en", "kn"] = "en"
    query: Optional[str] = None
    audio: Optional[str] = None            # base64
    respond_with_voice: bool = False
    # Which evidence card the console had selected when the officer said "pin this" —
    # apps/web already tracks this as `activeEvidence`; threading it through lets
    # BOARD_PIN_EVIDENCE pin exactly what was in view instead of guessing.
    active_evidence_id: Optional[str] = None


def _next_turn_index(session_id: str) -> int:
    from data import get_conversation_history
    try:
        return len(get_conversation_history(session_id))
    except Exception:
        return 0


@router.post("/chat")
async def chat(req: ChatRequest, officer: Officer = Depends(current_officer)):
    focus = get_session_focus(req.session_id) or SessionFocus()

    state = InvestigationState(
        session_id=req.session_id,
        officer_id=officer.officer_id,
        officer_role=officer.role,          # from the token, never the body
        original_query=req.query,
        input_audio=base64.b64decode(req.audio) if req.audio else None,
        respond_with_voice=req.respond_with_voice,
        language=req.language,
        active_entities=focus,
        active_evidence_id=req.active_evidence_id,
    )

    async def stream():
        # The engine is sync and CPU/IO-bound (Neo4j, Postgres, models); running it in
        # a worker thread keeps the event loop free to flush SSE frames.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def work():
            # Hand the exception back rather than letting it die in the worker thread.
            # If work() raises, put_nowait never runs, `await queue.get()` blocks
            # forever, and the officer watches keep-alive pings until the connection
            # times out — a silent hang is the worst way for an engine bug to surface.
            try:
                outcome = run_investigation(state)
            except Exception as exc:              # noqa: BLE001 — reported, not swallowed
                outcome = exc
            loop.call_soon_threadsafe(queue.put_nowait, outcome)

        loop.run_in_executor(None, work)
        outcome = await queue.get()

        if isinstance(outcome, Exception):
            log.exception("investigation failed", exc_info=outcome)
            yield {"data": json.dumps({
                "type": "error",
                "message": "The investigation engine failed on this query. Nothing was "
                           "answered — no partial or unsourced result is being shown.",
                "detail": f"{type(outcome).__name__}: {outcome}",
            })}
            return
        result: InvestigationState = outcome

        for entry in result.agent_trace:
            yield {"data": json.dumps({
                "type": "trace", "step": entry.step, "detail": entry.detail,
                "duration_ms": entry.duration_ms, "confidence": entry.confidence,
            })}
            await asyncio.sleep(0)          # let the frame flush

        final = {
            "type": "final",
            "final_answer": result.final_answer,
            "citations": [c.model_dump() for c in result.citations],
            "evidence_items": [e.model_dump(mode="json") for e in result.evidence_items],
            "visualization": result.visualization.model_dump(),
            # Whether this is a genuine refusal, distinct from "no citations": a
            # CAPABILITY answer or a successful case-board confirmation also carries
            # zero citations (there is no record behind either) but is not a refusal
            # — the console used to infer "refusal" from an empty citation list
            # alone, which rendered every successful board action in the same red
            # styling as "I could not find this in the records."
            "refused": result.answer_is_refusal,
        }
        yield {"data": json.dumps(final)}

        if result.output_audio:
            yield {"data": json.dumps({
                "type": "audio",
                "data": base64.b64encode(result.output_audio).decode(),
            })}

        # Persist AFTER streaming, so a slow write never delays the officer's answer.
        # Both writes happen: conversation_turn is the content store (re-render, PDF),
        # audit_log is the tamper-evident trail. Neither substitutes for the other.
        trace = [t.model_dump() for t in result.agent_trace]
        write_conversation_turn(
            session_id=req.session_id,
            turn_index=_next_turn_index(req.session_id),
            query=result.original_query or "",
            language=req.language,
            final_answer=result.final_answer or "",
            citations=[c.model_dump() for c in result.citations],
            evidence_items=[e.model_dump(mode="json") for e in result.evidence_items],
            visualization=result.visualization.model_dump(),
            agent_trace=trace,
            # last_request is a separate InvestigationState field precisely so it
            # survives every specialist branch that overwrites result_context
            # wholesale (see state.py) — merged in only here, at the one point a
            # turn is actually persisted, so it round-trips regardless of which
            # path node_retrieve took this turn.
            result_context={**(result.result_context or {}), "last_request": result.last_request},
        )
        record(officer.officer_id, req.session_id, "/chat",
               req.model_dump(exclude={"audio"}), final, trace)

    return EventSourceResponse(stream())
