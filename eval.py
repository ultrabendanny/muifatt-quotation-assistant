"""eval.py: LLM-as-a-Judge harness (Capstone Step 7, Lab 7 Page 5).

    python eval.py            # live if GOOGLE_API_KEY is set, otherwise labelled STUB
    python eval.py --stub     # force the offline stub (no key, no network)

For every case in data/capstone_golden.json the harness
  1. asks the candidate agent (the coordinator) the question,
  2. gives question + reference + actual answer to a SEPARATE judge agent,
  3. records a 1 to 5 score (rubric in agent/prompts.py: JUDGE),
and writes eval_report.md with per-case scores, the average, and the telemetry spend.

In stub mode the candidate is the rule-based stub and the "judge" is a rule-based fact
checker. That run is labelled STUB everywhere and is NOT an LLM-as-a-Judge result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

from agent import telemetry  # noqa: E402
from agent.agent import MODEL, AgentChatSession, api_key_present, ask_analyst, build_judge_agent, new_chat_session  # noqa: E402

ROOT = Path(__file__).resolve().parent
GOLDEN = ROOT / "data" / "capstone_golden.json"
REPORT = ROOT / "eval_report.md"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace(",", "").replace("*", ""))


def stub_judge(case: dict, answer: str) -> tuple[int, str]:
    """Rule-based scorer: share of expected_facts present ('a|b' = either), 1 if a must_not appears."""
    text = _norm(answer)
    bad = [m for m in case.get("must_not", []) if _norm(m) in text]
    if bad:
        return 1, f"contains forbidden text: {bad}"
    facts = case.get("expected_facts", [])
    hits = [f for f in facts if any(_norm(alt) in text for alt in f.split("|"))]
    frac = len(hits) / len(facts) if facts else 1.0
    score = 5 if frac == 1 else 4 if frac >= 0.75 else 3 if frac >= 0.5 else 2 if frac > 0 else 1
    missing = [f for f in facts if f not in hits]
    return score, f"{len(hits)}/{len(facts)} expected facts found" + (f"; missing {missing}" if missing else "")


def parse_judge(raw: str) -> tuple[int, str, bool]:
    """Returns (score, reasoning, parse_error). Unparseable output scores 1, never a generous default."""
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        score = max(1, min(5, int(data["score"])))
        return score, str(data.get("reasoning", "")), False
    except Exception:
        return 1, "judge output could not be parsed", True


PASS_THRESHOLD = 4  # a case passes at 4 or 5


def load_golden(golden_path: Path = GOLDEN) -> list[dict]:
    return json.loads(Path(golden_path).read_text(encoding="utf-8"))["cases"]


def run_eval(stub: bool, golden_path: Path = GOLDEN, report_path: Path | None = REPORT,
             progress=None) -> dict:
    """Run every golden case. Used by the CLI and by the Streamlit Evaluation tab.

    progress(done, total, next_case) is called before each case and once at the end
    (next_case is None). A failure in one case is recorded on that case and the run continues.
    """
    golden = load_golden(golden_path)
    live = (not stub) and api_key_present()
    start = telemetry.snapshot()

    results = []
    for i, case in enumerate(golden):
        if progress:
            progress(i, len(golden), case)
        row = {"id": case["id"], "category": case["category"], "question": case["question"], "score": None,
               "reason": "", "answer": "", "judge": "stub", "candidate_mode": "stub", "parse_error": False,
               "error": None}
        try:
            reply = ask_analyst(case["question"],
                                session=new_chat_session() if live else None,
                                force_stub=not live)
            row.update(answer=reply["answer"], candidate_mode=reply["mode"], error=reply.get("error") if live else None)
            if live and reply["mode"] == "live":
                # a fresh judge session per case, so earlier cases cannot influence the score
                judge = AgentChatSession(build_judge_agent(), app_name="eval_judge")
                raw = judge.send(
                    f"Question: {case['question']}\nReference Answer: {case['reference']}\n"
                    f"Actual Answer: {reply['answer']}\n"
                )
                row["score"], row["reason"], row["parse_error"] = parse_judge(raw)
                row["judge"] = "llm"
            else:
                row["score"], row["reason"] = stub_judge(case, reply["answer"])
        except Exception as exc:  # keep going: report this case as errored
            key = os.environ.get("GOOGLE_API_KEY")
            msg = f"{type(exc).__name__}: {str(exc)}"
            row.update(score=None, error=msg.replace(key, "[REDACTED_KEY]") if key else msg,
                       reason="case errored, not scored")
        results.append(row)
    if progress:
        progress(len(golden), len(golden), None)

    scored = [r["score"] for r in results if r["score"] is not None]
    out = {"mode": "live" if live else "stub", "model": MODEL,
           "average": sum(scored) / len(scored) if scored else 0.0,
           "passed": sum(1 for r in results if r["score"] is not None and r["score"] >= PASS_THRESHOLD),
           "errored": sum(1 for r in results if r["score"] is None),
           "results": results, "usage": telemetry.delta(start),
           "all_live": all(r["candidate_mode"] == "live" and r["judge"] == "llm" for r in results)}
    if report_path:
        Path(report_path).write_text(render_report(out), encoding="utf-8")
    return out


def render_report(out: dict) -> str:
    stub = not out["all_live"]
    lines = ["# Evaluation Report: Enterprise Quotation Assistant", ""]
    if stub:
        lines += ["> **STUB RUN. Not an LLM-as-a-Judge result.** The candidate answers came from the "
                  "offline rule-based stub engine and the scores from a rule-based fact checker, with no "
                  "language model and no API key. Run `python eval.py` with `GOOGLE_API_KEY` set to produce "
                  "the real benchmark for submission.", ""]
    else:
        lines += [f"Live run on `{out['model']}` with a separate judge agent (rubric 1 to 5).", ""]
    if stub and out["mode"] == "live":
        lines += ["> **Warning:** some cases fell back to the stub (see the Judge column), so this is a mixed run.", ""]
    lines += [f"- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
              f"- Mode: **{'STUB' if stub else 'LIVE'}**",
              f"- Cases: {len(out['results'])}",
              f"- **Average score: {out['average']:.2f} / 5.0**",
              f"- Passed (score 4 or more): {out['passed']} / {len(out['results'])}",
              f"- Errored cases (not scored, excluded from the average): {out['errored']}", "",
              "## Per-case scores", "", "| Case | Category | Score | Judge | Reasoning |", "| --- | --- | --- | --- | --- |"]
    for r in out["results"]:
        score = f"{r['score']}/5" if r["score"] is not None else "error"
        reason = (r["reason"] + (f" ({r['error']})" if r.get("error") else "")).replace("|", "/")
        lines.append(f"| {r['id']} | {r['category']} | {score} | {r['judge']} | {reason} |")
    u = out["usage"]
    lines += ["", "## Telemetry spend (estimated)", "",
              f"- Model calls: {u['calls']}",
              f"- Prompt tokens: {u['prompt_tokens']:,}",
              f"- Completion tokens: {u['completion_tokens']:,}",
              f"- Estimated cost: ${u['usd']:.6f} USD",
              f"- Rates: ${telemetry.PRICE_PER_M_PROMPT}/1M prompt, ${telemetry.PRICE_PER_M_COMPLETION}/1M completion "
              "(example rates, check current Gemini pricing)."]
    if stub:
        lines.append("- Stub runs make no model calls, so spend is 0 by construction.")
    lines += ["", "## Answers", ""]
    for r in out["results"]:
        snippet = r["answer"].strip().replace("\n", "\n> ")
        lines += [f"### {r['id']} ({r['score'] if r['score'] is not None else 'error'}/5)", "", f"> {snippet}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="force the offline stub")
    args = ap.parse_args()
    result = run_eval(stub=args.stub)
    label = "STUB (rule-based, not LLM-as-a-Judge)" if not result["all_live"] else "LIVE"
    print(f"{label}: average {result['average']:.2f} / 5.0 over {len(result['results'])} cases")
    for r in result["results"]:
        print(f"  {r['id']:<26} {r['score']}/5  {r['reason']}" if r["score"] is not None
              else f"  {r['id']:<26} ERROR  {r['error']}")
    print(f"Report written to {REPORT}")
    sys.exit(0)
