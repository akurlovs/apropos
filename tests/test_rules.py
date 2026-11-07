import pytest

from backend import db, rules, tools


def counts():
    return {r["clause"]: r["n"] for r in db.query("SELECT clause, count(*) AS n FROM policy_flags GROUP BY clause")}


def test_flag_counts():
    assert counts() == {"§2.2": 21, "§3.1": 25, "§4.1": 29, "§6.1": 2}


def test_maverick_is_fx_independent():
    # smallest no-PO amount is EUR 2,026.78, far above 1,000
    assert db.query("SELECT min(amount_eur) AS m FROM invoices_eur WHERE po_number IS NULL")[0]["m"] > 2000


def test_recurring_annotation_count():
    r = db.query("SELECT count(*) AS n FROM policy_flags WHERE clause='§2.2' AND annotation IS NOT NULL")[0]
    assert r["n"] == 10


def test_vendor_status_split():
    rows = db.query("""SELECT vendor_name, count(*) AS n FROM policy_flags JOIN invoices_eur USING (invoice_number)
                       WHERE clause='§4.1' GROUP BY 1 ORDER BY 1""")
    assert {r["vendor_name"]: r["n"] for r in rows} == {"Crown Travel Partners": 12, "PharmaPrint Studios": 17}


def test_both_missing():
    r = db.query("SELECT count(*) AS n FROM invoices_eur WHERE po_number IS NULL AND approved_by IS NULL")[0]
    assert r["n"] == 3


@pytest.mark.parametrize("amount,tier", [
    (5000.00, "Cost Center Owner"), (5000.01, "Department Head"), (50000.00, "Department Head"),
    (50000.01, "Finance Director"), (250000.00, "Finance Director"),
    (250000.01, "CFO + Procurement Excellence review"), (-10.0, None)])
def test_tier_boundaries(amount, tier):
    assert rules.approval_tier(amount) == tier


def test_approved_only_scope_leaves_flags_unchanged():
    for scope in ("all", "approved_only"):
        ctx = tools.ToolContext(gui=tools.Settings(approval_scope=scope))
        assert tools.missing_approval(ctx)["count"] == 25
        assert tools.maverick_spend(ctx)["flagged_count"] == 21
        assert tools.invoices_by_vendor_status(ctx)["count"] == 29
        assert tools.credit_notes(ctx)["count"] == 2
        s = tools.summary(tools.Settings(approval_scope=scope))
        assert s["flags"]["§3.1 no approver record (must be held)"] == 25


def test_approved_only_changes_spend():
    a = tools.spend_summary(tools.ToolContext())["rows"][0]
    b = tools.spend_summary(tools.ToolContext(gui=tools.Settings(approval_scope="approved_only")))
    assert b["rows"][0]["invoice_count"] == 115 and b["excluded_by_scope"]["count"] == 25
    assert a["invoice_count"] == 140
