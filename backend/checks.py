"""Deterministic checks on a finished answer: they catch invented details and dropped caveats.

Warnings are shown on the answer card and fail the evals; the answer itself is still returned. These checks catch
details that don't exist or disclosures that are missing. They do not catch wrong reasoning over real values
(see Known limitations).
"""
from __future__ import annotations

import calendar
import json
import re
from collections import Counter
from typing import Any

_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_INVOICE = re.compile(r"\bINV-\d+\b", re.I)
_COST_CENTER = re.compile(r"\bCC-[A-Z]+-\d+\b", re.I)
_APPROVER = re.compile(r"(?<![\w.@])[a-z]\.[a-z]{2,}\b(?![.@]\w)")
_CLAUSE = re.compile(r"(?:§\s?|\b[Ss]ections?\s+)(\d+(?:\.\d+)?)")
_POLICY_SECTIONS = re.compile(r"^(?:##\s+(\d+)\.|(\d+\.\d+)\s)", re.M)
_COUNT = re.compile(r"(?<![\w.,§-])(\d{1,3}(?:,\d{3})+|\d+)\s+(?:[A-Za-z-]+\s+){0,2}?invoices?\b", re.I)
_LIST_LINE = re.compile(r"^\s*(?:\|\s*|[-*]\s+|\d+\.\s+)\**(INV-\d+)", re.I | re.M)

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTH = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
          r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b\.?")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_POLICY_DATE = re.compile(rf"\b(\d{{1,2}})-{_MONTH}-(\d{{4}})\b", re.I)
_DAY_MONTH = re.compile(rf"(?<![\d,.])\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+(\d{{4}}))?", re.I)
_MONTH_DAY = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\d)(?:,?\s+(\d{{4}}))?", re.I)

# A sentence that asks, or says the data can't tell, is not asserting the claim.
_HEDGE = re.compile(r"\bwhether\b|not determinable|\bcan(?:'|’)?t (?:tell|say|determine|confirm|know)\b|"
                    r"\bcannot (?:tell|say|determine|confirm|know)\b|\bunknown\b|\bnot able to\b|\bno way to\b|"
                    r"\b(?:does|do)(?:n(?:'|’)t| not) (?:show|record|say|tell|indicate)\b|"
                    r"\bno (?:payment|status|record)\b|\bif any\b|"
                    r"\b(?:haven(?:'|’)t|have not|won(?:'|’)t|will not|never|not|can(?:'|’)t|cannot) (?:assum|infer)\w*", re.I)
_FORBIDDEN = [
    ("payment status", re.compile(r"\b(?:was|were)(?: not|n(?:'|’)t)? (?:\w+ )?paid\b|\b(?:has|have)(?: not|n(?:'|’)t)? "
                                  r"been (?:\w+ )?paid\b|\bunpaid\b|\bpaid on\b", re.I)),
    ("a confirmed violation", re.compile(r"(?<!not )(?<!not a )(?<!not confirmed )(?<!not a confirmed )(?<!no )(?<!any )\bviolat(?:ion|ions|ed|es)\b|"
                                         r"\bconfirmed maverick\b", re.I)),
    ("past vendor status", re.compile(r"\b(?:was|were) (?:already |previously )?(?:inactive|on hold)\b", re.I)),
    ("an emergency or exception", re.compile(r"\b(?:was|were) an? (?:emergency|exception)\b", re.I)),
    ("self-approval", re.compile(r"\bself-approved\b", re.I)),
]
_POLICY_CLAIM = re.compile(r"\b(?:the )?policy (?:says|states|requires|sets|provides|stipulates|prohibits|mandates)\b|"
                           r"\b(?:under|per|according to) (?:the )?policy\b", re.I)
_PARTIAL_WORDS = re.compile(r"\b(first|top|largest|sample|example|examples|including|such as|remaining|others|the rest|"
                            r"full list|narrower|also|of these|of which)\b", re.I)
_COUNT_KEYS = ("count", "flagged_count", "total_invoices")


def _walk(obj: Any):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk(v)


def totals_across(results: list[Any]) -> set[float]:
    """When one question took several lookups (e.g. one per quarter), the total across them."""
    totals: set[float] = set()
    for key in ("count", "flagged_count", "amount_eur", "flagged_amount_eur"):
        values = [r[key] for r in results if isinstance(r, dict) and isinstance(r.get(key), (int, float))]
        if len(values) > 1:
            totals.add(round(sum(values), 2))
    return totals


