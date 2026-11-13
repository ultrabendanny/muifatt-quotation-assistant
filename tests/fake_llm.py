"""A scripted stand-in for Gemini so the real ADK graph (callbacks, AgentTool, state) runs offline."""
from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

DRAFT = {
    "quote_id": "DRAFT-FAKE", "example_only": True, "currency": "MYR", "validity_days": 14,
    "lines": [{"line_no": 1, "sku": "EXAMPLE-RESIN-001", "description": "EXAMPLE resin", "qty": 500, "uom": "KG",
               "unit_price": 5.0, "line_total": 2500.0, "lead_time_days": 3, "source": "price_rule"}],
    "subtotal": 2500.0, "notes": [], "warnings": [],
}
ENQUIRY = {"buyer_label": "EXAMPLE_CUSTOMER", "currency": "MYR",
           "lines": [{"line_no": 1, "suggested_sku": "EXAMPLE-RESIN-001", "qty": 500, "uom": "KG"}]}


def _role(request: LlmRequest) -> str:
    instruction = request.config.system_instruction if request.config else ""
    text = instruction if isinstance(instruction, str) else str(instruction)
    for line in text.splitlines() + [text]:
        if "ROLE:" in line:
            return line.split("ROLE:")[1].split()[0]
    return "unknown"


def _n_function_responses(request: LlmRequest) -> int:
    return sum(1 for c in request.contents for p in (c.parts or []) if getattr(p, "function_response", None))


def _call(name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


class FakeLlm(BaseLlm):
    model: str = "fake-model"
    seen_texts: list = []
    roles: list = []

    @classmethod
    def supported_models(cls):
        return [r"fake-model"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        role, n = _role(llm_request), _n_function_responses(llm_request)
        self.roles.append(role)
        for c in llm_request.contents:
            for p in c.parts or []:
                if getattr(p, "text", None):
                    self.seen_texts.append(p.text)
        if role == "enterprise_analyst_agent":
            part = (_call("mcp_list_tables") if n == 0 else
                    _call("data_pricing_analyst", request="Price and stock for 500 KG EXAMPLE-RESIN-001") if n == 1 else
                    types.Part(text="FAKE FINAL: 500 KG of EXAMPLE-RESIN-001 at MYR 5.00 per KG."))
        elif role == "data_pricing_analyst":
            part = (_call("mcp_list_tables") if n == 0 else
                    _call("mcp_read_query", sql_query="SELECT sku, list_price FROM price_rules") if n == 1 else
                    types.Part(text=json.dumps({"lines": [{"sku": "EXAMPLE-RESIN-001", "list_price": 5.0}], "warnings": []})))
        elif role == "policy_checker":
            part = _call("mcp_list_policies") if n == 0 else types.Part(text=json.dumps({"rules_applied": ["floor"], "violations": []}))
        elif role == "intake_parser":
            part = types.Part(text="```json\n" + json.dumps(ENQUIRY) + "\n```")
        elif role == "quote_drafter":
            part = types.Part(text=json.dumps(DRAFT))
        elif role == "quote_reviewer":
            part = types.Part(text=json.dumps({"score": 5, "pass": True, "issues": []}))
        elif role == "eval_judge":
            part = types.Part(text=json.dumps({"score": 4, "reasoning": "fake"}))
        else:
            part = types.Part(text="unknown role")
        yield LlmResponse(
            content=types.Content(role="model", parts=[part]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20),
        )
