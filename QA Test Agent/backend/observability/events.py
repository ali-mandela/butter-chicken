"""Event bus: every agent action is emitted here, persisted, and fanned out
to WebSocket subscribers in real time. The frontend never needs to poll."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from schemas.state import AgentEvent

logger = logging.getLogger("aivar.events")

_SECRET_KEYS = {"password", "token", "secret", "credential", "authorization"}


def _redact(data: dict) -> dict:
    redacted = {}
    for k, v in data.items():
        if any(s in k.lower() for s in _SECRET_KEYS):
            redacted[k] = "********"
        elif isinstance(v, dict):
            redacted[k] = _redact(v)
        else:
            redacted[k] = v
    return redacted


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[str, list[AgentEvent]] = defaultdict(list)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        if q in self._subscribers.get(run_id, []):
            self._subscribers[run_id].remove(q)

    def history(self, run_id: str) -> list[AgentEvent]:
        return self._history.get(run_id, [])

    async def emit(self, event: AgentEvent) -> None:
        event.data = _redact(event.data)
        self._history[event.run_id].append(event)
        logger.info("[%s] %s.%s: %s", event.run_id, event.agent, event.event, event.message)
        for q in list(self._subscribers.get(event.run_id, [])):
            await q.put(event)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
