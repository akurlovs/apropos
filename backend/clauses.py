"""Clause registry: single source of truth for checkability and routing.

It drives (1) the checkability table in the system prompt, (2) the clause tool
descriptions, and (3) the "not determinable" text returned by clause_info.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Clause:
    id: str                      # canonical id, e.g. "§2.2" or "§6.1 matching"
    title: str
    checkability: str            # full | partial | none | design
    tool: str | None             # clause tool that answers it (None -> clause_info only)
    fields_used: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    caveat: str = ""
    aliases: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("aliases")
        d["fields_used"] = list(self.fields_used)
        d["missing_fields"] = list(self.missing_fields)
        return d


NOT_DETERMINABLE = "not determinable from available data"

REGISTRY: tuple[Clause, ...] = (
    Clause("§1", "Scope (clinical trial site payments excluded, FIN-POL-021)", "none", None,
           missing_fields=("clinical-trial-site-payment flag",),
           caveat="No field identifies clinical trial site payments, so all invoices are assumed in scope."),
    Clause("§2.1", "PO required for purchases of EUR 1,000 or above", "full", "po_status",
           fields_used=("po_number", "amount_eur"),
           caveat="Threshold applied as amount_eur >= 1,000 (converted at the ECB rate on the invoice date)."),
    Clause("§2.1 timing", "PO issued before the supplier begins work / ships goods", "none", None,
           missing_fields=("PO issue date", "work start / goods shipment date"),
           caveat="Only the presence of a PO number is known, not when it was issued.",
           aliases=("2.1 timing", "po timing", "before work")),
    Clause("§2.2", "Maverick spend: no valid PO reference above EUR 1,000 -> flag to Cost Center owner, report quarterly",
           "full", "maverick_spend",
           fields_used=("po_number", "amount_eur", "cost_center", "invoice_date"),
           missing_fields=("record of flagging to the Cost Center owner", "Finance Controls Committee reports",
                           "Cost Center owner names"),
           caveat="Flags are 'no PO reference on file', not confirmed violations. Whether a flag was actually "
                  "raised/reported, §9 exception status and §2.3 blanket-PO status are not determinable."),
    Clause("§2.3", "Recurring services may operate under a blanket PO renewed annually", "none", None,
           missing_fields=("blanket-PO register", "blanket-PO renewal dates"),
           caveat="Every PO number in the data is unique (no PO reuse), so there is no evidence of blanket POs. "
                  "A blank po_number is still a §2.2 flag; recurring-service descriptions are only annotated."),
    Clause("§3", "Approval thresholds (required approver tier by EUR value)", "partial", "approval_tier",
           fields_used=("amount_eur", "approved_by"),
           missing_fields=("approver -> role mapping",),
           caveat="The required tier is computed from amount_eur; whether approved_by holds that role is "
                  "not determinable. Tiers for non-EUR invoices depend on the FX rate (fx_rate_date shown)."),
    Clause("§3.1", "Invoices lacking an approver record must be held and may not be paid", "full", "missing_approval",
           fields_used=("approved_by",),
           missing_fields=("payment status", "payment date"),
           caveat="We know whether an approver record exists, not whether the invoice was paid. "
                  "Say 'lacks approver record -> must be held per §3.1', never 'paid'/'unpaid'."),
    Clause("§4.1", "Payments only to ACTIVE vendors; ON_HOLD / INACTIVE -> escalate to Procurement Excellence",
           "full", "invoices_by_vendor_status",
           fields_used=("vendor_id", "vendors.status"),
           missing_fields=("vendor status effective date / history", "payment records"),
           caveat="Vendor status is a present-tense snapshot with no effective date: we cannot say whether a vendor "
                  "was inactive when it invoiced, nor whether payments were made."),
    Clause("§4.2", "New vendor due diligence before first payment", "none", None,
           missing_fields=("vendor onboarding date", "due-diligence records", "GxP qualification records",
                           "first payment date")),
    Clause("§4.3", "Vendor master data changes: dual approval + callback verification", "none", None,
           missing_fields=("vendor master change log", "dual-approval records", "callback verification records")),
    Clause("§5.1", "EUR reporting currency; convert at ECB reference rate on the invoice date", "full", "invoice_lookup",
           fields_used=("amount_original", "currency", "fx_rate", "fx_rate_date", "amount_eur"),
           caveat="Weekend and TARGET-holiday invoice dates use the most recent prior ECB fixing (fx_rate_date)."),
    Clause("§5.2", "60 days net payment terms; early-payment discounts > 2% need Treasury approval", "none", None,
           missing_fields=("invoice receipt date", "payment date", "payment terms", "early-payment discount"),
           aliases=("payment terms", "60 days")),
    Clause("§6.1", "Negative amounts processed as credit notes", "full", "credit_notes",
           fields_used=("amount_original", "is_credit_note")),
    Clause("§6.1 matching", "Credit notes matched to original invoice; unmatched > 90 days escalated", "none", None,
           missing_fields=("original invoice reference", "matching status", "credit note receipt date"),
           caveat="Never match credit notes heuristically (by vendor, amount or PO).",
           aliases=("6.1 matching", "credit note matching", "90 days")),
    Clause("§7.1", "Approver may not be the requester", "none", None,
           missing_fields=("requester",),
           caveat="approved_by is known, but there is no requester field to compare it with."),
    Clause("§7.2", "Self-approval prohibited", "none", None,
           missing_fields=("requester",),
           caveat="approved_by is known, but there is no requester field to compare it with."),
    Clause("§8.1", "Records retained for 10 years", "none", None,
           missing_fields=("record retention metadata",)),
    Clause("§8.2", "Traceable lineage from source to report", "design", None,
           caveat="Met by design: every figure carries source files (SHA-256), the query/function run, "
                  "FX rows and invoice IDs."),
    Clause("§9", "Emergency purchases: retrospective approval via the Exception Register", "none", None,
           missing_fields=("Exception Register", "emergency flag", "retrospective approval date"),
           caveat="Never infer that a purchase was an emergency.",
           aliases=("9.1", "exception", "exceptions", "emergency")),
)

_BY_ID = {c.id: c for c in REGISTRY}

# Tool descriptions are generated from this + the registry; this holds only the routing prose.
TOOL_ROUTING: dict[str, str] = {
    "po_status": "Invoices with vs without a PO among those at or above EUR 1,000; e.g. 'how many invoices "
                 "over €1k had a PO?'",
    "maverick_spend": "Invoices without a PO reference at or above EUR 1,000 (§2.2 flags), with §2.3 "
                      "recurring-service annotations; group by quarter, cost_center or vendor. e.g. 'maverick spend "
                      "in Q3', 'which cost centers need to be flagged', 'are the no-PO cloud invoices OK?'",
    "approval_tier": "Required approver tier per invoice from amount_eur; e.g. 'who needed to approve INV-x', "
                     "'how many invoices need Finance Director approval'",
    "missing_approval": "Invoices with no approver record (must be held); e.g. 'which invoices lack approval', "
                        "'was INV-x approved'",
    "invoices_by_vendor_status": "Invoices from vendors currently INACTIVE / ON_HOLD that must be escalated; "
                                 "e.g. 'which invoices need escalation', 'invoices from inactive vendors'",
    "invoice_lookup": "Per-invoice details incl. FX conversion (rate, rate date, EUR amount); e.g. 'what rate was "
                      "used for INV-x', 'show invoice INV-x'",
    "credit_notes": "Negative invoices (credit notes); e.g. 'which credit notes do we have'",
}


def normalize_clause_id(raw: str) -> str | None:
    s = raw.strip().lower().replace("section", "").replace("§", "").strip()
    for c in REGISTRY:
        if s in {c.id.lower().replace("§", "").strip()} | {a.lower() for a in c.aliases}:
            return c.id
    m = re.match(r"^(\d+)(?:\.(\d+))?", s)
    if not m:
        return None
    major, minor = m.group(1), m.group(2)
    rest = s[m.end():].strip()
    if minor:
        base = f"§{major}.{minor}"
        if rest and f"{base} {rest}" in _BY_ID:
            return f"{base} {rest}"
        if base in _BY_ID:
            return base
    if f"§{major}" in _BY_ID:
        return f"§{major}"
    # "§7" -> first sub-clause family member; "§6" -> §6.1
    for c in REGISTRY:
        if c.id.startswith(f"§{major}."):
            return c.id
    return None


def get(clause_id: str) -> Clause | None:
    cid = normalize_clause_id(clause_id)
    return _BY_ID.get(cid) if cid else None


def related(clause_id: str) -> list[Clause]:
    """All registry entries sharing the major section (e.g. §7 -> §7.1, §7.2)."""
    c = get(clause_id)
    if not c:
        return []
    major = re.match(r"§(\d+)", c.id).group(1)
    return [x for x in REGISTRY if re.match(rf"§{major}(\.|\s|$)", x.id)]


def clauses_for_tool(tool: str) -> list[Clause]:
    return [c for c in REGISTRY if c.tool == tool]


def tool_description(tool: str) -> str:
    cs = clauses_for_tool(tool)
    head = "; ".join(f"{c.id} {c.title}" for c in cs)
    caveats = " ".join(c.caveat for c in cs if c.caveat)
    return f"Answers {head}. {TOOL_ROUTING[tool]}. {caveats}".strip()


def checkability_table() -> str:
    lines = ["| Clause | Checkability | Tool | Missing field(s) | Caveat |", "|---|---|---|---|---|"]
    for c in REGISTRY:
        lines.append(f"| {c.id} {c.title} | {c.checkability} | {c.tool or 'clause_info'} | "
                     f"{', '.join(c.missing_fields) or '—'} | {c.caveat or '—'} |")
    return "\n".join(lines)
