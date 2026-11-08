"""/api/ask: tool-use loop with policy citations and system-produced sources."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import anthropic

from backend import checks, db, prompts, tools

log = logging.getLogger("apropos.llm")

MODEL = os.environ.get("MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8000"))
MAX_ITERATIONS = 6
MAX_HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _client


def policy_text() -> str:
    return db.POLICY_MD.read_text()


# ---------------------------------------------------------------------------- citations -> sections

_CLAUSE_RE = re.compile(r"^(\d+\.\d+)\s", re.M)
_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.M)
_BLOCK_SPLIT = re.compile(r"^(?=## |\d+\.\d+\s)", re.M)


def section_for(char_index: int, text: str | None = None) -> str:
    text = text or policy_text()
    best, best_pos = "header", -1
    for m in _HEADING_RE.finditer(text):
        if m.start() <= char_index and m.start() > best_pos:
            best, best_pos = f"§{m.group(1)} {m.group(2).strip()}", m.start()
    for m in _CLAUSE_RE.finditer(text):
        if m.start() <= char_index and m.start() > best_pos:
            best, best_pos = f"§{m.group(1)}", m.start()
    return best


def policy_blocks() -> list[str]:
    """The policy split so each clause is its own citable block (a table and the clause after it stay separate)."""
    return [b for b in _BLOCK_SPLIT.split(policy_text()) if b]


def _cited_section(block_index: int, text: str, blocks: list[str]) -> str:
    return section_for(sum(len(b) for b in blocks[:block_index]), text)


def render_answer(content: list[Any]) -> str:
    """Join the text blocks, marking each cited passage with its clause, e.g. "... must be held. [§3.1]".

    The markers come from the Citations API response, so they are system-produced like every other source.
    """
    text, blocks = policy_text(), policy_blocks()
    parts = []
    for block in content:
        if block.type != "text":
            continue
        tags: list[str] = []
        for c in getattr(block, "citations", None) or []:
            tag = _cited_section(c.start_block_index, text, blocks).split()[0]
            if tag.startswith("§") and tag not in tags:
                tags.append(tag)
        body = block.text.rstrip()
        parts.append(f"{body} [{', '.join(tags)}]{block.text[len(body):]}" if tags else block.text)
    return "".join(parts).strip()


def extract_citations(content: list[Any]) -> list[dict]:
    text, blocks = policy_text(), policy_blocks()
    out, seen = [], set()
    for block in content:
        for c in getattr(block, "citations", None) or []:
            quoted = (getattr(c, "cited_text", "") or "").strip()
            start = c.start_block_index
            key = (start, quoted)
            if key in seen or not quoted:
                continue
            seen.add(key)
            out.append({"section": _cited_section(start, text, blocks), "quoted_text": quoted,
                        "document": db.POLICY_ID, "start_block_index": start})
    return out


# ---------------------------------------------------------------------------- numbers guard

_SKIP_PATTERNS = [
    r"\b(?:INV|PO|V|CC-[A-Z]+)-\d+\b", r"\bCC-[A-Z]+-\d+\b", r"§\s?\d+(?:\.\d+)?", r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b20\d{2}-\d{2}\b", r"\bQ[1-4]\b", r"\bFIN-POL-\d+\b", r"\bv\d+(?:\.\d+)?\b", r"\b20\d{2}\b", r"^\s*\d+\.\s",
    r"(?<![\d,.])\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b",
]
_NUM_RE = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-−]?\d+(?:\.\d+)?")
_SCALE_RE = re.compile(r"\s*(k|m|bn|million|thousand|billion)\b", re.I)


_SCALED_RANGE_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s*(?:-|–|to|and)\s*(\d+(?:\.\d+)?))?\s*"
                              r"(k|m|bn|thousand|million|billion)\b", re.I)
_SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


def scaled_figures(text: str) -> list[float]:
    """Amounts written as '60k' or '60-70k' (the suffix applies to both ends of a range)."""
    out = []
    for low, high, scale in _SCALED_RANGE_RE.findall(text):
        out += [float(x) * _SCALES[scale.lower()] for x in (low, high) if x]
    return out


def _numbers_in(obj: Any, acc: set[float]) -> set[float]:
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        for m in _NUM_RE.finditer(obj):
            try:
                acc.add(float(m.group().replace(",", "").replace("−", "-")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, acc)
    return acc


def _matches(n: float, decimals: int, known: set[float]) -> bool:
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    for k in known:
        for cand in (k, abs(k), k * 100):  # k*100: shares returned as fractions
            if abs(abs(n) - abs(cand)) <= tol:
                return True
    return False


def _without_row_numbers(answer: str) -> str:
    """Blank a table's 1, 2, 3... rank column: those are positions, not figures."""
    lines, n = [], 0
    for line in answer.split("\n"):
        m = re.match(r"\s*\|\s*(\d+)\s*\|", line)
        if m and int(m.group(1)) == n + 1:
            n += 1
            line = "| |" + line[m.end():]
        elif not line.lstrip().startswith("|"):
            n = 0
        lines.append(line)
    return "\n".join(lines)


