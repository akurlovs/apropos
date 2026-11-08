"""Fetch ECB euro reference rates through today and merge them into data/fx_rates.csv.

Source: ECB Data Portal SDMX API, series EXR.D.{CUR}.EUR.SP00.A
  https://data-api.ecb.europa.eu/service/data/EXR/D.{CUR}.EUR.SP00.A?startPeriod=2025-01-01&endPeriod=<today>&format=csvdata
Quote convention: units of foreign currency per 1 EUR (so amount_eur = amount / rate).
The output file is committed so the app runs offline. Run this BEFORE adding or replacing an invoice file, so
new invoices have rates. Currencies come from the invoice files, so a new one is picked up automatically.
Existing rows are kept; dates the ECB returns replace them.

Usage:
  python scripts/fetch_fx.py                 # download from the ECB
  python scripts/fetch_fx.py --from-dir DIR  # parse previously downloaded ecb_USD.csv / ecb_GBP.csv
  python scripts/fetch_fx.py --out PATH      # write somewhere other than data/fx_rates.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import ssl
import urllib.request
from pathlib import Path

CURRENCIES = ("GBP", "USD")
START = "2025-01-01"
URL = ("https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
       f"?startPeriod={START}&endPeriod={{end}}&format=csvdata")
DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "fx_rates.csv"


def currencies() -> tuple[str, ...]:
    """GBP and USD plus any other non-EUR currency found in the invoice files."""
    found = set(CURRENCIES)
    for path in DATA.glob("invoices_*_clean.csv"):
        with path.open(newline="", encoding="utf-8-sig") as f:
            found |= {r["currency"].strip() for r in csv.DictReader(f) if r["currency"].strip()}
    return tuple(sorted(found - {"EUR"}))


def merge(existing: dict[tuple[str, str], str], rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    merged = dict(existing)
    merged.update({(d, c): r for d, c, r in rows})
    return sorted((d, c, r) for (d, c), r in merged.items())


def read_existing(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {(r["rate_date"], r["currency"]): r["rate"] for r in csv.DictReader(f)}


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # newer CA bundle; the ECB chain ends at Sectigo Root E46
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(cur: str) -> str:
    url = URL.format(cur=cur, end=dt.date.today().isoformat())
    req = urllib.request.Request(url, headers={"User-Agent": "apropos-fetch-fx"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse(cur: str, text: str) -> list[tuple[str, str, str]]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["CURRENCY"] != cur or r["CURRENCY_DENOM"] != "EUR":
            raise ValueError(f"unexpected series {r['KEY']}")
        if r["OBS_VALUE"]:
            rows.append((r["TIME_PERIOD"], cur, r["OBS_VALUE"]))
    if not rows:
        raise ValueError(f"the ECB returned no rates for {cur}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows: list[tuple[str, str, str]] = []
    for cur in currencies():
        text = (args.from_dir / f"ecb_{cur}.csv").read_text() if args.from_dir else download(cur)
        rows += parse(cur, text)
    rows = merge(read_existing(args.out), rows)
    with args.out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rate_date", "currency", "rate"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
