# Parallel Background Conversations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable multiple council conversations to run in parallel, continuing to completion even when the user navigates away or closes the browser tab.

**Architecture:** Decouple council execution from SSE streams using in-process `asyncio.create_task()` with an in-memory task registry. Background tasks produce events that are buffered and broadcast to any connected SSE subscribers. Reconnecting clients replay buffered events, then receive live updates. Storage is updated after each stage as before, so partial results survive server restarts.

**Tech Stack:** Python asyncio (no new dependencies), FastAPI SSE, React

---

## Current State

- Backend uses FastAPI with async SSE streaming per request
- Council execution is tied to the SSE generator — if client disconnects, the generator stops
- Storage already updates atomically after each stage (`status: "in_progress"` → `"stage1_complete"` → etc.)
- Frontend tracks loading state via `loadingConversationIds` Set and `activeStreamsRef` Map
- Metadata (axes, aggregate_scores, label_to_model) is ephemeral — NOT persisted to storage

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/tasks.py` | **CREATE** | Task registry: start, track, subscribe, broadcast |
| `backend/main.py` | **MODIFY** | Use task registry; add subscribe endpoint; remove SSE-coupled execution |
| `backend/storage.py` | **MODIFY** | Persist metadata in assistant messages |
| `frontend/src/api.js` | **MODIFY** | Add subscribe endpoint; add status check |
| `frontend/src/App.jsx` | **MODIFY** | Auto-reconnect to running tasks on load/navigate |

---

### Task 1: Persist metadata in storage

Currently metadata (label_to_model, axes, aggregate_scores) is ephemeral — only returned in the SSE stream. This must be persisted so reconnecting clients can display complete Stage 2 data.

**Files:**
- Modify: `backend/main.py:253-255` (already calls `update_assistant_message` for stage2, just need to include metadata)
- Modify: `frontend/src/App.jsx:94-103` (loadConversation should read metadata from stored message)

- [ ] **Step 1: Persist metadata in stage2 storage update**

In `backend/main.py`, the `_run_stages_1_through_3` generator already calls `storage.update_assistant_message()` after stage2. Add metadata fields:

```python
# In _run_stages_1_through_3, after stage2b completes (~line 253):
storage.update_assistant_message(
    conversation_id, msg_index,
    stage2=stage2_results,
    status="stage2_complete",
    metadata={
        "label_to_model": label_to_model,
        "axes": axes,
        "aggregate_scores": aggregate_scores,
    },
)
```

- [ ] **Step 2: Frontend reads metadata from stored messages**

In `frontend/src/App.jsx`, when `loadConversation()` fetches a conversation, assistant messages may already have `metadata` from storage. The existing rendering code in `Stage2.jsx` reads `msg.metadata` — verify it works with stored metadata. No change needed if the field name matches.

Check: In `ChatInterface.jsx`, how does it pass metadata to Stage2? Ensure the prop path works for both live (SSE) and loaded (storage) messages.

- [ ] **Step 3: Test — reload page mid-conversation, verify Stage 2 shows metadata**

Start a council run, wait for Stage 2 to complete, hard-refresh the page. Verify axes, scores, and label_to_model display correctly.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: persist stage2 metadata (axes, scores, label_to_model) to storage"
```

---

### Task 2: Create task registry (`backend/tasks.py`)

The core infrastructure: an in-memory registry that tracks running council tasks, buffers their events, and supports multiple SSE subscribers.

**Files:**
- Create: `backend/tasks.py`

- [ ] **Step 1: Write the task registry module**

```python
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


# Global registry: conversation_id → CouncilTask
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
    asyncio.get_running_loop().call_later(900, lambda: _tasks.pop(conversation_id, None))


def register_task(conversation_id: str) -> CouncilTask:
    """Register a placeholder task entry BEFORE creating the asyncio.Task.

    This eliminates the race where create_task() starts the coroutine
    before register_task() runs, causing broadcast() to silently drop events.

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

        # Drain live events (skip any that were already replayed)
        events_seen = replay_count
        while True:
            event = await queue.get()
            if event is None:  # Sentinel: task finished
                break
            # Skip events we already replayed (they were broadcast while
            # we were yielding the replay)
            event_index = task_state.events.index(event) if event in task_state.events else events_seen
            if event_index < replay_count:
                continue
            events_seen += 1
            yield event
    finally:
        if queue in task_state.subscribers:
            task_state.subscribers.remove(queue)
```

