# Plan: Replace Ordinal Ranking with Axis-Based Scoring

## Context

Stage 2 currently asks models to **rank** responses (1st, 2nd, 3rd). This produces a single ordinal signal that loses information about *why* one response is better. Replacing this with **axis-based scoring** gives richer, multi-dimensional feedback — each response gets scored 1-5 on criteria the chairman selects based on the question type.

## Design

**New flow:** Stage 1 → Stage 2a (chairman picks axes) → Stage 2b (parallel scoring) → Aggregate → Stage 3

**Scale:** 1=Poor, 2=Below Average, 3=Average, 4=Good, 5=Excellent

**Axes:** 3-5 axes selected by chairman per question (e.g., factual → Accuracy/Completeness/Clarity; creative → Creativity/Engagement/Language Quality). Falls back to 3 generic axes if parsing fails.

## Files to Modify

| File | Changes |
|------|---------|
| `backend/council.py` | New `stage2a_select_axes()`, replace `stage2_collect_rankings()` → `stage2b_collect_scores()`, new `parse_scores_from_text()` + `parse_axes_from_text()`, new `calculate_aggregate_scores()`, update `stage3_synthesize_final()` and `run_full_council()` |
| `backend/main.py` | Update imports, add `axes_complete` SSE event in streaming, update metadata structure |
| `backend/storage.py` | No structural changes needed (`update_assistant_message` already accepts `**updates`) |
| `frontend/src/App.jsx` | Add `axes_complete` event handler in SSE switch |
| `frontend/src/components/ChatInterface.jsx` | Update Stage2 props, update loading text |
| `frontend/src/components/Stage2.jsx` | Rewrite: score matrix table, axes display, parsed scores instead of parsed ranking |
| `frontend/src/components/Stage2.css` | New styles for score matrix, score badges, axes list |

## Implementation Steps

### Step 1: Backend — `council.py` core logic

**1a. Add `stage2a_select_axes(user_query)` (~line 35)**
- Calls `query_model(CHAIRMAN_MODEL, ...)` with prompt asking chairman to select 3-5 evaluation axes based on question type
- Output format: `EVALUATION AXES:\n- Name: Description` per line
- Add `parse_axes_from_text()` — regex `r'-\s*([^:]+):\s*(.+)'` after `EVALUATION AXES:` header
- Fallback: `[{Accuracy, Completeness, Clarity}]` if parsing fails
- Returns `List[Dict[str, str]]` with `name` and `description` keys

**1b. Replace `stage2_collect_rankings()` with `stage2b_collect_scores(user_query, stage1_results, axes)`**
- Keep: shuffle + anonymize logic (already done)
- Change: prompt asks models to score each response on each axis (1-5), ending with `SCORES:` section
- Format: `Response A: Accuracy=4, Completeness=3, Clarity=5`
- Each result dict: `{model, evaluation (text), parsed_scores: {Response A: {axis: score}}}`
- Add `parse_scores_from_text(text, axes)` with case-insensitive axis matching and score clamping to 1-5

**1c. Replace `calculate_aggregate_rankings()` with `calculate_aggregate_scores(stage2_results, label_to_model, axes)`**
- Average scores per model per axis across all evaluators
- Compute overall score (mean of all axis scores)
- Sort descending (higher = better, unlike old ranking where lower = better)
- Returns: `[{model, axis_scores: {name: avg}, overall_score, evaluator_count}]`

**1d. Update `stage3_synthesize_final()` signature: add `axes` and `aggregate_scores` params**
- Chairman prompt references scores instead of rankings
- Include aggregate score summary so chairman sees the consensus

**1e. Update `run_full_council()`**
- Add `stage2a_select_axes()` call between Stage 1 and Stage 2b
- Pass axes through to scoring and synthesis
- Return `(stage1, stage2, stage3, metadata)` where metadata now includes `axes` and `aggregate_scores`

**1f. Keep old `parse_ranking_from_text()` and `calculate_aggregate_rankings()`** for now — they're not imported elsewhere after main.py updates, but no harm leaving them until cleanup.

### Step 2: Backend — `main.py` API layer

**2a. Update imports** (line 13): `stage2_collect_rankings` → `stage2a_select_axes, stage2b_collect_scores`, `calculate_aggregate_rankings` → `calculate_aggregate_scores`

**2b. Non-streaming endpoint** (line 120): Return structure unchanged (still `{stage1, stage2, stage3, metadata}`) but metadata content changes

**2c. Streaming endpoint** (line 160): Between stage1_complete and stage2_start:
- Call `stage2a_select_axes()` and emit `axes_complete` event with axes data
- Save axes to assistant message: `storage.update_assistant_message(..., axes=axes)`
- Then proceed with `stage2b_collect_scores()` using the axes
- `stage2_complete` metadata changes: `aggregate_rankings` → `aggregate_scores`, add `axes`
- Stage 3 call updated with new params

### Step 3: Frontend — `App.jsx` event handling

Add `axes_complete` case in SSE switch (~line 317):
```js
case 'axes_complete':
  setCurrentConversation(prev => {
    const messages = [...prev.messages];
    const lastMsg = messages[messages.length - 1];
    lastMsg.axes = event.data;
    return { ...prev, messages };
  });
  break;
```

### Step 4: Frontend — `ChatInterface.jsx` props

- Update loading text: "Running Stage 2: Peer scoring..." (line 178)
- Update Stage2 props (lines 181-186):
  ```jsx
  <Stage2
    evaluations={msg.stage2}
    axes={msg.axes || msg.metadata?.axes}
    labelToModel={msg.metadata?.label_to_model}
    aggregateScores={msg.metadata?.aggregate_scores}
  />
  ```

### Step 5: Frontend — `Stage2.jsx` rewrite

**Structure:**
1. **Axes display** — list of chairman-selected criteria with descriptions
2. **Score matrix** — table with models as rows, axes + Overall as columns, color-coded score badges
3. **Shuffle order** — keep existing display
4. **Raw evaluations** — keep tab view, but replace "Extracted Ranking" with "Extracted Scores" per response

**Score badge colors:** green (≥4.0), yellow (≥3.0), red (<3.0)

**Backward compatibility:** Check for `parsed_ranking` vs `parsed_scores` on first evaluation — if legacy format, render old-style ranking UI.

### Step 6: Frontend — `Stage2.css`

Add styles for:
- `.score-matrix` table with blue header row
- `.score-badge` with `.score-good` / `.score-avg` / `.score-poor` color variants
- `.axes-list` with `.axis-name` and `.axis-description`
- `.parsed-scores` replacing `.parsed-ranking`

## Verification

1. Start backend: `cd /Users/yulong/writing/llm-council && python -m backend.main`
2. Start frontend: `cd frontend && npm run dev`
3. Send a message and verify:
   - Axes appear between Stage 1 and Stage 2 in the UI
   - Score matrix renders with correct model names and scores
   - Raw evaluations show de-anonymized text with extracted scores
   - Stage 3 synthesis references scores
4. Test edge cases:
   - Model fails to follow SCORES: format → should degrade gracefully (empty scores for that evaluator)
   - Chairman fails to produce axes → should fall back to Accuracy/Completeness/Clarity
