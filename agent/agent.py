# agent.py: the capstone agents (Capstone Step 6) and the functions that run them.
#
# Patterns taken from the class Colab notebooks:
#   Lab 1   MODEL = "gemini-3.5-flash"; GOOGLE_GENAI_USE_VERTEXAI=FALSE;
#           Runner + InMemorySessionService + auto_create_session=True; runner.run(...)
#   Lab 4   SequentialAgent / ParallelAgent + output_key + {placeholders}
#   Lab 5   coordinator with AgentTool specialists (load-bearing descriptions)
#   Lab 6   mcp_* discovery tools, no mutation tool registered
#   Lab 7   before_model_callback guardrail + after_model_callback cost tracker
#
# Pillar 1 (multi-agent):
#   enterprise_analyst_agent   coordinator used by the chat tab and by eval.py
#       tools: mcp_* discovery tools + AgentTool(data_pricing_analyst, policy_checker, quote_drafter)
#   quotation_pipeline         SequentialAgent used by the "Quote" tab (structured result)
#       intake_parser -> research[data_pricing_analyst || policy_checker] -> quote_drafter -> quote_reviewer
#
# Every agent carries both callbacks, so every model call is guarded and metered.

from __future__ import annotations

import inspect
import json
import os
import uuid
from typing import Any

from . import prompts, stub, telemetry
from .guardrails import (
    BLOCK_MESSAGE,
    append_audit,
    before_model_guardrail,
    enforce_price_floor,
    looks_like_injection,
    redact_pii,
)
from .mcp_tools import MCP_DB_TOOLS, MCP_POLICY_TOOLS, MCP_TOOLS

# Lab 1 / Lab 2 / Lab 4 / Lab 5 notebooks: use the Gemini Developer API, not Vertex.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

# Exact constant from the class labs. Optional env override for one-off tests.
MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

APP_NAME = "quotation_assistant"


def _callbacks() -> dict:
    return {
        "before_model_callback": before_model_guardrail,
        "after_model_callback": telemetry.after_model_cost_tracker,
    }


# --------------------------------------------------------------------------
# Agent factories (new instances each call, so no agent ever has two parents)
# --------------------------------------------------------------------------
def build_specialists(model=None, for_pipeline: bool = False) -> dict:
    """The three specialists. Pipeline versions read {state}, chat versions take a request."""
    from google.adk.agents import Agent

    model = model or MODEL
    analyst_instruction = prompts.DATA_PRICING_ANALYST
    policy_instruction = prompts.POLICY_CHECKER
    if for_pipeline:
        analyst_instruction += "\nEnquiry to research:\n{enquiry}\n"
        policy_instruction += "\nEnquiry to check against policy:\n{enquiry}\n"

    data_pricing_analyst = Agent(
        name="data_pricing_analyst",
        model=model,
        description=(
            "Looks up list prices, price floors, volume breaks, stock levels, lead times and "
            "similar past quotes in the enterprise SQLite database. Use for any price, stock or "
            "history question. Read-only."
        ),
        instruction=analyst_instruction,
        tools=list(MCP_DB_TOOLS),
        output_key="pricing_data" if for_pipeline else None,
        **_callbacks(),
    )
    policy_checker = Agent(
        name="policy_checker",
        model=model,
        description=(
            "Reads the markdown policy documents (quoting policy, stock and lead time rules, "
            "compliance handbook) and reports which rules apply and whether a request breaks one."
        ),
        instruction=policy_instruction,
        tools=list(MCP_POLICY_TOOLS),
        output_key="policy_notes" if for_pipeline else None,
        **_callbacks(),
    )
    drafter_instruction = prompts.QUOTE_DRAFTER
    if not for_pipeline:
        drafter_instruction = (
            drafter_instruction.replace("Enquiry: {enquiry}\n", "")
            .replace("Data and pricing findings: {pricing_data}\n", "")
            .replace("Policy findings: {policy_notes}\n", "")
            .replace("Use ONLY the inputs below.", "Use ONLY the facts given in the request.")
        )
    quote_drafter = Agent(
        name="quote_drafter",
        model=model,
        description=(
            "Turns an enquiry plus price, stock and policy findings into a JSON draft quote. "
            "Pass the enquiry and the findings in the request. It has no tools."
        ),
        instruction=drafter_instruction,
        output_key="quote_draft" if for_pipeline else None,
        **_callbacks(),
    )
    return {
        "data_pricing_analyst": data_pricing_analyst,
        "policy_checker": policy_checker,
        "quote_drafter": quote_drafter,
    }


