"""Redis pub/sub event bus — the spine of real-time streaming.

Three channels:

  • `events:mentions`  — fires when a Mention row is persisted
  • `events:alerts`    — fires when an Alert is generated
  • `events:signals`   — fires when intelligence detects a noteworthy state
                         change (high-momentum entity, anomaly, etc.)

Publishers are mostly sync (Celery workers, alert engine) so the publish
helper is sync (uses `redis.Redis.from_url`). Subscribers are async (FastAPI
SSE endpoints) and consume via `subscribe_events()` which yields parsed
dicts as JSON arrives.

Publishing is fire-and-forget: if Redis is unreachable we log and swallow.
Streaming is best-effort by design — durability comes from the persisted
Mention / Alert rows, not the pub/sub feed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional

from core.config import settings
from core.logging import get_logger
from core.redis_client import get_redis

logger = get_logger(__name__)


class Channel:
    MENTIONS = "events:mentions"
    ALERTS = "events:alerts"
    SIGNALS = "events:signals"


_sync_redis = None


def _get_sync_redis():
    """Lazy-init sync redis client for publish from Celery / sync code."""
    global _sync_redis
    if _sync_redis is None:
        import redis as sync_redis_mod
        _sync_redis = sync_redis_mod.Redis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _sync_redis


def publish_event(channel: str, payload: Dict[str, Any]) -> bool:
    """Publish a single event synchronously. Returns True on success.

    Failure is logged but never raised — streaming is decoration, not the
    source of truth.
    """
    try:
        client = _get_sync_redis()
        msg = json.dumps(payload, default=str)
        client.publish(channel, msg)
        return True
    except Exception as exc:
        logger.warning("event_publish_failed", channel=channel, error=str(exc))
        return False


async def publish_event_async(channel: str, payload: Dict[str, Any]) -> bool:
    """Async version for use inside async routers / workers."""
    try:
        client = await get_redis()
        await client.publish(channel, json.dumps(payload, default=str))
        return True
    except Exception as exc:
        logger.warning("event_publish_async_failed", channel=channel, error=str(exc))
        return False


async def subscribe_events(
    channel: str,
    *,
    heartbeat_seconds: int = 15,
) -> AsyncIterator[Optional[Dict[str, Any]]]:
    """Async iterator over messages on `channel`.

    Yields `None` every `heartbeat_seconds` if no messages arrive — useful for
    SSE keep-alive comments that prevent proxies from closing the connection.
    Otherwise yields the decoded JSON dict.

    Resilient to Redis being unavailable: rather than raising (which ends the SSE
    generator and makes the browser EventSource reconnect-storm — one logged
    warning every few seconds), it degrades to keep-alive-only, retries the
    connection each heartbeat, and logs the outage just ONCE per episode.
    """
    warned = False
    while True:
        pubsub = None
        try:
            client = await get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            if warned:
                logger.info("event_bus_recovered", channel=channel)
                warned = False
            while True:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    yield None
                    continue
                if msg is None:
                    yield None
                    continue
                data = msg.get("data")
                if not data:
                    continue
                try:
                    yield json.loads(data)
                except (TypeError, json.JSONDecodeError):
                    # Bad payload — log but keep stream alive
                    logger.warning("event_decode_failed", channel=channel)
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Redis unreachable or the connection dropped. Keep the SSE connection
            # OPEN (yield a keep-alive) and retry on the next heartbeat instead of
            # propagating — so the client isn't forced into a reconnect loop. Log
            # only the first failure of an outage to avoid flooding the logs.
            if not warned:
                logger.warning("event_bus_unavailable", channel=channel, error=str(exc))
                warned = True
            yield None
            await asyncio.sleep(heartbeat_seconds)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass
