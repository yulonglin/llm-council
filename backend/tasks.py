"""In-memory registry for background council tasks.

Each council run is an asyncio.Task that produces SSE-style events.
Events are buffered so reconnecting clients can replay history.
Multiple SSE subscribers can connect/disconnect independently.
Tasks run to completion regardless of subscriber count.

CRITICAL DESIGN NOTE: subscribe() adds the queue to subscribers BEFORE
replaying buffered events, then uses an index to skip duplicates. This
eliminates the TOCTOU gap where events could be missed between replay
and live subscription.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CouncilTask:
    """Tracks a running council deliberation."""

    conversation_id: str
    task: Optional[asyncio.Task] = None  # None initially, set after create_task()
    events: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    status: str = "running"  # running | complete | error | cancelled


# Global registry: conversation_id -> CouncilTask
_tasks: dict[str, CouncilTask] = {}


def get_task(conversation_id: str) -> Optional[CouncilTask]:
    """Get the running task for a conversation, or None."""
    return _tasks.get(conversation_id)


def is_running(conversation_id: str) -> bool:
    """Check if a council task is currently running for this conversation."""
    task = _tasks.get(conversation_id)
    return task is not None and task.status == "running"


def broadcast(conversation_id: str, event: dict) -> None:
    """Store event and push to all subscribers."""
    task_state = _tasks.get(conversation_id)
    if not task_state:
        return
    task_state.events.append(event)
    for q in task_state.subscribers:
        q.put_nowait(event)


def complete_task(conversation_id: str, status: str = "complete") -> None:
    """Mark task as finished, notify subscribers, schedule cleanup."""
    task_state = _tasks.get(conversation_id)
    if not task_state:
        return
    task_state.status = status
    for q in task_state.subscribers:
        q.put_nowait(None)
    # Auto-cleanup after 15 minutes (enough for suspended browser tabs)
    asyncio.get_running_loop().call_later(
        900, lambda: _tasks.pop(conversation_id, None)
    )


def register_task(conversation_id: str) -> CouncilTask:
    """Register a placeholder task entry BEFORE creating the asyncio.Task.

    This eliminates the race where create_task() starts the coroutine
    before the registry entry exists, causing broadcast() to silently drop events.

    Usage:
        task_state = tasks.register_task(conversation_id)
        bg_task = asyncio.create_task(...)
        task_state.task = bg_task
    """
    existing = _tasks.get(conversation_id)
    if existing and existing.task and not existing.task.done():
        existing.task.cancel()
    task_state = CouncilTask(conversation_id=conversation_id)
    _tasks[conversation_id] = task_state
    return task_state


def cancel_task(conversation_id: str) -> bool:
    """Cancel a running task. Returns True if a task was cancelled."""
    task_state = _tasks.get(conversation_id)
    if not task_state or not task_state.task:
        return False
    if task_state.status != "running":
        return False
    task_state.task.cancel()
    return True


def remove_task(conversation_id: str) -> None:
    """Remove a completed task from the registry."""
    _tasks.pop(conversation_id, None)


async def subscribe(conversation_id: str):
    """Async generator yielding events. Replays buffered events, then live.

    CRITICAL: Subscribes to the queue FIRST, then replays buffered events,
    using an index to avoid the TOCTOU gap where events arrive between
    replay and subscription.

    Yields dicts like {"type": "stage1_complete", "data": ...}.
    Returns when task completes or is removed.
    Safe to call even if no task is running (yields nothing).
    """
    task_state = _tasks.get(conversation_id)
    if not task_state:
        return

    # Subscribe to queue FIRST to avoid missing events during replay
    queue: asyncio.Queue = asyncio.Queue()
    task_state.subscribers.append(queue)
    try:
        # Snapshot the current event count, then replay
        replay_count = len(task_state.events)
        for event in task_state.events[:replay_count]:
            yield event

        # If task already finished and no new events queued, we're done
        if task_state.status != "running" and queue.empty():
            return

        # Drain live events (dedup against replayed ones by index)
        events_yielded = replay_count
        while True:
            event = await queue.get()
            if event is None:  # Sentinel: task finished
                break
            # Events broadcast during replay are already in the queue
            # but were also yielded in the replay loop. Use the global
            # events list position to detect duplicates.
            try:
                idx = task_state.events.index(event)
            except ValueError:
                idx = events_yielded
            if idx < replay_count:
                continue  # Already replayed
            events_yielded += 1
            yield event
    finally:
        if queue in task_state.subscribers:
            task_state.subscribers.remove(queue)