def build_enterprise_analyst_agent(model=None):
    """Coordinator (Step 6): discovery tools + specialist AgentTools + both callbacks."""
    from google.adk.agents import Agent
    from google.adk.tools.agent_tool import AgentTool

    specialists = build_specialists(model, for_pipeline=False)
    return Agent(
        name="enterprise_analyst_agent",
        model=model or MODEL,
        description="Coordinator for the quoting desk: delegates to data, policy and drafting specialists.",
        instruction=prompts.COORDINATOR,
        tools=[*MCP_TOOLS, *[AgentTool(agent=a) for a in specialists.values()]],
        **_callbacks(),
    )


def build_quotation_pipeline(model=None):
    """Structured quote workflow for the Quote tab (Lab 4 style)."""
    from google.adk.agents import Agent, ParallelAgent, SequentialAgent

    model = model or MODEL
    intake_parser = Agent(
        name="intake_parser",
        model=model,
        instruction=prompts.INTAKE_PARSER,
        output_key="enquiry",
        **_callbacks(),
    )
    s = build_specialists(model, for_pipeline=True)
    research = ParallelAgent(
        name="research",
        sub_agents=[s["data_pricing_analyst"], s["policy_checker"]],
    )
    quote_reviewer = Agent(
        name="quote_reviewer",
        model=model,
        instruction=prompts.QUOTE_REVIEWER,
        output_key="review",
        **_callbacks(),
    )
    return SequentialAgent(
        name="quotation_pipeline",
        sub_agents=[intake_parser, research, s["quote_drafter"], quote_reviewer],
    )


def build_judge_agent(model=None):
    """Separate judge (Lab 7 Page 5). Deliberately has NO data tools and no callbacks that block."""
    from google.adk.agents import Agent

    return Agent(
        name="eval_judge",
        model=model or MODEL,
        instruction=prompts.JUDGE,
        after_model_callback=telemetry.after_model_cost_tracker,
    )


# --------------------------------------------------------------------------
# Running agents (same session helper as Lab 1 / 4 / 5 / 7)
# --------------------------------------------------------------------------
def _maybe_sync(value: Any) -> Any:
    """Unwrap a coroutine if the installed ADK exposes an async session API."""
    if not inspect.iscoroutine(value):
        return value
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result()


class AgentChatSession:
    """InMemorySessionService + Runner.run, as in the lab notebooks."""

    def __init__(self, agent, app_name=APP_NAME, user_id="local-demo", state=None):
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        self.agent = agent
        self.app_name = app_name
        self.user_id = user_id
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=agent, app_name=app_name,
            session_service=self.session_service, auto_create_session=True,
        )
        self.session_id = f"session_{uuid.uuid4().hex[:8]}"
        self.session = _maybe_sync(
            self.session_service.create_session(
                app_name=app_name, user_id=user_id, session_id=self.session_id, state=state or {},
            )
        )

    def send(self, prompt: str) -> str:
        from google.genai import types as genai_types

        message = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=prompt)])
        events = _maybe_sync(
            self.runner.run(user_id=self.user_id, session_id=self.session_id, new_message=message)
        )
        parts = []
        for event in events:
            if getattr(event, "content", None) and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        parts.append(part.text)
        return "".join(parts)

    def state(self) -> dict:
        sess = self.session
        fetched = _maybe_sync(
            self.session_service.get_session(
                app_name=self.app_name, user_id=self.user_id, session_id=self.session_id
            )
        )
        if fetched is not None:
            sess = fetched
        return dict(getattr(sess, "state", {}) or {})