def unverified_numbers(answer: str, sources: list[Any], tool_results: list[Any] | None = None) -> list[str]:
    """sources: everything a figure may legitimately come from. tool_results: also countable row by row."""
    known = _numbers_in(sources, set())
    _numbers_in(policy_text(), known)
    rows = tool_results if tool_results is not None else sources
    known |= {float(n) for n in checks.allowed_counts(rows)} | checks.totals_across(rows)
    text = _without_row_numbers(answer)
    for pat in _SKIP_PATTERNS:
        text = re.sub(pat, " ", text, flags=re.M)
    found, verified = [], []
    for m in _NUM_RE.finditer(text):
        raw = m.group()
        val = float(raw.replace(",", "").replace("−", "-"))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        scale = _SCALE_RE.match(text, m.end())
        if scale:
            mult = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}[scale.group(1).lower()]
            ok = _matches(val, decimals, {k / mult for k in known})
        else:
            ok = _matches(val, decimals, known)
        if ok:
            verified.append(val)
        else:
            found.append((raw, val, decimals))
    if not found:
        return []
    derived = checks.arithmetic_of(verified)
    return sorted({raw for raw, val, decimals in found if not _matches(val, decimals, derived)})


# ---------------------------------------------------------------------------- loop

def _tool_param(spec: tools.ToolSpec) -> dict:
    return {"name": spec.name, "description": spec.description, "input_schema": spec.input_schema}


def tool_params() -> list[dict]:
    return [_tool_param(t) for t in tools.TOOLS_BY_NAME.values()]


def _trim_history(messages: list[dict]) -> list[dict]:
    clean = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        clean.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    while clean and clean[0]["role"] != "user":
        clean.pop(0)
    if not clean or clean[-1]["role"] != "user":
        raise ValueError("the last message must be a non-empty user message")
    # merge consecutive same-role messages (the API requires alternation)
    merged: list[dict] = []
    for m in clean:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n\n" + m["content"]
        else:
            merged.append(dict(m))
    return merged


def _build_messages(history: list[dict]) -> list[dict]:
    """Policy document goes first in the first user turn (stable prefix -> cached)."""
    doc = {
        "type": "document",
        "source": {"type": "content", "content": [{"type": "text", "text": b} for b in policy_blocks()]},
        "title": f"{db.POLICY_ID} Global Procurement & Spend Policy",
        "citations": {"enabled": True},
        "cache_control": {"type": "ephemeral"},
    }
    msgs = []
    for i, m in enumerate(history):
        if i == 0:
            msgs.append({"role": "user", "content": [doc, {"type": "text", "text": m["content"]}]})
        else:
            msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


def failure(message: str, ctx: tools.ToolContext | None, **extra: Any) -> dict:
    return {
        "answer": message, "status": "error",
        "applied_settings": ctx.applied_settings() if ctx else None,
        "data_sources": [], "not_determinable": [], "policy_citations": [], "unverified_figures": [],
        "answer_warnings": [], "workflow": [],
        **extra,
    }


