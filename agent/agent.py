# agent.py — quotation_pipeline wiring
# Patterns taken from the class Colab notebooks (plus Day 1–2 slides):
#   lab1_hello_world_adk_colab_participants.ipynb
#     MODEL = "gemini-3.5-flash"; GOOGLE_GENAI_USE_VERTEXAI=FALSE;
#     Runner + InMemorySessionService + auto_create_session=True;
#     runner.run(...) (sync); genai_types.Part.from_text;
#     LiteLlm(model="gemini/gemini-3.5-flash") only when swapping providers
#   lab4_multi_agent_orchestration_colab_participants.ipynb
#     SequentialAgent / ParallelAgent / LoopAgent + output_key + {placeholders}
#   lab5_dynamic_routing_colab_participants.ipynb (and Danny's copy)
#     same session/runner helper; AgentTool from google.adk.tools (optional later)
#   lab2_multi_tool_agent_colab_participants.ipynb
#     before_model_callback=block_injection on the agent

from __future__ import annotations

import inspect
import json
import os
import uuid
from typing import Any

from . import prompts
from .guardrails import append_audit, enforce_price_floor, block_injection
from .tools import check_stock, get_price_rule, search_past_quotes

# Lab 1 / Lab 2 / Lab 4 / Lab 5 notebooks: use the Gemini Developer API, not Vertex.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

# Exact constant from the class labs (e.g. Lab 1 cell, Lab 5 cell 7).
MODEL = "gemini-3.5-flash"

# Optional override for a one-off test; default stays the class MODEL.
MODEL = os.environ.get("MODEL", MODEL)

APP_NAME = "quotation_assistant"


def _build_root_agent():
    """Build the SequentialAgent pipeline the way Lab 4 assembles movie_pitch_team."""
    from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent

    intake_parser = Agent(
        name="intake_parser",
        model=MODEL,
        instruction=prompts.INTAKE_PARSER,
        output_key="enquiry",
        before_model_callback=block_injection,
    )

    past_quote_retriever = Agent(
        name="past_quote_retriever",
        model=MODEL,
        instruction=prompts.PAST_QUOTE_RETRIEVER,
        tools=[search_past_quotes],
        output_key="past_quotes",
        before_model_callback=block_injection,
    )
    pricing_agent = Agent(
        name="pricing_agent",
        model=MODEL,
        instruction=prompts.PRICING_AGENT,
        tools=[get_price_rule],
        output_key="pricing",
        before_model_callback=block_injection,
    )
    stock_agent = Agent(
        name="stock_agent",
        model=MODEL,
        instruction=prompts.STOCK_AGENT,
        tools=[check_stock],
        output_key="stock",
        before_model_callback=block_injection,
    )
    research = ParallelAgent(
        name="research",
        sub_agents=[past_quote_retriever, pricing_agent, stock_agent],
    )

    quote_drafter = Agent(
        name="quote_drafter",
        model=MODEL,
        instruction=prompts.QUOTE_DRAFTER,
        output_key="quote_draft",
        before_model_callback=block_injection,
    )

    judge_agent = Agent(
        name="judge_agent",
        model=MODEL,
        instruction=prompts.JUDGE_AGENT,
        output_key="judge_review",
        before_model_callback=block_injection,
    )
    refiner_agent = Agent(
        name="refiner_agent",
        model=MODEL,
        instruction=prompts.REFINER_AGENT,
        output_key="quote_draft",  # Lab 4 refiner overwrites the draft key
        before_model_callback=block_injection,
    )
    review_loop = LoopAgent(
        name="review_loop",
        sub_agents=[judge_agent, refiner_agent],
        max_iterations=2,
    )

    return SequentialAgent(
        name="quotation_pipeline",
        sub_agents=[intake_parser, research, quote_drafter, review_loop],
    )


try:
    root_agent = _build_root_agent()
except Exception:  # google-adk may not be installed yet
    root_agent = None


def _as_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _state_to_result(state: dict, raw_enquiry: str) -> dict:
    enquiry = _as_dict(state.get("enquiry")) or {}
    quote_draft = _as_dict(state.get("quote_draft")) or {}
    judge_review = _as_dict(state.get("judge_review")) or {}
    pricing = _as_dict(state.get("pricing")) or {}
    floor = enforce_price_floor(quote_draft, pricing)
    if not floor["ok"]:
        warnings = list(quote_draft.get("warnings") or []) if isinstance(quote_draft, dict) else []
        warnings.append("Price floor check failed; not ready to approve.")
        if isinstance(quote_draft, dict):
            quote_draft = dict(quote_draft)
            quote_draft["warnings"] = warnings
        if isinstance(judge_review, dict):
            judge_review = dict(judge_review)
            judge_review["pass"] = False
            judge_review.setdefault("issues", []).append("Deterministic price-floor check failed.")
    return {
        "enquiry": enquiry,
        "past_quotes": _as_dict(state.get("past_quotes")),
        "pricing": pricing,
        "stock": _as_dict(state.get("stock")),
        "quote_draft": quote_draft,
        "judge_review": judge_review,
        "cost_trace": _as_dict(state.get("cost_trace"))
        or {"calls": 0, "total_usd_estimate": 0.0, "note": "Fill from Langfuse / token usage"},
        "approval_status": "pending",
        "floor_check": {"ok": floor["ok"], "violations": floor["violations"]},
        "raw_enquiry_preview": (raw_enquiry or "")[:80],
        "used_stub": False,
    }


