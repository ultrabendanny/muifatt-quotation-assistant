# Enterprise Quotation Assistant (FDE capstone)

A multi-agent quoting desk assistant built with **Google ADK** and **Streamlit**. It answers price, stock and policy questions and drafts quotes from an **SQLite database** and **markdown policy documents**, found at run time through MCP-style discovery tools. A human approves every draft; the app never sends a quote.

**All data is invented example data** (`EXAMPLE-RESIN-001`, "Example Customer A", ...). Do not put real customers, prices, codes or API keys in this repo. It is public.

## Architecture summary (for the submission)

The `enterprise_analyst_agent` coordinator delegates to three specialist agents (a data and pricing analyst, a policy checker and a quote drafter) through ADK `AgentTool`, and a `SequentialAgent` / `ParallelAgent` pipeline (intake parser, research, drafter, reviewer) produces the structured quote. Agents hold no schema or price in their prompts. They discover the data at run time through MCP discovery primitives: `mcp_list_tables()`, `mcp_describe_table()`, `mcp_read_query()`, `mcp_list_policies()` and `mcp_read_policy()`. Because the agent lists tables on every question, a table added later (the sidebar "Live migration simulator" adds `supplier_lead_times`) is used immediately with no change to agent code. The tools follow protocol-level least privilege: no mutation tool exists to be registered, and the write connection used by the migration button is a separate human-only function.

Safety has two tiers. At the **input level**, a `before_model_guardrail` callback redacts PII in place (emails, phone numbers, credit cards, Malaysian IC numbers) and short-circuits prompt injection with "Request blocked by safety policy." before the model is called. At the **data level**, `is_sql_mutation` uses `sqlparse` statement and token analysis to reject DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, CREATE, REPLACE, ATTACH, PRAGMA and stacked statements, and every connection is opened with `file:...enterprise.db?mode=ro`, so SQLite itself refuses writes even if the parser were bypassed. An `after_model_cost_tracker` callback reads `usage_metadata` on every model call and shows prompt tokens, completion tokens and estimated USD in the sidebar. An LLM-as-a-Judge harness (`eval.py`) scores the agent against a golden set.

## The six pillars

| Pillar | Where |
| --- | --- |
| 1 Multi-agent coordinator + specialists | `agent/agent.py` |
| 2 SQLite + policies, queried by discovery tools | `agent/db.py`, `seed_db.py`, `data/enterprise.db`, `policies/` |
| 3 Two-tier guardrails | `agent/guardrails.py` (input), `agent/mcp_tools.py` (`is_sql_mutation`, `mode=ro`) |
| 4 Cost tracking | `agent/telemetry.py`, sidebar widget in `app.py` |
| 5 Judge harness | `eval.py`, `data/capstone_golden.json`, `eval_report.md` |
| 6 Streamlit Cloud | `app.py`, `requirements.txt`, `.streamlit/secrets.toml.example` |

## Real MCP or function tools?

**Function tools named as the course's MCP discovery primitives.** This is not a separate MCP server process.

Why: the capstone notebook (Step 9) and the course's `bank_mcp_virtual_analyst_streamlit` notebook use exactly these `mcp_*` names as in-process ADK function tools. A real stdio MCP server (`McpToolset` + `mcp_db_server.py`, shown in `true_mcp_protocol_streamlit_participants.ipynb`) needs a subprocess and `asyncio.run` inside Streamlit, which adds failure modes on Streamlit Community Cloud. The behaviour the capstone grades (runtime discovery, least privilege, AST guard, read-only URI) is the same. The `mcp` package is therefore **not** in `requirements.txt`.

## Run locally

```bash
pip install -r requirements.txt
python seed_db.py            # optional: app.py also creates data/enterprise.db if it is missing
cp .env.example .env         # then put GOOGLE_API_KEY=... in .env (never commit it)
streamlit run app.py
```

Without a key the app runs in a **labelled STUB mode** (rule-based, no model) so you can still demo the UI, the schema inspector and the migration button. With a key the sidebar shows "Live mode" and each answer shows `Mode: live (gemini-3.5-flash)`. If a live call fails, the app falls back to the stub and prints the reason with the key masked.

Demo script: ask "Which tables exist?", press **Add table 'supplier_lead_times'**, ask "What are the supplier lead times for EXAMPLE-RESIN-001?", then try the injection and `DROP TABLE` samples, then open the **Evaluation** tab and press **Run evaluation**.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repo (branch `main`). Check `.env` and `.streamlit/secrets.toml` are not committed. `data/enterprise.db` should be committed (it is recreated automatically if missing).
2. Go to [share.streamlit.io](https://share.streamlit.io) -> **New app**. Pick the repo, branch `main`, main file `app.py`.
3. **Advanced settings**: choose Python 3.11 and open **Secrets**. Paste:
   ```toml
   GOOGLE_API_KEY = "your-key-from-google-ai-studio"
   ```
4. Click **Deploy**. The key lives only in Streamlit Secrets, read through `st.secrets`.

Notes: the Cloud filesystem is not persistent. A table added with the migration button and the audit log reset when the app restarts; the committed database is the baseline. The cost widget is per browser session; `STATS` in `agent/telemetry.py` is process-wide.

Docker (optional): `docker build -t quotation-assistant . && docker run -p 8080:8080 -e GOOGLE_API_KEY quotation-assistant`.

## Evaluation (LLM-as-a-Judge)

You can run it **inside the app**: open the **Evaluation (LLM-as-a-Judge)** tab, read the 7 cases, press **Run evaluation** (progress bar, results table, average, pass count, token and USD spend) and download the markdown report. It is the same code as `eval.py`. With a key it is labelled LIVE and uses real model calls; without one it is labelled STUB and is not a real benchmark. Or from a terminal:

```bash
python eval.py          # live if GOOGLE_API_KEY is set, otherwise labelled STUB
python eval.py --stub   # force the offline stub
```

Pass means a score of 4 or 5. `data/capstone_golden.json` has 7 cases: two normal quotes, a stock shortfall, a prompt injection, a SQL mutation attempt, a policy question and a below-floor price request. For each case the coordinator answers, then a **separate judge agent** scores the answer 1 to 5 against the reference (5 accurate and grounded, 3 partial, 1 hallucinated, wrong or unsafe). The run writes `eval_report.md` with per-case scores, the average and the telemetry spend.

The `eval_report.md` committed here is a **STUB run** (rule-based, no model). It checks that the data, guardrails and tools work; it is not an LLM-as-a-Judge benchmark. Run `python eval.py` with your key and use that report and its spend for the submission.

## Tests

```bash
pip install pytest
python -m pytest tests -q
```

Covers `is_sql_mutation` (block and allow), the read-only connection, PII and injection guardrails, the cost tracker, the full ADK agent graph on a scripted fake model (including AgentTool children), the stub eval, and `streamlit.testing` `AppTest` for `app.py` (including the migration button). Tests use a temporary copy of the database.

## Secrets and privacy

- The Google API key is never in code, chat, Codeshare or GitHub. Use `.env` (local) or Streamlit Secrets (Cloud). `.env.example` and `.streamlit/secrets.toml.example` hold placeholders only.
- Example data only. PII is masked before any text reaches a model.
- `data/audit.jsonl` (approve / reject log) is created at run time and is git-ignored.
