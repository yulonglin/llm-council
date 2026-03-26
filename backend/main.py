"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from pathlib import Path
import time as _time

from . import storage
from . import tasks
from .council import (
    run_full_council,
    generate_conversation_title,
    stage0_analyze_query,
    stage0_rewrite_with_answers,
    stage1_collect_responses,
    stage2a_select_axes,
    stage2b_collect_scores,
    stage3_synthesize_final,
    calculate_aggregate_scores,
)

COUNCIL_RUNS_DIR = Path("data/council_runs")


def save_council_markdown(
    query: str,
    stage1_results: list,
    stage2_results: list,
    stage3_result: dict,
    metadata: dict,
) -> str:
    """Save a council run as markdown. Returns the output file path."""
    COUNCIL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    out_path = COUNCIL_RUNS_DIR / f"run_{ts}.md"

    axes = metadata.get("axes", [])
    aggregate_scores = metadata.get("aggregate_scores", [])
    axis_names = [a["name"] for a in axes]

    lines = [
        f"# LLM Council Run — {ts}\n",
        f"**Query:** {query[:200]}{'...' if len(query) > 200 else ''}\n",
    ]

    if axis_names and aggregate_scores:
        lines.append("## Aggregate Scores\n")
        lines.append(f"| Model | {' | '.join(axis_names)} | Overall |")
        lines.append(f"|{'|'.join(['---'] * (len(axis_names) + 2))}|")
        for agg in aggregate_scores:
            short = agg["model"].split("/")[-1]
            scores = [str(agg["axis_scores"].get(n, "N/A")) for n in axis_names]
            lines.append(f"| {short} | {' | '.join(scores)} | {agg['overall_score']} |")
        lines.append("")

    lines.append("\n---\n")
    lines.append("## Final Synthesis\n")
    lines.append(stage3_result.get("response", ""))

    lines.append("\n---\n")
    lines.append("## Individual Responses\n")
    for r in stage1_results:
        short = r["model"].split("/")[-1]
        lines.append(f"<details>\n<summary>{short}</summary>\n")
        lines.append(r.get("response", ""))
        lines.append("\n</details>\n")

    out_path.write_text("\n".join(lines))
    return str(out_path)


app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""

    content: str
    skip_rewrite: bool = False


class UpdateConversationRequest(BaseModel):
    """Request to update conversation metadata."""

    title: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    draft: Optional[str] = None


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""

    id: str
    created_at: str
    title: str
    message_count: int
    pinned: bool
    archived: bool
    has_draft: bool