- [ ] **Step 2: Commit**

```bash
git add backend/tasks.py
git commit -m "feat: add in-memory task registry for background council runs"
```

---

### Task 3: Background council execution in `main.py`

Refactor `_run_stages_1_through_3` from an SSE generator into a background task that uses the task registry to broadcast events. The SSE endpoints become thin subscribers.

**Files:**
- Modify: `backend/main.py:232-287` (refactor `_run_stages_1_through_3`)
- Modify: `backend/main.py:295-373` (`send_message_stream` endpoint)
- Modify: `backend/main.py:1-26` (imports)

- [ ] **Step 1: Add imports for task registry**

At top of `main.py`, add:
```python
from . import tasks
```

- [ ] **Step 2: Convert `_run_stages_1_through_3` from generator to background coroutine**

Replace the async generator with a plain async function that broadcasts events via the task registry:

```python
async def _run_council_background(conversation_id: str, msg_index: int, query: str, title_task):
    """Run council stages 1-3 as a background task, broadcasting events via task registry."""
    try:
        # Stage 1
        tasks.broadcast(conversation_id, {"type": "stage1_start"})
        stage1_results = await stage1_collect_responses(query)
        storage.update_assistant_message(
            conversation_id, msg_index, stage1=stage1_results, status="stage1_complete"
        )
        tasks.broadcast(conversation_id, {"type": "stage1_complete", "data": stage1_results})

        # Stage 2a: axes
        axes = await stage2a_select_axes(query)
        storage.update_assistant_message(conversation_id, msg_index, axes=axes)
        tasks.broadcast(conversation_id, {"type": "axes_complete", "data": axes})

        # Stage 2b: scores
        tasks.broadcast(conversation_id, {"type": "stage2_start"})
        stage2_results, label_to_model = await stage2b_collect_scores(query, stage1_results, axes)
        aggregate_scores = calculate_aggregate_scores(stage2_results, label_to_model, axes)
        metadata = {
            "label_to_model": label_to_model,
            "axes": axes,
            "aggregate_scores": aggregate_scores,
        }
        storage.update_assistant_message(
            conversation_id, msg_index,
            stage2=stage2_results, status="stage2_complete", metadata=metadata,
        )
        tasks.broadcast(conversation_id, {
            "type": "stage2_complete",
            "data": stage2_results,
            "metadata": metadata,
        })

        # Stage 3
        tasks.broadcast(conversation_id, {"type": "stage3_start"})
        stage3_result = await stage3_synthesize_final(
            query, stage1_results, stage2_results, axes, aggregate_scores
        )
        storage.update_assistant_message(
            conversation_id, msg_index, stage3=stage3_result, status="complete"
        )
        tasks.broadcast(conversation_id, {"type": "stage3_complete", "data": stage3_result})

        # Save markdown
        md_path = save_council_markdown(query, stage1_results, stage2_results, stage3_result, metadata)
        tasks.broadcast(conversation_id, {"type": "markdown_saved", "data": {"path": md_path}})

        # Title
        if title_task:
            title = await title_task
            storage.update_conversation_title(conversation_id, title)
            tasks.broadcast(conversation_id, {"type": "title_complete", "data": {"title": title}})

        tasks.broadcast(conversation_id, {"type": "complete"})
        tasks.complete_task(conversation_id)

    except asyncio.CancelledError:
        storage.update_assistant_message(conversation_id, msg_index, status="cancelled")
        tasks.complete_task(conversation_id, "cancelled")
    except Exception as e:
        try:
            storage.update_assistant_message(
                conversation_id, msg_index, status="error", error=str(e)
            )
        except Exception:
            pass
        tasks.broadcast(conversation_id, {"type": "error", "message": str(e)})
        tasks.complete_task(conversation_id, "error")
    finally:
        if title_task and not title_task.done():
            title_task.cancel()
            try:
                await title_task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 3: Refactor `send_message_stream` to start background task + subscribe**

The endpoint now:
1. Creates the assistant message placeholder (as before)
2. Runs Stage 0 inline (fast, needs client interaction for clarification)
3. Starts the council as a background `asyncio.create_task()`
4. Subscribes to the task's event stream via SSE

```python
@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        msg_index = None
        title_task = None
        try:
            is_first_message = storage.add_user_message_atomic(
                conversation_id, request.content
            )
            msg_index = storage.create_assistant_message(conversation_id)

            if is_first_message:
                title_task = asyncio.create_task(
                    generate_conversation_title(request.content)
                )

            # Stage 0 runs inline (may need clarification)
            if request.skip_rewrite:
                rewritten_query = request.content
                yield f"data: {json.dumps({'type': 'stage0_complete', 'data': {'rewritten_query': None, 'skipped': True}})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'stage0_start'})}\n\n"
                stage0_result = await stage0_analyze_query(request.content)
                storage.update_assistant_message(
                    conversation_id, msg_index, stage0=stage0_result
                )

                if stage0_result["needs_clarification"]:
                    storage.update_assistant_message(
                        conversation_id, msg_index, status="awaiting_clarification"
                    )
                    yield f"data: {json.dumps({'type': 'clarification_needed', 'data': {'questions': stage0_result['questions']}})}\n\n"
                    yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return

                rewritten_query = stage0_result.get("rewritten_query") or request.content
                storage.update_assistant_message(
                    conversation_id, msg_index, rewritten_query=rewritten_query
                )
                yield f"data: {json.dumps({'type': 'stage0_complete', 'data': {'rewritten_query': rewritten_query}})}\n\n"

            # Register placeholder FIRST, then create task (prevents event drop race)
            task_state = tasks.register_task(conversation_id)
            bg_task = asyncio.create_task(
                _run_council_background(conversation_id, msg_index, rewritten_query, title_task)
            )
            task_state.task = bg_task

            # Subscribe to events from the background task
            async for event in tasks.subscribe(conversation_id):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            if msg_index is not None:
                try:
                    storage.update_assistant_message(
                        conversation_id, msg_index, status="error", error=str(e)
                    )
                except Exception:
                    pass
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

