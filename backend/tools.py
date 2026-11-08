"""Deterministic data functions shared by /api/summary, /api/invoices and the LLM tools.

Every call goes through a ToolContext that records what was actually run
(SQL/function, args, invoice IDs, FX rows, settings). Sources are produced here,
never by the model.
"""
from __future__ import annotations

import datetime as dt
import decimal
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

import duckdb

from backend import clauses, db, rules

REPORT_CURRENCIES = ("EUR", "original")
APPROVAL_SCOPES = ("all", "approved_only")
RUN_SQL_ROW_LIMIT = 200
APPROVAL_TIER_LISTED = 60
RUN_SQL_TIMEOUT_S = 5.0
CREDIT_NOTE_TREATMENT = ("Gross spend = positive invoices; credit notes (negative invoices) reported separately; "
                         "net = gross + credit notes. Credit notes are excluded from §2.2 thresholds and §3 tiers.")


# Reader-facing names for the source chips on an answer; the technical name stays in the trace.
TOOL_LABELS = {
    "spend_summary": "Spend totals", "po_status": "PO coverage", "maverick_spend": "Invoices without a PO",
    "approval_tier": "Required approvers", "missing_approval": "Invoices without an approver",
    "vendor_status": "Vendor status", "invoices_by_vendor_status": "Invoices by vendor status",
    "credit_notes": "Credit notes", "invoice_lookup": "Invoice details",
    "clause_info": "Data availability check", "run_sql": "Custom invoice lookup",
}


class ToolInputError(ValueError):
    """Bad tool arguments: reported back to the model so it can correct itself."""


@dataclass
class Settings:
    report_currency: str = "EUR"
    approval_scope: str = "all"

    def validate(self) -> "Settings":
        if self.report_currency not in REPORT_CURRENCIES:
            raise ToolInputError(f"report_currency must be one of {REPORT_CURRENCIES}")
        if self.approval_scope not in APPROVAL_SCOPES:
            raise ToolInputError(f"approval_scope must be one of {APPROVAL_SCOPES}")
        return self


@dataclass
class ToolContext:
    gui: Settings = field(default_factory=Settings)
    data_sources: list[dict] = field(default_factory=list)
    not_determinable: list[dict] = field(default_factory=list)
    overrides: dict[str, str] = field(default_factory=dict)

    def resolve(self, args: dict, uses_scope: bool = True) -> Settings:
        s = Settings(args.get("report_currency") or self.gui.report_currency,
                     args.get("approval_scope") or self.gui.approval_scope).validate()
        for k in ("report_currency", "approval_scope"):
            if args.get(k) and args[k] != getattr(self.gui, k) and (k != "approval_scope" or uses_scope):
                self.overrides[k] = args[k]
        if not uses_scope:
            s.approval_scope = "all"
        return s

    def applied_settings(self) -> dict:
        return {
            "report_currency": self.overrides.get("report_currency", self.gui.report_currency),
            "approval_scope": self.overrides.get("approval_scope", self.gui.approval_scope),
            "source": "question" if self.overrides else "gui",
        }

    def record(self, tool: str, query: str, args: dict, invoice_ids: list[str], fx_rows: list[dict],
               settings: Settings | None, note: str = "") -> None:
        self.data_sources.append({
            "tool": tool, "label": TOOL_LABELS.get(tool, tool), "query": query.strip(), "args": args,
            "invoice_ids": invoice_ids, "fx_rows": fx_rows,
            "settings": None if settings is None else {"report_currency": settings.report_currency,
                                                       "approval_scope": settings.approval_scope},
            "credit_note_treatment": CREDIT_NOTE_TREATMENT, "note": note,
            **db.source_metadata(),
        })

    def mark_not_determinable(self, clause: clauses.Clause) -> None:
        if any(n["clause"] == clause.id for n in self.not_determinable):
            return
        self.not_determinable.append({"clause": clause.id, "title": clause.title,
                                      "missing_fields": list(clause.missing_fields), "caveat": clause.caveat})


# ---------------------------------------------------------------------------- helpers

