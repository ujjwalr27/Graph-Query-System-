"""
Chat API routes – LLM-powered conversational query interface.
"""

import json
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from llm import chat_stream

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Simple in-memory session store for conversation history
_sessions: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    stream: bool = True


class ChatResponse(BaseModel):
    answer: str
    sql: str | None = None
    results: list[dict] | None = None
    session_id: str
    is_guardrail: bool = False


@router.post("")
async def chat_endpoint(request: ChatRequest):
    """
    Process a chat message. Supports both streaming (SSE) and non-streaming modes.
    """
    session_id = request.session_id or str(uuid.uuid4())

    # Get or create session history
    if session_id not in _sessions:
        _sessions[session_id] = []
    history = _sessions[session_id]

    # All requests use streaming (non-streaming mode removed)
    return StreamingResponse(
        _stream_response(request.message, session_id, history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_response(message: str, session_id: str, history: list[dict]):
    """Generate SSE events for streaming response."""
    # Send session ID first
    yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

    full_answer = []

    async for chunk_json in _async_stream_wrapper(message, history):
        yield f"data: {chunk_json}\n\n"

        # Collect answer chunks for history
        try:
            chunk_data = json.loads(chunk_json)
            if chunk_data.get("type") == "chunk":
                full_answer.append(chunk_data["content"])
            elif chunk_data.get("type") in ("guardrail", "answer"):
                full_answer.append(chunk_data["content"])
        except json.JSONDecodeError:
            pass

    # Update session history
    history.append({"role": "user", "content": message})
    history.append({"role": "model", "content": "".join(full_answer)})

    if len(history) > 20:
        _sessions[session_id] = history[-20:]


async def _async_stream_wrapper(message: str, history: list[dict]):
    """Wrap the async generator from chat_stream."""
    async for chunk in chat_stream(message, history):
        yield chunk


@router.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a chat session's history."""
    if session_id in _sessions:
        del _sessions[session_id]
        return {"status": "cleared"}
    return {"status": "not_found"}
