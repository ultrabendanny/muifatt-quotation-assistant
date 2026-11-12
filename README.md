# Quotation Assistant (Day 3 capstone draft)

Internal demo app: enquiry in → draft quote out → a human Approves or Rejects. The app **never sends** a quote to a customer.

All customers, SKUs, and prices in this folder are **labelled examples only**. Do not put real quotes, names, or API keys in Codeshare (it is public) or in GitHub.

Full design notes, source mapping, and “How to explain it” lines are in [`GUIDE.md`](GUIDE.md).

## Requirements

The lecturer asked for a `requirements.txt`. It is in this folder (unpinned, as in the draft):

```txt
google-adk
litellm
google-genai
streamlit
python-dotenv
pandas
```

Labs 1, 2, 4, and 5 install `google-adk` and `litellm`. The notebooks also `from google.genai import types`, so `google-genai` is listed here. Do not add ChromaDB until the Lab 3 RAG tool is wired.

Add the Langfuse SDK later if the Day 3 starter names it.

## Secrets (never hardcode)

- Local: copy `.env.example` to `.env` and set `GOOGLE_API_KEY=` there only (Day 1 p.62, p.72).
- Streamlit Community Cloud: set the same name in app Secrets (`st.secrets["GOOGLE_API_KEY"]`) — General practice.
- `.env` and `.streamlit/secrets.toml` are in `.gitignore`. They are also in `.dockerignore` so they are not baked into a Cloud Run image.
- Do not paste the key into Codeshare, GitHub, screenshots, or `app.py`.

## Run locally (Anaconda Prompt, not plain cmd)

Class notes: use **Anaconda Prompt** so the environment is on the PATH.

1. `cd` into this folder (`quotation_assistant`).
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and set `GOOGLE_API_KEY` there only.
4. `streamlit run app.py`
5. Open the local URL Streamlit prints (usually `http://localhost:8501`).

Optional: `adk web .` still works for debugging if `root_agent` loads (Day 1 Lab 1). The pipeline lives in `agent/agent.py`.

If `google-adk` is not installed, the UI still opens and shows **stub example output** so you can walk through the screen. `run_quotation_pipeline` uses the same `AgentChatSession` / `Runner.run` helper as the Lab 1, Lab 4, and Lab 5 notebooks. The default model is `MODEL = "gemini-3.5-flash"` (what those labs use).

## Streamlit Community Cloud (General practice)

1. Create a **private** GitHub repo.
2. Confirm `.env` and `.streamlit/secrets.toml` are **not** in the commit.
3. Deploy the repo; in the Cloud app Secrets add `GOOGLE_API_KEY` (same name as local).

Good for a class demo. Course production targets remain Docker → Cloud Run and/or Vertex AI Agent Engine (Day 1 p.80).

## Docker / Cloud Run (Day 1 p.80)

```bash
docker build -t quotation-assistant .
docker run --rm -p 8080:8080 -e GOOGLE_API_KEY -e PORT=8080 quotation-assistant
```

Pass the key at runtime (`-e` or Cloud Run / Secret Manager). Do not copy `.env` into the image.

Cloud Run: deploy the same image, set `PORT` (the Dockerfile defaults to 8080), inject `GOOGLE_API_KEY` as a secret, and allow scale-to-zero. Vertex AI Agent Engine is the other course target — package the same `root_agent` if that is how Lab day is marked.

## What the pipeline does

`quotation_pipeline` is a `SequentialAgent` (Day 2 Lab 4):

1. `intake_parser` → `output_key="enquiry"`
2. `ParallelAgent` `research`: past-quote RAG, pricing, stock (`past_quotes`, `pricing`, `stock`)
3. `quote_drafter` → `quote_draft`
4. `LoopAgent` `review_loop` (`max_iterations=2`): judge then refine
5. Streamlit Approve / Reject writes `data/audit.jsonl` only (no send)

Guardrails (Lab 2 notebook `block_injection` / Day 3 preview): `before_model_callback` blocks prompt injection and redacts PII; a deterministic price-floor check runs before Approve is enabled.

## Source mapping (summary)

| Piece | Session |
| --- | --- |
| Workflow + human approval, not a free send-agent | Day 1 p.15–16, p.31, p.46, p.51; Day 2 p.46 |
| `agent.py` / `tools.py` / `prompts.py` / `.env` / `adk web` | Day 1 Block 2 · Lab 1 · p.62, p.72, p.81 |
| Default `MODEL = "gemini-3.5-flash"` (LiteLLM only to swap providers) | Lab 1 / Lab 4 / Lab 5 notebooks; Day 1 p.43–44, p.79 |
| Tool docstrings, few tools | Day 1 Lab 2 · p.36, p.38, p.87 |
| `before_model_callback` / `block_injection` | Lab 2 notebook; Day 1 p.84, p.87 |
| PII redaction + tool authorisation | Day 3, previewed Day 1 p.84 |
| Past-quote RAG | Day 1 Lab 3 (RAG is Lab 3 — not this capstone number) · p.116–117 |
| Sequential / Parallel / Loop + `output_key` | Day 2 Lab 4 / 4a · p.12–18, p.24 |
| Optional later `AgentTool` follow-ups | Day 2 Lab 5 · p.44–47 |
| MCP `tool_filter` for stock | Day 2 Lab 6 · p.69, p.75 |
| LLM-as-judge, golden set, cost | Day 1 p.48–49; Day 3 outline |
| Langfuse tracing | Day 3 course outline (not named in Day 1–2 PDFs) |
| Cloud Run / Agent Engine | Day 1 p.80 |
| Streamlit UI | FDE class notes + lecturer; Community Cloud = General practice |

See the table in `GUIDE.md` for slide-level detail.

## Data

- `data/example_past_quotes.csv` — fictional example rows only (`EXAMPLE_CUSTOMER_A`, `EXAMPLE-RESIN-001`, …).
- `data/golden_set.json` — 10 fictional test cases from the draft.
- `data/audit.jsonl` is created at runtime and is gitignored.