def stub_result(raw_enquiry: str) -> dict:
    """Example-only stub so the Streamlit UI can be demoed if ADK is not installed."""
    return {
        "enquiry": {
            "buyer_label": "EXAMPLE_CUSTOMER_A",
            "need_by": None,
            "currency": "MYR",
            "lines": [
                {
                    "line_no": 1,
                    "product_query": (raw_enquiry[:80] if raw_enquiry else "EXAMPLE general-purpose resin"),
                    "suggested_sku": "EXAMPLE-RESIN-001",
                    "qty": 500,
                    "uom": "KG",
                    "target_price": None,
                    "confidence": "medium",
                }
            ],
            "parse_warnings": ["Stub result — ADK pipeline not run"],
        },
        "quote_draft": {
            "quote_id": "DRAFT-EXAMPLE-001",
            "example_only": True,
            "currency": "MYR",
            "validity_days": 14,
            "lines": [
                {
                    "line_no": 1,
                    "sku": "EXAMPLE-RESIN-001",
                    "description": "EXAMPLE general-purpose resin, 25kg bag",
                    "qty": 500,
                    "uom": "KG",
                    "unit_price": 5.00,
                    "line_total": 2500.00,
                    "lead_time_days": 3,
                    "source": "price_rule",
                }
            ],
            "subtotal": 2500.00,
            "notes": ["Example figures only"],
            "warnings": [],
        },
        "judge_review": {
            "pass": True,
            "total": 8,
            "scores": {
                "completeness": 2,
                "floor_margin": 2,
                "grounding": 1,
                "consistency": 2,
                "safety": 1,
            },
            "issues": ["Stub scores"],
            "required_fixes": [],
        },
        "cost_trace": {"calls": 0, "total_usd_estimate": 0.00, "note": "Fill from Langfuse / token usage"},
        "approval_status": "pending",
        "used_stub": True,
    }


def _maybe_sync(value: Any) -> Any:
    """Labs call create_session / get_session synchronously. Unwrap a coroutine if the installed ADK is async."""
    if not inspect.iscoroutine(value):
        return value
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    # Streamlit (and similar) may already have a loop — run in a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, value).result()


class AgentChatSession:
    """Same helper as Lab 1 / Lab 4 / Lab 5 notebooks (InMemorySessionService + Runner.run).

    Extra: after drain, read session.state so Streamlit can show output_key values.
    """

    def __init__(self, agent, app_name=APP_NAME, user_id="local-demo"):
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        self.agent = agent
        self.app_name = app_name
        self.user_id = user_id
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
            auto_create_session=True,
        )
        self.session_id = f"session_{uuid.uuid4().hex[:8]}"
        self.session = _maybe_sync(
            self.session_service.create_session(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=self.session_id,
            )
        )

    def send(self, prompt: str) -> str:
        from google.genai import types as genai_types

        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=prompt)],
        )
        events = self.runner.run(
            user_id=self.user_id,
            session_id=self.session_id,
            new_message=message,
        )
        # runner.run may itself be a coroutine in some ADK versions
        events = _maybe_sync(events)
        parts = []
        for event in events:
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
        return "".join(parts)

    def state(self) -> dict:
        sess = self.session
        if hasattr(self.session_service, "get_session"):
            fetched = _maybe_sync(
                self.session_service.get_session(
                    app_name=self.app_name,
                    user_id=self.user_id,
                    session_id=self.session_id,
                )
            )
            if fetched is not None:
                sess = fetched
        return dict(getattr(sess, "state", {}) or {})


def run_quotation_pipeline(raw_enquiry: str) -> dict:
    """Run quotation_pipeline with the Lab 1/4/5 session helper; return output_key state."""
    enquiry_text = raw_enquiry or ""
    if root_agent is None:
        stub = stub_result(enquiry_text)
        stub["pipeline_error"] = "root_agent not built (install google-adk from requirements.txt)."
        return stub
    try:
        chat = AgentChatSession(root_agent)
        chat.send(enquiry_text)
        out = _state_to_result(chat.state(), enquiry_text)
        out["used_stub"] = False
        return out
    except TypeError:
        # Some ADK builds reject auto_create_session=True — retry without it.
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types as genai_types

            session_service = InMemorySessionService()
            session_id = f"session_{uuid.uuid4().hex[:8]}"
            _maybe_sync(
                session_service.create_session(
                    app_name=APP_NAME, user_id="local-demo", session_id=session_id
                )
            )
            runner = Runner(
                agent=root_agent, app_name=APP_NAME, session_service=session_service
            )
            message = genai_types.Content(
                role="user", parts=[genai_types.Part.from_text(text=enquiry_text)]
            )
            events = _maybe_sync(
                runner.run(user_id="local-demo", session_id=session_id, new_message=message)
            )
            for _ in events:
                pass
            sess = _maybe_sync(
                session_service.get_session(
                    app_name=APP_NAME, user_id="local-demo", session_id=session_id
                )
            )
            state = dict(getattr(sess, "state", {}) or {})
            out = _state_to_result(state, enquiry_text)
            out["used_stub"] = False
            return out
        except Exception as exc:
            stub = stub_result(enquiry_text)
            stub["pipeline_error"] = f"{type(exc).__name__}: {exc}. Showing stub output."
            return stub
    except Exception as exc:
        stub = stub_result(enquiry_text)
        stub["pipeline_error"] = f"{type(exc).__name__}: {exc}. Showing stub output."
        return stub
