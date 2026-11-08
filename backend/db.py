"""Build the in-memory DuckDB database from the CSVs on every startup.

The CSVs in data/ are the only source of truth; nothing is persisted. The shape of the data is fixed by
contract.py, while the amount of data is not: any number of invoices_YYYY_clean.csv files can be present.
Cleaning happens upstream, so this module checks rows and never repairs them.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

import duckdb

from backend import contract
from backend.contract import ContractBreach, DataLoadError  # noqa: F401  (re-exported)

log = logging.getLogger("apropos.db")

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
POLICY_MD = DATA_DIR / contract.POLICY_FILE
POLICY_ID = contract.POLICY_ID
MAX_REJECTED_LISTED = 200

sha256 = contract.sha256
_varchar_cols = {c: "VARCHAR" for c in contract.INVOICE_COLUMNS}


def _invoice_files(data_dir: Path) -> tuple[list[tuple[Path, int]], list[str]]:
    """Files matching the yearly name are loaded; other invoices* CSVs are ignored and reported."""
    files, ignored = [], []
    for p in sorted(data_dir.glob("invoices*.csv")):
        m = contract.INVOICE_FILE_RE.match(p.name)
        if m:
            files.append((p, int(m.group(1))))
        else:
            ignored.append(p.name)
    return files, ignored


def _read_csv_sql(path: Path, columns: dict[str, str]) -> str:
    cols = "{" + ", ".join(f"'{k}': '{v}'" for k, v in columns.items()) + "}"
    quoted = str(path).replace("'", "''")
    return (f"read_csv('{quoted}', header = true, auto_detect = false, delim = ',', quote = '\"', nullstr = '', "
            f"columns = {cols})")


def _execute(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> None:
    try:
        con.execute(sql)
    except duckdb.Error as e:
        raise DataLoadError(f"{path.name} could not be read: {e}") from e


def _load_reference(con: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    vendors, fx = data_dir / contract.VENDOR_FILE, data_dir / contract.FX_FILE
    for path, cols in ((vendors, contract.VENDOR_COLUMNS), (fx, contract.FX_COLUMNS)):
        if not path.exists():
            raise DataLoadError(f"The required file {path.name} is missing.")
        contract.check_header(path, cols)
    _execute(con, f"""CREATE TABLE vendors AS SELECT * FROM
                      {_read_csv_sql(vendors, {c: 'VARCHAR' for c in contract.VENDOR_COLUMNS})}""", vendors)
    _execute(con, f"""CREATE TABLE fx_rates AS SELECT * FROM
                      {_read_csv_sql(fx, {'rate_date': 'DATE', 'currency': 'VARCHAR', 'rate': 'DOUBLE'})}""", fx)
    allowed = ", ".join(f"'{s}'" for s in contract.VENDOR_STATUSES)
    bad = con.execute(f"""SELECT DISTINCT coalesce(status, '(blank)') FROM vendors
                          WHERE status IS NULL OR status NOT IN ({allowed}) ORDER BY 1""").fetchall()
    if bad:
        raise ContractBreach(f"{contract.VENDOR_FILE} contains vendor statuses the policy checks don't know: "
                             f"{', '.join(r[0] for r in bad)}. {contract.REDESIGN}")
    dup = con.execute("SELECT vendor_id FROM vendors GROUP BY vendor_id HAVING count(*) > 1 ORDER BY 1").fetchall()
    if dup:
        raise DataLoadError(f"{contract.VENDOR_FILE} lists these vendor IDs more than once: "
                            f"{', '.join(str(r[0]) for r in dup)}.")


def _load_raw_invoices(con: duckdb.DuckDBPyConnection, files: list[tuple[Path, int]]) -> None:
    con.execute(f"""CREATE TABLE raw_invoices (
        {', '.join(f'{c} VARCHAR' for c in contract.INVOICE_COLUMNS)},
        source_file VARCHAR, file_year INTEGER, csv_line BIGINT)""")
    for path, year in files:
        contract.check_header(path, contract.INVOICE_COLUMNS)
        name = path.name.replace("'", "''")
        _execute(con, f"""INSERT INTO raw_invoices
                          SELECT *, '{name}', {year}, row_number() OVER () + 1
                          FROM {_read_csv_sql(path, _varchar_cols)}""", path)


def _validate_invoices(con: duckdb.DuckDBPyConnection) -> int:
    """Split raw rows into clean_invoices and rejected_rows. Returns how many identical duplicates were collapsed."""
    required = [c for c in contract.INVOICE_COLUMNS if c not in contract.OPTIONAL_INVOICE_COLUMNS]
    missing = " OR ".join(f"nullif(trim({c}), '') IS NULL" for c in required)
    effective = contract.POLICY_EFFECTIVE.isoformat()
    con.execute(f"""
        CREATE TABLE checked_invoices AS
        WITH typed AS (
            SELECT *, TRY_CAST(invoice_date AS DATE) AS parsed_date, TRY_CAST(amount AS DECIMAL(12,2)) AS parsed_amount,
                   md5(concat_ws('|', {', '.join(f"coalesce({c}, '')" for c in contract.INVOICE_COLUMNS)})) AS row_hash
            FROM raw_invoices
        )
        SELECT *, CASE
            WHEN {missing} THEN 'A required value is blank'
            WHEN parsed_date IS NULL THEN 'Invoice date is not a valid date'
            WHEN parsed_amount IS NULL THEN 'Amount is not a valid number'
            WHEN NOT regexp_full_match(currency, '[A-Z]{{3}}') THEN 'Currency is not a 3-letter code'
            WHEN year(parsed_date) <> file_year THEN 'Invoice date is outside the year in the file name'
            WHEN parsed_date < DATE '{effective}' THEN 'Invoice is dated before the policy took effect'
            WHEN vendor_id NOT IN (SELECT vendor_id FROM vendors) THEN 'Vendor is not in the Vendor Master'
        END AS reason
        FROM typed
    """)
    con.execute("""
        CREATE TABLE conflicts AS
        SELECT invoice_number FROM checked_invoices WHERE reason IS NULL
        GROUP BY invoice_number HAVING count(DISTINCT row_hash) > 1
    """)
    con.execute("""
        CREATE TABLE rejected_rows AS
        SELECT source_file, csv_line, invoice_number, reason FROM checked_invoices WHERE reason IS NOT NULL
        UNION ALL
        SELECT source_file, csv_line, invoice_number,
               'The same invoice number appears with different details, so neither copy was loaded'
        FROM checked_invoices
        WHERE reason IS NULL AND invoice_number IN (SELECT invoice_number FROM conflicts)
        ORDER BY source_file, csv_line
    """)
    # Whitespace-only PO / approver count as blank (the one normalisation: it defines "no PO" and "no approver").
    con.execute("""
        CREATE TABLE clean_invoices AS
        SELECT invoice_number, parsed_date AS invoice_date, vendor_id, vendor_name, description,
               parsed_amount AS amount, currency, cost_center,
               nullif(trim(po_number), '') AS po_number, nullif(trim(approved_by), '') AS approved_by, source_file
        FROM checked_invoices
        WHERE reason IS NULL AND invoice_number NOT IN (SELECT invoice_number FROM conflicts)
        QUALIFY row_number() OVER (PARTITION BY invoice_number ORDER BY source_file, csv_line) = 1
    """)
    collapsed = con.execute("""
        SELECT count(*) - count(DISTINCT invoice_number) FROM checked_invoices
        WHERE reason IS NULL AND invoice_number NOT IN (SELECT invoice_number FROM conflicts)
    """).fetchone()[0]
    return int(collapsed)


def _build_invoices_eur(con: duckdb.DuckDBPyConnection) -> None:
    # ECB quotes foreign units per 1 EUR -> amount_eur = amount / rate (divide, never multiply).
    # ASOF join: latest rate on or before the invoice date (weekends/holidays use the prior rate), but never one
    # older than FX_MAX_AGE_DAYS. Without a usable rate the invoice stays, with NULL amount_eur and fx_missing.
    age = contract.FX_MAX_AGE_DAYS
    con.execute(f"""
        CREATE TABLE invoices_eur AS
        WITH eur AS (
            SELECT i.*, 1.0::DOUBLE AS fx_rate, i.invoice_date AS fx_rate_date
            FROM clean_invoices i WHERE i.currency = 'EUR'
        ), fx AS (
            SELECT i.*,
                   CASE WHEN date_diff('day', f.rate_date, i.invoice_date) <= {age} THEN f.rate END AS fx_rate,
                   CASE WHEN date_diff('day', f.rate_date, i.invoice_date) <= {age} THEN f.rate_date END AS fx_rate_date
            FROM clean_invoices i
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
            year(invoice_date) AS invoice_year,
            year(invoice_date)::VARCHAR || '-Q' || quarter(invoice_date)::VARCHAR AS quarter,
            cost_center, po_number, approved_by, source_file
        FROM allrows
        ORDER BY invoice_number
    """)
    for table in ("raw_invoices", "checked_invoices", "conflicts", "clean_invoices"):
        con.execute(f"DROP TABLE {table}")


def _load_report(con: duckdb.DuckDBPyConnection, files: list[tuple[Path, int]], ignored: list[str],
                 raw_counts: dict[str, int], collapsed: int) -> dict:
    def col(sql: str) -> list:
        return [r[0] for r in con.execute(sql).fetchall()]

    per_file = {r[0]: r[1:] for r in con.execute(
        "SELECT source_file, count(*), min(invoice_date), max(invoice_date) FROM invoices_eur GROUP BY 1").fetchall()}
    rejected_per_file = dict(con.execute("SELECT source_file, count(*) FROM rejected_rows GROUP BY 1").fetchall())
    file_rows = []
    for path, year in files:
        loaded, first, last = per_file.get(path.name, (0, None, None))
        file_rows.append({"file": path.name, "year": year, "sha256": contract.sha256(path),
                          "rows_read": raw_counts[path.name], "rows_loaded": loaded,
                          "rows_rejected": rejected_per_file.get(path.name, 0),
                          "date_from": first.isoformat() if first else None,
                          "date_to": last.isoformat() if last else None})
    rejected = [{"file": r[0], "csv_line": r[1], "invoice_number": r[2], "reason": r[3]} for r in con.execute(
        f"SELECT * FROM rejected_rows ORDER BY 1, 2 LIMIT {MAX_REJECTED_LISTED}").fetchall()]
    years = col("SELECT DISTINCT invoice_year FROM invoices_eur ORDER BY 1")
    latest = years[-1]
    through = col(f"SELECT max(invoice_date) FROM invoices_eur WHERE invoice_year = {latest}")[0]
    fx_latest = col("SELECT max(rate_date) FROM fx_rates")[0]
    pending = col("SELECT invoice_number FROM invoices_eur WHERE fx_missing ORDER BY 1")
    return {
        "loaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "policy": contract.POLICY_ID,
        "files": file_rows,
        "ignored_files": ignored,
        "invoices_loaded": col("SELECT count(*) FROM invoices_eur")[0],
        "rejected_count": col("SELECT count(*) FROM rejected_rows")[0],
        "rejected": rejected,
        "identical_duplicates_collapsed": collapsed,
        "rate_pending": {"count": len(pending), "invoice_numbers": pending[:60]},
        "fx_latest_date": fx_latest.isoformat() if fx_latest else None,
        "years": years,
        "quarters": col("SELECT DISTINCT quarter FROM invoices_eur ORDER BY 1"),
        "latest_year": latest,
        "latest_year_through": through.isoformat(),
    }


def build_db(data_dir: Path | None = None) -> tuple[duckdb.DuckDBPyConnection, dict]:
    from backend import rules  # local import: rules needs the loaded tables

    data_dir = Path(data_dir or DATA_DIR)
    contract.check_policy(data_dir / contract.POLICY_FILE)
    files, ignored = _invoice_files(data_dir)
    if not files:
        raise DataLoadError(f"No invoice files named invoices_YYYY_clean.csv were found in {data_dir.name}/.")
    con = duckdb.connect(":memory:")
    _load_reference(con, data_dir)
    _load_raw_invoices(con, files)
    raw_counts = dict(con.execute("SELECT source_file, count(*) FROM raw_invoices GROUP BY 1").fetchall())
    for path, _ in files:
        raw_counts.setdefault(path.name, 0)
    collapsed = _validate_invoices(con)
    _build_invoices_eur(con)
    if not con.execute("SELECT count(*) FROM invoices_eur").fetchone()[0]:
        raise DataLoadError("No valid invoices could be loaded from the invoice files.")
    report = _load_report(con, files, ignored, raw_counts, collapsed)
    rules.build_policy_flags(con)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con, report


_CON: duckdb.DuckDBPyConnection | None = None
_REPORT: dict | None = None
_FAILURE: DataLoadError | None = None
RELOAD_HOOKS: list[Callable[[], None]] = []  # caches built from the data register here


def load(data_dir: Path | None = None) -> None:
    """(Re)build the database. On failure no data is served and the reason is kept for /api/status."""
    global DATA_DIR, POLICY_MD, _CON, _REPORT, _FAILURE
    if data_dir is not None:
        DATA_DIR = Path(data_dir)
        POLICY_MD = DATA_DIR / contract.POLICY_FILE
    source_metadata.cache_clear()
    for hook in RELOAD_HOOKS:
        hook()
    try:
        _CON, _REPORT = build_db(DATA_DIR)
        _FAILURE = None
    except DataLoadError as e:
        _CON, _REPORT, _FAILURE = None, None, e
        raise


def get_con() -> duckdb.DuckDBPyConnection:
    """Shared connection; callers should use .cursor() for thread safety."""
    if _CON is None:
        if _FAILURE is not None:
            raise _FAILURE
        load()
    return _CON


def report() -> dict:
    get_con()
    return _REPORT


def status() -> dict:
    try:
        return {"state": "ready", "message": None, "redesign_needed": False, **report()}
    except DataLoadError as e:
        return {"state": "failed", "message": str(e), "redesign_needed": isinstance(e, ContractBreach)}


@lru_cache(maxsize=1)
def source_metadata() -> dict:
    """Lineage metadata attached to every payload (§8.2)."""
    r = report()
    others = [DATA_DIR / contract.VENDOR_FILE, DATA_DIR / contract.FX_FILE, POLICY_MD]
    return {
        "policy": POLICY_ID,
        "data_loaded_at": r["loaded_at"],
        "source_files": [{"file": f"data/{f['file']}", "sha256": f["sha256"]} for f in r["files"]]
                        + [{"file": f"data/{p.name}", "sha256": sha256(p)} for p in others],
        "fx_source": "ECB euro foreign exchange reference rates (data-api.ecb.europa.eu, series EXR.D.{CUR}.EUR.SP00.A)",
    }


def append_load_log() -> None:
    """Record what was loaded, only when it differs from the previous load, so changed files leave a trace."""
    path = Path(os.environ.get("LOAD_LOG", DATA_DIR / "load_log.jsonl"))
    r = report()
    keep = ("file", "sha256", "rows_read", "rows_loaded", "rows_rejected")
    files = [{k: f[k] for k in keep} for f in r["files"]]
    try:
        last = None
        if path.exists():
            lines = path.read_text().strip().splitlines()
            last = json.loads(lines[-1]) if lines else None
        if last is None or last["files"] != files:
            with path.open("a") as f:
                f.write(json.dumps({"loaded_at": r["loaded_at"], "files": files}) + "\n")
    except (OSError, ValueError, KeyError) as e:
        log.warning("could not update the load log %s: %s", path, e)



def query(sql: str, params: list | None = None) -> list[dict]:
    cur = get_con().cursor()
    rel = cur.execute(sql, params or [])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]
