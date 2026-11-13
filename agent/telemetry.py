# telemetry.py: Pillar 4, cost tracking (Capstone Step 5 / Lab 7 Page 4).
#
# after_model_cost_tracker is an ADK after_model_callback. It reads usage_metadata on
# every model completion and accumulates prompt / completion tokens and estimated USD.
# STATS is process-wide (as in Lab 7), so on Streamlit Cloud it counts every visitor
# since the server started. app.py and eval.py show per-run deltas via snapshot().

from __future__ import annotations

import threading

# Example rates in USD per 1M tokens. EXAMPLE RATES, CHECK CURRENT GEMINI PRICING:
# https://ai.google.dev/gemini-api/docs/pricing  (the course Lab 7 used ~0.075 / 0.30).
PRICE_PER_M_PROMPT = 0.30
PRICE_PER_M_COMPLETION = 2.50

_LOCK = threading.Lock()
STATS = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def after_model_cost_tracker(callback_context, llm_response):
    """Post-model callback: tally token usage. Returns None so the response is unchanged."""
    usage = getattr(llm_response, "usage_metadata", None)
    if usage:
        prompt = getattr(usage, "prompt_token_count", 0) or 0
        completion = (getattr(usage, "candidates_token_count", 0) or 0) + (
            getattr(usage, "thoughts_token_count", 0) or 0
        )
        with _LOCK:
            STATS["prompt_tokens"] += prompt
            STATS["completion_tokens"] += completion
            STATS["calls"] += 1
    return None


def estimate_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens / 1_000_000) * PRICE_PER_M_PROMPT + (
        completion_tokens / 1_000_000
    ) * PRICE_PER_M_COMPLETION


def snapshot() -> dict:
    with _LOCK:
        s = dict(STATS)
    s["total_tokens"] = s["prompt_tokens"] + s["completion_tokens"]
    s["usd"] = round(estimate_usd(s["prompt_tokens"], s["completion_tokens"]), 6)
    return s


def delta(before: dict, after: dict | None = None) -> dict:
    """Usage between two snapshots (after defaults to now)."""
    after = after or snapshot()
    out = {k: after[k] - before[k] for k in ("calls", "prompt_tokens", "completion_tokens")}
    out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    out["usd"] = round(estimate_usd(out["prompt_tokens"], out["completion_tokens"]), 6)
    return out


def reset() -> None:
    with _LOCK:
        for k in STATS:
            STATS[k] = 0


def dashboard() -> str:
    s = snapshot()
    return (
        "TELEMETRY & COST (estimated, example rates)\n"
        f"  API calls:         {s['calls']}\n"
        f"  Prompt tokens:     {s['prompt_tokens']:,}\n"
        f"  Completion tokens: {s['completion_tokens']:,}\n"
        f"  Total tokens:      {s['total_tokens']:,}\n"
        f"  Estimated cost:    ${s['usd']:.6f} USD"
    )
