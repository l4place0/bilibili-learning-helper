"""asyncio.Queue-based SSE streaming for task progress."""

import asyncio
from collections import defaultdict

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(task_id: str) -> asyncio.Queue:
    """Subscribe to a task's event stream. Returns an asyncio.Queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[task_id].append(q)
    return q


def unsubscribe(task_id: str, q: asyncio.Queue):
    """Remove a subscriber queue for a task."""
    if q in _subscribers[task_id]:
        _subscribers[task_id].remove(q)


def publish(task_id: str, data: dict):
    """Publish data to all subscribers of a task."""
    for q in _subscribers.get(task_id, []):
        q.put_nowait(data)
