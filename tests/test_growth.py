"""The data may grow; its shape and the policy may not. Scenarios run on a private copy of the frozen data."""
import csv
import json
import re

import pytest
from fastapi.testclient import TestClient

from backend import contract, db, llm, tools
from backend.main import app

client = TestClient(app)
HEADER = list(contract.INVOICE_COLUMNS)
VENDOR = ("V-001", "Helix Consulting AG")


def row(number, date="2026-02-02", amount="1500.00", currency="EUR", po="PO-9", approver="j.smith",
        description="Cloud hosting", vendor_id=None, cost_center="CC-FIN-100"):
    return [number, date, vendor_id or _vendor_id(), VENDOR[1], description, amount, currency, cost_center, po, approver]


def _vendor_id():
    with (contract_dir() / contract.VENDOR_FILE).open(newline="") as f:
        return next(csv.DictReader(f))["vendor_id"]


def contract_dir():
    from tests.conftest import FIXTURES
    return FIXTURES


def write(d, name, rows, header=None):
    with (d / name).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header or HEADER)
        w.writerows(rows)


def add_rates(d, *dates, currency="GBP", rate="0.85"):
    with (d / contract.FX_FILE).open("a", newline="") as f:
        csv.writer(f).writerows((x, currency, rate) for x in dates)


def n_invoices():
    return db.query("SELECT count(*) AS n FROM invoices_eur")[0]["n"]


# ---------------------------------------------------------------- growth

def test_new_year_file_loads_without_any_fixed_count(data_copy, load_data):
    add_rates(data_copy, "2026-02-02")
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001"), row("INV-30002", amount="850.00", currency="GBP")])
    load_data(data_copy)
    assert n_invoices() == 142
    r = db.report()
    assert r["years"] == [2025, 2026] and r["latest_year"] == 2026
    assert [f["file"] for f in r["files"]] == ["invoices_2025_clean.csv", "invoices_2026_clean.csv"]
    gbp = db.query("SELECT amount_eur, source_file FROM invoices_eur WHERE invoice_number = 'INV-30002'")[0]
    assert float(gbp["amount_eur"]) == 1000.00 and gbp["source_file"] == "invoices_2026_clean.csv"


def test_replacing_the_current_year_file_is_picked_up(data_copy, load_data):
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001")])
    load_data(data_copy)
    assert n_invoices() == 141
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001", amount="9.00"), row("INV-30002"), row("INV-30003")])
    load_data(data_copy)
    assert n_invoices() == 143
    assert float(db.query("SELECT amount_eur FROM invoices_eur WHERE invoice_number='INV-30001'")[0]["amount_eur"]) == 9


def test_other_invoice_files_are_ignored_and_reported(data_copy, load_data):
    write(data_copy, "invoices_backup.csv", [row("INV-30001")])
    write(data_copy, "invoices_2026_draft.csv", [row("INV-30002")])
    load_data(data_copy)
    assert n_invoices() == 140
    assert db.report()["ignored_files"] == ["invoices_2026_draft.csv", "invoices_backup.csv"]


# ---------------------------------------------------------------- periods

@pytest.fixture
def two_years(data_copy, load_data):
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001", "2026-08-03", "1000.00"),
                                                 row("INV-30002", "2026-02-02", "2000.00", po="")])
    load_data(data_copy)


def test_quarters_always_carry_a_year(two_years):
    assert all(re.fullmatch(r"\d{4}-Q[1-4]", r["quarter"]) for r in db.query("SELECT quarter FROM invoices_eur"))


def test_same_quarter_in_two_years_is_not_merged(two_years):
    ctx = tools.ToolContext()
    q3_25 = tools.spend_summary(ctx, filters={"quarter": "2025-Q3"})["rows"][0]["net"]
    q3_26 = tools.spend_summary(ctx, filters={"quarter": "2026-Q3"})["rows"][0]
    assert q3_26["net"] == 1000.00 and q3_26["invoice_count"] == 1 and q3_25 > 1000
    groups = tools.spend_summary(ctx, group_by="quarter", filters={"year": "all"})["rows"]
    assert {"2025-Q3", "2026-Q3"} <= {r["grp"] for r in groups}


