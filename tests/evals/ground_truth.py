"""Independent ground truth for evals, computed with pandas straight from the CSVs.

Deliberately does NOT import anything from backend/ (that would be circular).
Run directly to print all figures: python tests/evals/ground_truth.py
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "fixtures"  # frozen copy, like the tests
RECURRING = {"Cloud hosting", "Facilities services"}


def _eur(amount: str, rate: float) -> Decimal:
    return (Decimal(amount) / Decimal(str(rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load() -> pd.DataFrame:
    inv = pd.read_csv(DATA / "invoices_2025_clean.csv", dtype=str, keep_default_na=False)
    ven = pd.read_csv(DATA / "vendor_master.csv", dtype=str)
    fx = pd.read_csv(DATA / "fx_rates.csv", dtype={"rate": float})
    inv["date"] = pd.to_datetime(inv["invoice_date"])
    fx["date"] = pd.to_datetime(fx["rate_date"])
    rates, dates = [], []
    for _, r in inv.iterrows():
        if r["currency"] == "EUR":
            rates.append(1.0)
            dates.append(r["invoice_date"])
            continue
        f = fx[(fx.currency == r["currency"]) & (fx.date <= r["date"])].sort_values("date").iloc[-1]
        rates.append(f["rate"])
        dates.append(f["rate_date"])
    inv["fx_rate"], inv["fx_rate_date"] = rates, dates
    inv["eur"] = [_eur(a, x) for a, x in zip(inv["amount"], inv["fx_rate"])]
    inv["orig"] = inv["amount"].map(Decimal)
    inv["credit"] = inv["orig"] < 0
    inv["no_po"] = inv["po_number"].str.strip() == ""
    inv["no_appr"] = inv["approved_by"].str.strip() == ""
    inv["q"] = "Q" + inv["date"].dt.quarter.astype(str)
    return inv.merge(ven[["vendor_id", "category", "status"]], on="vendor_id", how="left")


def _s(series) -> float:
    return float(sum(series, Decimal("0")))


def tier(eur: Decimal) -> str:
    if eur <= 5000:
        return "Cost Center Owner"
    if eur <= 50000:
        return "Department Head"
    if eur <= 250000:
        return "Finance Director"
    return "CFO + Procurement Excellence review"


def compute() -> dict:
    d = load()
    pos, neg = d[~d.credit], d[d.credit]
    mav = d[d.no_po & ~d.credit & (d.eur >= 1000)]
    appr = d[~d.no_appr]
    esc = d[d.status.isin(["INACTIVE", "ON_HOLD"])]
    i133 = d[d.invoice_number == "INV-20133"].iloc[0]
    crown = d[d.vendor_name == "Crown Travel Partners"]
    gt = {
        "gross_eur": _s(pos.eur), "credits_eur": _s(neg.eur), "net_eur": _s(d.eur),
        "maverick_count": len(mav), "maverick_eur": _s(mav.eur),
        "maverick_annotated": int(mav.description.isin(RECURRING).sum()),
        "missing_appr_count": int(d.no_appr.sum()), "missing_appr_eur": _s(d[d.no_appr].eur),
        "esc_count": len(esc), "esc_eur": _s(esc.eur),
        "pharmaprint_count": int((esc.vendor_name == "PharmaPrint Studios").sum()),
        "crown_count": int((esc.vendor_name == "Crown Travel Partners").sum()),
        "credit_note_count": len(neg),
        "inv20133_eur": float(i133.eur), "inv20133_rate": float(i133.fx_rate),
        "inv20133_rate_date": i133.fx_rate_date, "inv20133_tier": tier(i133.eur),
        "approved_only_net_eur": _s(appr.eur), "approved_only_count": len(appr),
        "both_missing_count": int((d.no_po & d.no_appr).sum()),
        "fin_director_count": int(sum(1 for e in pos.eur if 50000 < e <= 250000)),
    }
    for q in ("Q1", "Q2", "Q3", "Q4"):
        m = mav[mav.q == q]
        gt[f"maverick_{q.lower()}_count"] = len(m)
        gt[f"maverick_{q.lower()}_eur"] = _s(m.eur)
    for cur in ("EUR", "GBP", "USD"):
        c = crown[crown.currency == cur]
        gt[f"crown_net_{cur.lower()}_orig"] = _s(c.orig)
    top = d.groupby("vendor_name")["eur"].apply(lambda s: sum(s, Decimal("0"))).sort_values(ascending=False)
    gt["top_vendor"] = top.index[0]
    gt["top_vendor_net_eur"] = float(top.iloc[0])
    return gt


def scenario_2026() -> dict:
    """Figures for tests/evals/scenario_invoices_2026.csv (EUR only, so no conversion)."""
    d = pd.read_csv(Path(__file__).parent / "scenario_invoices_2026.csv", dtype={"amount": str})
    d["month"] = pd.to_datetime(d["invoice_date"]).dt.month
    return {"scen_2026_gross": float(sum(Decimal(a) for a in d.amount)),
            "scen_2026_q3": float(sum(Decimal(a) for a in d[d.month.between(7, 9)].amount))}


if __name__ == "__main__":
    for k, v in compute().items():
        print(f"{k:28} {v}")
