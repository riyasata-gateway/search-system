"""Server-Sent Events streaming endpoints.

Three live channels forwarded from the Redis event bus:

  GET /api/v1/stream/mentions   — every newly-persisted Mention
  GET /api/v1/stream/alerts     — every Alert created by the engine
  GET /api/v1/stream/signals    — anomaly / momentum / pivot signals

Why SSE not WebSocket?
- Pure server-to-client push fits our model — we don't need client-to-server
  messages on the same socket.
- SSE works over plain HTTP/2 — no upgrade dance, no extra middleware,
  passes through ingress controllers cleanly.
- Auto-reconnect is built into the browser EventSource API.

Auth: token query param is supported in addition to the Authorization header
because the browser EventSource API can't set headers. Same token validation,
same scope.
"""
import asyncio
import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.event_bus import Channel, subscribe_events
from core.logging import get_logger
from core.security import decode_token
from models.user import User

# Same token URL as the global scheme but `auto_error=False` so SSE clients
# that can't set headers (browser EventSource) can fall back to ?token=.
_optional_bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

logger = get_logger(__name__)

router = APIRouter()


async def _user_from_token(token: str, db: AsyncSession) -> User:
    """Token validation that mirrors `get_current_user` but accepts a raw
    string (not a bearer header). Used by the SSE query-param fallback."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
    )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        if payload.get("type") != "access":
            raise credentials_exc
    except (ValueError, TypeError):
        raise credentials_exc
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exc
    return user


async def _resolve_user(
    bearer: Optional[str],
    token_qs: Optional[str],
    db: AsyncSession,
) -> User:
    if bearer:
        return await _user_from_token(bearer, db)
    if token_qs:
        return await _user_from_token(token_qs, db)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing token (Authorization header or ?token= query param)",
    )


def _sse_format(payload: dict, event: Optional[str] = None) -> bytes:
    """Encode a dict as one SSE frame."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    body = json.dumps(payload, default=str)
    for line in body.splitlines() or [body]:
        lines.append(f"data: {line}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _channel_stream(
    request: Request,
    channel: str,
    *,
    keepalive_seconds: int = 15,
) -> AsyncIterator[bytes]:
    """Bridge a Redis pub/sub channel to an SSE-formatted byte stream."""
    yield _sse_format({"channel": channel, "status": "connected"}, event="open")

    try:
        async for evt in subscribe_events(channel, heartbeat_seconds=keepalive_seconds):
            if await request.is_disconnected():
                break
            if evt is None:
                # SSE comment line — keeps proxies from idling the connection out
                yield b": keepalive\n\n"
                continue
            event_name = evt.get("event") or "message"
            yield _sse_format(evt, event=event_name)
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.warning("sse_stream_error", channel=channel, error=str(exc))
        yield _sse_format({"error": str(exc)}, event="error")


def _sse_response(generator) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/mentions")
async def stream_mentions(
    request: Request,
    token: Optional[str] = Query(None, description="JWT — fallback when EventSource can't set Authorization"),
    db: AsyncSession = Depends(get_db),
    bearer: Optional[str] = Depends(_optional_bearer),
):
    await _resolve_user(bearer, token, db)
    return _sse_response(_channel_stream(request, Channel.MENTIONS))


@router.get("/alerts")
async def stream_alerts(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    bearer: Optional[str] = Depends(_optional_bearer),
):
    await _resolve_user(bearer, token, db)
    return _sse_response(_channel_stream(request, Channel.ALERTS))


@router.get("/signals")
async def stream_signals(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    bearer: Optional[str] = Depends(_optional_bearer),
):
    await _resolve_user(bearer, token, db)
    return _sse_response(_channel_stream(request, Channel.SIGNALS))
