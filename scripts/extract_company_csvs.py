#!/usr/bin/env python3
"""Extract forecasting-oriented CSVs from a company's markdown document corpus.

This intentionally favors reproducible, auditable extraction over aggressive NLP:
every qualitative row retains its source file and a short quote.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


OUTPUTS = {
    "document_inventory.csv": [
        "company", "ticker", "published_at", "period", "document_type",
        "document_family", "source_file", "file_size_bytes", "has_tables",
        "has_guidance_terms", "has_product_terms", "has_numeric_content",
    ],
    "filing_earnings_release_quarterly.csv": [
        "company", "ticker", "published_at", "period", "fiscal_year",
        "fiscal_quarter", "source_file", "net_sales_usd_m", "net_sales_yoy_pct",
        "comparable_sales_total_pct", "comparable_sales_us_pct", "fx_comp_impact_bps",
        "net_earnings_usd_m", "diluted_eps_gaap_usd", "adjusted_diluted_eps_usd",
        "stores_count", "srs_locations_count", "associates_count",
        "guidance_reaffirmed_flag",
    ],
    "guidance.csv": [
        "company", "ticker", "published_at", "guidance_period", "metric",
        "value_low", "value_high", "unit", "basis", "directionality",
        "prior_base_value", "quote", "source_file",
    ],
    "filing_financials_periodic.csv": [
        "company", "ticker", "published_at", "document_subtype", "period",
        "fiscal_year", "fiscal_quarter", "period_length_months", "source_file",
        "net_sales_usd_m", "cost_of_sales_usd_m", "gross_profit_usd_m",
        "gross_margin_pct", "sga_usd_m", "depreciation_amortization_usd_m",
        "operating_income_usd_m", "operating_margin_pct", "interest_expense_usd_m",
        "tax_provision_usd_m", "effective_tax_rate_pct", "net_earnings_usd_m",
        "basic_eps_usd", "diluted_eps_gaap_usd", "basic_weighted_avg_shares_m",
        "diluted_weighted_avg_shares_m", "cash_and_equivalents_usd_m",
        "receivables_usd_m", "merchandise_inventory_usd_m", "capex_usd_m",
        "operating_cash_flow_usd_m", "dividends_paid_usd_m", "long_term_debt_usd_m",
    ],
    "segment_product_line_sales.csv": [
        "company", "ticker", "published_at", "period", "fiscal_year",
        "fiscal_quarter", "source_file", "dimension_type", "dimension_name",
        "parent_dimension_name", "net_sales_usd_m", "net_sales_mix_pct",
        "operating_income_usd_m", "operating_margin_pct", "yoy_growth_pct", "notes",
    ],
    "call_prepared_remarks_quarterly.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "speaker_role", "metric", "value", "value_low", "value_high", "unit",
        "time_scope", "category", "directionality", "quote",
    ],
    "call_qna_driver_signals.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "question_topic", "driver", "affected_metric", "affected_category",
        "impact_value", "impact_unit", "impact_direction", "time_scope",
        "confidence_hint", "quote",
    ],
    "category_signals.csv": [
        "company", "ticker", "published_at", "period", "source_file", "category",
        "taxonomy_level", "signal_type", "value", "unit", "directionality", "quote",
    ],
    "slide_strategy_metrics.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "slide_section", "metric", "value", "unit", "dimension",
        "dimension_name", "time_scope", "quote",
    ],
    "slide_product_taxonomy.csv": [
        "company", "ticker", "published_at", "source_file", "taxonomy_level",
        "name", "parent_name", "description", "examples",
    ],
}


def metadata(text: str) -> dict[str, str]:
    block = re.search(r"\A---\s*\n(.*?)\n---", text, re.S)
    result: dict[str, str] = {}
    if not block:
        return result
    for line in block.group(1).splitlines():
        match = re.match(r"([^:]+):\s*(.*)", line)
        if match:
            result[match.group(1).strip()] = match.group(2).strip().strip('"')
    return result


def clean_quote(value: str, limit: int = 420) -> str:
    value = re.sub(r"\s+", " ", value).strip(" -|")
    return value[:limit]


def body_only(text: str) -> str:
    return re.sub(r"\A---.*?---\s*", "", text, count=1, flags=re.S)


def number(value: str | None) -> float | None:
    if not value:
        return None
    value = value.replace(",", "").replace("$", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def fmt(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else str(value)


def parse_table_rows(text: str):
    for line in text.splitlines():
        if not line.strip().startswith("|") or line.count("|") < 2:
            continue
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in line.strip().strip("|").split("|")]
        if cells and not all(re.fullmatch(r"[-: ]+", c or " ") for c in cells):
            yield cells


def all_numbers(text: str) -> list[float]:
    return [float(x.replace(",", "")) for x in re.findall(r"\(?-?\$?\d[\d,]*(?:\.\d+)?\)?", text)]


def base(meta: dict[str, str], rel: str) -> dict[str, str]:
    period = meta.get("period", "")
    year = re.search(r"(20\d{2})", period)
    quarter = re.search(r"\b(Q[1-4])\b", period, re.I)
    return {
        "company": meta.get("company", ""),
        "ticker": meta.get("ticker", ""),
        "published_at": meta.get("published_at", ""),
        "period": period,
        "fiscal_year": year.group(1) if year else "",
        "fiscal_quarter": quarter.group(1).upper() if quarter else "",
        "source_file": rel,
    }


def metric_from_label(label: str) -> str | None:
    mappings = {
        "net sales": "net_sales_usd_m",
        "cost of sales": "cost_of_sales_usd_m",
        "gross profit": "gross_profit_usd_m",
        "selling, general and administrative": "sga_usd_m",
        "depreciation and amortization": "depreciation_amortization_usd_m",
        "operating income": "operating_income_usd_m",
        "interest expense": "interest_expense_usd_m",
        "provision for income taxes": "tax_provision_usd_m",
        "net earnings": "net_earnings_usd_m",
        "basic earnings per share": "basic_eps_usd",
        "diluted earnings per share": "diluted_eps_gaap_usd",
        "basic weighted average common shares": "basic_weighted_avg_shares_m",
        "diluted weighted average common shares": "diluted_weighted_avg_shares_m",
        "cash and cash equivalents": "cash_and_equivalents_usd_m",
        "receivables, net": "receivables_usd_m",
        "merchandise inventories": "merchandise_inventory_usd_m",
        "capital expenditures": "capex_usd_m",
        "net cash provided by operating activities": "operating_cash_flow_usd_m",
        "cash dividends": "dividends_paid_usd_m",
        "long-term debt, excluding current installments": "long_term_debt_usd_m",
    }
    normalized = re.sub(r"\s+", " ", label.lower()).strip()
    for needle, metric in mappings.items():
        if normalized.startswith(needle):
            return metric
    return None


def filing_rows(meta: dict[str, str], rel: str, text: str):
    row = base(meta, rel)
    if "8k" in rel.lower():
        row["document_subtype"] = "8-K"
    elif re.search(r"(?:10-k|q4-10k|fy-10k)", rel.lower()):
        row["document_subtype"] = "10-K"
    else:
        row["document_subtype"] = "10-Q"
    row["period_length_months"] = "12" if "FY" in row["period"] or row["document_subtype"] == "10-K" else "3"
    values = {}
    for cells in parse_table_rows(text):
        if not cells:
            continue
        metric = metric_from_label(cells[0])
        if metric and len(cells) > 1 and metric not in values:
            numeric_cells = [number(cell) for cell in cells[1:] if number(cell) is not None]
            if numeric_cells:
                values[metric] = fmt(numeric_cells[0])
    financial_fields = [
        key for key in OUTPUTS["filing_financials_periodic.csv"]
        if key not in row
    ]
    row.update({key: values.get(key, "") for key in financial_fields})
    # Keep only filings that contain at least one financial statement metric.
    if any(row.get(k) for k in ("net_sales_usd_m", "gross_profit_usd_m", "operating_income_usd_m")):
        yield row


def segment_rows(meta: dict[str, str], rel: str, text: str):
    known = {
        "primary": ("segment", ""),
        "other": ("segment", ""),
        "building materials": ("major_product_line", ""),
        "decor": ("major_product_line", ""),
        "hardlines": ("major_product_line", ""),
        "appliances": ("department", "Decor"),
        "bath": ("department", "Decor"),
        "flooring": ("department", "Decor"),
        "kitchen": ("department", "Decor"),
        "lighting": ("department", "Decor"),
        "paint": ("department", "Decor"),
        "hardware": ("department", "Hardlines"),
        "indoor garden": ("department", "Hardlines"),
        "outdoor garden": ("department", "Hardlines"),
        "power": ("department", "Hardlines"),
        "storage & organization": ("department", "Hardlines"),
        "building materials": ("major_product_line", ""),
        "electrical": ("department", "Building Materials"),
        "lumber": ("department", "Building Materials"),
        "millwork": ("department", "Building Materials"),
        "plumbing": ("department", "Building Materials"),
    }
    headings = list(re.finditer(
        r"^##\s+(?:\d+\.\s*)?SEGMENT REPORTING(?: AND NET SALES)?\s*$",
        text,
        re.I | re.M,
    ))
    if headings:
        start = headings[-1].start()
        segment_text = text[start:]
        next_section = re.search(r"\n##\s+", segment_text[1:])
        if next_section:
            segment_text = segment_text[: next_section.start() + 1]
    else:
        segment_text = ""
    seen = set()
    for cells in parse_table_rows(segment_text):
        if len(cells) < 2:
            continue
        label = re.sub(r"\s+", " ", cells[0].lower()).strip()
        match_name = next((name for name in known if label == name or label.startswith(name + " ")), None)
        if not match_name:
            continue
        values = [number(cell) for cell in cells[1:] if number(cell) is not None]
        if not values:
            continue
        name = match_name.title() if match_name != "storage & organization" else "Storage & Organization"
        dimension_type, parent = known[match_name]
        row = base(meta, rel)
        row.update({
            "dimension_type": dimension_type,
            "dimension_name": name,
            "parent_dimension_name": parent,
            "net_sales_usd_m": fmt(values[0]),
            "net_sales_mix_pct": "",
            "operating_income_usd_m": "",
            "operating_margin_pct": "",
            "yoy_growth_pct": "",
            "notes": clean_quote(" | ".join(cells)),
        })
        identity = tuple(row.get(k, "") for k in ("source_file", "dimension_type", "dimension_name", "net_sales_usd_m"))
        if identity not in seen:
            seen.add(identity)
            yield row


def release_rows(meta: dict[str, str], rel: str, text: str):
    if not ("8k" in rel.lower() or "earnings release" in text.lower() or "fiscal guidance" in text.lower()):
        return
    row = base(meta, rel)
    flat = re.sub(r"\s+", " ", text)
    patterns = {
        "net_sales_usd_m": r"reported sales of \$([\d.]+)\s*billion",
        "net_sales_yoy_pct": r"sales of .*? increase of .*?, or ([\d.]+)%",
        "comparable_sales_total_pct": r"comparable sales .*? increased ([\d.]+)%",
        "comparable_sales_us_pct": r"comparable sales in the U\.S\. increased ([\d.]+)%",
        "fx_comp_impact_bps": r"impacted .*? comparable sales by approximately ([\d.]+) basis points",
        "diluted_eps_gaap_usd": r"or \$([\d.]+) per diluted share",
        "adjusted_diluted_eps_usd": r"Adjusted diluted earnings per share .*? were \$([\d.]+)",
        "stores_count": r"operated a total of ([\d,]+) retail stores",
        "srs_locations_count": r"over ([\d,]+) SRS locations",
        "associates_count": r"employs over ([\d,]+) associates",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, flat, re.I)
        if match:
            value = number(match.group(1))
            if key == "net_sales_usd_m" and value is not None:
                value *= 1000
            row[key] = fmt(value)
    row["net_earnings_usd_m"] = ""
    row["guidance_reaffirmed_flag"] = "true" if re.search(r"reaffirms?|reaffirmed", flat, re.I) else "false"
    row.update({key: row.get(key, "") for key in OUTPUTS["filing_earnings_release_quarterly.csv"]})
    if any(row.get(k) for k in ("net_sales_usd_m", "adjusted_diluted_eps_usd", "comparable_sales_total_pct")):
        yield row


def guidance_rows(meta: dict[str, str], rel: str, text: str):
    if not ("8k" in rel.lower() or "guidance" in text.lower()):
        return
    patterns = [
        ("total_sales_growth_pct", r"Total sales growth of approximately ([\d.]+)% to ([\d.]+)%"),
        ("comparable_sales_growth_pct", r"Comparable sales growth of approximately (?:flat to )?([\d.]+)%"),
        ("gross_margin_pct", r"Gross margin of approximately ([\d.]+)%"),
        ("operating_margin_pct", r"Operating margin of approximately ([\d.]+)% to ([\d.]+)%"),
        ("adjusted_operating_margin_pct", r"Adjusted operating margin of approximately ([\d.]+)% to ([\d.]+)%"),
        ("effective_tax_rate_pct", r"Effective tax rate of approximately ([\d.]+)%"),
        ("net_interest_expense_usd_m", r"Net interest expense of approximately \$([\d.]+) billion"),
        ("capex_pct_sales", r"Capital expenditures of approximately ([\d.]+)% of total sales"),
        ("diluted_eps_growth_pct", r"Diluted earnings-per-share to grow approximately ([\w\s.-]+?) from \$([\d.]+)"),
    ]
    flat = re.sub(r"\s+", " ", text)
    for metric, pattern in patterns:
        for match in re.finditer(pattern, flat, re.I):
            groups = match.groups()
            values = [number(g) for g in groups if number(g) is not None]
            quote = clean_quote(flat[max(0, match.start() - 45):match.end() + 45])
            row = {
                "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                "published_at": meta.get("published_at", ""), "guidance_period": meta.get("period", ""),
                "metric": metric, "value_low": fmt(values[0] * (1000 if "usd_m" in metric else 1)) if values else "",
                "value_high": fmt(values[1] * (1000 if "usd_m" in metric else 1)) if len(values) > 1 else "",
                "unit": "usd_m" if "usd_m" in metric else "%" if "pct" in metric else "",
                "basis": "adjusted" if "adjusted" in metric else "reported",
                "directionality": "range" if len(values) > 1 else "approximately",
                "prior_base_value": fmt(values[-1]) if metric == "diluted_eps_growth_pct" and len(values) > 1 else "",
                "quote": quote, "source_file": rel,
            }
            yield row


def call_rows(meta: dict[str, str], rel: str, text: str):
    is_qna = "qna" in rel.lower()
    output = "call_qna_driver_signals.csv" if is_qna else "call_prepared_remarks_quarterly.csv"
    categories = ["building materials", "power", "hardware", "plumbing", "electrical", "bath",
                  "paint", "kitchens", "patio", "live goods", "roofing", "landscape", "pool",
                  "hvac", "appliances", "storage", "pro", "diy", "srs", "gms"]
    for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body_only(text))):
        if len(sentence) < 35:
            continue
        low = sentence.lower()
        nums = re.findall(r"(?<!\w)(-?\d+(?:\.\d+)?)\s*(%|basis points|billion|million|times)?", sentence, re.I)
        relevant = any(k in low for k in ("sales", "comp", "margin", "ticket", "transaction", "guidance",
                                          "pricing", "tariff", "weather", "inventory", "organic growth",
                                          "capital expenditure", "dividend", "online"))
        if not relevant:
            continue
        category = next((c for c in categories if c in low), "")
        direction = "negative" if any(w in low for w in ("negative", "decrease", "decline", "pressure", "down", "headwind")) else \
            "positive" if any(w in low for w in ("positive", "increase", "growth", "strong", "up", "tailwind")) else "neutral"
        value, unit = (nums[0] if nums else ("", ""))
        if is_qna:
            topic = next((t for t in ("gross_margin", "weather", "tariffs", "fuel", "srs", "gms", "pro", "housing", "guidance")
                          if t.replace("_", " ") in low), "demand")
            yield {
                "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
                "source_file": rel, "question_topic": topic, "driver": clean_quote(sentence, 120),
                "affected_metric": "comparable_sales_total_pct" if "comp" in low or "sales" in low else "gross_margin_pct" if "margin" in low else "",
                "affected_category": category, "impact_value": value, "impact_unit": unit,
                "impact_direction": direction, "time_scope": "future" if any(w in low for w in ("expect", "guide", "will", "year")) else "current",
                "confidence_hint": "high" if nums else "low", "quote": clean_quote(sentence),
            }
        else:
            metric = "comparable_sales" if "comp" in low else "gross_margin" if "margin" in low else \
                "average_ticket" if "ticket" in low else "transactions" if "transaction" in low else "sales"
            yield {
                "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
                "source_file": rel, "speaker_role": "management", "metric": metric,
                "value": value, "value_low": "", "value_high": "", "unit": unit,
                "time_scope": "future" if any(w in low for w in ("expect", "guide", "outlook", "will")) else "quarter",
                "category": category, "directionality": direction, "quote": clean_quote(sentence),
            }


def slide_rows(meta: dict[str, str], rel: str, text: str):
    flat = re.sub(r"\s+", " ", text)
    for match in re.finditer(r"(?P<label>[A-Z][A-Z &/+-]{3,60}?)\s+(?P<value>~?\$?[\d,.]+)\s*(?P<unit>[TB%]|BILLION|MILLION|%)?", flat):
        label = clean_quote(match.group("label"))
        value = number(match.group("value"))
        unit = match.group("unit") or ""
        if value is None or not any(k in label.lower() for k in ("market", "revenue", "ebitda", "share", "branch", "sales", "opportunity", "tam")):
            continue
        quote = clean_quote(flat[max(0, match.start() - 30):match.end() + 40])
        yield {
            "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
            "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
            "source_file": rel, "slide_section": "", "metric": re.sub(r"\s+", "_", label.lower()),
            "value": fmt(value), "unit": unit.lower(), "dimension": "strategy",
            "dimension_name": label, "time_scope": "current", "quote": quote,
        }
    for match in re.finditer(r"(?P<value>~?\$?[\d,.]+)\s*(?P<unit>[TB%]|BILLION|MILLION)?\s+(?P<label>[A-Z][A-Z &/+-]{4,70})", flat):
        label = clean_quote(match.group("label"))
        value = number(match.group("value"))
        if value is None or not any(k in label.lower() for k in ("market", "revenue", "ebitda", "share", "branch", "sales", "opportunity", "tam")):
            continue
        yield {
            "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
            "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
            "source_file": rel, "slide_section": "", "metric": re.sub(r"\s+", "_", label.lower()),
            "value": fmt(value), "unit": (match.group("unit") or "").lower(),
            "dimension": "strategy", "dimension_name": label, "time_scope": "current",
            "quote": clean_quote(flat[max(0, match.start() - 30):match.end() + 40]),
        }
    names = ["Lumber", "Roofing", "Drywall", "Insulation", "Siding", "Paint", "Plumbing",
             "Electrical", "Appliances", "Bath", "Flooring", "Landscape", "Pool", "HVAC",
             "Power", "Hardware", "Storage", "MRO", "Pro", "Consumer", "DIY"]
    for name in names:
        if re.search(rf"\b{re.escape(name)}\b", text, re.I):
            yield {
                "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                "published_at": meta.get("published_at", ""), "source_file": rel,
                "taxonomy_level": "category", "name": name, "parent_name": "",
                "description": "Category or customer type mentioned in slide deck.",
                "examples": "",
            }


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    key_fields = {
        "guidance.csv": ["source_file", "metric", "value_low", "value_high"],
        "filing_earnings_release_quarterly.csv": ["source_file"],
        "filing_financials_periodic.csv": ["source_file"],
    }.get(path.name, fields)
    unique = []
    seen = set()
    for row in rows:
        normalized = tuple(row.get(field, "") for field in key_fields)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append({field: row.get(field, "") for field in fields})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(unique)
    return len(unique)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: extract_company_csvs.py <company-folder>", file=sys.stderr)
        return 2
    folder = Path(sys.argv[1]).resolve()
    output_dir = folder / "csv"
    output_dir.mkdir(exist_ok=True)
    rows = {name: [] for name in OUTPUTS}
    files = sorted(folder.rglob("*.md"))
    for path in files:
        if path.name in ("INDEX.md", "CSV_EXTRACTION_SCHEMA.md", "MASTER_SCHEMA.md"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = metadata(text)
        rel = path.relative_to(folder).as_posix()
        family = path.parent.name
        rows["document_inventory.csv"].append({
            "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
            "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
            "document_type": meta.get("document_type", ""), "document_family": family,
            "source_file": rel, "file_size_bytes": str(path.stat().st_size),
            "has_tables": "true" if "|" in text else "false",
            "has_guidance_terms": "true" if re.search(r"\bguidance|outlook|expect", text, re.I) else "false",
            "has_product_terms": "true" if re.search(r"\bproduct|category|department|segment", text, re.I) else "false",
            "has_numeric_content": "true" if re.search(r"\d", text) else "false",
        })
        if path.parent.name == "filings":
            rows["filing_financials_periodic.csv"].extend(filing_rows(meta, rel, text))
            rows["segment_product_line_sales.csv"].extend(segment_rows(meta, rel, text))
            rows["filing_earnings_release_quarterly.csv"].extend(release_rows(meta, rel, text) or [])
            rows["guidance.csv"].extend(guidance_rows(meta, rel, text) or [])
        elif path.parent.name == "call-transcripts":
            output = "call_qna_driver_signals.csv" if "qna" in rel.lower() else "call_prepared_remarks_quarterly.csv"
            rows[output].extend(call_rows(meta, rel, text) or [])
        elif path.parent.name == "slides":
            strategy = []
            taxonomy = []
            for item in slide_rows(meta, rel, text) or []:
                (taxonomy if "taxonomy_level" in item else strategy).append(item)
            rows["slide_strategy_metrics.csv"].extend(strategy)
            rows["slide_product_taxonomy.csv"].extend(taxonomy)
            for item in taxonomy:
                rows["category_signals.csv"].append({
                    **{k: item.get(k, "") for k in ("company", "ticker", "published_at", "source_file")},
                    "period": meta.get("period", ""), "category": item.get("name", ""),
                    "taxonomy_level": item.get("taxonomy_level", ""), "signal_type": "taxonomy",
                    "value": "", "unit": "", "directionality": "neutral",
                    "quote": item.get("description", ""),
                })
        # Derive category signals from prepared remarks and Q&A as a separate, simple corpus.
        if path.parent.name in ("call-transcripts", "filings"):
            for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body_only(text))):
                category = next((c for c in ("building materials", "roofing", "landscape", "pool", "hvac",
                                              "paint", "power", "patio", "appliances", "plumbing", "pro", "diy")
                                 if c in sentence.lower()), "")
                if category and any(w in sentence.lower() for w in ("positive", "negative", "growth", "sales", "comp", "margin", "pressure")):
                    rows["category_signals.csv"].append({
                        "company": meta.get("company", ""), "ticker": meta.get("ticker", ""),
                        "published_at": meta.get("published_at", ""), "period": meta.get("period", ""),
                        "source_file": rel, "category": category, "taxonomy_level": "category",
                        "signal_type": "narrative", "value": "", "unit": "",
                        "directionality": "negative" if "negative" in sentence.lower() or "pressure" in sentence.lower() else "positive",
                        "quote": clean_quote(sentence),
                    })
    for name, fields in OUTPUTS.items():
        print(f"{name}: {write_csv(output_dir / name, rows[name], fields)} rows")
    print(f"Processed {len(files)} markdown files from {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