def arithmetic_of(values: list[float]) -> set[float]:
    """Sums, differences and percentages of figures shown in the answer: "48 vs 31, so 17 more"."""
    uniq = sorted(set(values))[:300]
    out: set[float] = set()
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            out.update((a + b, b - a))
            if b:
                out.add(a / b * 100)
    return out


def allowed_counts(results: list[Any], question: str = "") -> set[int]:
    """Integers in the data, list lengths, and how many listed rows share a value (e.g. 5 invoices in one cost center)."""
    allowed = {0} | {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", question)}
    for node in (n for r in results for n in _walk(r)):
        if isinstance(node, int) and not isinstance(node, bool):
            allowed.add(node)
        elif isinstance(node, (list, tuple)):
            allowed.add(len(node))
            rows = [r for r in node if isinstance(r, dict)]
            for key in {k for r in rows for k in r}:
                allowed.update(Counter(str(r.get(key)) for r in rows).values())
    return allowed


def _dates(text: str) -> tuple[set[str], set[str]]:
    """Full dates as YYYY-MM-DD, and dates written without a year as MM-DD."""
    full, partial = set(), set()

    def add(year, month, day) -> None:
        m, d = int(month), int(day)
        if not 1 <= d <= 31:
            return
        if year:
            full.add(f"{int(year):04d}-{m:02d}-{d:02d}")
        else:
            partial.add(f"{m:02d}-{d:02d}")

    for y, m, d in _ISO.findall(text):
        add(y, m, d)
    for d, mon, y in _POLICY_DATE.findall(text):
        add(y, _MONTHS[mon[:3].lower()], d)
    for d, mon, y in _DAY_MONTH.findall(text):
        add(y, _MONTHS[mon[:3].lower()], d)
    for mon, d, y in _MONTH_DAY.findall(text):
        add(y, _MONTHS[mon[:3].lower()], d)
    return full, partial


def _month_boundary(mm_dd: str, year: int = 2024) -> bool:
    """Period edges ("1 July to 30 September") need not appear in the data."""
    try:
        m, d = (int(x) for x in mm_dd.split("-"))
        return d == 1 or d == calendar.monthrange(year, m)[1]
    except ValueError:
        return False


def _warn(check: str, message: str, items: list[str] | None = None) -> dict:
    return {"check": check, "message": message, "items": items or []}


def _missing_identifiers(answer: str, known: str) -> list[dict]:
    upper, lower = known.upper(), known.lower()
    out = []
    bad = sorted({m.upper() for m in _INVOICE.findall(answer) if m.upper() not in upper})
    if bad:
        out.append(_warn("invoice_numbers", "These invoice numbers could not be found in the data:", bad))
    bad = sorted({m.upper() for m in _COST_CENTER.findall(answer) if m.upper() not in upper})
    if bad:
        out.append(_warn("cost_centers", "These cost centers could not be found in the data:", bad))
    bad = sorted({m for m in _APPROVER.findall(answer) if m not in lower})
    if bad:
        out.append(_warn("approvers", "These approvers could not be found in the data:", bad))
    return out


def _missing_dates(answer: str, known: str) -> list[dict]:
    a_full, a_partial = _dates(answer)
    k_full, k_partial = _dates(known)
    known_days = k_partial | {d[5:] for d in k_full}
    bad = {d for d in a_full if d not in k_full and not _month_boundary(d[5:], int(d[:4]))}
    bad |= {d for d in a_partial if d not in known_days and not _month_boundary(d)}
    return [_warn("dates", "These dates could not be found in the data:", sorted(bad))] if bad else []


def _unknown_clauses(answer: str, policy: str) -> list[dict]:
    known = {a or b for a, b in _POLICY_SECTIONS.findall(policy)}
    bad = sorted({f"§{c}" for c in _CLAUSE.findall(answer) if c not in known})
    return [_warn("clauses", "These policy sections do not exist:", bad)] if bad else []


def _unsupported_counts(answer: str, results: list[Any], question: str) -> list[dict]:
    allowed = allowed_counts(results, question)
    shown = [float(n.replace(",", "")) for n in re.findall(r"(?<![\w.,§-])\d[\d,]*(?![\w.])", answer)]
    allowed |= {int(n) for n in arithmetic_of([n for n in shown if n in allowed]) if float(n).is_integer()}
    allowed |= {int(n) for n in totals_across(results) if float(n).is_integer()}
    bad = set()
    for m in _COUNT.finditer(answer):
        value = int(m.group(1).replace(",", ""))
        before = answer[max(0, m.start() - 4):m.start()]
        if re.fullmatch(r"20\d\d", m.group(1)) or re.search(r"(EUR|GBP|USD|€|£|\$)\s*$", before):
            continue
        if value not in allowed:
            bad.add(f"{m.group(1)} invoices")
    return [_warn("invoice_counts", "These invoice counts could not be traced to the data:", sorted(bad))] if bad else []


def _forbidden_claims(answer: str) -> list[dict]:
    out = []
    for sentence in _SENTENCES.split(answer):
        if sentence.rstrip("*_ ").endswith("?") or _HEDGE.search(sentence):
            continue
        for what, pattern in _FORBIDDEN:
            if pattern.search(sentence):
                out.append(_warn("forbidden_claim", f"This may state {what}, which the data cannot show:",
                                 [sentence.strip()[:200]]))
    return out


def _missing_disclosures(answer: str, results: list[Any], tools_called: list[str],
                         not_determinable: list[dict]) -> list[dict]:
    out = []
    dicts = [r for r in results if isinstance(r, dict)]
    pending = max((r["rate_pending"]["count"] for r in dicts if r.get("rate_pending")), default=0)
    if pending and not re.search(r"exchange rate|pending|no rate", answer, re.I):
        out.append(_warn("disclosure", f"The answer does not mention {pending} invoice(s) left out for lack of an "
                                       "exchange rate."))
    for r in dicts:
        period = r.get("period")
        if not period or period.startswith("all years") and re.search(r"\b(all|every|both|across)\b", answer, re.I):
            continue
        if not any(y in answer for y in re.findall(r"\b20\d{2}\b", period)):
            out.append(_warn("disclosure", f"The answer does not say which period it covers ({period})."))
            break
    found_nothing = any(r.get("count") == 0 for r in dicts)  # e.g. an invoice that doesn't exist
    if "clause_info" in tools_called and not_determinable and not found_nothing and "not determinable" not in answer.lower():
        out.append(_warn("disclosure", "The answer does not say that part of this is not determinable from the data."))
    return out


def _partial_list(answer: str, results: list[Any]) -> list[dict]:
    listed = {m.upper() for m in _LIST_LINE.findall(answer)}
    if len(listed) < 2 or _PARTIAL_WORDS.search(answer):
        return []
    for r in results:
        if not isinstance(r, dict) or not isinstance(r.get("invoices"), list):
            continue
        ids = {str(i.get("invoice_number", "")).upper() for i in r["invoices"]}
        total = next((r[k] for k in _COUNT_KEYS if isinstance(r.get(k), int)), None)
        if listed <= ids and total and len(listed) < total and (f"{total:,}" in answer or str(total) in answer):
            return [_warn("partial_list", f"The answer lists {len(listed)} of {total} invoices without saying the list "
                                          "is partial.")]
    return []


def _uncited_policy(answer: str, citations: list[dict]) -> list[dict]:
    if citations:
        return []
    hits = [s.strip()[:200] for s in _SENTENCES.split(answer) if _POLICY_CLAIM.search(s) and not _HEDGE.search(s)]
    return [_warn("uncited_policy", "This describes the policy without a citation:", hits[:3])] if hits else []


def check_answer(answer: str, conversation: list[str], results: list[Any], policy: str, tools_called: list[str],
                 not_determinable: list[dict], citations: list[dict]) -> list[dict]:
    """conversation: the user's and earlier assistant messages, with the current question last."""
    known = "\n".join([json.dumps(results, default=str), policy, *conversation])
    said_earlier = "\n".join(conversation)
    return [
        *_missing_identifiers(answer, known),
        *_missing_dates(answer, known),
        *_unknown_clauses(answer, policy),
        *_unsupported_counts(answer, results, said_earlier),
        *_forbidden_claims(answer),
        *_missing_disclosures(answer, results, tools_called, not_determinable),
        *_partial_list(answer, results),
        *_uncited_policy(answer, citations),
    ]