def test_bare_quarter_is_rejected_and_lists_what_exists(two_years):
    with pytest.raises(tools.ToolInputError, match="2026-Q3"):
        tools.spend_summary(tools.ToolContext(), filters={"quarter": "Q3"})


def test_default_is_latest_year_and_labelled(two_years):
    ctx = tools.ToolContext()
    out = tools.call_tool(ctx, "spend_summary", {})
    assert out["rows"][0]["invoice_count"] == 2
    assert out["period"].startswith("2026")
    assert ctx.applied_settings()["period"].startswith("2026")
    assert tools.missing_approval(tools.ToolContext())["count"] == 0  # compliance tools follow the same default


def test_all_and_specific_year(two_years):
    assert tools.spend_summary(tools.ToolContext(), filters={"year": "all"})["rows"][0]["invoice_count"] == 142
    assert tools.spend_summary(tools.ToolContext(), filters={"year": "2025"})["rows"][0]["invoice_count"] == 140
    assert tools.missing_approval(tools.ToolContext(gui=tools.Settings(year="2025")))["count"] == 25


def test_invoice_lookup_by_number_crosses_years(two_years):
    out = tools.call_tool(tools.ToolContext(), "invoice_lookup", {"filters": {"invoice_numbers": ["INV-20133"]}})
    assert out["count"] == 1 and "period" not in out


def test_summary_and_export_follow_year(two_years):
    assert client.get("/api/summary").json()["total"]["rows"][0]["invoice_count"] == 2
    s = client.get("/api/summary?year=2025").json()
    assert s["total"]["rows"][0]["invoice_count"] == 140 and s["flags"]["§3.1 no approver record (must be held)"] == 25
    assert len(client.get("/api/invoices?year=all").json()["rows"]) == 142
    c = client.get("/api/invoices?year=2025&format=csv")
    assert "invoices_2025_conversion" in c.headers["content-disposition"]


def test_current_year_is_labelled_to_date(data_copy, load_data):
    write(data_copy, "invoices_2099_clean.csv", [row("INV-30001", "2099-03-14")])
    load_data(data_copy)
    assert tools.call_tool(tools.ToolContext(), "spend_summary", {})["period"] == "2099 to date (through 2099-03-14)"


def test_numbers_guard_knows_any_year():
    assert llm.unverified_numbers("Spend in 2031 and in 2031-03 and Q3 2031.", []) == []


# ---------------------------------------------------------------- exchange rates

@pytest.fixture
def pending(data_copy, load_data):
    """A GBP invoice dated after the last rate, a new currency, and a no-PO invoice among them."""
    write(data_copy, "invoices_2026_clean.csv", [
        row("INV-30001", "2026-06-01", "100.00", "GBP", po="", approver=""),
        row("INV-30002", "2026-06-01", "100.00", "CHF"),
        row("INV-30003", "2026-06-01", "1000.00", "EUR"),
    ])
    load_data(data_copy)


def test_stale_or_missing_rate_is_pending_never_an_old_rate(pending):
    rows = db.query("SELECT invoice_number, fx_rate, amount_eur, fx_missing FROM invoices_eur "
                    "WHERE invoice_number IN ('INV-30001', 'INV-30002') ORDER BY 1")
    assert len(rows) == 2 and all(r["fx_rate"] is None and r["amount_eur"] is None and r["fx_missing"] for r in rows)
    assert db.report()["rate_pending"]["count"] == 2


def test_easter_gap_is_within_the_age_limit():
    assert db.query("SELECT fx_missing FROM invoices_eur WHERE invoice_number='INV-20133'")[0]["fx_missing"] is False


