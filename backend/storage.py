"""JSON-based storage for conversations."""

import json
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, TypeVar
from pathlib import Path
from filelock import FileLock
from .config import DATA_DIR

# Ensure data directory exists once at module load
Path(DATA_DIR).mkdir(parents=True, exist_ok=True)

# UUID pattern for conversation IDs (prevents path traversal)
_UUID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.IGNORECASE)

T = TypeVar('T')


def _validate_conversation_id(conversation_id: str) -> None:
    """Validate conversation ID is a valid UUID to prevent path traversal."""
    if not _UUID_PATTERN.match(conversation_id):
        raise ValueError(f"Invalid conversation ID format: {conversation_id}")


def _get_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    _validate_conversation_id(conversation_id)
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


def _get_lock(conversation_id: str) -> FileLock:
    """Get a file lock for a specific conversation to prevent race conditions."""
    return FileLock(_get_path(conversation_id) + ".lock", timeout=30)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Write data to JSON file with consistent formatting."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    """Read JSON file if it exists, return None otherwise."""
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """Create a new conversation and return it."""
    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "messages": []
    }
    with _get_lock(conversation_id):
        _write_json(_get_path(conversation_id), conversation)
    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Load a conversation from storage, or None if not found."""
    return _read_json(_get_path(conversation_id))


def list_conversations() -> List[Dict[str, Any]]:
    """List all conversations (metadata only), sorted newest first."""
    conversations = []
    for filename in os.listdir(DATA_DIR):
        if not filename.endswith('.json'):
            continue
        data = _read_json(os.path.join(DATA_DIR, filename))
        if data:
            conversations.append({
                "id": data["id"],
                "created_at": data["created_at"],
                "title": data.get("title", "New Conversation"),
                "message_count": len(data["messages"])
            })
    conversations.sort(key=lambda x: x["created_at"], reverse=True)
    return conversations


def _load_and_save(conversation_id: str, modifier: Callable[[Dict[str, Any]], T]) -> T:
    """
    Load a conversation, apply a modifier function, and save atomically.

    The modifier function receives the conversation dict and can modify it in place.
    It can optionally return a value which will be returned from this function.
    """
    path = _get_path(conversation_id)
    with _get_lock(conversation_id):
        conversation = _read_json(path)
        if conversation is None:
            raise ValueError(f"Conversation {conversation_id} not found")
        result = modifier(conversation)
        _write_json(path, conversation)
        return result


def add_user_message(conversation_id: str, content: str) -> None:
    """Add a user message to a conversation."""
    def modifier(conv):
        conv["messages"].append({"role": "user", "content": content})
    _load_and_save(conversation_id, modifier)


def add_user_message_atomic(conversation_id: str, content: str) -> bool:
    """
    Add a user message and return whether this is the first message.

    This atomic operation prevents race conditions where two concurrent requests
    both think they're the first message.

    Returns:
        True if this was the first message in the conversation
    """
    def modifier(conv):
        is_first = len(conv["messages"]) == 0
        conv["messages"].append({"role": "user", "content": content})
        return is_first
    return _load_and_save(conversation_id, modifier)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
) -> None:
    """Add an assistant message with all 3 stages to a conversation."""
    def modifier(conv):
        conv["messages"].append({
            "role": "assistant",
            "stage1": stage1,
            "stage2": stage2,
            "stage3": stage3,
            "status": "complete"
        })
    _load_and_save(conversation_id, modifier)


def create_assistant_message(conversation_id: str) -> int:
    """Create an empty assistant message placeholder and return its index."""
    def modifier(conv):
        conv["messages"].append({
            "role": "assistant",
            "status": "in_progress",
            "stage1": None,
            "stage2": None,
            "stage3": None
        })
        return len(conv["messages"]) - 1
    return _load_and_save(conversation_id, modifier)


def update_assistant_message(conversation_id: str, message_index: int, **updates) -> None:
    """Update an existing assistant message with new stage data."""
    def modifier(conv):
        if message_index >= len(conv["messages"]):
            raise ValueError(f"Message index {message_index} out of range")
        message = conv["messages"][message_index]
        if message["role"] != "assistant":
            raise ValueError(f"Message at index {message_index} is not an assistant message")
        message.update(updates)
    _load_and_save(conversation_id, modifier)


def update_conversation_title(conversation_id: str, title: str) -> None:
    """Update the title of a conversation."""
    def modifier(conv):
        conv["title"] = title
    _load_and_save(conversation_id, modifier)
