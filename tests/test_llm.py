"""Offline tests for the /ask loop (fake Anthropic client; no API key needed)."""
from types import SimpleNamespace as NS

import pytest

from backend import llm, tools


def test_section_mapping():
    text = llm.policy_text()
    assert llm.section_for(text.index("3.1 Approval is evidenced")) == "§3.1"
    assert llm.section_for(text.index("| Up to 5,000")) == "§3 Approval Thresholds"
    assert llm.section_for(text.index("Emergency purchases")) == "§9.1"


def test_numbers_guard():
    results = [{"count": 21, "amount_eur": 1131481.11, "rate": 1.136}]
    ok = "There are 21 invoices (§2.2) totalling €1,131,481.11 (≈ €1.13 million); INV-20010 on 2025-04-17 at 1.136."
    assert llm.unverified_numbers(ok, results) == []
    assert llm.unverified_numbers("That is 37% of spend.", results) == ["37"]
    # policy numbers are allowed (EUR 1,000, 60 days)
    assert llm.unverified_numbers("Threshold EUR 1,000; terms 60 days net.", []) == []


def test_trim_history():
    msgs = [{"role": "assistant", "content": "hi"}] + [{"role": "user", "content": "q"}]
    assert llm._trim_history(msgs) == [{"role": "user", "content": "q"}]
    with pytest.raises(ValueError):
        llm._trim_history([{"role": "assistant", "content": "x"}])


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        return self.script.pop(0)


def _resp(content, stop):
    return NS(content=content, stop_reason=stop, model="fake",
              usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _fake(monkeypatch, script):
    fm = FakeMessages(script)
    monkeypatch.setattr(llm, "client", lambda: NS(beta=NS(messages=fm)))
    return fm


def test_loop_sources_and_citations(monkeypatch):
    text = llm.policy_text()
    start = text.index("Invoices lacking")
    cit = NS(cited_text="Invoices lacking an approver record must be held and may not be paid.",
             start_char_index=start, end_char_index=start + 70)
    fm = _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="missing_approval", input={}),
               NS(type="tool_use", id="t2", name="clause_info", input={"clause": "§3.1"})], "tool_use"),
        _resp([NS(type="text", text="25 invoices lack an approver record ", citations=None),
               NS(type="text", text="and must be held.", citations=[cit])], "end_turn"),
    ])
    out = llm.ask([{"role": "user", "content": "which invoices lack approval?"}], tools.Settings())
    assert out["status"] == "ok" and out["unverified_figures"] == []
    assert out["tools_called"] == ["missing_approval", "clause_info"]
    assert [s["tool"] for s in out["data_sources"]] == ["missing_approval", "clause_info"]
    assert len(out["data_sources"][0]["invoice_ids"]) == 25
    assert out["policy_citations"][0]["section"] == "§3.1"
    assert out["not_determinable"][0]["clause"] == "§3.1"
    first = fm.calls[0]["messages"][0]["content"][0]
    assert first["type"] == "document" and first["citations"] == {"enabled": True}
    # tool results returned in a single user message
    assert [b["tool_use_id"] for b in fm.calls[1]["messages"][-1]["content"]] == ["t1", "t2"]


def test_question_override(monkeypatch):
    _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="spend_summary",
                  input={"report_currency": "original"})], "tool_use"),
        _resp([NS(type="text", text="done", citations=None)], "end_turn"),
    ])
    out = llm.ask([{"role": "user", "content": "spend in original currency"}], tools.Settings())
    assert out["applied_settings"] == {"report_currency": "original", "approval_scope": "all", "source": "question"}


def test_unverified_figure_flagged(monkeypatch):
    _fake(monkeypatch, [_resp([NS(type="text", text="We spent €9,999,999.", citations=None)], "end_turn")])
    out = llm.ask([{"role": "user", "content": "spend?"}], tools.Settings())
    assert out["unverified_figures"] == ["9,999,999"]


def test_iteration_cap_gives_no_figures(monkeypatch):
    loop = [_resp([NS(type="tool_use", id=f"t{i}", name="vendor_status", input={})], "tool_use")
            for i in range(llm.MAX_ITERATIONS)]
    _fake(monkeypatch, loop)
    out = llm.ask([{"role": "user", "content": "x"}], tools.Settings())
    assert out["status"] == "error" and out["data_sources"] == []


def test_bad_tool_input_is_returned_to_model(monkeypatch):
    fm = _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="run_sql", input={"sql": "DROP TABLE vendors"})], "tool_use"),
        _resp([NS(type="text", text="ok", citations=None)], "end_turn"),
    ])
    out = llm.ask([{"role": "user", "content": "x"}], tools.Settings())
    assert out["status"] == "ok"
    assert fm.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_run_sql_limits():
    ctx = tools.ToolContext()
    with pytest.raises(tools.ToolInputError):
        tools.run_sql(ctx, "SELECT 1; SELECT 2")
    with pytest.raises(tools.ToolInputError):
        tools.run_sql(ctx, "SELECT * FROM read_csv('data/invoices_2025_clean.csv')")
    out = tools.run_sql(ctx, "SELECT * FROM range(1000)")
    assert out["row_count"] == tools.RUN_SQL_ROW_LIMIT and out["truncated"]
