"""Fetch ECB euro reference rates (USD, GBP) for 2025 into data/fx_rates.csv.

Source: ECB Data Portal SDMX API, series EXR.D.{CUR}.EUR.SP00.A
  https://data-api.ecb.europa.eu/service/data/EXR/D.{CUR}.EUR.SP00.A?startPeriod=2025-01-01&endPeriod=2025-12-31&format=csvdata
Quote convention: units of foreign currency per 1 EUR (so amount_eur = amount / rate).
Fetched for this repo on 2026-11-07. The output file is committed so the app runs offline;
re-run this script only to refresh it.

Usage:
  python scripts/fetch_fx.py                 # download from the ECB
  python scripts/fetch_fx.py --from-dir DIR  # parse previously downloaded ecb_USD.csv / ecb_GBP.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import ssl
import urllib.request
from pathlib import Path

CURRENCIES = ("GBP", "USD")
START, END = "2025-01-01", "2025-12-31"
URL = ("https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
       f"?startPeriod={START}&endPeriod={END}&format=csvdata")
OUT = Path(__file__).resolve().parent.parent / "data" / "fx_rates.csv"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # newer CA bundle; the ECB chain ends at Sectigo Root E46
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download(cur: str) -> str:
    req = urllib.request.Request(URL.format(cur=cur), headers={"User-Agent": "apropos-fetch-fx"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse(cur: str, text: str) -> list[tuple[str, str, str]]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["CURRENCY"] != cur or r["CURRENCY_DENOM"] != "EUR":
            raise ValueError(f"unexpected series {r['KEY']}")
        if r["OBS_VALUE"]:
            rows.append((r["TIME_PERIOD"], cur, r["OBS_VALUE"]))
    if len(rows) < 240:
        raise ValueError(f"only {len(rows)} {cur} fixings; expected ~250 for a full year")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", type=Path)
    args = ap.parse_args()
    rows: list[tuple[str, str, str]] = []
    for cur in CURRENCIES:
        text = (args.from_dir / f"ecb_{cur}.csv").read_text() if args.from_dir else download(cur)
        rows += parse(cur, text)
    rows.sort()
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rate_date", "currency", "rate"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