- [ ] **Step 4: Test — start a council run, verify it works identically to before**

Run backend, send a message, confirm SSE events arrive and conversation completes normally.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "refactor: decouple council execution from SSE stream using background tasks"
```

---

### Task 4: Subscribe endpoint for reconnecting clients

Add a GET endpoint that lets clients reconnect to a running council task after navigating away and back.

**Files:**
- Modify: `backend/main.py` (add new endpoint)

- [ ] **Step 1: Add subscribe endpoint**

```python
@app.get("/api/conversations/{conversation_id}/subscribe")
async def subscribe_to_task(conversation_id: str):
    """Subscribe to a running council task's event stream.

    If a task is running, replays buffered events then streams live events.
    If no task is running, returns the conversation's current state as a single event.
    """
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        if tasks.is_running(conversation_id):
            async for event in tasks.subscribe(conversation_id):
                yield f"data: {json.dumps(event)}\n\n"
        else:
            # No running task — send current state from storage
            yield f"data: {json.dumps({'type': 'no_active_task'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

- [ ] **Step 2: Add cancel endpoint**

```python
@app.post("/api/conversations/{conversation_id}/cancel")
async def cancel_task(conversation_id: str):
    """Cancel a running council task."""
    cancelled = tasks.cancel_task(conversation_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="No running task to cancel")
    return {"cancelled": True}
```

- [ ] **Step 3: Add status check endpoint (lightweight, no SSE)**

```python
@app.get("/api/conversations/{conversation_id}/task-status")
async def get_task_status(conversation_id: str):
    """Check if a council task is running for this conversation."""
    return {"running": tasks.is_running(conversation_id)}
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: add subscribe and task-status endpoints for reconnection"
```

---

### Task 5: Refactor clarification flow to use background tasks

The clarification endpoint (`/clarify/stream`) also needs to use background tasks so it survives disconnection.

**Files:**
- Modify: `backend/main.py:376+` (clarify endpoint)

- [ ] **Step 1: Refactor `send_clarification_stream` to use background task**

Same pattern as Task 3: Stage 0 rewrite runs inline, then stages 1-3 run as background task.

Read the existing `send_clarification_stream` implementation, then apply the same refactoring:
1. Find the assistant message awaiting clarification
2. Run stage0 rewrite inline
3. Start `_run_council_background()` as a background task
4. Subscribe to events

