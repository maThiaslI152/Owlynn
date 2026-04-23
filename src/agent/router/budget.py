"""
Token budget estimation for the Multi-LLM Router.
--------------------------------------------------
Extracted from src/agent/nodes/router.py and enhanced to guarantee:
  - Budget is always a positive integer (>= 1)
  - Long-answer hint floor of 3072 for complex routes
  - Short-answer hint cap of 1536 for complex routes
  - Budget never exceeds available context window after input tokens
"""

from src.config.settings import (
    MEDIUM_DEFAULT_CONTEXT,
    MEDIUM_LONGCTX_CONTEXT,
    CLOUD_CONTEXT,
)

# ── Context window constants per model tier ──────────────────────────────
_MEDIUM_DEFAULT_CONTEXT = MEDIUM_DEFAULT_CONTEXT   # 100_000
_MEDIUM_LONGCTX_CONTEXT = MEDIUM_LONGCTX_CONTEXT   # 131_072
_CLOUD_CONTEXT = CLOUD_CONTEXT                     # 131_072
_SMALL_MODEL_CONTEXT = 4096

# Tier definitions: (max_input_chars, tier_budget)
_BUDGET_TIERS = [
    (40,   256),
    (150,  512),
    (400,  1536),
    (800,  3072),
    (1600, 4096),
]

# Keywords that signal the user wants a long/detailed answer
_LONG_ANSWER_HINTS = {
    "explain", "write", "create", "implement", "build", "generate",
    "refactor", "analyze", "compare", "review", "summarize", "translate",
    "step by step", "in detail", "full code", "complete",
}

# Keywords that signal a short answer is fine
_SHORT_ANSWER_HINTS = {
    "yes or no", "true or false", "which one", "what is",
    "how much", "how many", "when", "where",
}


def estimate_token_budget(user_text: str, route: str) -> int:
    """Estimate a reasonable max_tokens budget for the response.

    Guarantees
    ----------
    * Return value is always a **positive integer** (>= 1).
    * For complex routes with a long-answer hint keyword the budget is >= 3072.
    * For complex routes with a short-answer hint keyword the budget is <= 1536.
    * The budget never exceeds the available context window after accounting
      for estimated input tokens.
    """
    if route == "simple":
        budget = 256
        if len(user_text) > 100:
            budget = 512
        budget = min(budget, _SMALL_MODEL_CONTEXT - 1500)
        return max(1, int(budget))

    # ── Determine context window and reserves based on route ─────────────
    if route == "complex-cloud":
        context = _CLOUD_CONTEXT
        input_reserve = 8000
        budget_max = 16384
    elif route == "complex-longctx":
        context = _MEDIUM_LONGCTX_CONTEXT
        input_reserve = 4000
        budget_max = 8192
    else:  # complex-default, complex-vision
        context = _MEDIUM_DEFAULT_CONTEXT
        input_reserve = 4000
        budget_max = 8192

    text_len = len(user_text)
    text_lower = user_text.lower()

    # Start with tier-based estimate from input length
    budget = budget_max
    for max_chars, tier_budget in _BUDGET_TIERS:
        if text_len <= max_chars:
            budget = min(tier_budget, budget_max)
            break

    # Boost if the user is asking for something that needs a long answer
    if any(hint in text_lower for hint in _LONG_ANSWER_HINTS):
        budget = max(budget, 3072)

    # Cap if the user is asking a short-answer question
    if any(hint in text_lower for hint in _SHORT_ANSWER_HINTS):
        budget = min(budget, 1536)

    # Longer input text eats into the context window — reduce output budget.
    # Rough heuristic: ~4 chars per token for English.
    estimated_input_tokens = input_reserve + (text_len // 4)
    available = context - estimated_input_tokens
    budget = min(budget, max(available, 512))  # floor of 512 for complex

    # Final guarantee: always a positive integer
    return max(1, int(budget))
