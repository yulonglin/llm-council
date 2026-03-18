"""Configuration for the LLM Council."""

import os
from typing import TypedDict

from dotenv import load_dotenv


class EvaluationCriterion(TypedDict):
    name: str
    weight: int
    description: str

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.4-pro",
    "anthropic/claude-opus-4.6",
    "google/gemini-3.1-pro-preview",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "anthropic/claude-opus-4.6"

# Evaluation criteria for Stage 2 scoring (weights are relative, not percentages)
EVALUATION_CRITERIA: list[EvaluationCriterion] = [
    {"name": "Accuracy", "weight": 3, "description": "Factual correctness, absence of hallucinations, and reliable claims"},
    {"name": "Depth",    "weight": 2, "description": "Completeness of coverage, insightfulness, and substantive analysis"},
    {"name": "Clarity",  "weight": 1, "description": "Coherent structure, readable prose, and well-organized presentation"},
]

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"
