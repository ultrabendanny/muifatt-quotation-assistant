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

from agent.agent import MODEL, run_quotation_pipeline
from agent.guardrails import append_audit, enforce_price_floor
from agent.tools import format_quote_pdf

load_dotenv()  # local .env; on Cloud this is a no-op if the file is absent

# Lab 1 notebook: use the Gemini Developer API, not Vertex.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")


def get_google_api_key() -> str:
    """Fill GOOGLE_API_KEY from .env (local) or st.secrets (Streamlit Cloud).

    Labs use os.environ["GOOGLE_API_KEY"] (Colab userdata / getpass). ADK and the
    Gemini client read that env var, so st.secrets is copied into it. The key is
    never hardcoded, printed, or written to disk.
    """
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        try:
            if "GOOGLE_API_KEY" in st.secrets:
                key = st.secrets["GOOGLE_API_KEY"]
        except Exception:  # no secrets file locally
            key = None
    if not key:
        st.error(
            "GOOGLE_API_KEY is not set. For local use, add it to a .env file. "
            "For Streamlit Cloud, add it in the app Secrets. Do not paste it into this screen."
        )
        st.stop()
    os.environ["GOOGLE_API_KEY"] = str(key).strip()
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

    if result.get("blocked"):
        st.error(result.get("block_reason", "Request blocked by safety policy."))
        st.caption("Lab 2 guardrail: the injection phrase was caught before any model call.")
        st.stop()

    # Mode line: live ADK pipeline on Gemini vs. stub example output.
    if result.get("used_stub"):
        st.caption("Mode: stub")
        st.warning(
            "The live pipeline failed, so this is stub example output, not a real "
            f"{MODEL} result.\n\n"
            f"Reason: {result.get('pipeline_error') or 'unknown'}"
        )
    else:
        st.caption(f"Mode: live ({MODEL})")

    st.subheader("Parsed lines")
    lines = enquiry.get("lines") if isinstance(enquiry, dict) else None
    if lines:
        st.dataframe(pd.DataFrame(lines), width="stretch")
    else:
        st.json(enquiry)
    if isinstance(enquiry, dict) and enquiry.get("parse_warnings"):
        st.warning("; ".join(enquiry["parse_warnings"]))

    st.subheader("Draft quote")
    if isinstance(draft, dict) and draft.get("example_only"):
        st.info("Figures are example only — not live customer pricing.")
    draft_lines = draft.get("lines") if isinstance(draft, dict) else None
    if draft_lines:
        st.dataframe(pd.DataFrame(draft_lines), width="stretch")
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
    quote_id = draft.get("quote_id") if isinstance(draft, dict) else None
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Approve (do not send)", disabled=not can_approve):
            result["approval_status"] = "approved"
            append_audit(
                {
                    "event": "approved",
                    "quote_id": quote_id,
                    "sent": False,
                    "judge_total": judge.get("total") if isinstance(judge, dict) else None,
                }
            )
    with c2:
        if st.button("Reject"):
            result["approval_status"] = "rejected"
            append_audit({"event": "rejected", "quote_id": quote_id, "sent": False})

    # Status is kept in the result (session_state), so it survives the rerun that
    # st.download_button triggers.
    status = result.get("approval_status")
    if status == "approved":
        st.success("Approved and written to the audit log. Not sent to any customer.")
        pdf = format_quote_pdf(draft, "approved")
        if pdf.get("ok"):
            st.download_button(
                "Download quote PDF",
                data=pdf["pdf_bytes"],
                file_name=pdf["filename"],
                mime="application/pdf",
            )
            st.caption("Saved to your device only. Nothing is emailed or shared.")
        else:
            st.error(f"Could not build the PDF: {pdf.get('error')}")
    elif status == "rejected":
        st.warning("Rejected. Nothing was sent.")
