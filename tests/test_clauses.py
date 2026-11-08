import re

from backend import clauses, prompts, tools


def test_none_entries_have_missing_fields():
    for c in clauses.REGISTRY:
        if c.checkability in ("none", "partial"):
            assert c.missing_fields, c.id


def test_every_clause_tool_exists():
    for c in clauses.REGISTRY:
        if c.tool:
            assert c.tool in tools.TOOLS_BY_NAME, c.id


def test_normalize():
    assert clauses.normalize_clause_id("7.1") == "§7.1"
    assert clauses.normalize_clause_id("§6.1 matching") == "§6.1 matching"
    assert clauses.normalize_clause_id("section 9") == "§9"
    assert clauses.normalize_clause_id("9.1") == "§9"
    assert clauses.normalize_clause_id("§3 tiers") == "§3"
    assert clauses.normalize_clause_id("bogus") is None


def test_clause_info_marks_not_determinable():
    ctx = tools.ToolContext()
    out = tools.clause_info(ctx, "§7")
    ids = {c["id"] for c in out["clauses"]}
    assert ids == {"§7.1", "§7.2"}
    assert {"requester"} == {f for n in ctx.not_determinable for f in n["missing_fields"]}
    assert ctx.data_sources[0]["tool"] == "clause_info"


def test_tool_descriptions_generated_from_registry():
    d = tools.TOOLS_BY_NAME["maverick_spend"].description
    assert "§2.2" in d and "quarter" in d


def test_every_tool_has_a_reader_facing_label():
    assert set(tools.TOOLS_BY_NAME) <= set(tools.TOOL_LABELS)


def test_registry_text_shown_to_readers_has_no_column_names():
    pat = re.compile(r"amount_eur|approved_by|po_number|fx_rate|->")
    for c in clauses.REGISTRY:
        assert not pat.search(" ".join((c.caveat, *c.missing_fields))), c.id


def test_system_prompt_contains_generated_table():
    assert clauses.checkability_table() in prompts.system_prompt()
