"""3-stage LLM Council orchestration."""

import json
from collections import defaultdict
from typing import List, Dict, Any, Tuple, Optional
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, EVALUATION_CRITERIA


async def stage1_collect_responses(user_query: str) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [{"role": "user", "content": user_query}]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', '')
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    criteria_lines = "\n".join(
        f"- **{c['name']}** (weight {c['weight']}): {c['description']}"
        for c in EVALUATION_CRITERIA
    )

    # Build dynamic example with actual response labels and criteria
    example_scores = {
        f"Response {label}": {c['name']: 4 for c in EVALUATION_CRITERIA}
        for label in labels
    }
    example_scores_json = json.dumps(example_scores, indent=2)
    # Escape braces for f-string
    example_scores_escaped = example_scores_json.replace("{", "{{").replace("}", "}}")

    example_ranking = "\n".join(
        f"{i+1}. Response {label}" for i, label in enumerate(labels)
    )

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. Evaluate each response on these criteria (1–5 scale, 1=poor, 5=excellent):
{criteria_lines}

2. Provide a final ranking from best to worst.
3. At the very end, output a SCORES JSON block with numeric values 1–5 for each criterion.

FORMAT — follow exactly:

[Your evaluation text for each response here...]

FINAL RANKING:
{example_ranking}

SCORES:
{example_scores_escaped}

Rules:
- FINAL RANKING and SCORES must both appear at the end
- SCORES must be valid JSON with numeric values 1–5
- Include every response label and every criterion in SCORES
- Do not add text after the SCORES block

Remember: you MUST end with FINAL RANKING then SCORES JSON block.

Now provide your evaluation:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    aggregate_rankings: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2
        aggregate_rankings: Weighted aggregate scores from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    scores_text = ""
    if aggregate_rankings:
        scores_lines = []
        for agg in aggregate_rankings:
            model_short = agg['model'].split('/')[-1]
            score = agg.get('weighted_score', 'N/A')
            criteria = agg.get('criteria_scores', {})
            criteria_str = ", ".join(
                f"{k}: {v:.1f}" for k, v in criteria.items() if v is not None
            )
            scores_lines.append(f"- {model_short}: {score}/5 ({criteria_str})")
        scores_text = "\n\nWEIGHTED CRITERIA SCORES (from peer evaluation):\n" + "\n".join(scores_lines)

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}{scores_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- The weighted criteria scores showing each model's strengths
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', '')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [match.group() for m in numbered_matches if (match := re.search(r'Response [A-Z]', m))]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def parse_criteria_scores_from_text(
    evaluation_text: str,
    criteria_names: List[str]
) -> Dict[str, Dict[str, Optional[float]]]:
    """Extract per-criterion scores from the SCORES: JSON block.

    Returns: {label -> {criterion_name -> score_or_None}}
    Returns empty dict if SCORES block is absent or unparseable.
    """
    scores_idx = evaluation_text.find('SCORES:')
    if scores_idx == -1:
        return {}
    brace_idx = evaluation_text.find('{', scores_idx)
    if brace_idx == -1:
        return {}
    try:
        raw, _ = json.JSONDecoder().raw_decode(evaluation_text, brace_idx)
    except json.JSONDecodeError:
        return {}

    results: Dict[str, Dict[str, Optional[float]]] = {}
    for label, criterion_map in raw.items():
        if not isinstance(criterion_map, dict):
            continue
        scores: Dict[str, Optional[float]] = {}
        for cname in criteria_names:
            val = criterion_map.get(cname)
            try:
                score = float(val) if val is not None else None
                scores[cname] = score if score is not None and 1.0 <= score <= 5.0 else None
            except (TypeError, ValueError):
                scores[cname] = None
        results[label] = scores

    return results


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings using weighted criteria scores.

    Falls back to ordinal rank conversion if criteria scores are unavailable.
    """
    criteria_names = [c['name'] for c in EVALUATION_CRITERIA]
    weight_map = {c['name']: c['weight'] for c in EVALUATION_CRITERIA}

    model_criterion_scores: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    model_positions: Dict[str, List[int]] = defaultdict(list)
    model_evaluator_count: Dict[str, int] = defaultdict(int)

    for ranking in stage2_results:
        text = ranking['ranking']
        label_scores = parse_criteria_scores_from_text(text, criteria_names)
        for label, cscores in label_scores.items():
            if label not in label_to_model:
                continue
            model = label_to_model[label]
            has_any_score = False
            for cname, score in cscores.items():
                if score is not None:
                    model_criterion_scores[model][cname].append(score)
                    has_any_score = True
            if has_any_score:
                model_evaluator_count[model] += 1

        for pos, label in enumerate(parse_ranking_from_text(text), start=1):
            if label in label_to_model:
                model_positions[label_to_model[label]].append(pos)

    all_models = set(label_to_model.values())
    aggregate = []

    for model in all_models:
        # Per-criterion averages across all evaluators
        avg_criteria: Dict[str, Optional[float]] = {}
        for cname in criteria_names:
            scores = model_criterion_scores[model][cname]
            avg_criteria[cname] = round(sum(scores) / len(scores), 2) if scores else None

        scored = [(c, s) for c, s in avg_criteria.items() if s is not None]
        score_available = bool(scored)

        if score_available:
            weighted_score = round(
                sum(s * weight_map[c] for c, s in scored) / sum(weight_map[c] for c, _ in scored),
                2
            )
            rankings_count = model_evaluator_count[model]
        else:
            positions = model_positions[model]
            n = len(all_models)
            if positions:
                avg_rank = sum(positions) / len(positions)
                raw = 5.0 - (avg_rank - 1) * (4.0 / max(n - 1, 1))
                weighted_score = round(max(1.0, min(5.0, raw)), 2)
                rankings_count = len(positions)
            else:
                weighted_score, rankings_count = 0.0, 0

        positions = model_positions[model]
        aggregate.append({
            "model": model,
            "weighted_score": weighted_score,
            "criteria_scores": {c: avg_criteria.get(c) for c in criteria_names},
            "rankings_count": rankings_count,
            "average_rank": round(sum(positions) / len(positions), 2) if positions else None,
            "score_available": score_available,
        })

    aggregate.sort(key=lambda x: x['weighted_score'], reverse=True)
    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use gemini-2.5-flash for title generation (fast and cheap)
    response = await query_model("google/gemini-2.5-flash", messages, timeout=30.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


async def run_full_council(user_query: str) -> Tuple[List, List, Dict, Dict]:
    """
    Run the complete 3-stage council process.

    Args:
        user_query: The user's question

    Returns:
        Tuple of (stage1_results, stage2_results, stage3_result, metadata)
    """
    # Stage 1: Collect individual responses
    stage1_results = await stage1_collect_responses(user_query)

    # If no models responded successfully, return error
    if not stage1_results:
        return [], [], {
            "model": "error",
            "response": "All models failed to respond. Please try again."
        }, {}

    # Stage 2: Collect rankings
    stage2_results, label_to_model = await stage2_collect_rankings(user_query, stage1_results)

    # Calculate aggregate rankings
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        aggregate_rankings
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings
    }

    return stage1_results, stage2_results, stage3_result, metadata
