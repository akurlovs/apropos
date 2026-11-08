"""Run the /api/ask evals against the real model (needs ANTHROPIC_API_KEY).

  python tests/run_evals.py                          # all evals
  python tests/run_evals.py --routing --md ROUTING_TEST_RESULTS.md
  python tests/run_evals.py --ids R1_maverick_q3_reporting U_9_exceptions

Fails (exit 1) on any failed check, including any "unverified figure" warning.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "evals"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import ground_truth  # noqa: E402

from backend import llm, tools  # noqa: E402


def figure_patterns(v) -> list[str]:
    if isinstance(v, str):
        return [re.escape(v)]
    if isinstance(v, int) or float(v).is_integer() and abs(v) < 1000:
        return [rf"(?<![\d.,]){int(v)}(?![\d]|[.,]\d)"]
    a = abs(float(v))
    forms = {f"{a:,.2f}", f"{a:.2f}", f"{a:,.0f}", f"{a:.0f}", f"{a:,.4f}".rstrip("0"), f"{a:g}"}
    if a >= 1e6:
        forms |= {f"{a / 1e6:.2f} ?(m|million)", f"{a / 1e6:.1f} ?(m|million)"}
    elif a >= 1e3:
        forms |= {f"{a / 1e3:.1f} ?k", f"{a / 1e3:.0f} ?k"}
    return [rf"(?<![\d]){re.escape(f) if '?' not in f else f.replace('.', r'\.')}(?![\d])" for f in forms]


HEDGE = r"\b(whether|not determinable|\w+n't|cannot|can not|not|no record|unknown|never|will not|infer)\b"


# Answers are for finance readers: system vocabulary belongs in the trace, not the answer.
JARGON = (r"`|->|\b(invoices_eur|amount_eur|amount_original|fx_rate\w*|approved_by|po_number|policy_flags|"
          r"is_credit_note|invoice_number|cost_center|vendor_status\w*|run_sql|clause_info|spend_summary|po_status|"
          r"maverick_spend|approval_tier|missing_approval|invoice_lookup|SQL|truncated?|row limit|schema|"
          r"registry|database|annotat\w+|tool|tools|column|columns|query|queries)\b")


def _any(patterns, text) -> bool:
    return any(re.search(p, text, re.I | re.S) for p in patterns)


def check(q: dict, res: dict, gt: dict) -> list[tuple[str, bool, str]]:
    checks = []
    answer = res.get("answer", "")
    called = res.get("tools_called", [])
    checks.append(("status ok", res.get("status") == "ok", res.get("status", "")))
    for t in q.get("expected_tools", []):
        alts = t if isinstance(t, list) else [t]
        checks.append((f"tool called: {' | '.join(alts)}", any(a in called for a in alts), ", ".join(called)))
    if q.get("expected_tools") == []:
        checks.append(("no tools called", not called, ", ".join(called) or "none"))
    nd = [n["clause"] for n in res.get("not_determinable", [])]
    for c in q.get("not_determinable", []):
        alts = c if isinstance(c, list) else [c]
        checks.append((f"not_determinable: {' | '.join(alts)}", any(a in nd for a in alts), ", ".join(nd)))
    for f in q.get("figures", []):
        key = f.split(":", 1)[1]
        val = gt[key]
        checks.append((f"figure {key} = {val}", _any(figure_patterns(val), answer), ""))
    for m in q.get("must_include", []):
        alts = m if isinstance(m, list) else [m]
        checks.append((f"mentions /{'|'.join(alts)}/", _any(alts, answer), ""))
    sentences = re.split(r"(?<=[.!?])\s+|\n+", answer)
    for m in q.get("must_not_include", []):
        affirm_only = "{AFFIRM}" in m
        pat = m.replace("{AFFIRM}", "")
        hits = [s for s in sentences if re.search(pat, s, re.I)
                and not (affirm_only and re.search(HEDGE, s, re.I))]
        checks.append((f"does not say /{pat}/" + (" (unhedged)" if affirm_only else ""), not hits,
                       " | ".join(hits)[:200]))
    for k, v in (q.get("expected_settings") or {}).items():
        got = (res.get("applied_settings") or {}).get(k)
        checks.append((f"applied_settings.{k} = {v}", got == v, str(got)))
    if res.get("status") == "ok":
        hits = sorted({m.group(0) for m in re.finditer(JARGON, answer, re.I)})
        checks.append(("plain language (no system jargon)", not hits, ", ".join(hits)))
    unv = res.get("unverified_figures", [])
    checks.append(("no unverified figures", not unv, ", ".join(unv)))
    return checks


def md_report(results: list[dict], path: Path, title: str) -> None:
    passed = sum(r["ok"] for r in results)
    lines = [f"# {title}", "",
             f"Run: {dt.datetime.now().isoformat(timespec='seconds')} · model `{llm.MODEL}` · "
             f"settings: report_currency=EUR, approval_scope=all (GUI defaults) · "
             f"**{passed}/{len(results)} passed**", "",
             "Each question needs both the **policy** (FIN-POL-014, cited via the Citations API) and the "
             "**database** (DuckDB tool calls). Expected figures come from `tests/evals/ground_truth.py` "
             "(independent pandas computation), not from the app.", "",
             "| # | Question | Tools called | Result |", "|---|---|---|---|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | {r['q']['question']} | {', '.join(r['res'].get('tools_called', [])) or '—'} | "
                     f"{'✅ pass' if r['ok'] else '❌ fail'} |")
    for i, r in enumerate(results, 1):
        q, res = r["q"], r["res"]
        lines += ["", "---", "", f"## {i}. {q['question']}", ""]
        if q.get("routes"):
            lines += [f"**Expected routing:** {q['routes']}", ""]
        lines += [f"**Tools called (in order):** {', '.join(f'`{t}`' for t in res.get('tools_called', [])) or '—'}  ",
                  f"**Applied settings:** `{json.dumps(res.get('applied_settings'))}`  ",
                  f"**Latency:** {r['secs']:.1f} s · **Tokens:** {json.dumps(res.get('usage', {}))}", "",
                  "### Answer", "", res.get("answer", "").strip(), ""]
        if res.get("not_determinable"):
            lines += ["### Not determinable (from clause registry)", ""]
            for n in res["not_determinable"]:
                lines.append(f"- **{n['clause']}** {n['title']}: missing {', '.join(n['missing_fields'])}")
            lines.append("")
        if res.get("policy_citations"):
            lines += ["### Policy citations (Citations API)", ""]
            for c in res["policy_citations"]:
                quote = c["quoted_text"].replace("\n", " ")
                lines.append(f"- **{c['section']}**: “{quote}”")
            lines.append("")
        if res.get("data_sources"):
            lines += ["### Data sources (tool calls run by the backend)", ""]
            for s in res["data_sources"]:
                lines.append(f"- `{s['tool']}` args `{json.dumps(s['args'], default=str)}` → "
                             f"{len(s['invoice_ids'])} invoice IDs, {len(s['fx_rows'])} FX rows  ")
                lines.append(f"  <details><summary>query</summary>\n\n  ```sql\n  {s['query']}\n  ```\n  </details>")
            lines.append("")
        lines += ["### Checks", ""]
        for name, ok, detail in r["checks"]:
            lines.append(f"- {'✅' if ok else '❌'} {name}" + (f" — got: {detail}" if detail and not ok else ""))
        if res.get("unverified_figures"):
            lines.append(f"\n> ⚠️ Unverified figures: {', '.join(res['unverified_figures'])}")
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routing", action="store_true", help="only the five routing questions")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--md", type=Path, help="write a Markdown report")
    args = ap.parse_args()
    qs = yaml.safe_load((ROOT / "tests" / "evals" / "questions.yaml").read_text())
    if args.routing:
        qs = [q for q in qs if q.get("routing")]
    if args.ids:
        qs = [q for q in qs if q["id"] in args.ids]
    gt = ground_truth.compute()
    results = []
    for q in qs:
        t0 = time.time()
        res = llm.ask([{"role": "user", "content": q["question"]}], tools.Settings())
        secs = time.time() - t0
        checks = check(q, res, gt)
        ok = all(c[1] for c in checks)
        results.append({"q": q, "res": res, "checks": checks, "ok": ok, "secs": secs})
        print(f"{'PASS' if ok else 'FAIL'} {q['id']} ({secs:.1f}s) tools={res.get('tools_called')}")
        for name, good, detail in checks:
            if not good:
                print(f"     ✗ {name} {('— ' + detail) if detail else ''}")
    if args.md:
        md_report(results, args.md, "Routing test results" if args.routing else "Eval results")
        print(f"wrote {args.md}")
    n_ok = sum(r["ok"] for r in results)
    print(f"{n_ok}/{len(results)} passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
