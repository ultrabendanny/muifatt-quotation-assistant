# app.py — Streamlit UI for the Quotation Assistant
# (Class notes + lecturer: Streamlit UI.)
# (Lab 1 notebook: GOOGLE_API_KEY in the environment, GOOGLE_GENAI_USE_VERTEXAI=FALSE;
#  pipeline runs via AgentChatSession / Runner.run from lab1/lab4/lab5 notebooks.)
# Example data only. Do not hardcode secrets.

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from agent.agent import run_quotation_pipeline
from agent.guardrails import append_audit, enforce_price_floor
from agent.tools import format_quote_pdf

load_dotenv()  # local .env; on Cloud this is a no-op if the file is absent

# Lab 1 notebook: use the Gemini Developer API, not Vertex.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")


def get_google_api_key() -> str:
    """Read GOOGLE_API_KEY from .env (local) or Streamlit secrets (Cloud).

    Labs use os.environ["GOOGLE_API_KEY"] (Colab userdata / getpass). Here the
    same env var is filled from .env or st.secrets — never hardcoded.
    """
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        try:
            key = st.secrets["GOOGLE_API_KEY"]
        except Exception:
            key = None
    if not key:
        st.error(
            "GOOGLE_API_KEY is not set. For local use, add it to a .env file. "
            "For Streamlit Cloud, add it in the app Secrets. Do not paste it into this screen."
        )
        st.stop()
    os.environ["GOOGLE_API_KEY"] = key
    return key


st.set_page_config(page_title="Quotation Assistant (draft)", layout="wide")
get_google_api_key()

st.title("Quotation Assistant")
st.caption(
    "Internal draft only. Example data. A human must approve — this app does not send quotes."
)

raw = st.text_area(
    "Customer enquiry",
    height=160,
    placeholder="Paste the enquiry text (example / redacted)…",
)
upload = st.file_uploader("Or upload a .txt / .pdf enquiry", type=["txt", "pdf"])
if upload and upload.type == "text/plain":
    raw = upload.getvalue().decode("utf-8", errors="replace")

if st.button("Generate draft quote", type="primary", disabled=not (raw and raw.strip())):
    with st.spinner("Running quotation pipeline…"):
        st.session_state["result"] = run_quotation_pipeline(raw.strip())

result = st.session_state.get("result")
if result:
    enquiry = result.get("enquiry") or {}
    draft = result.get("quote_draft") or {}
    judge = result.get("judge_review") or {}
    cost = result.get("cost_trace") or {}
    pricing = result.get("pricing") or {}

    if result.get("used_stub"):
        st.info(
            "Showing stub example output (ADK runner not used yet). "
            "Install requirements and set GOOGLE_API_KEY, then rerun."
        )
        if result.get("pipeline_error"):
            st.caption(result["pipeline_error"])

    st.subheader("Parsed lines")
    lines = enquiry.get("lines") if isinstance(enquiry, dict) else None
    if lines:
        st.dataframe(pd.DataFrame(lines), use_container_width=True)
    else:
        st.json(enquiry)
    if isinstance(enquiry, dict) and enquiry.get("parse_warnings"):
        st.warning("; ".join(enquiry["parse_warnings"]))

    st.subheader("Draft quote")
    if isinstance(draft, dict) and draft.get("example_only"):
        st.info("Figures are example only — not live customer pricing.")
    draft_lines = draft.get("lines") if isinstance(draft, dict) else None
    if draft_lines:
        st.dataframe(pd.DataFrame(draft_lines), use_container_width=True)
        st.write(f"Subtotal: {draft.get('currency')} {draft.get('subtotal')}")
    else:
        st.json(draft)

    floor = result.get("floor_check") or enforce_price_floor(draft, pricing)
    if not floor.get("ok", True):
        st.error("Price floor check failed. Not ready to approve.")
        st.json(floor.get("violations"))

    col_j, col_c = st.columns(2)
    with col_j:
        st.metric(
            "Judge score",
            f"{judge.get('total', '–')}/10" if isinstance(judge, dict) else "–",
            "PASS" if isinstance(judge, dict) and judge.get("pass") else "FAIL",
        )
        st.json(judge)
    with col_c:
        estimate = 0.0
        if isinstance(cost, dict):
            estimate = float(cost.get("total_usd_estimate") or 0)
        st.metric("Estimated cost (USD)", f"{estimate:.4f}")
        st.json(cost)

    can_approve = bool(
        floor.get("ok", True)
        and isinstance(judge, dict)
        and judge.get("pass")
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Approve (do not send)", disabled=not can_approve):
            result["approval_status"] = "approved"
            append_audit(
                {
                    "event": "approved",
                    "quote_id": draft.get("quote_id") if isinstance(draft, dict) else None,
                    "sent": False,
                    "judge_total": judge.get("total") if isinstance(judge, dict) else None,
                }
            )
            pdf = format_quote_pdf(draft, "approved")
            st.success("Approved and written to the audit log. Not sent to any customer.")
            if pdf.get("ok"):
                st.caption(f"Local PDF preview path (not emailed): {pdf.get('path')}")
    with c2:
        if st.button("Reject"):
            result["approval_status"] = "rejected"
            append_audit(
                {
                    "event": "rejected",
                    "quote_id": draft.get("quote_id") if isinstance(draft, dict) else None,
                    "sent": False,
                }
            )
            st.warning("Rejected. Nothing was sent.")