def _jsonable(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _rows(sql: str, params: list | None = None) -> list[dict]:
    return [_jsonable(r) for r in db.query(sql, params)]


FILTER_KEYS = ("vendor", "cost_center", "quarter", "date_from", "date_to", "currency", "invoice_numbers",
               "description", "approver")


def _where(filters: dict | None, settings: Settings | None = None, alias: str = "i") -> tuple[str, list]:
    f = filters or {}
    unknown = set(f) - set(FILTER_KEYS)
    if unknown:
        raise ToolInputError(f"unknown filter(s) {sorted(unknown)}; allowed: {FILTER_KEYS}")
    clauses_, params = ["TRUE"], []
    if f.get("vendor"):
        clauses_.append(f"({alias}.vendor_id = ? OR {alias}.vendor_name ILIKE ?)")
        params += [f["vendor"], f"%{f['vendor']}%"]
    if f.get("cost_center"):
        clauses_.append(f"{alias}.cost_center ILIKE ?")
        params.append(f"%{f['cost_center']}%")
    if f.get("quarter"):
        q = str(f["quarter"]).upper().replace("2025", "").strip(" -")
        if q not in ("Q1", "Q2", "Q3", "Q4"):
            raise ToolInputError("quarter must be Q1..Q4 (calendar quarters of 2025)")
        clauses_.append(f"{alias}.quarter = ?")
        params.append(q)
    for key, op in (("date_from", ">="), ("date_to", "<=")):
        if f.get(key):
            try:
                d = dt.date.fromisoformat(str(f[key]))
            except ValueError as e:
                raise ToolInputError(f"{key} must be YYYY-MM-DD") from e
            clauses_.append(f"{alias}.invoice_date {op} ?")
            params.append(d)
    if f.get("currency"):
        clauses_.append(f"{alias}.currency = ?")
        params.append(str(f["currency"]).upper())
    if f.get("invoice_numbers"):
        ids = [str(x).upper() for x in f["invoice_numbers"]]
        clauses_.append(f"{alias}.invoice_number IN ({', '.join('?' * len(ids))})")
        params += ids
    if f.get("description"):
        clauses_.append(f"{alias}.description ILIKE ?")
        params.append(f"%{f['description']}%")
    if f.get("approver"):
        clauses_.append(f"{alias}.approved_by = ?")
        params.append(f["approver"])
    if settings and settings.approval_scope == "approved_only":
        clauses_.append(f"{alias}.approved_by IS NOT NULL")
    return " AND ".join(clauses_), params


def _render(sql: str, params: list) -> str:
    """SQL text with parameters inlined, for display in lineage only (never executed)."""
    out = sql
    for p in params:
        lit = f"'{p}'" if isinstance(p, (str, dt.date)) else str(p)
        out = out.replace("?", lit, 1)
    return re.sub(r"\s+", " ", out).strip()


def _fx_rows(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        if r.get("currency") and r["currency"] != "EUR" and r.get("invoice_number") not in seen:
            seen.add(r["invoice_number"])
            out.append({k: r.get(k) for k in ("invoice_number", "currency", "amount_original", "fx_rate",
                                              "fx_rate_date", "amount_eur")})
    return out


INVOICE_COLS = ", ".join("i." + c for c in (
    "invoice_number", "invoice_date", "vendor_id", "vendor_name", "description", "amount_original", "currency",
    "fx_rate", "fx_rate_date", "amount_eur", "is_credit_note", "cost_center", "po_number", "approved_by"))


def _excluded_by_scope(filters: dict | None, s: Settings) -> list[str]:
    if s.approval_scope != "approved_only":
        return []
    w, p = _where(filters)
    return [r["invoice_number"] for r in
            _rows(f"SELECT invoice_number FROM invoices_eur i WHERE {w} AND approved_by IS NULL "
                  "ORDER BY invoice_number", p)]


# ---------------------------------------------------------------------------- spend

GROUPS = {
    "none": None,
    "currency": "i.currency",
    "vendor": "i.vendor_name",
    "vendor_category": "v.category",
    "description": "i.description",
    "cost_center": "i.cost_center",
    "quarter": "i.quarter",
    "month": "strftime(i.invoice_date, '%Y-%m')",
    "approver": "coalesce(i.approved_by, '(no approver record)')",
}
GROUP_LABELS = {"vendor_category": "Vendor category (from Vendor Master)",
                "description": "Invoice description (what was bought; not vendor category)"}


def spend_summary(ctx: ToolContext, group_by: str = "none", filters: dict | None = None,
                  report_currency: str | None = None, approval_scope: str | None = None,
                  top_n: int | None = None) -> dict:
    args = {"group_by": group_by, "filters": filters or {}, "report_currency": report_currency,
            "approval_scope": approval_scope, "top_n": top_n}
    s = ctx.resolve(args)
    if group_by not in GROUPS:
        raise ToolInputError(f"group_by must be one of {list(GROUPS)}")
    w, p = _where(filters, s)
    g = GROUPS[group_by]
    original = s.report_currency == "original"
    keys = ([f"{g} AS grp"] if g else []) + (["i.currency AS currency"] if original else [])
    key_names = (["grp"] if g else []) + (["currency"] if original else [])
    amt = "i.amount_original" if original else "i.amount_eur"
    sql = f"""
        SELECT {', '.join(keys + [''])}
               count(*) AS invoice_count,
               count(*) FILTER (WHERE NOT i.is_credit_note) AS positive_invoice_count,
               count(*) FILTER (WHERE i.is_credit_note) AS credit_note_count,
               coalesce(sum({amt}) FILTER (WHERE NOT i.is_credit_note), 0) AS gross,
               coalesce(sum({amt}) FILTER (WHERE i.is_credit_note), 0) AS credit_notes,
               coalesce(sum({amt}), 0) AS net
        FROM invoices_eur i JOIN vendors v USING (vendor_id)
        WHERE {w}
        {('GROUP BY ' + ', '.join(key_names)) if key_names else ''}
        ORDER BY {('net DESC, ' + ', '.join(key_names)) if key_names else '1'}
    """
    rows = _rows(sql, p)
    if top_n and g:
        if original:
            raise ToolInputError("top_n rankings need a single currency: use report_currency='EUR'")
        rows = rows[: int(top_n)]
    id_sql = f"SELECT {INVOICE_COLS} FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE {w}"
    inv = _rows(id_sql + " ORDER BY i.invoice_number", p)
    if top_n and g:
        keep = {r["grp"] for r in rows}
        grp_sql = f"SELECT i.invoice_number, {g} AS grp FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE {w}"
        members = {r["invoice_number"] for r in _rows(grp_sql, p) if r["grp"] in keep}
        inv = [r for r in inv if r["invoice_number"] in members]
    result: dict[str, Any] = {
        "currency": "original currency (per-currency subtotals; never summed across currencies)" if original else "EUR",
        "group_by": GROUP_LABELS.get(group_by, group_by),
        "rows": rows,
        "credit_note_treatment": CREDIT_NOTE_TREATMENT,
        "approval_scope": s.approval_scope,
    }
    excluded = _excluded_by_scope(filters, s)
    if excluded:
        result["excluded_by_scope"] = {"count": len(excluded), "invoice_numbers": excluded,
                                       "reason": "no approver record (§3.1 hold)"}
    if original:
        # Cross-currency totals are always EUR, and labelled as such.
        eur = _rows(f"""SELECT count(*) AS invoice_count,
                               coalesce(sum(amount_eur) FILTER (WHERE NOT is_credit_note),0) AS gross,
                               coalesce(sum(amount_eur) FILTER (WHERE is_credit_note),0) AS credit_notes,
                               coalesce(sum(amount_eur),0) AS net
                        FROM invoices_eur i WHERE {w}""", p)[0]
        result["cross_currency_total_eur"] = {"label": "EUR (converted at ECB rate on invoice date)", **eur}
    ctx.record("spend_summary", _render(sql, p), args, [r["invoice_number"] for r in inv], _fx_rows(inv), s)
    return result


# ---------------------------------------------------------------------------- clause tools

def _flag_rows(clause: str, filters: dict | None) -> tuple[list[dict], str, list]:
    w, p = _where(filters)
    sql = f"""SELECT {INVOICE_COLS}, i.quarter,
                     f.reason, f.annotation
              FROM policy_flags f JOIN invoices_eur i USING (invoice_number)
              WHERE f.clause = '{clause}' AND {w} ORDER BY i.invoice_number"""
    return _rows(sql, p), sql, p


def _sum_eur(rows: list[dict]) -> float:
    return round(sum(r["amount_eur"] for r in rows), 2)


def _group(rows: list[dict], key: str) -> list[dict]:
    out: dict[str, dict] = {}
    for r in rows:
        g = out.setdefault(r[key], {key: r[key], "count": 0, "amount_eur": 0.0, "annotated_count": 0,
                                    "invoice_numbers": []})
        g["count"] += 1
        g["amount_eur"] = round(g["amount_eur"] + r["amount_eur"], 2)
        g["annotated_count"] += 1 if r.get("annotation") else 0
        g["invoice_numbers"].append(r["invoice_number"])
    return sorted(out.values(), key=lambda x: str(x[key]))


def po_status(ctx: ToolContext, filters: dict | None = None, report_currency: str | None = None,
              approval_scope: str | None = None) -> dict:
    args = {"filters": filters or {}, "report_currency": report_currency, "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    w, p = _where(filters)
    sql = f"""SELECT {INVOICE_COLS} FROM invoices_eur i
              WHERE NOT i.is_credit_note AND i.amount_eur >= {rules.PO_THRESHOLD_EUR} AND {w}
              ORDER BY i.invoice_number"""
    rows = _rows(sql, p)
    with_po = [r for r in rows if r["po_number"]]
    without = [r for r in rows if not r["po_number"]]
    result = {
        "threshold": "EUR equivalent of 1,000 or above (§2.1), credit notes excluded",
        "invoices_at_or_above_threshold": len(rows),
        "with_po": {"count": len(with_po), "amount_eur": _sum_eur(with_po)},
        "without_po": {"count": len(without), "amount_eur": _sum_eur(without),
                       "invoice_numbers": [r["invoice_number"] for r in without]},
        "not_determinable": "Whether each PO was issued before work began (§2.1 timing): no PO issue date.",
    }
    ctx.mark_not_determinable(clauses.get("§2.1 timing"))
    ctx.record("po_status", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s,
               note="Compliance check: approval_scope ignored.")
    return result


def maverick_spend(ctx: ToolContext, filters: dict | None = None, group_by: str = "none",
                   report_currency: str | None = None, approval_scope: str | None = None) -> dict:
    args = {"filters": filters or {}, "group_by": group_by, "report_currency": report_currency,
            "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    if group_by not in ("none", "quarter", "cost_center", "vendor"):
        raise ToolInputError("group_by must be none|quarter|cost_center|vendor")
    rows, sql, p = _flag_rows("§2.2", filters)
    annotated = [r for r in rows if r["annotation"]]
    keep = ("invoice_number", "invoice_date", "quarter", "vendor_name", "description", "cost_center",
            "amount_original", "currency", "fx_rate_date", "amount_eur", "approved_by", "annotation")
    result: dict[str, Any] = {
        "label": "§2.2 flags: no PO reference on file, amount_eur >= 1,000 (not confirmed violations)",
        "flagged_count": len(rows),
        "flagged_amount_eur": _sum_eur(rows),
        "annotated_possible_recurring_count": len(annotated),
        "annotation_rule": f"description in {list(rules.RECURRING_DESCRIPTIONS)} -> '{rules.RECURRING_ANNOTATION}'. "
                           "Annotated invoices stay flagged (never auto-exempted under §2.3).",
        "invoices": [{k: r[k] for k in keep} for r in rows],
        "not_determinable": ["whether the flag was raised to the Cost Center owner / reported to the Finance "
                             "Controls Committee", "Cost Center owner names", "§9 emergency-exception status",
                             "§2.3 blanket-PO coverage", "§2.1 PO timing"],
    }
    if s.report_currency == "original":
        by_cur: dict[str, float] = {}
        for r in rows:
            by_cur[r["currency"]] = round(by_cur.get(r["currency"], 0) + r["amount_original"], 2)
        result["flagged_amount_by_original_currency"] = by_cur
    if group_by != "none":
        key = {"vendor": "vendor_name"}.get(group_by, group_by)
        result["groups"] = _group(rows, key)
    if annotated:
        ctx.mark_not_determinable(clauses.get("§2.3"))
    ctx.record("maverick_spend", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s,
               note="Compliance check: approval_scope ignored.")
    return result


def approval_tier(ctx: ToolContext, filters: dict | None = None, report_currency: str | None = None,
                  approval_scope: str | None = None) -> dict:
    args = {"filters": filters or {}, "report_currency": report_currency, "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    w, p = _where(filters)
    sql = f"SELECT {INVOICE_COLS} FROM invoices_eur i WHERE {w} ORDER BY i.invoice_number"
    rows = _rows(sql, p)
    out, counts = [], {}
    for r in rows:
        tier = rules.approval_tier(r["amount_eur"])
        out.append({"invoice_number": r["invoice_number"], "amount_original": r["amount_original"],
                    "currency": r["currency"], "fx_rate": r["fx_rate"], "fx_rate_date": r["fx_rate_date"],
                    "amount_eur": r["amount_eur"],
                    "required_approver": tier or "n/a (credit note: excluded from tiers)",
                    "approved_by": r["approved_by"]})
        if tier:
            c = counts.setdefault(tier, {"count": 0, "amount_eur": 0.0})
            c["count"] += 1
            c["amount_eur"] = round(c["amount_eur"] + r["amount_eur"], 2)
    result = {
        "tiers": "<= 5,000 Cost Center Owner; <= 50,000 Department Head; <= 250,000 Finance Director; "
                 "above: CFO + Procurement Excellence review (based on the EUR equivalent)",
        "counts_by_required_approver": counts,
        "total_invoices": len(out),
        "invoices_excluding_credit_notes": sum(c["count"] for c in counts.values()),
        "invoices": out[:APPROVAL_TIER_LISTED],
        "not_determinable": "Whether the named approver actually holds the required role: the data has no record "
                            "of each approver's role.",
    }
    if len(out) > APPROVAL_TIER_LISTED:
        result["listing_note"] = (f"The first {APPROVAL_TIER_LISTED} of {len(out)} invoices are listed here. All "
                                  f"{len(out)} invoice numbers are under 'How this was computed'.")
    ctx.mark_not_determinable(clauses.get("§3"))
    ctx.record("approval_tier", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s,
               note="Compliance check: approval_scope ignored.")
    return result


def missing_approval(ctx: ToolContext, filters: dict | None = None, report_currency: str | None = None,
                     approval_scope: str | None = None) -> dict:
    args = {"filters": filters or {}, "report_currency": report_currency, "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    rows, sql, p = _flag_rows("§3.1", filters)
    keep = ("invoice_number", "invoice_date", "vendor_name", "description", "cost_center", "amount_original",
            "currency", "fx_rate_date", "amount_eur", "po_number")
    result = {
        "label": "§3.1: invoices lacking an approver record -> must be held per §3.1",
        "count": len(rows),
        "amount_eur": _sum_eur(rows),
        "also_missing_po": [r["invoice_number"] for r in rows if not r["po_number"]],
        "invoices": [{k: r[k] for k in keep} for r in rows],
        "caveat": clauses.get("§3.1").caveat,
    }
    ctx.record("missing_approval", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s,
               note="Compliance check: approval_scope ignored.")
    return result


def vendor_status(ctx: ToolContext, vendor: str | None = None) -> dict:
    args = {"vendor": vendor}
    sql = "SELECT vendor_id, vendor_name, country, category, status FROM vendors"
    p: list = []
    if vendor:
        sql += " WHERE vendor_id = ? OR vendor_name ILIKE ?"
        p = [vendor, f"%{vendor}%"]
    sql += " ORDER BY vendor_id"
    rows = _rows(sql, p)
    result = {"as_of": "currently (Vendor Master snapshot, date unknown)", "vendors": rows,
              "caveat": clauses.get("§4.1").caveat}
    ctx.record("vendor_status", _render(sql, p), args, [], [], None)
    return result


def invoices_by_vendor_status(ctx: ToolContext, statuses: list[str] | None = None, filters: dict | None = None,
                              report_currency: str | None = None, approval_scope: str | None = None) -> dict:
    statuses = [x.upper() for x in (statuses or list(rules.ESCALATION_STATUSES))]
    if not set(statuses) <= {"ACTIVE", "INACTIVE", "ON_HOLD"}:
        raise ToolInputError("statuses must be from ACTIVE, INACTIVE, ON_HOLD")
    args = {"statuses": statuses, "filters": filters or {}, "report_currency": report_currency,
            "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    w, p = _where(filters)
    sql = f"""SELECT {INVOICE_COLS}, v.status AS vendor_status_now
              FROM invoices_eur i JOIN vendors v USING (vendor_id)
              WHERE v.status IN ({', '.join('?' * len(statuses))}) AND {w} ORDER BY i.invoice_number"""
    params = statuses + p
    rows = _rows(sql, params)
    by_vendor: dict[str, dict] = {}
    for r in rows:
        g = by_vendor.setdefault(r["vendor_name"], {"vendor": r["vendor_name"], "status_now": r["vendor_status_now"],
                                                    "count": 0, "amount_eur": 0.0})
        g["count"] += 1
        g["amount_eur"] = round(g["amount_eur"] + r["amount_eur"], 2)
    result = {
        "as_of": "currently (Vendor Master snapshot, date unknown)",
        "rule": "§4.1: invoices from ON_HOLD / INACTIVE vendors must be escalated to Procurement Excellence",
        "count": len(rows), "amount_eur": _sum_eur(rows),
        "by_vendor": list(by_vendor.values()),
        "invoices": [{k: r[k] for k in ("invoice_number", "invoice_date", "vendor_name", "vendor_status_now",
                                        "amount_original", "currency", "amount_eur")} for r in rows],
        "not_determinable": "Whether the vendor had this status on the invoice date (no status effective date), "
                            "and whether any payment was made (no payment records).",
    }
    ctx.mark_not_determinable(clauses.Clause(
        "§4.1 history", "Vendor status at invoice time / payments made", "none", None,
        missing_fields=clauses.get("§4.1").missing_fields, caveat=clauses.get("§4.1").caveat))
    ctx.record("invoices_by_vendor_status", _render(sql, params), args, [r["invoice_number"] for r in rows],
               _fx_rows(rows), s, note="Compliance check: approval_scope ignored.")
    return result


def credit_notes(ctx: ToolContext, filters: dict | None = None, report_currency: str | None = None,
                 approval_scope: str | None = None) -> dict:
    args = {"filters": filters or {}, "report_currency": report_currency, "approval_scope": approval_scope}
    s = ctx.resolve(args, uses_scope=False)
    rows, sql, p = _flag_rows("§6.1", filters)
    keep = ("invoice_number", "invoice_date", "vendor_name", "description", "amount_original", "currency",
            "fx_rate", "fx_rate_date", "amount_eur", "po_number", "approved_by")
    result = {"count": len(rows), "amount_eur": _sum_eur(rows),
              "invoices": [{k: r[k] for k in keep} for r in rows],
              "matching": "Matching to original invoices is not determinable: no original-invoice reference. "
                          "Do not match heuristically."}
    ctx.record("credit_notes", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s,
               note="Compliance check: approval_scope ignored.")
    return result


def invoice_lookup(ctx: ToolContext, filters: dict | None = None, report_currency: str | None = None,
                   approval_scope: str | None = None, limit: int = 50) -> dict:
    args = {"filters": filters or {}, "report_currency": report_currency, "approval_scope": approval_scope,
            "limit": limit}
    s = ctx.resolve(args)
    w, p = _where(filters, s)
    sql = f"""SELECT {INVOICE_COLS}, i.quarter,
                     v.status AS vendor_status_now, v.category AS vendor_category,
                     (SELECT list(f.clause ORDER BY f.clause) FROM policy_flags f
                      WHERE f.invoice_number = i.invoice_number) AS policy_flags
              FROM invoices_eur i JOIN vendors v USING (vendor_id) WHERE {w}
              ORDER BY i.invoice_number LIMIT {min(int(limit), 140)}"""
    rows = _rows(sql, p)
    for r in rows:
        r["required_approver_tier"] = rules.approval_tier(r["amount_eur"])
    result = {"count": len(rows), "invoices": rows,
              "fx_rule": clauses.get("§5.1").caveat,
              "vendor_status_note": "Vendor status is the current Vendor Master snapshot (date unknown)"}
    ctx.record("invoice_lookup", _render(sql, p), args, [r["invoice_number"] for r in rows], _fx_rows(rows), s)
    return result


def clause_info(ctx: ToolContext, clause: str) -> dict:
    c = clauses.get(clause)
    if not c:
        raise ToolInputError(f"unknown clause '{clause}'. Known: {[x.id for x in clauses.REGISTRY]}")
    entries = clauses.related(clause) if re.fullmatch(r"\s*§?\s*\d+\s*", clause) else [c]
    if c.id.startswith("§2.1") or c.id.startswith("§6.1"):
        entries = [x for x in clauses.related(clause) if x.id.split()[0] == c.id.split()[0]]
    out = []
    for e in entries:
        d = e.to_dict()
        if e.missing_fields:
            d["answer"] = f"{NOT_DET_PREFIX(e)}: missing {', '.join(e.missing_fields)}."
            ctx.mark_not_determinable(e)
        out.append(d)
    ctx.record("clause_info", f"clause registry lookup: {clause}", {"clause": clause}, [], [], None)
    return {"clauses": out}


def NOT_DET_PREFIX(e: clauses.Clause) -> str:
    if e.checkability == "none":
        return f"{e.id} is {clauses.NOT_DETERMINABLE}"
    if e.checkability == "partial":
        return f"{e.id} is only partly checkable; the rest is {clauses.NOT_DETERMINABLE}"
    return f"{e.id} is checkable from the data, but these aspects are {clauses.NOT_DETERMINABLE}"


# ---------------------------------------------------------------------------- run_sql

_FORBIDDEN = re.compile(r"\b(attach|detach|copy|export|import|install|load|pragma|set|reset|call|create|insert|"
                        r"update|delete|drop|alter|checkpoint|vacuum|read_csv\w*|read_parquet|read_json\w*|"
                        r"glob|read_text|read_blob)\b", re.I)


def run_sql(ctx: ToolContext, sql: str) -> dict:
    args = {"sql": sql}
    con = db.get_con()
    stmts = con.extract_statements(sql)
    if len(stmts) != 1 or stmts[0].type != duckdb.StatementType.SELECT:
        raise ToolInputError("run_sql accepts exactly one read-only SELECT statement")
    if _FORBIDDEN.search(sql):
        raise ToolInputError("run_sql: statement uses a disallowed keyword/function")
    cur = con.cursor()
    wrapped = f"SELECT * FROM ({sql.strip().rstrip(';')}) AS q LIMIT {RUN_SQL_ROW_LIMIT + 1}"
    timer = threading.Timer(RUN_SQL_TIMEOUT_S, cur.interrupt)
    timer.start()
    try:
        rel = cur.execute(wrapped)
        cols = [d[0] for d in rel.description]
        data = rel.fetchall()
    except duckdb.InterruptException as e:
        raise ToolInputError(f"query exceeded {RUN_SQL_TIMEOUT_S}s timeout") from e
    except duckdb.Error as e:
        raise ToolInputError(f"SQL error: {e}") from e
    finally:
        timer.cancel()
    rows = [_jsonable(dict(zip(cols, r))) for r in data]
    truncated = len(rows) > RUN_SQL_ROW_LIMIT
    rows = rows[:RUN_SQL_ROW_LIMIT]
    ids = sorted({r["invoice_number"] for r in rows if r.get("invoice_number")})
    ctx.record("run_sql", sql, args, ids, _fx_rows(rows), None,
               note="Free-form read-only SQL (fallback). invoice_ids only listed if the query returned invoice_number.")
    out = {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}
    if truncated:
        out["listing_note"] = (f"Only the first {RUN_SQL_ROW_LIMIT} results are shown. A narrower question "
                               "(a vendor, quarter or cost center) will show the rest.")
    return out


# ---------------------------------------------------------------------------- registry of LLM tools

SETTINGS_PROPS = {
    "report_currency": {"type": "string", "enum": list(REPORT_CURRENCIES),
                        "description": "Only set if the question explicitly asks for a currency view "
                                       "('in original currency', 'in GBP'). Otherwise omit (GUI setting applies)."},
    "approval_scope": {"type": "string", "enum": list(APPROVAL_SCOPES),
                       "description": "Only set if the question explicitly asks e.g. 'only approved invoices'. "
                                      "Otherwise omit (GUI setting applies)."},
}
FILTERS_SCHEMA = {
    "type": "object",
    "description": "Optional filters (all combinable).",
    "properties": {
        "vendor": {"type": "string", "description": "vendor_id or (partial) vendor name"},
        "cost_center": {"type": "string", "description": "e.g. CC-FIN-100"},
        "quarter": {"type": "string", "enum": ["Q1", "Q2", "Q3", "Q4"], "description": "calendar quarter of 2025"},
        "date_from": {"type": "string", "description": "YYYY-MM-DD inclusive"},
        "date_to": {"type": "string", "description": "YYYY-MM-DD inclusive"},
        "currency": {"type": "string", "enum": ["EUR", "GBP", "USD"], "description": "original invoice currency"},
        "invoice_numbers": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string", "description": "substring of invoice description"},
        "approver": {"type": "string", "description": "approved_by user id, e.g. j.smith"},
    },
}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable[..., dict]
    description: str
    input_schema: dict


def tool_specs() -> list[ToolSpec]:
    with_settings = {"filters": FILTERS_SCHEMA, **SETTINGS_PROPS}
    return [
        ToolSpec("spend_summary", spend_summary,
                 "Spend totals (gross positive invoices, credit notes, net) overall or grouped by currency, vendor, "
                 "vendor_category (Vendor Master), description (what was bought), cost_center, quarter, month or "
                 "approver; optional top_n ranking. Use for any 'how much did we spend' / 'top vendors' question. "
                 "Same function as the summary panel. Respects report_currency and approval_scope.",
                 _schema({"group_by": {"type": "string", "enum": list(GROUPS)},
                          "top_n": {"type": "integer", "minimum": 1}, **with_settings})),
        ToolSpec("po_status", po_status, clauses.tool_description("po_status"), _schema(with_settings)),
        ToolSpec("maverick_spend", maverick_spend, clauses.tool_description("maverick_spend"),
                 _schema({"group_by": {"type": "string", "enum": ["none", "quarter", "cost_center", "vendor"]},
                          **with_settings})),
        ToolSpec("approval_tier", approval_tier, clauses.tool_description("approval_tier"), _schema(with_settings)),
        ToolSpec("missing_approval", missing_approval, clauses.tool_description("missing_approval"),
                 _schema(with_settings)),
        ToolSpec("vendor_status", vendor_status,
                 "Current Vendor Master status (ACTIVE / INACTIVE / ON_HOLD), country and category for one or all "
                 "vendors. Present tense only: snapshot with no effective date (§4.1).",
                 _schema({"vendor": {"type": "string", "description": "vendor_id or (partial) name; omit for all"}})),
        ToolSpec("invoices_by_vendor_status", invoices_by_vendor_status,
                 clauses.tool_description("invoices_by_vendor_status"),
                 _schema({"statuses": {"type": "array", "items": {"type": "string",
                                                                  "enum": ["ACTIVE", "INACTIVE", "ON_HOLD"]},
                                       "description": "default INACTIVE + ON_HOLD"}, **with_settings})),
        ToolSpec("credit_notes", credit_notes, clauses.tool_description("credit_notes"), _schema(with_settings)),
        ToolSpec("invoice_lookup", invoice_lookup, clauses.tool_description("invoice_lookup"),
                 _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 140}, **with_settings})),
        ToolSpec("clause_info", clause_info,
                 "Registry entry for a policy clause: checkability, fields used, MISSING fields and caveat. Call it "
                 "for ANY clause the data cannot (fully) check — §1, §2.1 timing, §2.3 blanket POs, §3 approver "
                 "roles, §4.2, §4.3, §5.2 payment terms, §6.1 matching, §7.1/§7.2 requester/self-approval, §8.1, "
                 "§9 exceptions — and for every 'was X paid / when was it paid / who requested it / was it an "
                 "exception / was it an emergency' question. The returned text is the source of any "
                 "'not determinable' statement.",
                 _schema({"clause": {"type": "string", "description": "e.g. '§7.1', '§6.1 matching', '§2.1 timing', "
                                                                      "'§9', '§5.2'"}}, ["clause"])),
        ToolSpec("run_sql", run_sql,
                 "FALLBACK ONLY: use when no other tool fits. One read-only DuckDB SELECT over invoices_eur, vendors, "
                 "fx_rates, policy_flags (max 200 rows, 5 s). Use amount_eur for any cross-currency sum or threshold; "
                 "never sum amount_original across currencies.",
                 _schema({"sql": {"type": "string"}}, ["sql"])),
    ]


TOOLS_BY_NAME = {t.name: t for t in tool_specs()}


def call_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    spec = TOOLS_BY_NAME.get(name)
    if not spec:
        raise ToolInputError(f"unknown tool {name}")
    try:
        return spec.fn(ctx, **args)
    except TypeError as e:
        raise ToolInputError(f"bad arguments for {name}: {e}") from e


# ---------------------------------------------------------------------------- summary + export (no LLM)

def summary(settings: Settings) -> dict:
    ctx = ToolContext(gui=settings.validate())
    total = spend_summary(ctx)
    by_currency = spend_summary(ctx, group_by="currency")
    by_vendor = spend_summary(ctx, group_by="vendor")
    by_category = spend_summary(ctx, group_by="vendor_category")
    flag_counts = {r["clause"]: r["n"] for r in
                   _rows("SELECT clause, count(*) AS n FROM policy_flags GROUP BY clause ORDER BY clause")}
    annotated = _rows("SELECT count(*) AS n FROM policy_flags WHERE clause = '§2.2' AND annotation IS NOT NULL")[0]["n"]
    flags = {
        "§2.2 no PO reference (flagged)": flag_counts.get("§2.2", 0),
        "§2.2 of which possible §2.3 recurring service (annotated)": annotated,
        "§3.1 no approver record (must be held)": flag_counts.get("§3.1", 0),
        "§4.1 vendor currently INACTIVE / ON_HOLD (escalate)": flag_counts.get("§4.1", 0),
        "§6.1 credit notes": flag_counts.get("§6.1", 0),
    }
    ctx.data_sources.append({"tool": "flag_counts", "query": "SELECT clause, count(*) FROM policy_flags GROUP BY clause",
                             "args": {}, "invoice_ids": [], "fx_rows": [], "settings": None,
                             "credit_note_treatment": CREDIT_NOTE_TREATMENT,
                             "note": "Compliance flags ignore approval_scope.", **db.source_metadata()})
    return {
        "settings": {"report_currency": settings.report_currency, "approval_scope": settings.approval_scope},
        "total": total, "by_currency": by_currency, "by_vendor": by_vendor, "by_vendor_category": by_category,
        "flags": flags,
        "lineage": {**db.source_metadata(), "credit_note_treatment": CREDIT_NOTE_TREATMENT,
                    "computations": ctx.data_sources},
    }


def invoice_export(currency: str = "EUR") -> list[dict]:
    if currency not in REPORT_CURRENCIES:
        raise ToolInputError("currency must be EUR or original")
    return _rows("""SELECT invoice_number, invoice_date, vendor_name, description, cost_center,
                           amount_original AS amount, currency, fx_rate, fx_rate_date, amount_eur, is_credit_note,
                           po_number, approved_by
                    FROM invoices_eur ORDER BY invoice_number""")
