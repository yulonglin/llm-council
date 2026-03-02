# Plan: Rewrite Council Prompts + Add Stage 0 (Query Refinement)

## Context

The council currently sends raw user queries directly to Stage 1 models with no system prompt and no pre-processing. This means vague or underspecified queries get mediocre responses. We want the Chairman to analyze the query first — ask clarifying questions if needed, then rewrite the prompt for clarity, specificity, and decomposition before the council runs.

Additionally: update council model from `google/gemini-3-pro-preview` → `google/gemini-3.1-pro-preview`, add a system prompt for Stage 1 models, and clean up prompt formatting across all stages.

## Changes

### 1. Update model in `backend/config.py`

Change `google/gemini-3-pro-preview` → `google/gemini-3.1-pro-preview` in `COUNCIL_MODELS`.

### 2. Add Stage 0: Query Analysis & Rewrite (`backend/council.py`)

Two new functions:

**`stage0_analyze_query(user_query) → dict`** — Chairman analyzes the query and returns:
- `needs_clarification: bool`
- `questions: list[str]` (1-3 questions, empty if clear)
- `rewritten_query: str | None` (set when no clarification needed)

**`stage0_rewrite_with_answers(original_query, questions, answers) → str`** — Takes the original query + user's answers, returns the rewritten prompt.

Both use structured output format (`CLARIFICATION_NEEDED` / `REWRITTEN_QUERY` markers) with a `parse_stage0_response()` parser. Fallback: if Chairman fails, use the raw query (graceful degradation).

The rewritten query replaces the original for Stage 1 models (they only see the rewritten version). Stage 3 Chairman gets both original + rewritten for full context.

### 3. Add Stage 1 system prompt (`backend/council.py`)

Add a system message to `stage1_collect_responses()`:

```
You are an expert participating in a council of AI models. Answer the following question thoroughly, accurately, and with clear structure. Draw on your full knowledge and reasoning ability.
```

This goes in the `messages` list as `{"role": "system", "content": ...}` before the user message. `openrouter.py` already accepts a full `messages` list and passes it straight to OpenRouter — no changes needed there.

### 4. Clean up Stage 2a/2b/3 prompts (`backend/council.py`)

Reformat existing prompts for clarity without changing behavior:
- **Stage 2a** (axes): Tighten the prompt structure, reduce verbose examples
- **Stage 2b** (scoring): Make the output format instructions more prominent and unambiguous
- **Stage 3** (synthesis): Structure the context sections more clearly

No logic changes — just prompt text improvements.

### 5. Backend API changes (`backend/main.py`)

**Modify `send_message_stream()`** — Insert Stage 0 before Stage 1:
- Yield `stage0_start` event
- Call `stage0_analyze_query()`
- If needs clarification → yield `clarification_needed` with questions, then `complete` (stream ends)
- If no clarification → yield `stage0_complete` with `rewritten_query`, continue to Stage 1-3

**Add `POST /api/conversations/{id}/clarify/stream`**:
- Takes `{answers: [{question, answer}, ...]}`
- Calls `stage0_rewrite_with_answers()` with original query + answers
- Yields `stage0_complete` with rewritten query
- Continues through Stage 1-3 (reuse factored-out logic)

**Factor out** the Stage 1-3 SSE logic into `_run_stages_1_through_3()` async generator to avoid duplication.

### 6. Storage changes (`backend/storage.py`)

- Add `stage0` field to assistant message defaults (backward compat)
- Add `"awaiting_clarification"` as valid status
- Store `clarification_answers` when user responds

### 7. Frontend API (`frontend/src/api.js`)

Add `sendClarificationStream(conversationId, answers, onEvent)` — mirrors `sendMessageStream` but hits `/clarify/stream`.

### 8. Frontend state (`frontend/src/App.jsx`)

Handle new SSE events in `onEvent`:
- `stage0_start` → set `loading.stage0 = true`
- `stage0_complete` → store `rewritten_query` on assistant message, clear loading
- `clarification_needed` → store questions, set `isLoading = false` (user needs to interact)

Add `handleClarificationSubmit(answers)` → calls `api.sendClarificationStream()`.

### 9. Frontend components

**New `Stage0.jsx`** — Shows the rewritten query in a subtle amber box (`#fffbe6`), with original query shown smaller above it. If no rewrite (query was clear), skip display.

**New `ClarificationForm.jsx`** — Renders Chairman's questions with text inputs + "Submit" and "Skip" buttons. Inline in the chat, not a modal.

**Modify `ChatInterface.jsx`** — Render Stage0 before Stage1, show ClarificationForm when awaiting.

## Files to modify

| File | Type |
|------|------|
| `backend/config.py` | Edit (model name) |
| `backend/council.py` | Edit (add stage0 functions, stage1 system prompt, clean up prompts) |
| `backend/openrouter.py` | No changes needed (already accepts full messages list) |
| `backend/main.py` | Edit (stage0 in stream, add /clarify/stream, factor out stages 1-3) |
| `backend/storage.py` | Edit (stage0 field, new status) |
| `frontend/src/api.js` | Edit (add sendClarificationStream) |
| `frontend/src/App.jsx` | Edit (handle new events, clarification flow) |
| `frontend/src/components/ChatInterface.jsx` | Edit (render Stage0, ClarificationForm) |
| `frontend/src/components/Stage0.jsx` | **New** |
| `frontend/src/components/ClarificationForm.jsx` | **New** |

## Verification

1. **Backend unit test**: `curl` against `/message/stream` with a vague query ("help me with something") — should get `clarification_needed` event
2. **Backend unit test**: `curl` with a clear query ("What is the capital of France?") — should get `stage0_complete` with rewritten query, then normal stages
3. **Clarification flow**: Submit answers via `/clarify/stream`, verify full Stage 1-3 runs with rewritten query
4. **Graceful degradation**: If Chairman is down, verify raw query is used (no crash)
5. **Frontend E2E**: Both flows (with and without clarification) render correctly in the UI
6. **Backward compat**: Existing saved conversations load without errors (stage0 defaults to null)