- [ ] **Step 2: Test — start a conversation that triggers clarification, provide answers, verify it completes**

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "refactor: clarification flow uses background tasks for resilience"
```

---

### Task 6: Frontend — add subscribe API method

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: Add `subscribeToTask` method**

```javascript
async subscribeToTask(conversationId, onEvent, { signal } = {}) {
    const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/subscribe`,
        { signal }
    );

    if (!response.ok) {
        throw new Error('Failed to subscribe to task');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const event = JSON.parse(line.slice(6));
                    onEvent(event.type, event);
                } catch (e) {
                    console.error('Failed to parse SSE event:', e);
                }
            }
        }
    }
},
```

- [ ] **Step 2: Add `cancelTask` method**

```javascript
async cancelTask(conversationId) {
    const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/cancel`,
        { method: 'POST' }
    );
    return response.ok;
},
```

- [ ] **Step 3: Add `getTaskStatus` method**

```javascript
async getTaskStatus(conversationId) {
    const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/task-status`
    );
    if (!response.ok) throw new Error('Failed to get task status');
    return response.json();
},
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat: add subscribe and task-status API methods"
```

---

### Task 7: Frontend — auto-reconnect to running tasks

When the user navigates to a conversation (or reloads the page), detect if a council task is running and reconnect.

**Files:**
- Modify: `frontend/src/App.jsx:94-103` (`loadConversation`)
- Modify: `frontend/src/App.jsx:273-482` (event handler extraction)

- [ ] **Step 1: Extract SSE event handler into a reusable function**

The event handler logic inside `handleSendMessage` (lines 344-460) is duplicated between sending and reconnecting. Extract it:

```javascript
// Place near the top of the App component, after state declarations
const handleCouncilEvent = (targetId, eventType, event) => {
    // ... same switch statement as currently in handleSendMessage lines 345-459 ...
    // This is the unified handler for both initial sends and reconnections
};
```

Then `handleSendMessage` calls:
```javascript
await api.sendMessageStream(targetId, content, (eventType, event) => {
    handleCouncilEvent(targetId, eventType, event);
}, { signal: abortController.signal, skipRewrite: !queryRewriteEnabled });
```

- [ ] **Step 2: Auto-reconnect in `loadConversation`**

After loading a conversation from storage, check if a task is running. If so, subscribe:

```javascript
const loadConversation = async (id) => {
    try {
        const conv = await api.getConversation(id);
        setCurrentConversation(conv);

        // Check if there's a running council task to reconnect to
        const lastMsg = conv.messages?.[conv.messages.length - 1];
        if (lastMsg?.role === 'assistant' && lastMsg.status !== 'complete' && lastMsg.status !== 'error') {
            const { running } = await api.getTaskStatus(id);
            if (running) {
                // Reconnect to the running task
                setLoadingConversationIds(prev => new Set(prev).add(id));
                const abortController = new AbortController();
                activeStreamsRef.current.set(id, abortController);

                api.subscribeToTask(id, (eventType, event) => {
                    handleCouncilEvent(id, eventType, event);
                }, { signal: abortController.signal }).catch(err => {
                    if (err.name !== 'AbortError') {
                        console.error('Subscribe error:', err);
                    }
                });
            }
        }
    } catch (error) {
        console.error('Failed to load conversation:', error);
        setCurrentConversationId(null);
        setCurrentConversation(null);
    }
};
```

- [ ] **Step 3: Update `handleCancelStream` to call cancel endpoint**

The existing cancel handler only aborts the local SSE subscriber. Now it must also cancel the background task:

```javascript
const handleCancelStream = () => {
    if (!currentConversationId) return;
    const controller = activeStreamsRef.current.get(currentConversationId);
    if (controller) {
        controller.abort();
        activeStreamsRef.current.delete(currentConversationId);
    }
    // Cancel the background task on the server
    api.cancelTask(currentConversationId).catch(() => {});
    setLoadingConversationIds(prev => {
        const next = new Set(prev);
        next.delete(currentConversationId);
        return next;
    });
    // Mark last assistant message as cancelled
    setCurrentConversation((prev) => {
        if (!prev) return prev;
        const messages = [...prev.messages];
        const lastMsg = { ...messages[messages.length - 1] };
        if (lastMsg.role === 'assistant') {
            lastMsg.loading = { stage0: false, stage1: false, stage2: false, stage3: false };
            lastMsg.cancelled = true;
            messages[messages.length - 1] = lastMsg;
        }
        return { ...prev, messages };
    });
};
```

- [ ] **Step 4: Show loading indicator in sidebar for conversations with running tasks**

The sidebar already uses `loadingConversationIds` to show a spinner. When reconnecting, we add to this set (Step 2 above). No additional sidebar changes needed.

- [ ] **Step 4: Test full reconnection flow**

1. Start a council run on conversation A
2. Navigate to a different conversation (or create a new one)
3. Navigate back to conversation A — verify it reconnects and shows live progress
4. Start another council run on conversation B while A is still running — verify both work

- [ ] **Step 5: Test tab close + reopen flow**

1. Start a council run
2. Close the browser tab
3. Reopen the app — navigate to the conversation
4. If the server is still running, the task should be complete (or still running) — verify correct display

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.jsx
git commit -m "feat: auto-reconnect to running council tasks on navigation/reload"
```

---

### Task 8: Handle stale in-progress messages (server restart edge case)

If the server restarts while a council is running, the conversation will have `status: "in_progress"` but no running task. Handle this gracefully.

**Files:**
- Modify: `frontend/src/App.jsx` (loadConversation)
- Modify: `frontend/src/components/ChatInterface.jsx` (render stale state)

- [ ] **Step 1: Frontend detects stale in-progress and shows retry option**

In `loadConversation` (Task 7 Step 2), when `lastMsg.status !== 'complete'` but `running === false`:

```javascript
if (!running) {
    // Stale in-progress: server probably restarted. Show as incomplete.
    setCurrentConversation(prev => {
        if (!prev || prev.id !== id) return prev;
        const messages = [...prev.messages];
        const lastMsg = { ...messages[messages.length - 1] };
        lastMsg.stale = true;  // Flag for UI
        lastMsg.loading = { stage0: false, stage1: false, stage2: false, stage3: false };
        messages[messages.length - 1] = lastMsg;
        return { ...prev, messages };
    });
}
```

- [ ] **Step 2: Show "interrupted" indicator in ChatInterface for stale messages**

In `ChatInterface.jsx`, when rendering an assistant message with `msg.stale === true`, show a subtle indicator:

```jsx
{msg.stale && (
    <div className="stale-indicator">
        Council run was interrupted (server restarted). Partial results shown above.
    </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.jsx frontend/src/components/ChatInterface.jsx
git commit -m "feat: detect and display stale interrupted council runs"
```

---

### Task 9: Verify cleanup works (already built into Task 2)

Auto-cleanup was integrated into `complete_task()` in Task 2 using `asyncio.get_running_loop().call_later(900, ...)` (15 minutes). No separate task needed — just verify it works.

- [ ] **Step 1: Verify cleanup**

After a council run completes, confirm the task is removed from the registry after 15 minutes. For testing, temporarily reduce to 30 seconds:

```python
# Temporarily in tasks.py for testing:
asyncio.get_running_loop().call_later(30, lambda: _tasks.pop(conversation_id, None))
```

Check with: `GET /api/conversations/{id}/task-status` → should return `{"running": false}` after cleanup.

- [ ] **Step 2: Restore 15-minute timer and commit if any changes needed**

---

### Task 10: End-to-end testing

**Files:** No new files — manual testing

- [ ] **Step 1: Test parallel conversations**

1. Open conversation A, send a message → council starts
2. Create conversation B, send a different message → second council starts
3. Both should progress independently — switch between them and verify
4. Both complete successfully with full results

- [ ] **Step 2: Test navigate-away resilience**

1. Start a council run on conversation A
2. Click on a different conversation in the sidebar
3. Wait a few seconds, click back to conversation A
4. Verify: reconnects to running task, shows live progress, completes normally

- [ ] **Step 3: Test tab close resilience**

1. Start a council run
2. Close the browser tab entirely
3. Wait 30+ seconds (let it finish)
4. Reopen the app, navigate to that conversation
5. Verify: shows complete results from storage

- [ ] **Step 4: Test cancel button still works**

1. Start a council run
2. Click cancel
3. Verify: task stops, status shows cancelled, no zombie tasks in registry

- [ ] **Step 5: Test error handling**

1. Temporarily misconfigure API key
2. Start a council run
3. Verify: error propagates correctly, conversation shows error status

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in e2e testing"
```
