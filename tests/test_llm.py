"""Offline tests for the /ask loop (fake Anthropic client; no API key needed)."""
from types import SimpleNamespace as NS

import pytest

from backend import llm, tools


def _block_of(snippet):
    return next(i for i, b in enumerate(llm.policy_blocks()) if snippet in b)


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
    cit = NS(cited_text="Invoices lacking an approver record must be held and may not be paid.",
             start_block_index=_block_of("Invoices lacking"))
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
    assert out["applied_settings"] == {"report_currency": "original", "approval_scope": "all", "source": "question",
                                       "period": "2025"}


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


def test_numbers_guard_accepts_figure_from_the_question():
    assert llm.unverified_numbers("An invoice of EUR 60,000", [{"count": 73}, "invoice of EUR 60,000?"]) == []
    assert llm.unverified_numbers("An invoice of EUR 60,000", [{"count": 73}]) == ["60,000"]


def test_each_clause_is_its_own_citable_block():
    assert "".join(llm.policy_blocks()) == llm.policy_text()
    table, clause = _block_of("| Up to 5,000"), _block_of("Invoices lacking")
    assert table != clause
    cite = lambda i: llm.extract_citations([NS(citations=[NS(cited_text="x", start_block_index=i)])])[0]["section"]
    assert cite(table) == "§3 Approval Thresholds" and cite(clause) == "§3.1"
    assert cite(_block_of("Negative invoice amounts")) == "§6.1"


@pytest.mark.parametrize("text,expected", [
    ("invoices over 60k", [60000.0]), ("between 60-70k?", [60000.0, 70000.0]), ("60 and 70k", [60000.0, 70000.0]),
    ("about 1.5 million", [1500000.0]), ("Q3 2025 invoices", []),
])
def test_scaled_figures(text, expected):
    assert llm.scaled_figures(text) == expected


def _final(text):
    return _resp([NS(type="text", text=text, citations=None)], "end_turn")


def test_no_false_alarm_for_figures_the_user_gave(monkeypatch):
    _fake(monkeypatch, [_final("Between EUR 60,000 and EUR 70,000 in 2025.")])
    out = llm.ask([{"role": "user", "content": "invoices between 60-70k?"}], tools.Settings())
    assert out["unverified_figures"] == []


def test_no_false_alarm_for_figures_from_earlier_in_the_conversation(monkeypatch):
    _fake(monkeypatch, [_final("Of the 73 invoices, none changed in 2025.")])
    history = [{"role": "user", "content": "how many?"}, {"role": "assistant", "content": "73 invoices."},
               {"role": "user", "content": "did any change?"}]
    out = llm.ask(history, tools.Settings())
    assert out["unverified_figures"] == [] and out["answer_warnings"] == []


def test_no_false_alarm_for_limits_used_in_a_search(monkeypatch):
    sql = "SELECT count(*) AS n FROM invoices_eur WHERE amount_eur BETWEEN 60000 AND 70000"
    _fake(monkeypatch, [_resp([NS(type="tool_use", id="t1", name="run_sql", input={"sql": sql})], "tool_use"),
                        _final("Invoices between EUR 60,000 and EUR 70,000 in 2025.")])
    assert llm.ask([{"role": "user", "content": "mid-size invoices?"}], tools.Settings())["unverified_figures"] == []


def test_figures_the_model_invents_are_still_flagged(monkeypatch):
    _fake(monkeypatch, [_final("Spend was EUR 61,234 in 2025.")])
    assert llm.ask([{"role": "user", "content": "invoices between 60-70k?"}], tools.Settings())["unverified_figures"] == ["61,234"]


def test_citation_markers_sit_where_the_rule_is_stated():
    cit = NS(cited_text="Invoices lacking an approver record must be held", start_block_index=_block_of("Invoices lacking"))
    out = llm.render_answer([NS(type="text", text="The rule: ", citations=None),
                             NS(type="text", text="they must be held.", citations=[cit, cit]),
                             NS(type="text", text=" Next sentence.", citations=None)])
    assert out == "The rule: they must be held. [§3.1] Next sentence."


def test_workflow_records_policy_data_policy_in_order(monkeypatch):
    cit = NS(cited_text="Invoices lacking an approver record must be held.", start_block_index=_block_of("Invoices lacking"))
    _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="missing_approval",
                  input={"policy_basis": "§3.1: invoices with no approver must be held."})], "tool_use"),
        _resp([NS(type="text", text="In 2025, 25 invoices must be held.", citations=[cit])], "end_turn"),
    ])
    wf = llm.ask([{"role": "user", "content": "which lack approval?"}], tools.Settings())["workflow"]
    assert [(w["step"], w["label"]) for w in wf] == [
        ("policy", "Rule being checked"), ("data", "Invoices without an approver"), ("policy", "Policy applied in the answer")]
    assert wf[0]["text"].startswith("§3.1") and wf[1]["result"].startswith("25 invoices") and wf[2]["text"].startswith("§3.1")


def test_workflow_has_no_policy_step_when_none_applies(monkeypatch):
    _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="spend_summary", input={"policy_basis": "none"})], "tool_use"),
        _resp([NS(type="text", text="Spend in 2025 is shown.", citations=None)], "end_turn"),
    ])
    wf = llm.ask([{"role": "user", "content": "total?"}], tools.Settings())["workflow"]
    assert [w["step"] for w in wf] == ["data"]


def test_stated_reason_cannot_vouch_for_a_figure(monkeypatch):
    _fake(monkeypatch, [
        _resp([NS(type="tool_use", id="t1", name="spend_summary", input={"policy_basis": "checking 61,234"})], "tool_use"),
        _resp([NS(type="text", text="Spend was EUR 61,234 in 2025.", citations=None)], "end_turn"),
    ])
    assert llm.ask([{"role": "user", "content": "total?"}], tools.Settings())["unverified_figures"] == ["61,234"]


def test_rank_columns_are_not_figures():
    table = "| # | Invoice |\n|---|---|\n| 1 | INV-1 |\n| 2 | INV-2 |\n| 3 | INV-3 |"
    assert llm.unverified_numbers(table, []) == []
    assert llm.unverified_numbers("| 77 | INV-1 |", []) == ["77"]  # a first column that isn't a sequence is still a figure


def test_counts_from_listed_rows_are_traceable():
    rows = [{"invoices": [{"cost_center": "A"}, {"cost_center": "A"}, {"cost_center": "B"}]}]
    assert llm.unverified_numbers("A has 2 invoices.", rows) == []


def test_zero_is_not_a_finding():
    assert llm.unverified_numbers("CFO level: 0 invoices.", []) == []


def test_simple_arithmetic_on_shown_figures_is_accepted():
    results = [{"a": 48, "b": 31}]
    assert llm.unverified_numbers("Q2 had 48 and Q1 had 31, so 17 more.", results) == []
    assert llm.unverified_numbers("Q2 had 48 and Q1 had 31, a share of 64.6%.", results) == []
    assert llm.unverified_numbers("Q2 had 48 and Q1 had 31, so 19 more.", results) == ["19"]


def test_amount_before_a_month_is_not_read_as_a_date():
    assert llm.unverified_numbers("Spend of EUR 927,318.62 September was highest.", [{"net": 927318.62}]) == []


def test_total_across_several_lookups_is_traceable():
    assert llm.unverified_numbers("That is 29 in total.", [{"count": 12}, {"count": 17}]) == []
