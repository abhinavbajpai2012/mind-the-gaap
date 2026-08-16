---
name: company-master-schema
description: Create a firm-specific MASTER_SCHEMA.md from a company offline-data folder containing filings, call transcripts, slides, or similar markdown documents. Use when the user asks to inspect a company folder, infer extractable forecasting fields, design CSV schemas, identify products/categories, or create a master schema for quarterly financial prediction.
---

# Company Master Schema

## Goal

Given a folder for one public company, inspect its markdown documents and create a firm-specific `MASTER_SCHEMA.md` that explains what can be extracted, which product/category structure is useful, and which CSV schemas should be produced for forecasting quarterly results.

## Inputs

The user should provide a company folder path such as:

```text
challenge/offline-data/home-depot
```

If no output filename is specified, write:

```text
<company-folder>/MASTER_SCHEMA.md
```

## Workflow

1. Read the company folder's `INDEX.md` if present.
2. Identify document families from directories and front matter, such as `filings`, `call-transcripts`, `slides`, investor presentations, earnings releases, annual reports, quarterly reports, proxy filings, or event transcripts.
3. Sample at least one recent and one older representative file from each major document family when available. Cover SEC filings, earnings calls, and slides if the folder contains them.
4. For each document family, extract:
   - Clean historical financial metrics.
   - Guidance metrics.
   - Product, segment, geography, customer, and channel categories.
   - Price, volume, ticket, transaction, mix, cost, margin, and operating drivers.
   - Qualitative forward-looking signals.
   - Source-specific caveats.
5. Infer the firm's product/category taxonomy. Prefer public reporting categories over SKU-level detail unless documents actually provide product-level price or volume.
6. Map the user's target prediction fields to the firm:
   - Directly disclosed fields.
   - Derivable fields.
   - Fields that use a different company-specific label.
   - Fields that are not applicable.
7. Propose practical CSV schemas. Include row grain, column names, types, and descriptions.
8. Write `MASTER_SCHEMA.md` using the template in [MASTER_SCHEMA_TEMPLATE.md](MASTER_SCHEMA_TEMPLATE.md).
9. After writing, read the file back and run diagnostics on it if available.

## Sampling Guidance

Prioritize high-signal documents:

- Earnings releases and 8-Ks for current-quarter actuals and guidance.
- 10-Qs and 10-Ks for structured financial statements, segment/product tables, definitions, and historical series.
- Prepared remarks for category performance, management framing, and guidance rationale.
- Q&A transcripts for analyst-tested assumptions, risks, pricing, volume, cost, and margin drivers.
- Slide decks for product taxonomy, TAM, strategy, acquisition metrics, and platform capabilities.
- Proxy filings only if compensation metrics, ROIC, operating income, or capital allocation targets are relevant.

## Forecasting Feature Families

Consider these feature families even when the user's first idea is only price, volume, and margin:

- Revenue and sales growth.
- Comparable sales, same-store sales, organic growth, or equivalent volume proxies.
- Transaction count, average ticket, units, deliveries, production volume, shipments, backlog, bookings, AUM, users, or industry-specific operating volumes.
- Price realization, tariff/pricing actions, commodity prices, fee rates, discounting, or revenue yield.
- Gross margin, operating margin, mix, cost inflation, freight, fuel, labor, raw materials, credit losses, claims, or technology costs.
- Segment, product line, geography, customer type, channel, or platform mix.
- Inventory, backlog, capacity, store/branch count, utilization, pipeline, production assets, or other supply indicators.
- Macro variables management references: housing, rates, consumer spending, commodity cycles, crop prices, industrial production, employment, FX, regulation, or weather.
- Capital allocation: capex, buybacks, dividends, debt, interest expense, acquisitions, and dilution/accretion.

## Output Rules

- Keep the generated schema firm-specific; do not force Home Depot fields onto another company.
- Use normalized snake_case column names for CSV schemas.
- Include `source_file`, `published_at`, `period`, `company`, and `ticker` in every proposed CSV unless there is a clear reason not to.
- Preserve auditability by including a short `quote` or `evidence` column in qualitative-driver CSVs.
- Separate actuals, guidance, product/category taxonomy, and qualitative driver signals into different CSVs when they have different row grains.
- Use `null` for unavailable values rather than inventing estimates.
- State when a requested field is not applicable to the company.
- Do not create parser code unless the user explicitly asks for extraction implementation.
