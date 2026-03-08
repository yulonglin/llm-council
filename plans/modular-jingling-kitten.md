# Plan: Brainstorm TODO 3 Experiments via LLM Council

## Context

We need to brainstorm experiment ideas for extending an Apollo Research scheming eval (TODO 3). The eval tests whether an AI agent will falsify research project scores when goal conflicts arise. Currently it measures 3 things: honest scoring, which project gets cancelled, and goal prioritization. The gap: it doesn't test **covert behavior** (concealment, misrepresentation, cover stories) or measure behavior under varying conditions.

We'll run one full LLM Council pipeline (Stage 1 → 2a axes → 2b scoring → 3 synthesis) with a carefully distilled prompt.

## Step 1: Create Distilled Spec + Brainstorming Prompt

Create `data/brainstorm_todo3.json` — a single-question batch file for `batch_cli.py`.

The prompt will be ~1500 words, structured as:

```
## Context: The Eval
- Scenario summary (renewable energy, biased checklist, goal conflict)
- Current metrics (honest scoring, cancellation choice, goal prioritization)
- Available tools + phase flow
- Extension point: the eval can add new tools, modify prompts, vary conditions

## The Gap
- No measurement of covert vs overt defiance
- No measurement of behavior under monitoring variations
- No baselines (what happens without goal conflicts?)
- No measurement of post-hoc rationalization or history editing

## Seed Ideas (expand & improve these)
1. Variable monitoring — does behavior change with oversight?
2. Score editing tool — allow post-hoc correction, measure if used deceptively
3. Audit/confess tool — give model opportunity to report honestly
4. Escalation tool — human intervention pathway
5. Tool call log visibility — let models know logs are/aren't being reviewed
6. Baseline condition — same eval without conflicting goals

## What We Want From You
For each experiment idea:
- **Hypothesis**: What specific behavior are we testing? (falsifiable)
- **Metric**: What exactly do we measure? How do we compute it?
- **Implementation**: What tools/prompts/phases need to change?
- **Ablations**: What conditions do we vary?
- **Validation**: How do we verify the measurement is correct?
- **Why it matters**: How does this improve insight into scheming?

Prioritize ideas that are:
- Empirically verifiable (not just "interesting to think about")
- Concretely implementable (can be coded in the existing eval framework)
- Novel (go beyond the obvious score-falsification angle)
```

## Step 2: Run Council

```bash
cd /Users/yulong/writing/llm-council
python -u batch_cli.py \
  --questions data/brainstorm_todo3.json \
  --output-dir data/council_runs/todo3_brainstorm/
```

This runs the full 4-stage council:
- **Stage 1**: GPT-5.2-pro, Claude Opus 4.6, Gemini 3 Pro brainstorm independently
- **Stage 2a**: Chairman selects evaluation axes (likely: Novelty, Feasibility, Empirical Rigor, Insight Value)
- **Stage 2b**: All models anonymously score each other's brainstorms
- **Stage 3**: Chairman synthesizes best ideas with scores

Expected time: ~60-90s based on `time_council.py` benchmarks.

## Step 3: Review & Organize Results

Read the output markdown from `data/council_runs/todo3_brainstorm/`. The output includes:
- Stage 3 synthesis (main result)
- Individual model responses (collapsible)
- Aggregate scores per model per axis

## Files Modified

| File | Action |
|------|--------|
| `data/brainstorm_todo3.json` | CREATE — single-question batch input |
| `data/council_runs/todo3_brainstorm/*.md` | OUTPUT — council results |

## Verification

- Check that all 3 models responded in Stage 1
- Check that axes were selected (not fallback defaults)
- Check that Stage 3 synthesis references concrete experiment designs
- Cross-reference output with user's seed ideas to ensure coverage
- Flag any ideas that are not empirically verifiable