def ask(messages: list[dict], settings: tools.Settings) -> dict:
    ctx = tools.ToolContext(gui=settings.validate())
    try:
        history = _trim_history(messages)
    except ValueError as e:
        return failure(str(e), ctx)
    convo = _build_messages(history)
    system = [{"type": "text", "text": prompts.system_prompt(), "cache_control": {"type": "ephemeral"}}]
    tool_results_seen: list[Any] = []
    tool_inputs: list[Any] = []
    tools_called: list[str] = []
    usage_total = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}

    for _ in range(MAX_ITERATIONS):
        try:
            resp = client().beta.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=convo, tools=tool_params(),
                output_config={"effort": "medium"},
                betas=[FALLBACK_BETA], fallbacks="default",
            )
        except anthropic.AuthenticationError:
            return failure("The Anthropic API key is missing or invalid. Set ANTHROPIC_API_KEY in .env.", ctx)
        except anthropic.RateLimitError:
            return failure("The Anthropic API rate limit was hit. Please retry in a moment.", ctx)
        except anthropic.APIStatusError as e:
            log.exception("API error")
            return failure(f"The language model API returned an error ({e.status_code}). No answer was produced.", ctx)
        except anthropic.APIConnectionError:
            return failure("Could not reach the Anthropic API. No answer was produced.", ctx)

        for k in usage_total:
            usage_total[k] += getattr(resp.usage, k, 0) or 0

        if resp.stop_reason == "refusal":
            return failure("I can't answer this question.", ctx, tools_called=tools_called)
        if resp.stop_reason == "max_tokens":
            return failure("The full answer would be too long to show, so no partial answer is given. "
                           "Try asking about a specific vendor, quarter or cost center.", ctx,
                           tools_called=tools_called)

        convo.append({"role": "assistant", "content": resp.content})  # append-only (keeps thinking blocks valid)
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            answer = render_answer(resp.content)
            # Besides tool results, these are legitimate sources: anything said earlier in the conversation
            # ("an invoice of EUR 60,000", including as "60k") and the limits a search actually used.
            conversation = [m["content"] for m in history]
            scaled = [n for text in conversation for n in scaled_figures(text)]
            unverified = unverified_numbers(answer, [*tool_results_seen, *tool_inputs, *conversation, scaled], tool_results_seen)
            if unverified:
                log.warning("unverified figures %s; question: %r; answer: %r", unverified, history[-1]["content"], answer)
            citations = extract_citations(resp.content)
            warnings = checks.check_answer(answer, conversation, tool_results_seen, policy_text(),
                                           tools_called, ctx.not_determinable, citations)
            if warnings:
                log.warning("answer checks: %s", [w["check"] for w in warnings])
            return {
                "answer": answer, "status": "ok",
                "applied_settings": ctx.applied_settings(),
                "data_sources": ctx.data_sources,
                "not_determinable": ctx.not_determinable,
                "policy_citations": citations,
                "unverified_figures": unverified,
                "answer_warnings": warnings,
                "workflow": tools.finish_workflow(ctx, citations),
                "tools_called": tools_called,
                "model": resp.model, "usage": usage_total,
            }

        results = []
        for tu in tool_uses:
            tools_called.append(tu.name)
            # The stated reason is the model's own text, so it can't vouch for a figure.
            tool_inputs.append({k: v for k, v in (tu.input or {}).items() if k != "policy_basis"})
            try:
                out = tools.call_tool(ctx, tu.name, dict(tu.input or {}))
                tool_results_seen.append(out)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(out, default=str)})
            except tools.ToolInputError as e:
                results.append({"type": "tool_result", "tool_use_id": tu.id, "is_error": True,
                                "content": f"Error: {e}"})
            except Exception:  # unexpected internal failure -> no figures
                log.exception("tool %s failed", tu.name)
                return failure("Something went wrong while retrieving the invoice data, so no answer is shown. "
                               "Please try again.",
                               ctx, tools_called=tools_called)
        convo.append({"role": "user", "content": results})

    return failure("This question needed too many steps to answer reliably, so no answer is shown. "
                   "Try splitting it into smaller questions.", ctx, tools_called=tools_called)
