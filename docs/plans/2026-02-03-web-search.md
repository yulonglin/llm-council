# Web Search Plugin Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable OpenRouter web search for all council model calls by default.

**Architecture:** Add `OPENROUTER_PLUGINS` config defaulting to `[{"id": "web"}]` and include it in every OpenRouter request payload when non-empty. Add a unit test to verify the payload includes plugins and update README to document default behavior.

**Tech Stack:** Python 3.10+, FastAPI, httpx, pytest, uv.

### Task 1: Add failing test for OpenRouter payload

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_openrouter.py`

**Step 1: Write the failing test**
- Add `pytest>=8.0.0` to `dependencies` in `pyproject.toml`.
- Create `tests/test_openrouter.py` with:

```python
import asyncio
from backend import openrouter


def test_query_model_includes_web_plugin(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(openrouter.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        openrouter.query_model(
            "openai/gpt-5.2-pro",
            [{"role": "user", "content": "hi"}],
        )
    )

    assert result["content"] == "ok"
    assert captured["json"]["plugins"] == [{"id": "web"}]
```

**Step 2: Run test to verify it fails**
Run: `uv sync`
Run: `uv run pytest tests/test_openrouter.py -v`
Expected: FAIL because `plugins` key is missing from the payload.

**Step 3: Commit**
Run: `git add pyproject.toml tests/test_openrouter.py`
Run: `git commit -m "test: add failing payload test for web plugins"`

### Task 2: Add plugins to OpenRouter payload

**Files:**
- Modify: `backend/config.py`
- Modify: `backend/openrouter.py`
- Test: `tests/test_openrouter.py`

**Step 1: Write minimal implementation**
- In `backend/config.py`, add:

```python
OPENROUTER_PLUGINS = [{"id": "web"}]
```

- In `backend/openrouter.py`, import the constant and include it only when non-empty:

```python
from .config import OPENROUTER_API_KEY, OPENROUTER_API_URL, OPENROUTER_PLUGINS

payload = {
    "model": model,
    "messages": messages,
}
if OPENROUTER_PLUGINS:
    payload["plugins"] = OPENROUTER_PLUGINS
```

**Step 2: Run test to verify it passes**
Run: `uv run pytest tests/test_openrouter.py -v`
Expected: PASS.

**Step 3: Commit**
Run: `git add backend/config.py backend/openrouter.py`
Run: `git commit -m "feat: enable OpenRouter web plugin by default"`

### Task 3: Document default web search

**Files:**
- Modify: `README.md`

**Step 1: Update docs**
- Add a short note in README that web search is enabled by default via OpenRouter plugins, and that it can be disabled by setting `OPENROUTER_PLUGINS = []` in `backend/config.py`.

**Step 2: Commit**
Run: `git add README.md`
Run: `git commit -m "docs: note default web search plugin"`
