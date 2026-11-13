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


def run_eval(stub: bool, golden_path: Path = GOLDEN, report_path: Path | None = REPORT) -> dict:
    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))["cases"]
    live = (not stub) and api_key_present()
    start = telemetry.snapshot()
    judge_session = AgentChatSession(build_judge_agent(), app_name="eval_judge") if live else None

    results = []
    for case in golden:
        reply = ask_analyst(case["question"],
                            session=new_chat_session() if live else None,
                            force_stub=not live)
        answer = reply["answer"]
        if live and reply["mode"] == "live":
            raw = judge_session.send(
                f"Question: {case['question']}\nReference Answer: {case['reference']}\nActual Answer: {answer}\n"
            )
            score, reason, parse_error = parse_judge(raw)
            judge_kind = "llm"
        else:
            score, reason = stub_judge(case, answer)
            parse_error, judge_kind = False, "stub"
        results.append({"id": case["id"], "category": case["category"], "score": score, "reason": reason,
                        "answer": answer, "judge": judge_kind, "candidate_mode": reply["mode"],
                        "parse_error": parse_error})

    avg = sum(r["score"] for r in results) / len(results)
    usage = telemetry.delta(start)
    out = {"mode": "live" if live else "stub", "model": MODEL, "average": avg, "results": results, "usage": usage,
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
              f"- Cases scoring 4 or more: {sum(r['score'] >= 4 for r in out['results'])} / {len(out['results'])}", "",
              "## Per-case scores", "", "| Case | Category | Score | Judge | Reasoning |", "| --- | --- | --- | --- | --- |"]
    for r in out["results"]:
        lines.append(f"| {r['id']} | {r['category']} | {r['score']}/5 | {r['judge']} | {r['reason'].replace('|', '/')} |")
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
        lines += [f"### {r['id']} ({r['score']}/5)", "", f"> {snippet}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="force the offline stub")
    args = ap.parse_args()
    result = run_eval(stub=args.stub)
    label = "STUB (rule-based, not LLM-as-a-Judge)" if not result["all_live"] else "LIVE"
    print(f"{label}: average {result['average']:.2f} / 5.0 over {len(result['results'])} cases")
    for r in result["results"]:
        print(f"  {r['id']:<26} {r['score']}/5  {r['reason']}")
    print(f"Report written to {REPORT}")
    sys.exit(0)