def test_pending_invoices_are_left_out_and_said_so(pending):
    out = tools.call_tool(tools.ToolContext(), "spend_summary", {})
    assert out["rows"][0]["net"] == 1000.00 and out["rows"][0]["invoice_count"] == 1  # counts match what is totalled
    assert out["rate_pending"]["count"] == 2


@pytest.mark.parametrize("name", ["po_status", "maverick_spend", "approval_tier", "missing_approval",
                                  "invoices_by_vendor_status", "credit_notes", "invoice_lookup"])
def test_no_tool_crashes_on_a_pending_invoice(pending, name):
    tools.call_tool(tools.ToolContext(), name, {"filters": {"year": "all"}})


def test_pending_no_po_invoice_is_reported(pending):
    out = tools.maverick_spend(tools.ToolContext())
    assert out["flagged_count"] == 0 and out["rate_pending"]["invoice_numbers"] == ["INV-30001"]
    tier = tools.approval_tier(tools.ToolContext())
    assert {i["required_approver"] for i in tier["invoices"]} >= {"pending exchange rate"}


def test_api_handles_pending(pending):
    assert client.get("/api/summary").status_code == 200
    assert client.get("/api/invoices?format=csv").status_code == 200


# ---------------------------------------------------------------- bad rows

def test_bad_rows_are_set_aside_with_a_reason(data_copy, load_data):
    write(data_copy, "invoices_2026_clean.csv", [
        row("INV-30001"),
        row("INV-30002", date="not-a-date"),
        row("INV-30003", amount="abc"),
        row("INV-30004", date="2025-05-05"),
        row("INV-30005", vendor_id="V-999"),
        row("INV-30006", cost_center=""),
        row("INV-30007", currency="euro"),
    ])
    load_data(data_copy)
    assert n_invoices() == 141
    r = db.report()
    assert r["rejected_count"] == 6
    assert [x["csv_line"] for x in r["rejected"]] == [3, 4, 5, 6, 7, 8]
    reasons = " ".join(x["reason"] for x in r["rejected"])
    for text in ("valid date", "valid number", "outside the year", "Vendor Master", "blank", "3-letter"):
        assert text in reasons
    f = r["files"][1]
    assert (f["rows_read"], f["rows_loaded"], f["rows_rejected"]) == (7, 1, 6)


def test_identical_duplicates_collapse_conflicting_ones_are_set_aside(data_copy, load_data):
    write(data_copy, "invoices_2026_clean.csv", [
        row("INV-30001"), row("INV-30001"),
        row("INV-30002", amount="1.00"), row("INV-30002", amount="2.00"),
    ])
    load_data(data_copy)
    assert n_invoices() == 141
    r = db.report()
    assert r["identical_duplicates_collapsed"] == 1 and r["rejected_count"] == 2
    assert not db.query("SELECT 1 FROM invoices_eur WHERE invoice_number = 'INV-30002'")


def test_invoice_before_policy_took_effect_is_set_aside(data_copy, load_data):
    write(data_copy, "invoices_2024_clean.csv", [row("INV-10001", date="2024-06-03")])
    load_data(data_copy)
    assert n_invoices() == 140
    assert "before the policy" in db.report()["rejected"][0]["reason"]


# ---------------------------------------------------------------- contract breaches

def assert_breach(load_data, path, pattern):
    with pytest.raises(contract.ContractBreach, match=pattern):
        load_data(path)
    st = client.get("/api/status").json()
    assert st["state"] == "failed" and st["redesign_needed"] is True and re.search(pattern, st["message"])
    res = client.get("/api/summary")
    assert res.status_code == 503 and res.json()["redesign_needed"] is True


def test_extra_column_is_a_breach(data_copy, load_data):
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001") + ["x"]], header=HEADER + ["requester"])
    assert_breach(load_data, data_copy, "invoices_2026_clean.csv")


def test_reordered_columns_are_a_breach_not_a_silent_swap(data_copy, load_data):
    h = HEADER.copy()
    h[8], h[9] = h[9], h[8]
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001")], header=h)
    assert_breach(load_data, data_copy, "columns")


