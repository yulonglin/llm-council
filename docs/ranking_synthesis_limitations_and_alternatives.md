# Ranking & Synthesis: Limitations and Alternatives

## Current Behavior

### Stage 2: Peer Ranking

**Prompt excerpt** (`backend/council.py:73-75`):
```
For each response, explain what it does well and what it does poorly.
```

**What happens**:
- Each council model receives all Stage 1 responses (anonymized as Response A, B, C, D)
- Models evaluate and produce a linear ranking from "best" to "worst"
- Rankings are aggregated by average position

**Implicit assumptions**:
- Responses can be meaningfully ordered
- "Good" and "poor" are universal, context-independent qualities
- Convergence toward consensus is desirable

### Stage 3: Synthesis

**Prompt excerpt** (`backend/council.py:151-157`):
```
Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom
```

**What happens**:
- Chairman sees all responses + all rankings (with model attribution)
- Produces single "authoritative" answer

**Implicit assumptions**:
- There is a single best answer to converge on
- Synthesis improves on individual responses
- "Collective wisdom" means agreement, not diversity

---

## The Problem

The current design optimizes for **convergent, factual Q&A**. It breaks down for other query types:

| Query Type | Why Current Design Fails |
|------------|-------------------------|
| **Brainstorming** | Diversity is the value; ranking destroys it |
| **Creative tasks** | Aesthetic judgment is subjective; linear ranking is meaningless |
| **Exploratory questions** | Multiple valid paths exist; synthesis forces premature closure |
| **Debates/opinions** | Legitimate disagreement is the point, not a bug |
| **Preference-based** | No objective "best" exists |

### Concrete Example

**Query**: "What are some ways to reduce customer churn?"

**Stage 1 responses**:
- GPT: Focus on onboarding improvements
- Claude: Implement predictive analytics to identify at-risk customers
- Gemini: Build community and emotional connection
- Grok: Simplify pricing, remove friction

**Current behavior**: Models rank these, chairman picks a "winner" or blends them into mush.

**What would be more useful**: Show all four as distinct strategic directions, perhaps clustered by approach (proactive vs. reactive, emotional vs. analytical).

---

## Potential Directions

### 1. Query Classification → Different Pipelines

Detect query type before running council:

```
Factual/analytical  → Current 3-stage pipeline (ranking makes sense)
Brainstorming       → Stage 1 only, or cluster-based Stage 2
Creative            → Stage 1 only, let user choose
Exploratory         → Modified synthesis that preserves perspectives
```

**Implementation**: Add a classification step before Stage 1, route to different pipelines.

**Tradeoff**: Adds latency and complexity. Classification itself may be unreliable.

### 2. No-Rank Mode

Skip Stage 2 entirely for appropriate queries. Just show 4 responses side-by-side.

**Implementation**: Simple flag or automatic detection. Minimal code change.

**Tradeoff**: Loses the "which models are performing well" signal. User must do more cognitive work.

### 3. Cluster Instead of Rank

Replace linear ranking with thematic clustering:

**New Stage 2 prompt**:
```
Analyze these responses and identify:
1. What distinct approaches/perspectives are represented?
2. Which responses share similar reasoning?
3. What unique value does each response add that others miss?

Do NOT rank them from best to worst.
```

**Output**: Groups of related ideas + unique contributions highlighted.

**Tradeoff**: Harder to parse programmatically. May still implicitly favor some perspectives.

### 4. Reframe Stage 2: "Unique Value" Instead of "Best/Worst"

Keep the structure but change the evaluation criteria:

**Current**: "What does it do well and poorly?"
**Alternative**: "What unique insight or approach does this response offer that the others don't?"

This shifts from competitive ranking to complementary analysis.

### 5. Reframe Stage 3: Synthesis That Preserves Diversity

**Current prompt goal**: "single, comprehensive, accurate answer"

**Alternative prompt goal**:
```
Your task is to help the user understand the range of perspectives offered:
1. What are the distinct approaches or schools of thought represented?
2. What are the key tradeoffs between them?
3. Under what circumstances might each approach be most appropriate?

Do NOT collapse these into a single recommendation unless the responses genuinely converge.
```

### 6. Hybrid: Rank + Preserve

Keep ranking for factual accuracy, but add a "diversity preservation" layer:

- Stage 2 ranks as usual
- Stage 3 synthesis highlights: "The council converged on X, but Response B offered a unique perspective on Y that's worth considering if Z is important to you."

---

## Recommendation

**Short-term (minimal change)**: Add query-type detection and skip Stage 2 for brainstorming/creative queries. This is low-effort and immediately improves those use cases.

**Medium-term**: Reframe Stage 2 and Stage 3 prompts to emphasize "unique contributions" over "best/worst" ranking. This preserves the multi-stage structure while changing its character.

**Long-term**: Consider whether the 3-stage pipeline is even the right abstraction. For some queries, you might want:
- Iterative refinement (models build on each other)
- Adversarial debate (models argue positions)
- Structured decomposition (break question into parts, assign to different models)

---

## Questions to Resolve

1. How reliable is automatic query classification? Should it be user-controlled instead?
2. Is aggregate ranking data still valuable for understanding model performance, even if not shown to users?
3. Should the chairman always be a different model than council members, or could it rotate?
4. For brainstorming, is 4 responses the right number? Should we sample more models with shorter responses?
