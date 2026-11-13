# Guide: how each file maps to the course

Use this to explain the project. Example data only. For the architecture paragraphs see `README.md`.

## File map

| File | What it does | Course lab / pillar |
| --- | --- | --- |
| `app.py` | Streamlit UI: Quote tab, Ask-the-analyst chat, Evaluation tab (runs the judge harness live), sidebar schema inspector (`st.text`), live migration simulator, cost widget, Approve and PDF | Pillar 6, Capstone Step 9; Lab 1 key handling |
| `agent/agent.py` | `enterprise_analyst_agent` coordinator, three specialists, `quotation_pipeline`, judge agent, session helper, stub fallback | Pillar 1; Lab 4 (Sequential / Parallel + `output_key`), Lab 5 (`AgentTool`), Lab 1 (`Runner`) |
| `agent/mcp_tools.py` | `mcp_list_tables`, `mcp_describe_table`, `mcp_read_query`, `mcp_list_policies`, `mcp_read_policy`, `is_sql_mutation` | Pillar 2 and 3 (data level); Lab 6 |
| `agent/db.py` | Database path, seed data, `connect_ro()` (`mode=ro`), the human-only write path for the migration | Pillar 2; Capstone Steps 3 and 8 |
| `seed_db.py` | Command-line seed for `data/enterprise.db` | Capstone Step 3 |
| `agent/guardrails.py` | `before_model_guardrail` (PII redaction + injection block), price-floor check, audit log | Pillar 3 (input level); Lab 2 `block_injection`, Lab 7 `guard_input` |
| `agent/telemetry.py` | `after_model_cost_tracker`, token and USD totals | Pillar 4; Lab 7 `track_cost` |
| `agent/prompts.py` | Agent instructions, no schema or prices inside; judge rubric | Lab 4 placeholders; Lab 7 judge |
| `agent/stub.py` | Offline rule-based engine, always labelled STUB | Fallback so the demo and eval run without a key |
| `agent/quote_pdf.py` | In-memory PDF (fpdf2) for `st.download_button` | Approve flow (not an agent tool) |
| `eval.py` | Judge harness (CLI and the app's Evaluation tab), writes `eval_report.md` | Pillar 5; Lab 7 `EvalHarness` |
| `data/enterprise.db` | SQLite: `products`, `price_rules`, `stock`, `customers`, `past_quotes` | Pillar 2 |
| `data/capstone_golden.json` | 7 golden cases | Pillar 5 |
| `policies/*.md` | `quoting_policy`, `stock_and_lead_time`, `compliance_handbook` (price and stock rules) | Pillar 2; Lab 6 documents |
| `tests/` | Unit, fake-model and AppTest tests | Verification |
| `requirements.txt`, `.streamlit/secrets.toml.example`, `.env.example`, `Dockerfile` | Packaging and secrets placeholders | Pillar 6 |

## How to explain it (short lines)

- **Why not a schema in the prompt?** The agent calls `mcp_list_tables` every time. Add a table and it finds it. That is Step 8.
- **Why two guardrail tiers?** Tier 1 stops bad text before the model. Tier 2 stops bad SQL before the database. Even if both failed, the connection is `mode=ro`.
- **Why are the tools called `mcp_*` but not a server?** The course notebooks use those names as plain function tools. See `README.md`, "Real MCP or function tools?".
- **What is the judge?** A second agent with no data tools that compares the answer with a reference and returns `{"score": 1-5}`.
- **What is stub mode?** When there is no key the app answers from rules, through the same tools, and says so on screen.

## Demo order (3 minutes)

1. Open the app, point at the schema inspector and the mode line.
2. Quote tab: "Normal quote", press Generate, Approve, Download PDF.
3. Quote tab: "Below-floor price" shows the floor warning.
4. Ask the analyst: "Which tables exist?", press **Add table 'supplier_lead_times'**, ask about supplier lead times.
5. Ask the analyst: the injection sample, then the `DROP TABLE` sample.
6. Evaluation tab: show the 7 golden cases, press **Run evaluation**, point at the average, pass count and spend, download the report. Then show the sidebar cost widget.
