"""3-stage LLM Council orchestration."""

import re
import random
from typing import List, Dict, Any, Tuple
from collections import defaultdict
from .openrouter import query_models_parallel, query_model
from .config import COUNCIL_MODELS, CHAIRMAN_MODEL

# Default axes when chairman fails to produce custom ones
DEFAULT_AXES = [
    {"name": "Accuracy", "description": "Factual correctness and reliability of information"},
    {"name": "Completeness", "description": "How thoroughly the response addresses the question"},
    {"name": "Clarity", "description": "How well-organized and easy to understand the response is"},
]


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


async def stage2a_select_axes(user_query: str) -> List[Dict[str, str]]:
    """
    Stage 2a: Chairman selects evaluation axes based on the question type.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'name' and 'description' keys (3-5 axes)
    """
    axes_prompt = f"""You are the Chairman of an LLM Council. Based on the following question, select 3-5 evaluation criteria (axes) that are most appropriate for judging response quality.

Question: {user_query}

Consider what type of question this is (factual, creative, analytical, opinion-based, technical, etc.) and choose axes that best capture what makes a response good for this specific type.

IMPORTANT: Format your response EXACTLY as follows:
- Start with the line "EVALUATION AXES:" (all caps, with colon)
- Then list each axis as: "- Name: Description"
- Each axis name should be 1-2 words
- Each description should be one sentence

Example:

EVALUATION AXES:
- Accuracy: Factual correctness and reliability of information provided
- Depth: Level of detail and thoroughness in addressing the question
- Clarity: How well-organized and easy to understand the response is
- Practicality: Whether the response provides actionable and useful guidance

Now select the evaluation axes:"""

    messages = [{"role": "user", "content": axes_prompt}]
    response = await query_model(CHAIRMAN_MODEL, messages, timeout=30.0)

    if response is None:
        return DEFAULT_AXES

    axes = parse_axes_from_text(response.get('content', ''))
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
        section = text[idx + len("EVALUATION AXES:"):]

        # Extract "- Name: Description" lines
        matches = re.findall(r'-\s*([^:\n]+):\s*(.+)', section)
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
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    axes: List[Dict[str, str]]
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
        f"Response {label}": result['model']
        for label, result in zip(labels, shuffled_results)
    }

    # Build axes description for the prompt
    axes_text = "\n".join([
        f"- {axis['name']}: {axis['description']}"
        for axis in axes
    ])

    axes_names = ", ".join([axis['name'] for axis in axes])

    # Build the anonymized responses text
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, shuffled_results)
    ])

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

IMPORTANT: Your final scores MUST be formatted EXACTLY as follows:
- Start with the line "SCORES:" (all caps, with colon)
- Then for each response, write one line: "Response X: {axes_names}" with scores as integers
- Format each axis as "AxisName=N" separated by commas

Example of the correct format:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...

SCORES:
Response A: {", ".join([f"{axis['name']}=4" for axis in axes])}
Response B: {", ".join([f"{axis['name']}=3" for axis in axes])}

Now provide your evaluation and scores:"""

    messages = [{"role": "user", "content": scoring_prompt}]

    # Get scores from all council models in parallel
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_scores_from_text(full_text, axes)
            stage2_results.append({
                "model": model,
                "evaluation": full_text,
                "parsed_scores": parsed
            })

    return stage2_results, label_to_model


def parse_scores_from_text(
    text: str,
    axes: List[Dict[str, str]]
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
    axis_names = [axis['name'].lower() for axis in axes]
    axis_name_map = {axis['name'].lower(): axis['name'] for axis in axes}

    # Look for "SCORES:" section
    if "SCORES:" not in text.upper():
        return scores

    idx = text.upper().index("SCORES:")
    section = text[idx + len("SCORES:"):]

    # Extract lines with "Response X: ..." pattern
    for line in section.strip().split('\n'):
        line = line.strip()
        if not line:
            continue

        # Match "Response X:" at start of line
        resp_match = re.match(r'(Response [A-Z]):\s*(.*)', line)
        if not resp_match:
            continue

        label = resp_match.group(1)
        scores_part = resp_match.group(2)

        # Extract AxisName=N pairs (case-insensitive)
        axis_scores = {}
        pairs = re.findall(r'([A-Za-z\s]+?)\s*=\s*(\d+)', scores_part)
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
    axes: List[Dict[str, str]]
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
        parsed = result.get('parsed_scores', {})
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
    axis_names = [axis['name'] for axis in axes]

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
        aggregate.append({
            "model": model,
            "axis_scores": avg_axis,
            "overall_score": overall,
            "evaluator_count": model_evaluator_count[model]
        })

    # Sort by overall score descending (higher = better)
    aggregate.sort(key=lambda x: x['overall_score'], reverse=True)

    return aggregate


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
    axes: List[Dict[str, str]],
    aggregate_scores: List[Dict[str, Any]]
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
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nEvaluation: {result['evaluation']}"
        for result in stage2_results
    ])

    # Build score summary
    axes_names = [axis['name'] for axis in axes]
    score_summary_lines = []
    for agg in aggregate_scores:
        model_short = agg['model'].split('/')[-1]
        axis_parts = [f"{name}={agg['axis_scores'].get(name, 'N/A')}" for name in axes_names]
        score_summary_lines.append(
            f"  {model_short}: {', '.join(axis_parts)} (Overall: {agg['overall_score']})"
        )
    score_summary = "\n".join(score_summary_lines)

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then scored each other's responses on specific evaluation axes.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Evaluations:
{stage2_text}

AGGREGATE SCORES (1-5 scale, higher is better):
{score_summary}

Evaluation Axes Used: {', '.join(axes_names)}

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
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', '')
    }


# --- Legacy functions kept for backward compatibility ---

def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """Parse the FINAL RANKING section from the model's response."""
    if "FINAL RANKING:" in ranking_text:
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Calculate aggregate rankings across all models."""
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']
        parsed_ranking = parse_ranking_from_text(ranking_text)
        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    aggregate.sort(key=lambda x: x['average_rank'])
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

    # Stage 2a: Chairman selects evaluation axes
    axes = await stage2a_select_axes(user_query)

    # Stage 2b: Collect scores
    stage2_results, label_to_model = await stage2b_collect_scores(user_query, stage1_results, axes)

    # Calculate aggregate scores
    aggregate_scores = calculate_aggregate_scores(stage2_results, label_to_model, axes)

    # Stage 3: Synthesize final answer
    stage3_result = await stage3_synthesize_final(
        user_query,
        stage1_results,
        stage2_results,
        axes,
        aggregate_scores
    )

    # Prepare metadata
    metadata = {
        "label_to_model": label_to_model,
        "axes": axes,
        "aggregate_scores": aggregate_scores
    }

    return stage1_results, stage2_results, stage3_result, metadata
