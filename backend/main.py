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
from .council import (
    run_full_council, generate_conversation_title,
    stage1_collect_responses, stage2a_select_axes, stage2b_collect_scores,
    stage3_synthesize_final, calculate_aggregate_scores
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
        draft=request.draft
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
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
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


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists (early validation before starting stream)
    if storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        msg_index = None
        title_task = None
        try:
            # Add user message atomically and check if first (prevents race condition)
            is_first_message = storage.add_user_message_atomic(conversation_id, request.content)

            # Create assistant message placeholder BEFORE stage 1
            msg_index = storage.create_assistant_message(conversation_id)

            # Start title generation in parallel (don't await yet)
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content)
            # Save incrementally after stage 1
            storage.update_assistant_message(
                conversation_id, msg_index,
                stage1=stage1_results, status="stage1_complete"
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2a: Chairman selects evaluation axes
            axes = await stage2a_select_axes(request.content)
            storage.update_assistant_message(
                conversation_id, msg_index,
                axes=axes
            )
            yield f"data: {json.dumps({'type': 'axes_complete', 'data': axes})}\n\n"

            # Stage 2b: Collect scores
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2b_collect_scores(request.content, stage1_results, axes)
            aggregate_scores = calculate_aggregate_scores(stage2_results, label_to_model, axes)
            # Save incrementally after stage 2
            storage.update_assistant_message(
                conversation_id, msg_index,
                stage2=stage2_results, status="stage2_complete"
            )
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'axes': axes, 'aggregate_scores': aggregate_scores}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results, axes, aggregate_scores)
            # Save incrementally after stage 3 (complete)
            storage.update_assistant_message(
                conversation_id, msg_index,
                stage3=stage3_result, status="complete"
            )
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Save markdown output
            metadata = {'axes': axes, 'aggregate_scores': aggregate_scores, 'label_to_model': label_to_model}
            md_path = save_council_markdown(
                request.content, stage1_results, stage2_results, stage3_result, metadata
            )
            yield f"data: {json.dumps({'type': 'markdown_saved', 'data': {'path': md_path}})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Mark the assistant message as errored if it was created
            if msg_index is not None:
                try:
                    storage.update_assistant_message(
                        conversation_id, msg_index,
                        status="error", error=str(e)
                    )
                except Exception:
                    pass  # Best effort - don't mask the original error
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Cancel title task if still running (e.g., client disconnected)
            if title_task and not title_task.done():
                title_task.cancel()
                try:
                    await title_task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
