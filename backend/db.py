"""Build the in-memory DuckDB database from the CSVs on every startup.

The CSVs in data/ are the only source of truth; nothing is persisted.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import duckdb

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
INVOICES_CSV = DATA_DIR / "invoices_2025_clean.csv"
VENDORS_CSV = DATA_DIR / "vendor_master.csv"
FX_CSV = DATA_DIR / "fx_rates.csv"
POLICY_MD = DATA_DIR / "procurement_policy.md"

POLICY_ID = "FIN-POL-014 v3.2"
EXPECTED_INVOICES = 140
EXPECTED_VENDORS = 10


class DataLoadError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def source_metadata() -> dict:
    """Lineage metadata attached to every payload (§8.2)."""
    files = [INVOICES_CSV, VENDORS_CSV, FX_CSV, POLICY_MD]
    return {
        "policy": POLICY_ID,
        "source_files": [{"file": f"data/{p.name}", "sha256": sha256(p)} for p in files],
        "fx_source": "ECB euro foreign exchange reference rates (data-api.ecb.europa.eu, series EXR.D.{USD,GBP}.EUR.SP00.A)",
    }


def _load(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE TABLE raw_invoices AS
        SELECT * FROM read_csv('{INVOICES_CSV}', header = true, nullstr = '',
            columns = {{
                'invoice_number': 'VARCHAR', 'invoice_date': 'DATE', 'vendor_id': 'VARCHAR',
                'vendor_name': 'VARCHAR', 'description': 'VARCHAR', 'amount': 'DECIMAL(12,2)',
                'currency': 'VARCHAR', 'cost_center': 'VARCHAR', 'po_number': 'VARCHAR',
                'approved_by': 'VARCHAR'}})
    """)
    con.execute(f"""
        CREATE TABLE vendors AS
        SELECT * FROM read_csv('{VENDORS_CSV}', header = true, nullstr = '',
            columns = {{'vendor_id': 'VARCHAR', 'vendor_name': 'VARCHAR', 'country': 'VARCHAR',
                        'category': 'VARCHAR', 'status': 'VARCHAR'}})
    """)
    con.execute(f"""
        CREATE TABLE fx_rates AS
        SELECT * FROM read_csv('{FX_CSV}', header = true,
            columns = {{'rate_date': 'DATE', 'currency': 'VARCHAR', 'rate': 'DOUBLE'}})
    """)
    # Empty strings are already NULL via nullstr; also trim whitespace-only values.
    con.execute("UPDATE raw_invoices SET po_number = NULL WHERE trim(po_number) = ''")
    con.execute("UPDATE raw_invoices SET approved_by = NULL WHERE trim(approved_by) = ''")

    # ECB quotes foreign units per 1 EUR -> amount_eur = amount / rate (divide, never multiply).
    # ASOF join: latest fixing on or before the invoice date (weekends/holidays use the prior fixing).
    # LEFT ASOF so a missing rate yields NULL amount_eur + fx_missing, never a dropped row.
    con.execute("""
        CREATE TABLE invoices_eur AS
        WITH eur AS (
            SELECT i.*, 1.0::DOUBLE AS fx_rate, i.invoice_date AS fx_rate_date
            FROM raw_invoices i WHERE i.currency = 'EUR'
        ), fx AS (
            SELECT i.*, f.rate AS fx_rate, f.rate_date AS fx_rate_date
            FROM raw_invoices i
            ASOF LEFT JOIN fx_rates f
              ON i.currency = f.currency AND i.invoice_date >= f.rate_date
            WHERE i.currency <> 'EUR'
        ), allrows AS (SELECT * FROM eur UNION ALL BY NAME SELECT * FROM fx)
        SELECT
            invoice_number, invoice_date, vendor_id, vendor_name, description,
            amount AS amount_original, currency,
            fx_rate, fx_rate_date,
            ROUND(amount::DOUBLE / fx_rate, 2)::DECIMAL(14,2) AS amount_eur,
            fx_rate IS NULL AS fx_missing,
            amount < 0 AS is_credit_note,
            'Q' || quarter(invoice_date)::VARCHAR AS quarter,
            cost_center, po_number, approved_by
        FROM allrows
        ORDER BY invoice_number
    """)
    con.execute("DROP TABLE raw_invoices")


def _assert_loaded(con: duckdb.DuckDBPyConnection) -> None:
    n_inv = con.execute("SELECT count(*) FROM invoices_eur").fetchone()[0]
    n_ven = con.execute("SELECT count(*) FROM vendors").fetchone()[0]
    orphans = con.execute(
        "SELECT count(*) FROM invoices_eur i ANTI JOIN vendors v USING (vendor_id)").fetchone()[0]
    missing_fx = con.execute(
        "SELECT list(invoice_number) FROM invoices_eur WHERE amount_eur IS NULL").fetchone()[0]
    problems = []
    if n_inv != EXPECTED_INVOICES:
        problems.append(f"expected {EXPECTED_INVOICES} invoices, got {n_inv}")
    if n_ven != EXPECTED_VENDORS:
        problems.append(f"expected {EXPECTED_VENDORS} vendors, got {n_ven}")
    if orphans:
        problems.append(f"{orphans} invoices reference unknown vendor_id")
    if missing_fx:
        problems.append(f"no FX rate for {missing_fx}")
    if problems:
        raise DataLoadError("; ".join(problems))


def build_db(strict: bool = True) -> duckdb.DuckDBPyConnection:
    from backend import rules  # local import: rules needs the loaded tables

    con = duckdb.connect(":memory:")
    _load(con)
    if strict:
        _assert_loaded(con)
    rules.build_policy_flags(con)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


_CON: duckdb.DuckDBPyConnection | None = None


def get_con() -> duckdb.DuckDBPyConnection:
    """Shared connection; callers should use .cursor() for thread safety."""
    global _CON
    if _CON is None:
        _CON = build_db()
    return _CON


def query(sql: str, params: list | None = None) -> list[dict]:
    cur = get_con().cursor()
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]
