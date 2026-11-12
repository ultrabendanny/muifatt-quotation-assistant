# guardrails.py
# (Lab 2 notebook lab2_multi_tool_agent_colab_participants.ipynb:
#    INJECTION blocklist + block_injection before_model_callback + LlmResponse)
# (Day 1 p.84: same callback extends to PII redaction and tool-call authorisation on Day 3)
# (Day 1 p.46 tool-level price floor; Day 3 outline audit log)

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
AUDIT_LOG = DATA_DIR / "audit.jsonl"

# Exact phrases from Lab 2, plus two capstone golden-set variants (still a blocklist only).
INJECTION = (
    "ignore previous instructions",
    "reveal your system prompt",
    "ignore your rules",
    "give a 0 myr price",
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?6?0|0)?1[0-9\- ]{7,11}\b")
IC_RE = re.compile(r"\b\d{6}[-\s]?\d{2}[-\s]?\d{4}\b")


def redact_pii(text: str) -> str:
    """Mask emails, phone numbers, and IC-like numbers before the model sees them (Day 3)."""
    if not text:
        return text
    out = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    out = PHONE_RE.sub("[REDACTED_PHONE]", out)
    out = IC_RE.sub("[REDACTED_IC]", out)
    return out


def block_injection(callback_context, llm_request):
    """Block prompt-injection before the model runs.

    Lab 2 notebook (same signature and LlmResponse short-circuit). After an
    allow, redact PII in place (Day 3 extension of this callback).
    """
    last = ""
    if getattr(llm_request, "contents", None) and llm_request.contents[-1].parts:
        last = llm_request.contents[-1].parts[0].text or ""
    if any(p in last.lower() for p in INJECTION):
        try:
            from google.adk.models import LlmResponse
            from google.genai import types

            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="Request blocked by safety policy.")],
                )
            )
        except Exception:
            return {"blocked": True, "reason": "prompt_injection"}

    redacted = redact_pii(last)
    if redacted != last:
        try:
            llm_request.contents[-1].parts[0].text = redacted
        except Exception:
            pass
    return None


# Alias used in earlier draft comments.
safety_guard = block_injection


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            return {}
    return {}


def enforce_price_floor(quote_draft: Any, pricing: Any) -> dict:
    """Deterministic floor check (Day 1 p.46 tool-level layer). Not an LLM call."""
    draft = _as_dict(quote_draft)
    pricing_obj = _as_dict(pricing)
    floors = {}
    for line in pricing_obj.get("lines") or []:
        if not isinstance(line, dict):
            continue
        key = line.get("line_no") or line.get("sku")
        if key is not None and line.get("price_floor") is not None:
            floors[key] = float(line["price_floor"])

    violations = []
    for line in draft.get("lines") or []:
        if not isinstance(line, dict):
            continue
        price = line.get("unit_price")
        if price is None:
            continue
        floor = floors.get(line.get("line_no"), floors.get(line.get("sku")))
        if floor is None:
            continue
        if float(price) < float(floor):
            violations.append(
                {
                    "line_no": line.get("line_no"),
                    "sku": line.get("sku"),
                    "unit_price": float(price),
                    "price_floor": float(floor),
                }
            )
    return {"ok": not violations, "quote_draft": draft, "violations": violations}


def append_audit(event: dict) -> None:
    """Append one JSONL audit record. Never write API keys or raw PII."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(event or {})
    payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
    for banned in ("api_key", "GOOGLE_API_KEY", "password", "secret"):
        payload.pop(banned, None)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
