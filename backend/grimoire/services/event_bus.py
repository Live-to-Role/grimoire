"""In-process async event bus for real-time notifications via SSE."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Simple pub/sub event bus using asyncio.Queue per subscriber.

    Channels isolate event types (e.g. "queue", "scan") so subscribers
    only receive events they care about.
    """

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        """Publish an event to all subscribers of a channel."""
        queues = self._subscribers.get(channel, [])
        dead = []
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)

        # Remove dead subscribers
        for q in dead:
            queues.remove(q)

    async def subscribe(self, channel: str):
        """Async generator that yields events for a channel.

        Usage:
            async for event in event_bus.subscribe("queue"):
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.setdefault(channel, []).append(q)
        try:
            while True:
                event = await q.get()
                yield event
        finally:
            # Cleanup on disconnect
            subs = self._subscribers.get(channel, [])
            if q in subs:
                subs.remove(q)


# Global singleton
event_bus = EventBus()
