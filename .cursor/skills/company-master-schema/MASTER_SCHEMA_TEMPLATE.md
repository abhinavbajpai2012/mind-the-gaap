# [Company Name] Master Extraction Schema

This schema is based on sampled markdown documents in `[company-folder]`. It is intended to guide CSV extraction for forecasting quarterly reported metrics.

## Scope

- Company:
- Ticker:
- Folder:
- Documents sampled:
- Document families found:
- Coverage period:

## Executive Summary

Summarize the firm's reporting shape in 3-6 bullets:

- Primary target metrics that are directly available.
- Most useful product, segment, or customer categories.
- Best document types for historical actuals.
- Best document types for guidance and forward-looking drivers.
- Key limitations or caveats.

## Document Type Inventory

| Document type | Best use in forecasting | Extractable parameters | Example company-specific signals | Suggested CSV |
|---|---|---|---|---|
| [type] | [use] | [fields] | [examples] | `[csv_name].csv` |

## Product, Segment, And Category Taxonomy

Explain whether the company should be modeled by product, product category, segment, geography, customer type, channel, or another industry-specific unit.

| Level | Category | Examples or subcategories | Typical source | Forecasting use |
|---|---|---|---|---|
| [level] | [category] | [examples] | [source] | [use] |

## Target Metric Mapping

Map the user's target metrics plus firm-specific target metrics discovered during exploration.

| Target field | Company availability | Normalized column | Source document types | Notes |
|---|---|---|---|---|
| [field] | Direct / Derivable / Different label / Not applicable | `[column_name]` | [sources] | [notes] |

## Recommended CSV Schemas

Create one section per CSV. Use separate CSVs when row grain differs.

### `[csv_name].csv`

Row grain: [one row per company-period / company-period-segment / source-driver / guidance metric / product category]

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `[metric_or_dimension]` | [type] | [description] |

## Forecasting Feature Families

| Feature family | Suggested variables | Source document types | Why it matters |
|---|---|---|---|
| [family] | [variables] | [sources] | [reason] |

## Extraction Priority

1. [Highest priority document type and why.]
2. [Second priority document type and why.]
3. [Third priority document type and why.]

## Caveats

- Note metrics that are inconsistently disclosed.
- Note company-specific accounting terminology.
- Note document types that provide narrative but not structured numbers.
- Note where product-level price or volume is unavailable and which proxies should be used.
