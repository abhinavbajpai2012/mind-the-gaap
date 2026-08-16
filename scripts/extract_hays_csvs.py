#!/usr/bin/env python3
"""Extract Hays forecasting CSVs from the complete markdown corpus.

The extractor is deliberately conservative: numeric observations are retained
with their source sentence or table row, and unavailable values remain blank.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


OUTPUTS = {
    "financial_actuals.csv": [
        "company", "ticker", "published_at", "period", "period_type",
        "source_file", "division", "turnover", "net_fees",
        "operating_profit_pre_exceptional", "operating_profit_reported",
        "conversion_rate_pct", "profit_before_tax", "eps_pence",
        "cash_generated_by_operations", "net_cash_debt", "metric_basis",
        "currency", "unit",
    ],
    "segment_mix_actuals.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "division", "country", "contract_type", "specialism", "sector_type",
        "enterprise_channel", "net_fees", "net_fee_share_pct",
        "reported_growth_pct", "lfl_growth_pct", "operating_profit",
        "conversion_rate_pct",
    ],
    "operational_drivers.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "division", "country", "contract_type", "specialism", "driver_name",
        "driver_value", "driver_unit", "comparison_basis", "direction",
        "quote",
    ],
    "guidance_outlook.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "guidance_metric", "division", "contract_type", "value", "low",
        "high", "unit", "basis", "status", "quote",
    ],
    "qualitative_signals.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "signal_type", "division", "country", "contract_type", "direction",
        "time_horizon", "evidence", "confidence",
    ],
    "taxonomy.csv": [
        "company", "ticker", "published_at", "period", "source_file",
        "taxonomy_level", "category_name", "parent_category",
        "share_of_net_fees_pct", "category_status", "description",
    ],
}

DIVISIONS = [
    "Germany", "United Kingdom & Ireland", "UK&I",
    "Australia & New Zealand", "ANZ", "Rest of World", "RoW", "Group",
]
SPECIALISMS = [
    "Technology", "Accountancy & Finance", "Construction & Property",
    "Engineering", "Office Support", "Sales & Marketing", "Life Sciences",
    "Legal", "Education", "Automotive", "Finance", "IT",
]
COUNTRIES = [
    "Austria", "Australia", "Belgium", "Brazil", "Canada", "Chile",
    "China", "Colombia", "Czech Republic", "Denmark", "France", "Germany",
    "Greater China", "Hungary", "India", "Ireland", "Italy", "Japan",
    "Luxembourg", "Malaysia", "Mexico", "Netherlands", "New Zealand",
    "Poland", "Portugal", "Romania", "Singapore", "Spain", "Sweden",
    "Switzerland", "Thailand", "UAE", "United Arab Emirates", "USA",
    "United States",
]


def metadata(text: str) -> dict[str, str]:
    match = re.search(r"\A---\s*\n(.*?)\n---", text, re.S)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        item = re.match(r"([^:]+):\s*(.*)", line)
        if item:
            result[item.group(1).strip()] = item.group(2).strip().strip('"')
    return result


def body(text: str) -> str:
    return re.sub(r"\A---.*?---\s*", "", text, count=1, flags=re.S)


def clean(value: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", value).strip(" -|")[:limit]


def number(value: str) -> float | None:
    if not value:
        return None
    value = value.replace(",", "").replace("£", "").replace("$", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    parsed = float(match.group())
    return -parsed if value.lstrip().startswith("(") else parsed


def fmt(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if value.is_integer() else str(value)


def base(meta: dict[str, str], rel: str) -> dict[str, str]:
    return {
        "company": meta.get("company", "Hays plc"),
        "ticker": meta.get("ticker", "LSE:HAS"),
        "published_at": meta.get("published_at", ""),
        "period": meta.get("period", ""),
        "source_file": rel,
    }


def sentences(text: str):
    flat = re.sub(r"\s+", " ", body(text))
    for item in re.split(r"(?<=[.!?])\s+", flat):
        if len(item) >= 35:
            yield item.strip()


def values(text: str) -> list[float]:
    return [number(item) for item in re.findall(
        r"\(?-?£?[\d,]+(?:\.\d+)?\)?", text
    ) if number(item) is not None]


def division_in(text: str) -> str:
    low = text.lower()
    for item in DIVISIONS:
        if re.search(rf"\b{re.escape(item.lower())}\b", low):
            return {"UK&I": "United Kingdom & Ireland", "ANZ": "Australia & New Zealand",
                    "RoW": "Rest of World", "Group": "Group"}.get(item, item)
    return ""


def country_in(text: str) -> str:
    low = text.lower()
    return next((item for item in COUNTRIES
                 if re.search(rf"\b{re.escape(item.lower())}\b", low)), "")


def contract_in(text: str) -> str:
    low = text.lower()
    if "temp & contracting" in low or "temp and contracting" in low:
        return "temp_and_contracting"
    if "contracting" in low or "contractor" in low:
        return "contracting"
    if re.search(r"\btemp\b|\btemporary\b", low):
        return "temp"
    if re.search(r"\bperm\b|permanent", low):
        return "permanent"
    if "enterprise solutions" in low or re.search(r"\bmsps?\b|\brpo\b", low):
        return "enterprise_solutions"
    return ""


def specialism_in(text: str) -> str:
    low = text.lower()
    return next((item for item in SPECIALISMS
                 if re.search(rf"\b{re.escape(item.lower())}\b", low)), "")


def direction(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(down|decline|declined|decrease|fell|negative|tough|headwind|challenging|loss)\b", low):
        return "down"
    if re.search(r"\b(up|growth|grew|increase|increased|positive|strong|record|improved)\b", low):
        return "up"
    if re.search(r"\b(stable|flat|in line|resilient)\b", low):
        return "stable"
    return ""


def period_type(period: str) -> str:
    if re.search(r"\bQ[1-4]\b", period, re.I):
        return "quarter"
    if re.search(r"\bH[12]\b|half", period, re.I):
        return "half_year"
    if re.search(r"\bFY\b|full year|annual", period, re.I):
        return "full_year"
    return ""


def metric_value(text: str, labels: tuple[str, ...]) -> str:
    low = text.lower()
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}[^.\n|]{{0,100}}?([(\-]?\d[\d,]*(?:\.\d+)?%?)",
            low,
        )
        if match:
            raw = match.group(1).replace("(", "-").replace(")", "")
            return fmt(number(raw.rstrip("%")))
    return ""


def table_metric(text: str, labels: tuple[str, ...]) -> str:
    """Read the first numeric value from a table row, skipping footnotes."""
    for line in text.splitlines():
        if "|" not in line:
            continue
        cells = [clean(cell) for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        label = re.sub(r"\s+", " ", re.sub(r"\(\d+\)", "", cells[0].lower())).strip()
        if not any(label.startswith(item) for item in labels):
            continue
        for cell in cells[1:]:
            parsed = number(cell)
            if parsed is not None:
                return fmt(parsed)
    return ""


def financial_row(meta: dict[str, str], rel: str, text: str) -> dict[str, str] | None:
    flat = re.sub(r"\s+", " ", body(text))
    row = base(meta, rel)
    row.update({
        "period_type": period_type(meta.get("period", "")),
        "division": "Group",
        "turnover": table_metric(text, ("turnover",)) or metric_value(flat, ("turnover",)),
        "net_fees": table_metric(text, ("net fees", "net fee")) or metric_value(flat, ("net fees", "net fee")),
        "operating_profit_pre_exceptional": table_metric(
            text, ("operating profit before exceptional", "pre-exceptional operating profit")
        ) or metric_value(flat, ("operating profit before exceptional", "pre-exceptional operating profit")),
        "operating_profit_reported": table_metric(text, ("reported operating profit",)) or
                                    metric_value(flat, ("reported operating profit",)),
        "conversion_rate_pct": table_metric(text, ("conversion rate",)) or
                              metric_value(flat, ("conversion rate",)),
        "profit_before_tax": table_metric(text, ("profit before tax",)) or
                            metric_value(flat, ("profit before tax",)),
        "eps_pence": table_metric(text, ("basic earnings per share", "eps")) or
                     metric_value(flat, ("basic earnings per share", "eps")),
        "cash_generated_by_operations": table_metric(text, ("cash generated by operations",)) or
                                       metric_value(flat, ("cash generated by operations",)),
        "net_cash_debt": table_metric(text, ("net cash", "net debt")) or
                        metric_value(flat, ("net cash", "net debt")),
        "metric_basis": "pre_exceptional" if "pre-exceptional" in flat.lower() else "reported",
        "currency": "GBP",
        "unit": "gbp_millions",
    })
    if not any(row[key] for key in ("turnover", "net_fees",
                                    "operating_profit_pre_exceptional",
                                    "profit_before_tax")):
        return None
    return row


def segment_rows(meta: dict[str, str], rel: str, text: str):
    patterns = [
        (r"\b(?P<dimension>Germany|United Kingdom\s*&\s*Ireland|UK&I|Australia\s*&\s*New Zealand|ANZ|Rest of World|RoW)\b"
         r".{0,120}?(?:net fees|fees).{0,80}?(?P<growth>\(?-?\d+(?:\.\d+)?\)%?)",
         "division"),
        (r"(?P<dimension>Technology|Engineering|Accountancy\s*&\s*Finance|Construction\s*&\s*Property|"
         r"Office Support|Sales\s*&\s*Marketing|Life Sciences|Automotive).{0,80}?"
         r"(?:net fees|fees).{0,60}?(?P<growth>\(?-?\d+(?:\.\d+)?\)%?)", "specialism"),
    ]
    seen = set()
    for sentence in sentences(text):
        for pattern, level in patterns:
            match = re.search(pattern, sentence, re.I)
            if not match:
                continue
            name = clean(match.group("dimension")).replace("UK&I", "United Kingdom & Ireland")
            if name == "RoW":
                name = "Rest of World"
            key = (rel, level, name, match.group("growth"))
            if key in seen:
                continue
            seen.add(key)
            row = base(meta, rel)
            row.update({
                "division": name if level == "division" else division_in(sentence),
                "country": country_in(sentence),
                "contract_type": contract_in(sentence),
                "specialism": name if level == "specialism" else specialism_in(sentence),
                "sector_type": "public" if "public sector" in sentence.lower() else
                               "private" if "private sector" in sentence.lower() else "",
                "enterprise_channel": "msp" if re.search(r"\bMSP\b", sentence) else
                                      "rpo" if re.search(r"\bRPO\b", sentence) else "",
                "net_fees": metric_value(sentence, ("net fees", "fees")),
                "net_fee_share_pct": metric_value(sentence, ("of group net fees", "of net fees")),
                "reported_growth_pct": match.group("growth").replace("(", "-").replace(")", "").rstrip("%"),
                "lfl_growth_pct": match.group("growth").replace("(", "-").replace(")", "").rstrip("%"),
                "operating_profit": metric_value(sentence, ("operating profit",)),
                "conversion_rate_pct": metric_value(sentence, ("conversion rate",)),
            })
            yield row


DRIVER_PATTERNS = {
    "volume": r"\bvolume[s]?\b|\bplacements?\b|\bon assignment\b",
    "average_hours_worked": r"average hours worked|hours worked",
    "average_perm_fee": r"average perm(?:anent)? fee",
    "average_temp_fee": r"average (?:temp|contractor) fee",
    "underlying_temp_margin": r"underlying temp margin",
    "consultant_headcount": r"consultant headcount|consultants",
    "non_consultant_headcount": r"non-consultant headcount",
    "office_count": r"\boffices?\b",
    "net_fees_per_consultant": r"net fee productivity|net fees per consultant",
    "job_inflow": r"job inflow|job flow",
    "time_to_hire": r"time[- ]to[- ]hire",
    "new_order_intake": r"new order intake|pipeline|client wins",
    "candidate_salary": r"candidate salary|salary growth",
}


def driver_rows(meta: dict[str, str], rel: str, text: str):
    for sentence in sentences(text):
        low = sentence.lower()
        for driver, pattern in DRIVER_PATTERNS.items():
            if not re.search(pattern, low):
                continue
            numeric = re.search(r"(?<!\w)(-?\d+(?:\.\d+)?)\s*(%|bps|m|million|hours|days)?", sentence, re.I)
            row = base(meta, rel)
            row.update({
                "division": division_in(sentence),
                "country": country_in(sentence),
                "contract_type": contract_in(sentence),
                "specialism": specialism_in(sentence),
                "driver_name": driver,
                "driver_value": numeric.group(1) if numeric else "",
                "driver_unit": numeric.group(2).lower() if numeric and numeric.group(2) else "",
                "comparison_basis": "yoy" if re.search(r"year[- ]on[- ]year|yoy|prior year", low) else
                                   "sequential" if "sequential" in low else "actual",
                "direction": direction(sentence),
                "quote": clean(sentence),
            })
            yield row


GUIDANCE_TERMS = ("expect", "outlook", "guidance", "forecast", "target", "will ",
                  "anticipate", "remain broadly", "pipeline", "on track")


def guidance_rows(meta: dict[str, str], rel: str, text: str):
    for sentence in sentences(text):
        low = sentence.lower()
        if not any(term in low for term in GUIDANCE_TERMS):
            continue
        metric = next((name for name, pattern in [
            ("pre_exceptional_operating_profit", "operating profit"),
            ("net_fees", "net fees"),
            ("capex", "capex|capital expenditure"),
            ("effective_tax_rate", "effective tax rate|etr"),
            ("structural_cost_savings", "structural savings|cost savings"),
            ("net_finance_charge", "finance charge"),
            ("temp_outlook", "temp|contracting"),
            ("perm_outlook", "perm|permanent"),
            ("consultant_headcount", "headcount capacity|headcount"),
        ] if re.search(pattern, low)), "")
        if not metric:
            continue
        nums = re.findall(r"(?<!\w)(-?\d+(?:\.\d+)?)\s*(%|m|million|pence|p)?", sentence, re.I)
        parsed = [(item[0], item[1].lower()) for item in nums if item[0]]
        row = base(meta, rel)
        row.update({
            "guidance_metric": metric,
            "division": division_in(sentence),
            "contract_type": contract_in(sentence),
            "value": parsed[0][0] if parsed else "",
            "low": parsed[0][0] if len(parsed) == 2 else "",
            "high": parsed[1][0] if len(parsed) == 2 else "",
            "unit": parsed[0][1] if parsed else "qualitative",
            "basis": "company_expectation" if any(x in low for x in ("expect", "anticipate", "on track")) else "narrative",
            "status": "qualitative" if not parsed else "new",
            "quote": clean(sentence),
        })
        yield row


SIGNAL_TYPES = {
    "client_confidence": ("client confidence", "client decision"),
    "candidate_confidence": ("candidate confidence", "candidate decision"),
    "demand": ("job inflow", "job flow", "activity", "demand", "conversion"),
    "macro": ("macroeconomic", "macro", "economic uncertainty", "fiscal stimulus", "working days", "fx"),
    "pricing": ("fee", "pricing", "salary", "day rate"),
    "cost": ("cost savings", "cost base", "restructur", "office closure", "headcount"),
    "capacity": ("consultant capacity", "productivity", "consultant headcount"),
    "pipeline": ("pipeline", "client win", "contract win", "order intake"),
    "portfolio": ("portfolio", "disposed", "exited", "country review", "core countries"),
    "technology": ("digital platform", "ai ", "technology transformation"),
    "capital_allocation": ("dividend", "buyback", "net cash", "capex"),
}


def qualitative_rows(meta: dict[str, str], rel: str, text: str):
    for sentence in sentences(text):
        low = sentence.lower()
        signal = next((name for name, terms in SIGNAL_TYPES.items()
                       if any(term in low for term in terms)), "")
        if not signal:
            continue
        row = base(meta, rel)
        row.update({
            "signal_type": signal,
            "division": division_in(sentence),
            "country": country_in(sentence),
            "contract_type": contract_in(sentence),
            "direction": "negative" if direction(sentence) == "down" else
                         "positive" if direction(sentence) == "up" else
                         "stable" if direction(sentence) == "stable" else "uncertain",
            "time_horizon": "long_term" if re.search(r"long[- ]term|structural|over time", low) else
                            "next_quarter" if re.search(r"next quarter|q[1-4]", low) else
                            "full_year" if re.search(r"full year|fy\d{2}", low) else "current_quarter",
            "evidence": clean(sentence),
            "confidence": "high" if meta.get("document_type") == "FILING" else
                          "medium" if meta.get("document_type") == "SLIDE" else "low",
        })
        yield row


def taxonomy_rows(meta: dict[str, str], rel: str, text: str):
    found = []
    for level, items in (("division", DIVISIONS), ("country", COUNTRIES),
                         ("specialism", SPECIALISMS)):
        for item in items:
            if re.search(rf"\b{re.escape(item)}\b", text, re.I):
                found.append((level, item, "", ""))
    for item, level in (("Temp & Contracting", "contract_type"),
                        ("Permanent", "contract_type"), ("Temp", "contract_type"),
                        ("Contracting", "contract_type"), ("MSP", "enterprise_channel"),
                        ("RPO", "enterprise_channel"), ("Project Services", "enterprise_channel"),
                        ("Public sector", "sector_type"), ("Private sector", "sector_type")):
        if re.search(rf"\b{re.escape(item)}\b", text, re.I):
            found.append((level, item, "", ""))
    seen = set()
    for level, name, parent, status in found:
        key = (rel, level, name.lower())
        if key in seen:
            continue
        seen.add(key)
        yield {
            **base(meta, rel),
            "taxonomy_level": level,
            "category_name": name,
            "parent_category": parent,
            "share_of_net_fees_pct": "",
            "category_status": status or ("focus" if "focus" in text.lower() and name.lower() in text.lower() else "not_stated"),
            "description": "Disclosed Hays taxonomy value mentioned in the source document.",
        }


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]):
    seen = set()
    unique = []
    for row in rows:
        normalized = tuple(row.get(field, "") for field in fields)
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
        print("Usage: extract_hays_csvs.py <company-folder>", file=sys.stderr)
        return 2
    folder = Path(sys.argv[1]).resolve()
    output_dir = folder / "csv"
    output_dir.mkdir(exist_ok=True)
    rows = {name: [] for name in OUTPUTS}
    files = sorted(folder.rglob("*.md"))
    processed = 0
    for path in files:
        if path.name in {"INDEX.md", "MASTER_SCHEMA.md", "CSV_EXTRACTION_SCHEMA.md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = metadata(text)
        rel = path.relative_to(folder).as_posix()
        processed += 1
        if path.parent.name == "filings":
            actual = financial_row(meta, rel, text)
            if actual:
                rows["financial_actuals.csv"].append(actual)
            rows["segment_mix_actuals.csv"].extend(segment_rows(meta, rel, text))
        if path.parent.name in {"filings", "call-transcripts", "slides"}:
            rows["operational_drivers.csv"].extend(driver_rows(meta, rel, text))
            rows["guidance_outlook.csv"].extend(guidance_rows(meta, rel, text))
            rows["qualitative_signals.csv"].extend(qualitative_rows(meta, rel, text))
            rows["taxonomy.csv"].extend(taxonomy_rows(meta, rel, text))
    for name, fields in OUTPUTS.items():
        print(f"{name}: {write_csv(output_dir / name, rows[name], fields)} rows")
    print(f"Processed {processed} markdown files from {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
