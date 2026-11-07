"""Deterministic policy rule checks -> policy_flags table.

Only clauses the data can actually support are flagged here (see clauses.py).
"""
from __future__ import annotations

import duckdb

PO_THRESHOLD_EUR = 1000  # §2.1 "EUR 1,000 or above" -> >= (see README, Known limitations)
# §2.3 names services ("cloud hosting, facilities"), so match on description, not vendor category.
RECURRING_DESCRIPTIONS = ("Cloud hosting", "Facilities services")
RECURRING_ANNOTATION = "possible §2.3 recurring service; blanket-PO status not determinable"
ESCALATION_STATUSES = ("INACTIVE", "ON_HOLD")

# §3 tiers on amount_eur (cents): <= 5,000 / <= 50,000 / <= 250,000 / above.
TIERS = [
    (5000.00, "Cost Center Owner"),
    (50000.00, "Department Head"),
    (250000.00, "Finance Director"),
    (float("inf"), "CFO + Procurement Excellence review"),
]


def approval_tier(amount_eur: float | None) -> str | None:
    if amount_eur is None or amount_eur < 0:
        return None  # credit notes are excluded from tier assignment
    for upper, role in TIERS:
        if amount_eur <= upper:
            return role
    return None


def build_policy_flags(con: duckdb.DuckDBPyConnection) -> None:
    recurring = ", ".join(f"'{d}'" for d in RECURRING_DESCRIPTIONS)
    statuses = ", ".join(f"'{s}'" for s in ESCALATION_STATUSES)
    con.execute(f"""
        CREATE TABLE policy_flags AS
        SELECT invoice_number, '§2.2' AS clause,
               'No PO reference on file and amount_eur >= 1,000' AS reason,
               CASE WHEN description IN ({recurring}) THEN '{RECURRING_ANNOTATION}' END AS annotation
        FROM invoices_eur
        WHERE po_number IS NULL AND NOT is_credit_note AND amount_eur >= {PO_THRESHOLD_EUR}
        UNION ALL
        SELECT invoice_number, '§3.1', 'No approver record (approved_by is empty): must be held', NULL
        FROM invoices_eur WHERE approved_by IS NULL
        UNION ALL
        SELECT i.invoice_number, '§4.1',
               'Vendor status currently ' || v.status || ' in Vendor Master (snapshot, date unknown): escalate to Procurement Excellence',
               NULL
        FROM invoices_eur i JOIN vendors v USING (vendor_id)
        WHERE v.status IN ({statuses})
        UNION ALL
        SELECT invoice_number, '§6.1', 'Negative amount: credit note (matching not determinable)', NULL
        FROM invoices_eur WHERE is_credit_note
        ORDER BY clause, invoice_number
    """)
