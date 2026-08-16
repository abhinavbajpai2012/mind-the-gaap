#!/usr/bin/env python3
"""Create filtered, model-facing copies of extracted company CSVs.

Raw CSVs remain unchanged. Filtering is conservative: it removes duplicate
observations and empty qualitative rows, but does not invent or reconcile values.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def quote_key(value: str) -> str:
    value = normalized(value)
    value = re.sub(r"<!--.*?-->", "", value)
    return value


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames or [], list(reader)


def row_key(name: str, row: dict[str, str]) -> tuple:
    source = row.get("source_file", "")
    if name == "document_inventory.csv":
        return (source,)
    if name == "filing_earnings_release_quarterly.csv":
        return (source,)
    if name == "filing_financials_periodic.csv":
        return (source,)
    if name == "guidance.csv":
        return (
            source, row.get("metric", ""), row.get("value_low", ""),
            row.get("value_high", ""), row.get("unit", ""),
        )
    if name == "segment_product_line_sales.csv":
        return (
            source, row.get("dimension_type", ""), row.get("dimension_name", ""),
            row.get("net_sales_usd_m", ""),
        )
    if name in {"call_prepared_remarks_quarterly.csv", "call_qna_driver_signals.csv"}:
        return (
            source, row.get("metric", row.get("driver", "")),
            quote_key(row.get("quote", row.get("driver", ""))),
        )
    if name == "category_signals.csv":
        return (
            source, row.get("category", ""), row.get("signal_type", ""),
            quote_key(row.get("quote", "")),
        )
    if name == "slide_strategy_metrics.csv":
        return (
            source, row.get("metric", ""), row.get("value", ""),
            row.get("dimension_name", ""),
        )
    if name == "slide_product_taxonomy.csv":
        return (source, row.get("taxonomy_level", ""), row.get("name", ""))
    return tuple(row.values())


def should_keep(name: str, row: dict[str, str]) -> bool:
    if name == "document_inventory.csv":
        return bool(row.get("source_file"))
    if name in {"call_prepared_remarks_quarterly.csv", "call_qna_driver_signals.csv"}:
        quote = row.get("quote", "")
        if len(quote_key(quote)) < 45 or quote_key(quote).startswith(("company:", "ticker:")):
            return False
        raw_value = row.get("value", row.get("impact_value", "")).strip()
        if raw_value and not row.get("unit", "").strip():
            try:
                if 1900 <= float(raw_value) <= 2100:
                    return False
            except ValueError:
                pass
        return True
    if name == "category_signals.csv":
        return len(quote_key(row.get("quote", ""))) >= 35 and bool(row.get("category"))
    if name == "slide_strategy_metrics.csv":
        return bool(row.get("metric")) and bool(row.get("value"))
    if name == "slide_product_taxonomy.csv":
        return bool(row.get("name"))
    if name == "filing_financials_periodic.csv":
        sales = row.get("net_sales_usd_m", "")
        gross = row.get("gross_profit_usd_m", "")
        operating = row.get("operating_income_usd_m", "")
        try:
            if sales and gross and float(sales) < float(gross):
                return False
            if gross and operating and float(gross) < float(operating):
                return False
        except ValueError:
            return False
        return bool(row.get("source_file"))
    if name == "segment_product_line_sales.csv":
        return bool(row.get("dimension_name")) and bool(row.get("net_sales_usd_m"))
    return any(value.strip() for value in row.values())


def filter_file(source: Path, destination: Path) -> tuple[int, int]:
    fields, rows = read_rows(source)
    kept: list[dict[str, str]] = []
    seen: set[tuple] = set()
    for row in rows:
        if not should_keep(source.name, row):
            continue
        key = row_key(source.name, row)
        if key in seen:
            continue
        seen.add(key)
        kept.append({field: row.get(field, "") for field in fields})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)
    return len(rows), len(kept)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: filter_company_csvs.py <company-folder>", file=sys.stderr)
        return 2
    folder = Path(sys.argv[1]).resolve()
    raw_dir = folder / "csv"
    final_dir = raw_dir / "final"
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        print(f"No raw CSVs found in {raw_dir}", file=sys.stderr)
        return 1
    for source in files:
        before, after = filter_file(source, final_dir / source.name)
        print(f"{source.name}: {before} -> {after} rows")
    print(f"Final filtered CSVs written to {final_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