def api_key_present() -> bool:
    return bool(os.environ.get("GOOGLE_API_KEY", "").strip())


def _mask(message: str) -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    return message.replace(key, "[REDACTED_KEY]") if key else message


def _as_dict(value: Any) -> Any:
    """output_key values arrive as text; models often wrap JSON in ```json fences."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def new_chat_session(model=None) -> AgentChatSession:
    """A persistent coordinator conversation (one per Streamlit session)."""
    return AgentChatSession(build_enterprise_analyst_agent(model))


def ask_analyst(question: str, session: AgentChatSession | None = None, force_stub: bool = False) -> dict:
    """Ask the coordinator one question.

    Returns {"answer", "mode": "live"|"stub", "blocked", "usage", "error"}.
    Live mode needs GOOGLE_API_KEY. Any live failure falls back to the stub with a masked reason.
    """
    before = telemetry.snapshot()
    if not force_stub and api_key_present():
        try:
            session = session or new_chat_session()
            answer = session.send(question)
            return {
                "answer": answer,
                "mode": "live",
                "blocked": BLOCK_MESSAGE in answer,
                "usage": telemetry.delta(before),
                "error": None,
            }
        except Exception as exc:
            result = stub.stub_answer(question)
            result.update(mode="stub", usage=telemetry.delta(before),
                          error=f"{type(exc).__name__}: {_mask(str(exc))}")
            return result
    result = stub.stub_answer(question)
    result.update(mode="stub", usage=telemetry.delta(before),
                  error=None if force_stub else "GOOGLE_API_KEY is not set")
    return result


def _state_to_result(state: dict) -> dict:
    enquiry = _as_dict(state.get("enquiry")) or {}
    quote_draft = _as_dict(state.get("quote_draft")) or {}
    review = _as_dict(state.get("review")) or {}
    floor = enforce_price_floor(quote_draft)
    if not floor["ok"] and isinstance(review, dict):
        review = dict(review)
        review["pass"] = False
        review.setdefault("issues", []).append("Deterministic price-floor check failed.")
    return {
        "enquiry": enquiry,
        "pricing_data": _as_dict(state.get("pricing_data")),
        "policy_notes": _as_dict(state.get("policy_notes")),
        "quote_draft": quote_draft,
        "review": review,
        "floor_check": floor,
        "approval_status": "pending",
    }


def run_quotation_pipeline(raw_enquiry: str, force_stub: bool = False) -> dict:
    """Run the Quote tab pipeline. Always returns a dict the UI can render."""
    text = raw_enquiry or ""
    before = telemetry.snapshot()

    # Tier 1, up front: a blocked enquiry must not reach any stage of the pipeline.
    if looks_like_injection(text):
        append_audit({"event": "blocked", "reason": "prompt_injection", "sent": False})
        return {"blocked": True, "block_reason": BLOCK_MESSAGE, "mode": "live" if api_key_present() else "stub",
                "approval_status": "blocked", "usage": telemetry.delta(before), "error": None}

    error = None
    if not force_stub and api_key_present():
        try:
            clean = redact_pii(text)
            chat = AgentChatSession(build_quotation_pipeline(), state={"raw_enquiry": clean})
            chat.send(clean)
            out = _state_to_result(chat.state())
            out.update(mode="live", blocked=False, usage=telemetry.delta(before), error=None)
            return out
        except Exception as exc:  # never show the key: type + masked message only
            error = f"{type(exc).__name__}: {_mask(str(exc))}"
    elif not force_stub:
        error = "GOOGLE_API_KEY is not set"
    out = stub.stub_quote(text)
    out.update(mode="stub", blocked=False, usage=telemetry.delta(before), error=error)
    out["floor_check"] = enforce_price_floor(out["quote_draft"])
    return out
