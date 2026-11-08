"""The data and policy contract: what the app is built against.

Data may GROW freely: more rows, more vendors, new currencies, new yearly files, replaced current-year files.
Data may not change SHAPE, and the policy may not change at all, without a redesign: the clause registry, rules,
prompts and evals are all written against exactly this schema and exactly this policy text.

If a check here fails, do not simply edit the expected values. See "Data contract and change boundaries" in
CLAUDE.md for what has to be reviewed first.

Meaning that no check can see, because cleaning happens upstream (also part of the contract):
- blank po_number      = no PO reference on file (§2.2)
- blank approved_by    = no approver on record (§3.1)
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import re
from pathlib import Path

INVOICE_FILE_RE = re.compile(r"^invoices_(\d{4})_clean\.csv$")
VENDOR_FILE = "vendor_master.csv"
FX_FILE = "fx_rates.csv"
POLICY_FILE = "procurement_policy.md"

INVOICE_COLUMNS = ("invoice_number", "invoice_date", "vendor_id", "vendor_name", "description", "amount", "currency",
                   "cost_center", "po_number", "approved_by")
OPTIONAL_INVOICE_COLUMNS = ("po_number", "approved_by")  # blank is meaningful; every other column is required
VENDOR_COLUMNS = ("vendor_id", "vendor_name", "country", "category", "status")
FX_COLUMNS = ("rate_date", "currency", "rate")

# A status outside this list would silently skip §4.1 escalation, so it counts as a contract change.
VENDOR_STATUSES = ("ACTIVE", "INACTIVE", "ON_HOLD")

POLICY_ID = "FIN-POL-014 v3.2"
POLICY_EFFECTIVE = dt.date(2025, 1, 1)
POLICY_SHA256 = "7a094855ed1107bb8532fa1cc120e3631d7a06c89b9c3106d6199477373daf48"

# Longest gap the ECB leaves between rates is the Easter weekend; older than this means the rate file is behind.
FX_MAX_AGE_DAYS = 7


class DataLoadError(RuntimeError):
    """The data could not be loaded, so the app serves no figures."""


class ContractBreach(DataLoadError):
    """The schema or policy differs from what the app was designed for: a redesign is needed."""


REDESIGN = "The app was designed for the previous version, so a redesign is needed before it can serve this data."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_header(path: Path, expected: tuple[str, ...]) -> None:
    """Exact names in exact order: the loader assigns columns by position."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
    except (OSError, UnicodeDecodeError) as e:
        raise DataLoadError(f"{path.name} could not be read: {e}") from e
    found = tuple(c.strip() for c in header)
    if found != expected:
        raise ContractBreach(f"The columns in {path.name} have changed. Expected: {', '.join(expected)}. "
                             f"Found: {', '.join(found) or '(none)'}. {REDESIGN}")


def check_policy(path: Path) -> None:
    if not path.exists():
        raise ContractBreach(f"The policy file {path.name} is missing. {REDESIGN}")
    if sha256(path) != POLICY_SHA256:
        raise ContractBreach(f"The policy file {path.name} is no longer {POLICY_ID}. {REDESIGN}")