def test_unknown_vendor_status_is_a_breach(data_copy, load_data):
    p = data_copy / contract.VENDOR_FILE
    p.write_text(p.read_text().replace("ON_HOLD", "SUSPENDED"))
    assert_breach(load_data, data_copy, "SUSPENDED")


def test_policy_edit_is_a_breach(data_copy, load_data):
    p = data_copy / contract.POLICY_FILE
    p.write_text(p.read_text().replace("EUR 1,000", "EUR 2,000"))
    assert_breach(load_data, data_copy, "FIN-POL-014")


def test_ask_refuses_when_data_is_unavailable(data_copy, load_data, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    (data_copy / contract.POLICY_FILE).write_text("changed")
    with pytest.raises(contract.ContractBreach):
        load_data(data_copy)
    res = client.post("/api/ask", json={"messages": [{"role": "user", "content": "total spend?"}]})
    assert res.status_code == 503


def test_contract_matches_the_frozen_design():
    """Failing here means the schema or policy was changed. Read 'Data contract' in CLAUDE.md before updating it."""
    assert contract.INVOICE_COLUMNS == ("invoice_number", "invoice_date", "vendor_id", "vendor_name", "description",
                                        "amount", "currency", "cost_center", "po_number", "approved_by")
    assert contract.VENDOR_COLUMNS == ("vendor_id", "vendor_name", "country", "category", "status")
    assert contract.FX_COLUMNS == ("rate_date", "currency", "rate")
    assert contract.VENDOR_STATUSES == ("ACTIVE", "INACTIVE", "ON_HOLD")
    assert contract.POLICY_ID == "FIN-POL-014 v3.2"
    assert contract.POLICY_SHA256 == "7a094855ed1107bb8532fa1cc120e3631d7a06c89b9c3106d6199477373daf48"


# ---------------------------------------------------------------- caps and load log

def test_lists_are_capped_but_totals_are_complete(data_copy, load_data):
    limit = tools.MAX_LISTED_INVOICES
    write(data_copy, "invoices_2026_clean.csv",
          [row(f"INV-3{i:04d}", approver="", amount="10.00") for i in range(limit + 5)])
    load_data(data_copy)
    ctx = tools.ToolContext()
    out = tools.missing_approval(ctx)
    assert out["count"] == limit + 5 and out["amount_eur"] == (limit + 5) * 10
    assert len(out["invoices"]) == limit and str(limit + 5) in out["listing_note"]
    assert len(ctx.data_sources[0]["invoice_ids"]) == limit + 5  # the trace keeps every invoice


def test_load_log_records_only_changes(data_copy, load_data, tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("LOAD_LOG", str(log))
    load_data(data_copy)
    db.append_load_log()
    db.append_load_log()
    assert len(log.read_text().splitlines()) == 1
    write(data_copy, "invoices_2026_clean.csv", [row("INV-30001")])
    load_data(data_copy)
    db.append_load_log()
    lines = log.read_text().splitlines()
    assert len(lines) == 2 and len(json.loads(lines[1])["files"]) == 2


def test_fx_merge_keeps_existing_rows():
    import scripts.fetch_fx as fx

    merged = fx.merge({("2025-01-02", "USD"): "1.03"}, [("2026-01-02", "USD", "1.1")])
    assert merged == [("2025-01-02", "USD", "1.03"), ("2026-01-02", "USD", "1.1")]


def test_status_reports_coverage():
    st = client.get("/api/status").json()
    assert st["state"] == "ready" and st["invoices_loaded"] == 140 and st["quarters"][0] == "2025-Q1"
    assert st["policy"] == "FIN-POL-014 v3.2"


def test_grouped_spend_includes_the_overall_total(two_years):
    out = tools.spend_summary(tools.ToolContext(), group_by="description")
    assert out["all_groups_total"]["net"] == 3000.00 and out["all_groups_total"]["invoice_count"] == 2
