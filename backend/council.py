"""3-stage LLM Council orchestration."""

import json
import re
import random
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL, EVALUATION_CRITERIA

# Default axes when chairman fails to produce custom ones
DEFAULT_AXES = [
    {
        "name": "Accuracy",
        "description": "Factual correctness and reliability of information",
    },
    {
        "name": "Completeness",
        "description": "How thoroughly the response addresses the question",
    },
    {
        "name": "Clarity",
        "description": "How well-organized and easy to understand the response is",
    },
]


def parse_stage0_response(text: str) -> dict:
    """Parse stage0 chairman response for clarification or rewritten query."""
    result = {"needs_clarification": False, "questions": [], "rewritten_query": None}

    if "CLARIFICATION_NEEDED:" in text:
        idx = text.index("CLARIFICATION_NEEDED:")
        section = text[idx + len("CLARIFICATION_NEEDED:") :]
        questions = re.findall(r"\d+\.\s*(.+)", section)
        if questions:
            result["needs_clarification"] = True
            result["questions"] = [q.strip() for q in questions]
    elif "REWRITTEN_QUERY:" in text:
        idx = text.index("REWRITTEN_QUERY:")
        rewritten = text[idx + len("REWRITTEN_QUERY:") :].strip()
        if rewritten:
            result["rewritten_query"] = rewritten

    return result


async def stage0_analyze_query(user_query: str) -> dict:
    """Stage 0: Chairman analyzes query for clarity, asks clarification or rewrites."""
    prompt = f"""You are the Chairman of an LLM Council. Before the council answers a question, you analyze whether the query is clear enough to get high-quality responses.

Query: {user_query}

Your task: Determine if this query needs clarification or if you can rewrite it to be clearer and more specific.

If the query is VAGUE or UNDERSPECIFIED (missing key context, could mean multiple different things, or needs scope clarification):
- Ask 1-3 focused clarifying questions
- Format your response EXACTLY as:
CLARIFICATION_NEEDED:
1. [First question]
2. [Second question if needed]
3. [Third question if needed]

If the query is CLEAR ENOUGH to answer well (specific, has sufficient context, or is a simple factual/creative/technical question):
- Rewrite it to be more precise, structured, and comprehensive
- CRITICAL: You MUST preserve ALL information, details, and nuances from the original query. Do NOT truncate, summarize, or drop any part of the user's input. You may lightly reformat for clarity (e.g., add structure, clarify scope, decompose into sub-questions) but every piece of information in the original must appear in your rewrite.
- Format your response EXACTLY as:
REWRITTEN_QUERY:
[Your rewritten version of the query]

Now analyze the query:"""

    messages = [{"role": "user", "content": prompt}]
    response = await query_model(CHAIRMAN_MODEL, messages, timeout=30.0)

    if response is None:
        return {"needs_clarification": False, "questions": [], "rewritten_query": None}

    return parse_stage0_response(response.get("content", ""))


async def stage0_rewrite_with_answers(
    original_query: str, questions: list, answers: list
) -> str:
    """Rewrite query incorporating user's answers to clarifying questions."""
    qa_pairs_text = "\n".join(
        [f"Q: {item['question']}\nA: {item['answer']}" for item in answers]
    )

    prompt = f"""You are the Chairman of an LLM Council. A user asked a question and you asked for clarification. Now incorporate their answers to write a comprehensive, clear prompt for the council.

Original query: {original_query}

Clarifying questions and answers:
{qa_pairs_text}

Rewrite the query as a single, comprehensive prompt that incorporates all the clarification. The rewritten prompt should be clear, specific, and well-structured for the council to answer.

Provide ONLY the rewritten query, with no preamble or explanation:"""

    messages = [{"role": "user", "content": prompt}]
    response = await query_model(CHAIRMAN_MODEL, messages, timeout=30.0)

    if response is None:
        return original_query

    return response.get("content", original_query).strip() or original_query


async def stage1_collect_responses(user_query: str) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [
        {
            "role": "system",
            "content": "You are an expert participating in a council of AI models. Answer the following question thoroughly, accurately, and with clear structure. Draw on your full knowledge and reasoning ability.",
        },
        {"role": "user", "content": user_query},
    ]

    # Query all models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append(
                {"model": model, "response": response.get("content", "")}
            )

    return stage1_results


async def stage2a_select_axes(user_query: str) -> List[Dict[str, str]]:
    """
    Stage 2a: Chairman selects evaluation axes based on the question type.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'name' and 'description' keys (3-5 axes)
    """
    axes_prompt = f"""You are the Chairman of an LLM Council. Select 3-5 evaluation axes for judging response quality to this question.

Question: {user_query}

Consider the question type (factual, creative, analytical, technical, etc.) and choose axes that best capture what makes a response good for this specific type.

Format your response EXACTLY as:

EVALUATION AXES:
- Name: One-sentence description
- Name: One-sentence description
(3-5 axes, each name 1-2 words)

Now select the evaluation axes:"""

    messages = [{"role": "user", "content": axes_prompt}]
    response = await query_model(CHAIRMAN_MODEL, messages, timeout=30.0)

    if response is None:
        return DEFAULT_AXES

    axes = parse_axes_from_text(response.get("content", ""))
    if not axes:
        return DEFAULT_AXES

    return axes


