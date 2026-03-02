"""Disk-based LLM response cache keyed by (model, messages) hash."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

CACHE_DIR = Path("data/cache")


def _cache_key(model: str, messages: List[Dict[str, str]]) -> str:
    """Deterministic hash of model + messages."""
    payload = json.dumps({"model": model, "messages": messages}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get(model: str, messages: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Return cached response or None."""
    path = CACHE_DIR / f"{_cache_key(model, messages)}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def put(model: str, messages: List[Dict[str, str]], response: Dict[str, Any]) -> None:
    """Store a response in cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{_cache_key(model, messages)}.json"
    with open(path, "w") as f:
        json.dump(response, f)


def clear() -> int:
    """Remove all cached entries. Returns count of removed files."""
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for p in CACHE_DIR.glob("*.json"):
        p.unlink()
        count += 1
    return count


def stats() -> Dict[str, Any]:
    """Return cache statistics."""
    if not CACHE_DIR.exists():
        return {"entries": 0, "size_bytes": 0}
    files = list(CACHE_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files)
    return {"entries": len(files), "size_bytes": total_size}