class Conversation(BaseModel):
    """Full conversation with all messages."""

    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]
    pinned: bool
    archived: bool
    draft: str


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations(include_archived: bool = False):
    """List all conversations (metadata only)."""
    return storage.list_conversations(include_archived=include_archived)


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.patch("/api/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: UpdateConversationRequest):
    """Update conversation metadata (pinned, archived, draft, title)."""
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    updated = storage.update_conversation_fields(
        conversation_id,
        title=request.title,
        pinned=request.pinned,
        archived=request.archived,
        draft=request.draft,
    )
    return updated


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.delete_conversation(conversation_id)
    return {"status": "deleted"}


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Add user message atomically and check if first (prevents race condition)
    is_first_message = storage.add_user_message_atomic(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id, stage1_results, stage2_results, stage3_result
    )

    # Save markdown output
    md_path = save_council_markdown(
        request.content, stage1_results, stage2_results, stage3_result, metadata
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata,
        "markdown_path": md_path,
    }


async def _run_council_background(
    conversation_id: str, msg_index: int, query: str, title_task
):
    """Run council stages 1-3 as a background task, broadcasting events via task registry.

    This runs independently of any SSE subscriber connections. If all clients
    disconnect, the task continues to completion and results are persisted to storage.
    """
    try:
        # Stage 1: Collect responses
        tasks.broadcast(conversation_id, {"type": "stage1_start"})
        stage1_results = await stage1_collect_responses(query)
        storage.update_assistant_message(
            conversation_id, msg_index, stage1=stage1_results, status="stage1_complete"
        )
        tasks.broadcast(
            conversation_id, {"type": "stage1_complete", "data": stage1_results}
        )

        # Stage 2a: Chairman selects evaluation axes
        axes = await stage2a_select_axes(query)
        storage.update_assistant_message(conversation_id, msg_index, axes=axes)
        tasks.broadcast(conversation_id, {"type": "axes_complete", "data": axes})

        # Stage 2b: Collect scores
        tasks.broadcast(conversation_id, {"type": "stage2_start"})
        stage2_results, label_to_model = await stage2b_collect_scores(
            query, stage1_results, axes
        )
        aggregate_scores = calculate_aggregate_scores(
            stage2_results, label_to_model, axes
        )
        metadata = {
            "label_to_model": label_to_model,
            "axes": axes,
            "aggregate_scores": aggregate_scores,
        }
        storage.update_assistant_message(
            conversation_id,
            msg_index,
            stage2=stage2_results,
            status="stage2_complete",
            metadata=metadata,
        )
        tasks.broadcast(
            conversation_id,
            {
                "type": "stage2_complete",
                "data": stage2_results,
                "metadata": metadata,
            },
        )

        # Stage 3: Synthesize final answer
        tasks.broadcast(conversation_id, {"type": "stage3_start"})
        stage3_result = await stage3_synthesize_final(
            query, stage1_results, stage2_results, axes, aggregate_scores
        )
        storage.update_assistant_message(
            conversation_id, msg_index, stage3=stage3_result, status="complete"
        )
        tasks.broadcast(
            conversation_id, {"type": "stage3_complete", "data": stage3_result}
        )

        # Save markdown output
        md_path = save_council_markdown(
            query, stage1_results, stage2_results, stage3_result, metadata
        )
        tasks.broadcast(
            conversation_id, {"type": "markdown_saved", "data": {"path": md_path}}
        )

        # Wait for title generation if it was started
        if title_task:
            title = await title_task
            storage.update_conversation_title(conversation_id, title)
            tasks.broadcast(
                conversation_id, {"type": "title_complete", "data": {"title": title}}
            )

        tasks.broadcast(conversation_id, {"type": "complete"})
        tasks.complete_task(conversation_id)

    except asyncio.CancelledError:
        try:
            storage.update_assistant_message(
                conversation_id, msg_index, status="cancelled"
            )
        except Exception:
            pass
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


class ClarifyRequest(BaseModel):
    """Request to send clarification answers."""

    answers: List[Dict[str, str]]  # list of {"question": str, "answer": str}


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the council process (Stage 0 + Stages 1-3).

    Stage 0 runs inline (may need clarification from client).
    Stages 1-3 run as a background task that survives client disconnection.
    Returns Server-Sent Events as each stage completes.
    """
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

            # Stage 0: Query analysis (runs inline — may need clarification)
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
                _run_council_background(
                    conversation_id, msg_index, rewritten_query, title_task
                )
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
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/conversations/{conversation_id}/clarify/stream")
async def send_clarification_stream(conversation_id: str, request: ClarifyRequest):
    """
    Send clarification answers and continue the council process.
    Stage 0 rewrite runs inline, then stages 1-3 run as a background task.
    """
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        title_task = None
        try:
            conv = storage.get_conversation(conversation_id)

            # Find the last assistant message awaiting clarification
            msg_index = None
            for i in range(len(conv["messages"]) - 1, -1, -1):
                msg = conv["messages"][i]
                if (
                    msg.get("role") == "assistant"
                    and msg.get("status") == "awaiting_clarification"
                ):
                    msg_index = i
                    break

            if msg_index is None:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No message awaiting clarification'})}\n\n"
                return

            # Get original query from the user message just before
            original_query = conv["messages"][msg_index - 1].get("content", "")
            questions = (
                conv["messages"][msg_index].get("stage0", {}).get("questions", [])
            )

            # Rewrite query with clarification answers (inline — fast)
            rewritten_query = await stage0_rewrite_with_answers(
                original_query, questions, request.answers
            )
            storage.update_assistant_message(
                conversation_id,
                msg_index,
                clarification_answers=request.answers,
                rewritten_query=rewritten_query,
            )
            yield f"data: {json.dumps({'type': 'stage0_complete', 'data': {'rewritten_query': rewritten_query}})}\n\n"

            # Start title generation if this is the first exchange
            is_first = msg_index <= 1
            if is_first:
                title_task = asyncio.create_task(
                    generate_conversation_title(original_query)
                )

            # Register placeholder FIRST, then create task
            task_state = tasks.register_task(conversation_id)
            bg_task = asyncio.create_task(
                _run_council_background(
                    conversation_id, msg_index, rewritten_query, title_task
                )
            )
            task_state.task = bg_task

            # Subscribe to events from the background task
            async for event in tasks.subscribe(conversation_id):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# --- Reconnection & task management endpoints ---


@app.get("/api/conversations/{conversation_id}/subscribe")
async def subscribe_to_task(conversation_id: str):
    """Subscribe to a running council task's event stream.

    If a task is running, replays buffered events then streams live events.
    If no task is running, returns a no_active_task event.
    """
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        if tasks.get_task(conversation_id):
            async for event in tasks.subscribe(conversation_id):
                yield f"data: {json.dumps(event)}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'no_active_task'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/conversations/{conversation_id}/cancel")
async def cancel_council_task(conversation_id: str):
    """Cancel a running council task."""
    cancelled = tasks.cancel_task(conversation_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="No running task to cancel")
    return {"cancelled": True}


@app.get("/api/conversations/{conversation_id}/task-status")
async def get_task_status(conversation_id: str):
    """Check if a council task is running for this conversation."""
    return {"running": tasks.is_running(conversation_id)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