def parse_axes_from_text(text: str) -> List[Dict[str, str]]:
    """
    Parse evaluation axes from the chairman's response.

    Args:
        text: The full text response

    Returns:
        List of dicts with 'name' and 'description' keys, or empty list on failure
    """
    axes = []

    # Look for "EVALUATION AXES:" section
    if "EVALUATION AXES:" in text.upper():
        # Find the section (case-insensitive split)
        idx = text.upper().index("EVALUATION AXES:")
        section = text[idx + len("EVALUATION AXES:") :]

        # Extract "- Name: Description" lines
        matches = re.findall(r"-\s*([^:\n]+):\s*(.+)", section)
        for name, description in matches:
            name = name.strip()
            description = description.strip()
            if name and description:
                axes.append({"name": name, "description": description})

    # Validate: 3-5 axes
    if len(axes) < 3:
        return []
    if len(axes) > 5:
        axes = axes[:5]

    return axes


async def stage2b_collect_scores(
    user_query: str, stage1_results: List[Dict[str, Any]], axes: List[Dict[str, str]]
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2b: Each model scores the anonymized responses on each axis (1-5).

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1
        axes: Evaluation axes from Stage 2a

    Returns:
        Tuple of (scores list, label_to_model mapping)
    """
    # Shuffle responses to avoid positional bias
    shuffled_results = stage1_results.copy()
    random.shuffle(shuffled_results)

    # Create anonymized labels
    labels = [chr(65 + i) for i in range(len(shuffled_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result["model"]
        for label, result in zip(labels, shuffled_results)
    }

    # Build axes description for the prompt
    axes_text = "\n".join([f"- {axis['name']}: {axis['description']}" for axis in axes])

    # Build the anonymized responses text
    responses_text = "\n\n".join(
        [
            f"Response {label}:\n{result['response']}"
            for label, result in zip(labels, shuffled_results)
        ]
    )

    scoring_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Evaluate each response on the following axes using a 1-5 scale:
{axes_text}

Scale: 1=Poor, 2=Below Average, 3=Average, 4=Good, 5=Excellent

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly on each axis.
2. Then, at the very end of your response, provide scores.

IMPORTANT: Your final scores MUST be formatted EXACTLY as follows.
Format each axis as "AxisName=N" (integer 1-5) separated by commas.

Example of the correct format:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...

SCORES:
Response A: {", ".join([f"{axis['name']}=4" for axis in axes])}
Response B: {", ".join([f"{axis['name']}=3" for axis in axes])}

You MUST include the "SCORES:" line (all caps) followed by one line per response.

Now provide your evaluation and scores:"""

    messages = [{"role": "user", "content": scoring_prompt}]

    # Get scores from all council models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get("content", "")
            parsed = parse_scores_from_text(full_text, axes)
            stage2_results.append(
                {"model": model, "evaluation": full_text, "parsed_scores": parsed}
            )

    return stage2_results, label_to_model


def parse_scores_from_text(
    text: str, axes: List[Dict[str, str]]
) -> Dict[str, Dict[str, int]]:
    """
    Parse the SCORES section from a model's evaluation.

    Args:
        text: The full evaluation text
        axes: The evaluation axes (for axis name matching)

    Returns:
        Dict mapping response labels to axis scores, e.g.
        {"Response A": {"Accuracy": 4, "Clarity": 5}, ...}
    """
    scores = {}
    axis_name_map = {axis["name"].lower(): axis["name"] for axis in axes}

    # Look for "SCORES:" section
    if "SCORES:" not in text.upper():
        return scores

    idx = text.upper().index("SCORES:")
    section = text[idx + len("SCORES:") :]

    # Extract lines with "Response X: ..." pattern
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Match "Response X:" at start of line
        resp_match = re.match(r"(Response [A-Z]):\s*(.*)", line)
        if not resp_match:
            continue

        label = resp_match.group(1)
        scores_part = resp_match.group(2)

        # Extract AxisName=N pairs (case-insensitive)
        axis_scores = {}
        pairs = re.findall(r"([A-Za-z\s]+?)\s*=\s*(\d+)", scores_part)
        for axis_name_raw, score_str in pairs:
            axis_name_raw = axis_name_raw.strip()
            score = int(score_str)
            # Clamp to 1-5
            score = max(1, min(5, score))

            # Case-insensitive axis matching
            if axis_name_raw.lower() in axis_name_map:
                canonical_name = axis_name_map[axis_name_raw.lower()]
                axis_scores[canonical_name] = score

        if axis_scores:
            scores[label] = axis_scores

    return scores


def calculate_aggregate_scores(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str],
    axes: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate scores per model per axis across all evaluators.

    Args:
        stage2_results: Scores from each evaluator model
        label_to_model: Mapping from anonymous labels to model names
        axes: The evaluation axes

    Returns:
        List of dicts sorted by overall score (descending), each with:
        - model, axis_scores (name -> avg), overall_score, evaluator_count
    """
    # Collect all scores per model per axis
    model_axis_scores = defaultdict(lambda: defaultdict(list))
    model_evaluator_count = defaultdict(int)

    for result in stage2_results:
        parsed = result.get("parsed_scores", {})
        counted_models = set()
        for label, axis_scores in parsed.items():
            if label not in label_to_model:
                continue
            model = label_to_model[label]
            for axis_name, score in axis_scores.items():
                model_axis_scores[model][axis_name].append(score)
            if model not in counted_models:
                counted_models.add(model)
                model_evaluator_count[model] += 1

    # Compute averages
    aggregate = []
    axis_names = [axis["name"] for axis in axes]

    for model, axis_data in model_axis_scores.items():
        avg_axis = {}
        all_scores = []
        for axis_name in axis_names:
            scores_list = axis_data.get(axis_name, [])
            if scores_list:
                avg = sum(scores_list) / len(scores_list)
                avg_axis[axis_name] = round(avg, 2)
                all_scores.extend(scores_list)
            else:
                avg_axis[axis_name] = None

        overall = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0
        aggregate.append(
            {
                "model": model,
                "axis_scores": avg_axis,
                "overall_score": overall,
                "evaluator_count": model_evaluator_count[model],
            }
        )

    # Sort by overall score descending (higher = better)
    aggregate.sort(key=lambda x: x["overall_score"], reverse=True)

    return aggregate


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    axes: List[Dict[str, str]],
    aggregate_scores: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response using scores.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Evaluations from Stage 2b
        axes: Evaluation axes used
        aggregate_scores: Aggregate scores per model

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join(
        [
            f"Model: {result['model']}\nResponse: {result['response']}"
            for result in stage1_results
        ]
    )

    stage2_text = "\n\n".join(
        [
            f"Model: {result['model']}\nEvaluation: {result['evaluation']}"
            for result in stage2_results
        ]
    )

    # Build score summary
    axes_names = [axis["name"] for axis in axes]
    score_summary_lines = []
    for agg in aggregate_scores:
        model_short = agg["model"].split("/")[-1]
        axis_parts = [
            f"{name}={agg['axis_scores'].get(name, 'N/A')}" for name in axes_names
        ]
        score_summary_lines.append(
            f"  {model_short}: {', '.join(axis_parts)} (Overall: {agg['overall_score']})"
        )
    score_summary = "\n".join(score_summary_lines)

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then scored each other's responses on specific evaluation axes.

Original Question: {user_query}

## Individual Responses:
{stage1_text}

## Peer Evaluations:
{stage2_text}

## Aggregate Scores (1-5 scale, higher is better):
{score_summary}

Evaluation Axes Used: {", ".join(axes_names)}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer scores and what they reveal about response quality across different dimensions
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis.",
        }

    return {"model": CHAIRMAN_MODEL, "response": response.get("content", "")}


# --- Legacy functions kept for backward compatibility ---


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """Parse the FINAL RANKING section from the model's response."""
    if "FINAL RANKING:" in ranking_text:
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            numbered_matches = re.findall(r"\d+\.\s*Response [A-Z]", ranking_section)
            if numbered_matches:
                return [match.group() for m in numbered_matches if (match := re.search(r'Response [A-Z]', m))]
            matches = re.findall(r"Response [A-Z]", ranking_section)
            return matches
    matches = re.findall(r"Response [A-Z]", ranking_text)
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
    stage2_results: List[Dict[str, Any]], label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings using weighted criteria scores.

    Falls back to ordinal rank conversion if criteria scores are unavailable.
    """
    criteria_names: List[str] = [c['name'] for c in EVALUATION_CRITERIA]
    weight_map: Dict[str, int] = {c['name']: c['weight'] for c in EVALUATION_CRITERIA}

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

    title = response.get("content", "New Conversation").strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip("\"'")

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
        return (
            [],
            [],
            {
                "model": "error",
                "response": "All models failed to respond. Please try again.",
            },
            {},
        )

    # Stage 2a: Chairman selects evaluation axes
    axes = await stage2a_select_axes(user_query)

    # Stage 2b: Collect scores
    stage2_results, label_to_model = await stage2b_collect_scores(
        user_query, stage1_results, axes
    )

    # Calculate aggregate scores
    aggregate_scores = calculate_aggregate_scores(stage2_results, label_to_model, axes)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query, stage1_results, stage2_results, axes, aggregate_scores
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "axes": axes,
        "aggregate_scores": aggregate_scores,
    }

    return stage1_results, stage2_results, stage3_result, metadata
