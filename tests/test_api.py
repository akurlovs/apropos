from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_summary_eur_gross_credit_net():
    s = client.get("/api/summary").json()
    t = s["total"]["rows"][0]
    assert t["invoice_count"] == 140 and t["credit_note_count"] == 2
    assert round(t["gross"] + t["credit_notes"], 2) == round(t["net"], 2)
    assert t["credit_notes"] < 0 < t["gross"]
    assert s["flags"]["§2.2 no PO reference (flagged)"] == 21
    assert s["flags"]["§2.2 of which possible §2.3 recurring service (annotated)"] == 10
    assert s["lineage"]["policy"] == "FIN-POL-014 v3.2"
    assert all(len(f["sha256"]) == 64 for f in s["lineage"]["source_files"])


def test_summary_original_never_cross_sums():
    s = client.get("/api/summary?report_currency=original").json()
    rows = s["total"]["rows"]
    assert {r["currency"] for r in rows} == {"EUR", "GBP", "USD"}  # one subtotal per currency
    assert "cross_currency_total_eur" in s["total"]
    assert s["total"]["cross_currency_total_eur"]["label"].startswith("EUR")
    for r in s["by_vendor"]["rows"]:
        assert "currency" in r


def test_summary_original_eur_total_matches_eur_view():
    eur = client.get("/api/summary").json()["total"]["rows"][0]
    orig = client.get("/api/summary?report_currency=original").json()["total"]["cross_currency_total_eur"]
    assert orig["net"] == eur["net"]


def test_summary_approved_only():
    s = client.get("/api/summary?approval_scope=approved_only").json()
    assert s["total"]["rows"][0]["invoice_count"] == 115
    assert s["total"]["excluded_by_scope"]["count"] == 25
    assert s["flags"]["§3.1 no approver record (must be held)"] == 25


def test_invoices_json_and_csv():
    j = client.get("/api/invoices").json()
    assert len(j["rows"]) == 140 and {"fx_rate", "fx_rate_date", "amount_eur"} <= set(j["rows"][0])
    c = client.get("/api/invoices?format=csv")
    assert c.headers["content-type"].startswith("text/csv")
    assert c.text.count("\n") == 141


def test_bad_settings_rejected():
    assert client.get("/api/summary?report_currency=GBP").status_code == 422
