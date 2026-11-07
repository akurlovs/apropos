from decimal import Decimal

import duckdb
import pytest

from backend import db, tools


def one(sql, params=None):
    return db.query(sql, params)[0]


def inv(n):
    return one("SELECT * FROM invoices_eur WHERE invoice_number = ?", [n])


def test_load_assertions():
    assert one("SELECT count(*) AS n FROM invoices_eur")["n"] == 140
    assert one("SELECT count(*) AS n FROM vendors")["n"] == 10
    assert one("SELECT count(*) AS n FROM invoices_eur WHERE amount_eur IS NULL")["n"] == 0
    assert one("SELECT count(*) AS n FROM invoices_eur WHERE po_number IS NULL")["n"] == 21
    assert one("SELECT count(*) AS n FROM invoices_eur WHERE approved_by IS NULL")["n"] == 25


def test_no_bare_amount_column():
    cols = [r["column_name"] for r in db.query(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'invoices_eur'")]
    assert "amount" not in cols and {"amount_original", "amount_eur", "fx_rate", "fx_rate_date"} <= set(cols)


# Hand-computed: amount / ECB rate (foreign units per EUR), rounded half away from zero to cents.
def test_gbp_conversion_by_hand():
    r = inv("INV-20002")  # 21,082.18 GBP on Fri 2025-03-07, ECB GBP 0.84088
    assert r["fx_rate"] == 0.84088 and str(r["fx_rate_date"]) == "2025-03-07"
    assert r["amount_eur"] == Decimal("25071.57")  # 21082.18 / 0.84088 = 25071.5702...


def test_usd_conversion_by_hand():
    r = inv("INV-20014")  # 33,774.50 USD on Fri 2025-04-04, ECB USD 1.1057
    assert r["fx_rate"] == 1.1057
    assert r["amount_eur"] == Decimal("30545.81")  # 33774.50 / 1.1057 = 30545.8080...


def test_weekend_uses_prior_fixing():
    r = inv("INV-20034")  # Sun 2025-07-27 GBP -> Fri 2025-07-25 fixing 0.8715
    assert str(r["fx_rate_date"]) == "2025-07-25" and r["fx_rate"] == 0.8715
    assert r["amount_eur"] == Decimal("83527.77")  # 72794.45 / 0.8715 = 83527.7680...


def test_good_friday_uses_thursday_fixing():
    r = inv("INV-20133")
    assert str(r["invoice_date"]) == "2025-04-18" and r["currency"] == "USD"
    assert str(r["fx_rate_date"]) == "2025-04-17" and r["fx_rate"] == 1.136
    assert r["amount_eur"] == (r["amount_original"] / Decimal("1.136")).quantize(Decimal("0.01"))


def test_eur_rows_rate_one():
    assert one("SELECT count(*) AS n FROM invoices_eur WHERE currency='EUR' AND (fx_rate <> 1 OR amount_eur <> amount_original)")["n"] == 0


def test_credit_notes():
    rows = db.query("SELECT invoice_number FROM invoices_eur WHERE is_credit_note ORDER BY 1")
    assert [r["invoice_number"] for r in rows] == ["INV-20029", "INV-20096"]


def test_export_reconciles_with_summary():
    export = tools.invoice_export("EUR")
    s = tools.summary(tools.Settings())
    t = s["total"]["rows"][0]
    total_export = round(sum(r["amount_eur"] for r in export), 2)
    assert total_export == round(t["gross"] + t["credit_notes"], 2) == round(t["net"], 2)


def test_db_locked_down():
    cur = db.get_con().cursor()
    with pytest.raises(duckdb.Error):
        cur.execute("SELECT * FROM read_csv('data/vendor_master.csv')").fetchall()
    with pytest.raises(duckdb.Error):
        cur.execute("SET enable_external_access = true")
