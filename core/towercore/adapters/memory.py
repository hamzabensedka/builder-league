"""In-memory adapters for TowerCore: the SSE notifier fan-out.

The event log itself lives in the domain (EventStream) — it IS the source of
truth, not a port. What genuinely varies per deployment is how live events
reach connected operators; this adapter is an in-process queue fan-out good
for a single-process demo. Swapping to Redis pub/sub for multi-process later
touches only this module.
"""

import queue
import threading
from typing import Any

from core.towercore.domain.events import AgentEvent


class InMemoryNotifier:
    """Fan-out to N live SSE subscribers. Best-effort push; the stream remains
    authoritative (a dropped push is recovered by the next /fleet poll)."""

    def __init__(self) -> None:
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()

    def publish(self, event: AgentEvent) -> None:
        with self._lock:
            queues = list(self._queues)
        for q in queues:
            try:
                q.put_nowait(event.as_dict())
            except queue.Full:
                continue  # a slow consumer never blocks the log

    def subscribe(self, *, maxsize: int = 1000) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)


def attach_notifier(stream: Any, notifier: InMemoryNotifier) -> None:
    """Bridge: every appended event is pushed to subscribers. Wired in the
    composition root so the domain stream stays transport-agnostic."""
    stream.subscribe(notifier.publish)
