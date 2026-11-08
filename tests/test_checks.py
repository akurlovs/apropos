"""Do the answer checks work? Each deliberately wrong answer must be caught; correct answers must pass."""
import pytest

from backend import checks, llm

RESULT = {
    "count": 25, "amount_eur": 1057076.74, "period": "2025",
    "invoices": [
        {"invoice_number": "INV-20002", "invoice_date": "2025-03-07", "cost_center": "CC-FIN-100", "approved_by": "j.smith"},
        {"invoice_number": "INV-20014", "invoice_date": "2025-04-04", "cost_center": "CC-FIN-100", "approved_by": "r.okafor"},
        {"invoice_number": "INV-20029", "invoice_date": "2025-11-13", "cost_center": "CC-COM-440", "approved_by": "r.okafor"},
    ],
}
CITE = [{"section": "§3.1", "quoted_text": "x"}]


def run(answer, results=None, question="q", tools=(), nd=(), citations=CITE):
    return checks.check_answer(answer, [question], [RESULT] if results is None else results, llm.policy_text(),
                               list(tools), list(nd), list(citations))


def kinds(*a, **k):
    return {w["check"] for w in run(*a, **k)}


@pytest.mark.parametrize("answer,expected", [
    ("In 2025, INV-99999 lacks an approver.", "invoice_numbers"),
    ("In 2025, the invoice sits in CC-XYZ-999.", "cost_centers"),
    ("In 2025, it was approved by k.jones.", "approvers"),
    ("In 2025, the invoice is dated 2025-06-17.", "dates"),
    ("In 2025, the invoice is dated 17 June 2025.", "dates"),
    ("In 2025, the invoice is dated June 17.", "dates"),
    ("In 2025, §4.7 applies to this invoice.", "clauses"),
    ("In 2025, section 12 applies to this invoice.", "clauses"),
    ("In 2025 there are 60 invoices without an approver.", "invoice_counts"),
    ("In 2025 there are 26 flagged invoices.", "invoice_counts"),
    ("In 2025, INV-20002 was paid.", "forbidden_claim"),
    ("In 2025, INV-20002 was paid, not held.", "forbidden_claim"),
    ("In 2025, INV-20002 has not been paid.", "forbidden_claim"),
    ("In 2025, three invoices are unpaid.", "forbidden_claim"),
    ("In 2025, this is a policy violation.", "forbidden_claim"),
    ("In 2025, PharmaPrint was inactive in March.", "forbidden_claim"),
    ("In 2025, that purchase was an emergency.", "forbidden_claim"),
    ("Total is EUR 1,057,076.74.", "disclosure"),
])
def test_wrong_answers_are_caught(answer, expected):
    assert expected in kinds(answer)


def test_pending_rate_must_be_disclosed():
    r = {**RESULT, "rate_pending": {"count": 2, "invoice_numbers": []}}
    assert "disclosure" in kinds("In 2025 the total is EUR 1,057,076.74.", results=[r])
    assert not kinds("In 2025 the total is EUR 1,057,076.74; 2 invoices have no exchange rate yet.", results=[r])


def test_not_determinable_must_be_said_when_asked_about():
    nd = [{"clause": "§7.1"}]
    assert "disclosure" in kinds("In 2025 we cannot help.", tools=["clause_info"], nd=nd)
    assert not kinds("In 2025 this is not determinable from available data.", tools=["clause_info"], nd=nd)


def test_no_not_determinable_needed_when_nothing_was_found():
    nd = [{"clause": "§3"}]
    empty = {"count": 0, "invoices": []}
    assert not kinds("INV-77777 could not be found.", results=[empty], question="Who approved INV-77777?",
                     tools=["clause_info"], nd=nd)


def test_partial_list_is_caught():
    answer = "In 2025, 25 invoices lack an approver:\n\n| INV-20002 | a |\n| INV-20014 | b |\n"
    assert "partial_list" in kinds(answer)
    assert "partial_list" not in kinds("In 2025, 25 invoices lack an approver. The first two:\n\n| INV-20002 | a |\n| INV-20014 | b |\n")


def test_uncited_policy_claim_is_caught():
    assert "uncited_policy" in kinds("In 2025, the policy requires a Finance Director.", citations=[])
    assert not kinds("In 2025, the policy requires a Finance Director.")


@pytest.mark.parametrize("answer", [
    "In 2025, whether any of these were paid is not determinable from available data.",
    "**Was INV-20002 paid?** In 2025 this is not determinable from available data.",
    "In 2025 these are flags, not confirmed violations.",
    "In 2025 it is a flag only, not a confirmed violation.",
    "In 2025, I haven't assumed that any purchase was an emergency.",
    "In 2025, I can't infer that any purchase was an emergency.",
    "In 2025 PharmaPrint is currently inactive. I can't say whether it was inactive in March.",
    "In 2025, invoices lacking an approver record must be held and may not be paid.",
    "In 2025, 25 invoices have no approver on record, e.g. INV-20002 approved by nobody.",
    "In Q3 2025 (1 July to 30 September) nothing changed.",
    "In 2025 the rate is from 2025-03-07, i.e. the invoice date, under §3.1 and §9.1.",
    "In 2025 the policy took effect on 01-Jan-2025 for invoices above EUR 1,000.",
    "Spend on 2025 invoices: 3 invoices sit in one list, 2 of them in CC-FIN-100.",
])
def test_correct_answers_pass(answer):
    assert run(answer) == []


def test_count_derived_from_shown_counts_is_accepted():
    r = {"count": 48, "other": 31, "period": "2025"}
    assert not kinds("In 2025 there are 48 and 31, so 17 more invoices.", results=[r])
    assert "invoice_counts" in kinds("In 2025 there are 48 and 31, so 19 more invoices.", results=[r])


def test_amount_before_a_month_is_not_a_date():
    assert "dates" not in kinds("In 2025, EUR 1,057,076.74 September.")


def test_figures_and_ids_from_the_conversation_are_allowed():
    w = checks.check_answer("In 2025, is there an INV-77777? No.", ["Who approved INV-77777?"], [RESULT],
                            llm.policy_text(), [], [], CITE)
    assert w == []


def test_warnings_reach_the_response(monkeypatch):
    from types import SimpleNamespace as NS

    from backend import tools
    from tests.test_llm import _fake, _resp

    _fake(monkeypatch, [_resp([NS(type="text", text="INV-99999 was paid.", citations=None)], "end_turn")])
    out = llm.ask([{"role": "user", "content": "q"}], tools.Settings())
    assert {w["check"] for w in out["answer_warnings"]} == {"invoice_numbers", "forbidden_claim"}
