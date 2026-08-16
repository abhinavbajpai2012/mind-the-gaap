# Hays plc Master Extraction Schema

This schema is based on sampled markdown documents in `challenge/offline-data/hays`. It is intended to guide CSV extraction for forecasting Hays plc quarterly trading updates and interim/full-year reported metrics.

## Scope

- Company: Hays plc
- Ticker: LSE:HAS
- Folder: `challenge/offline-data/hays`
- Documents sampled:
  - `INDEX.md`
  - Recent filing: `filings/2026-02-27__has-ln-20260227-h1-8k__642921.md`
  - Recent quarterly filing: `filings/2026-07-10__has-ln-20260710-filing-2__1572799.md`
  - Older annual filing: `filings/2015-09-18__has-ln-20150918-h2-8k__671208.md`
  - Recent call Q&A: `call-transcripts/2026-07-10__has-ln-20260710-call-qna__1573114.md`
  - Older call: `call-transcripts/2019-01-15__has-ln-20190115-call-pres__546311.md`
  - Recent presentation: `slides/2026-02-27__has-ln-20260227-slide__643289.md`
  - Older presentation: `slides/2019-02-21__has-ln-20190221-slide__545625.md`
- Document families found: 123 filings, 100 call transcripts, and 16 slide documents, plus the index.
- Coverage period: 2015-09-18 to 2026-08-03

## Executive Summary

- The primary reported operating metric is **net fees**, defined as turnover less remuneration of temporary workers and other recruitment agencies. Turnover is available but is less useful for operating forecasting.
- The core business dimensions are region/division, contract type (`temp`, `contracting`, `permanent`), country, professional specialism, sector/customer type, and Enterprise Solutions channel.
- Filings and results releases are best for actual net fees, operating profit, conversion rate, headcount, offices, cash, and balance-sheet metrics. Quarterly trading statements are especially important because the company provides regular Q1-Q4 updates.
- Prepared remarks and slide decks provide volume, average hours, fee/rate, mix, productivity, and country/specialism detail. Q&A provides the best forward-looking evidence on job flow, time-to-hire, client confidence, market recovery, and cost actions.
- Hays generally reports growth as like-for-like (LFL) year-on-year organic growth at constant currency. Country exits, disposals, working days, FX, and exceptional items must be retained as separate fields rather than silently mixed into reported growth.

## Document Type Inventory

| Document type | Best use in forecasting | Extractable parameters | Example company-specific signals | Suggested CSV |
|---|---|---|---|---|
| Quarterly trading statement / filing | Quarterly actuals and near-term outlook | Net fee growth, LFL and actual growth, Temp & Contracting, Perm, regional/country results, volumes, average hours, average fee, guidance | Q4 2026 Group net fees down 5% LFL; Temp & Contracting down 3%; Perm down 7%; FY26 pre-exceptional operating profit expected at top of £37m-£46m consensus range | `financial_actuals.csv`, `segment_mix_actuals.csv`, `guidance_outlook.csv` |
| Half-year / full-year report | Structured financial statements, definitions, annual history, cash and balance sheet | Net fees, turnover, operating profit, conversion rate, EPS, cash flow, net cash/debt, tax, capex, dividends, exceptional items | H1 2026 net fees £453.3m, pre-exceptional operating profit £20.1m, conversion rate 4.4%, net cash £40.3m | `financial_actuals.csv` |
| Prepared call remarks | Management framing and operating drivers | Volumes, hours worked, fee/rate, mix, headcount, productivity, country and specialism commentary | Stable Temp & Contracting placements; lower German hours; higher consultant net-fee productivity | `operational_drivers.csv`, `qualitative_signals.csv` |
| Call Q&A | Analyst-tested assumptions and risks | Job inflow, conversion, time-to-hire, client confidence, macro sensitivity, pipeline, cost savings, portfolio actions | Perm decision-making lengthened; Enterprise pipeline and MSP wins expected to support H2; Germany fiscal stimulus not yet visible | `guidance_outlook.csv`, `qualitative_signals.csv` |
| Slide presentation | Historical series, mix, taxonomy, strategy KPIs | Regional tables, specialism/country mix, consultant and office counts, conversion, productivity, Enterprise Solutions, strategic targets | H1 2026 net fees were 64% Temp & Contracting and 36% Perm; Technology was 26% of Group net fees | `segment_mix_actuals.csv`, `taxonomy.csv`, `operational_drivers.csv` |
| Annual report | Long-run business model, accounting definitions, risk and market context | Regions, countries, specialisms, contract types, market backdrop, cash returns, KPI definitions | FY15 grouped 33 country businesses into Asia Pacific, Continental Europe & RoW, and UK & Ireland | `taxonomy.csv`, `qualitative_signals.csv` |

## Product, Segment, And Category Taxonomy

Hays is a staffing and recruitment services company, so “product” should not be modeled as a physical SKU. The preferred grain is `period × division/region × country × contract_type`, with optional `specialism`, `sector_type`, and `enterprise_channel` dimensions. Use only dimensions explicitly disclosed in the source; do not infer country or specialism values for an aggregate row.

| Level | Category | Examples or subcategories | Typical source | Forecasting use |
|---|---|---|---|---|
| Group | Service mix | Temp & Contracting; Permanent | Trading statements, reports, slides | Main volume/price/mix split |
| Division | Geographic reporting division | Germany; United Kingdom & Ireland; Australia & New Zealand; Rest of World | Trading statements, reports, slides | Primary regional forecast grain |
| Country | Individual operating market | France, USA, Spain, Japan, China, Poland, Italy, Switzerland, Canada, etc. | Reports, slides, calls | Identify growth markets, exits, and mix |
| Contract type | Staffing/recruitment service | Temp, Contracting/Flex, Permanent, Statement of Work / Project Services | Reports, slides, calls | Temp volume and hours versus Perm placements |
| Specialism | Professional job category | Technology, Accountancy & Finance, Construction & Property, Engineering, Office Support, Sales & Marketing, Life Sciences, Legal, Education, Automotive | Reports, slides, calls | Mix, structural growth, and sector cyclicality |
| Sector/customer | Client market | Public sector; private sector; industry sectors such as infrastructure, energy, automotive, resources/mining | Trading statements, calls | Demand and macro sensitivity |
| Channel | Enterprise/recruitment solution | MSP, RPO, PSL, Project Services, onboarding, compliance, assessment, workforce planning | Reports, slides, calls | Recurring/resilient fee pipeline and contract wins |
| Operating capacity | Delivery network | Consultant headcount, non-consultant headcount, offices, consultant net-fee productivity | Reports, slides | Capacity, cost base, and operating leverage |

## Target Metric Mapping

| Target field | Company availability | Normalized column | Source document types | Notes |
|---|---|---|---|---|
| Revenue | Different label / Direct | `turnover` | Reports, filings | Reported gross turnover includes temporary-worker remuneration; do not substitute for net fees. |
| Net revenue | Direct | `net_fees` | Trading statements, reports, slides | Hays’ principal revenue-like operating metric. |
| Price | Derivable / Different label | `average_perm_fee`, `average_temp_fee`, `average_contractor_fee`, `fee_rate_growth` | Reports, slides, calls | Explicitly disclosed in some regions; otherwise derive only when component values support it. |
| Volume | Direct / Different label | `temp_volume_growth`, `perm_volume_growth`, `contractor_count`, `placements` | Trading statements, reports, calls | Temp volume, Perm volume, placements, and temps/contractors on assignment are not interchangeable. |
| Hours | Direct | `average_hours_worked`, `hours_growth` | Trading statements, reports, calls | Especially important for Germany Temp; retain as a separate driver. |
| Gross margin | Different label | `underlying_temp_margin` | Reports, slides | Defined as Temp net fees divided by Temp gross revenue for qualifying Temp placements; not a Group gross margin. |
| Operating margin | Direct / Different label | `conversion_rate` | Reports, slides | Pre-exceptional operating profit as a percentage of net fees. |
| Operating profit | Direct | `operating_profit_pre_exceptional`, `operating_profit_reported` | Reports, filings, slides | Keep exceptional items separate. |
| Segment revenue | Direct | `net_fees` with `division`, `country`, or `specialism` | Trading statements, reports, slides | Usually disclosed as net fees and growth, not turnover. |
| Growth | Direct | `reported_growth_pct`, `lfl_growth_pct` | All results documents | Preserve actual and LFL growth separately. |
| Consultant productivity | Direct / Derivable | `net_fees_per_consultant`, `productivity_growth_pct` | Reports, slides, calls | Often reported directly; can be derived from net fees and consultant headcount. |
| Guidance | Direct / Narrative | `guidance_metric`, `guidance_value`, `guidance_low`, `guidance_high` | Trading statements, calls, slides | May be a range, consensus position, capex, ETR, savings, or qualitative outlook. |
| Transaction count / average ticket | Not applicable | `null` | — | Hays does not report retail-style transactions or tickets. Use recruitment volumes, placements, hours, and average fee instead. |

## Recommended CSV Schemas

### `financial_actuals.csv`

Row grain: one row per company-period and, when disclosed, company-period-division.

| Column | Type | Description |
|---|---|---|
| `company` | string | `Hays plc`. |
| `ticker` | string | `LSE:HAS`. |
| `published_at` | date | Source publication date. |
| `period` | string | Fiscal period such as `Q4 2026`, `H1 2026`, or `FY 2025`. |
| `period_type` | string | `quarter`, `half_year`, or `full_year`. |
| `source_file` | string | Relative source markdown path. |
| `division` | string/null | `Germany`, `United Kingdom & Ireland`, `Australia & New Zealand`, `Rest of World`, or `Group`. |
| `turnover` | number/null | Reported turnover, normally in GBP millions. |
| `net_fees` | number/null | Net fees, normally in GBP millions. |
| `operating_profit_pre_exceptional` | number/null | Pre-exceptional operating profit, normally in GBP millions. |
| `operating_profit_reported` | number/null | Reported operating profit after exceptional items. |
| `conversion_rate_pct` | number/null | Pre-exceptional operating profit divided by net fees. |
| `profit_before_tax` | number/null | Pre- or post-exceptional PBT, identified by `metric_basis`. |
| `eps_pence` | number/null | Basic EPS; retain pre-exceptional versus reported basis. |
| `cash_generated_by_operations` | number/null | Cash generated by operations, normally in GBP millions. |
| `net_cash_debt` | number/null | Net cash positive / net debt negative, normally in GBP millions. |
| `metric_basis` | string/null | `reported`, `pre_exceptional`, `actual`, or `lfl`. |
| `currency` | string | Usually `GBP`. |
| `unit` | string | Usually `gbp_millions`, `percent`, or `pence`. |

### `segment_mix_actuals.csv`

Row grain: one row per company-period-division-country-contract-type-specialism or the highest disclosed dimensional grain.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source publication date. |
| `period` | string | Fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `division` | string/null | Hays reporting division. |
| `country` | string/null | Disclosed country or country grouping. |
| `contract_type` | string/null | `temp`, `contracting`, `temp_and_contracting`, `permanent`, or `enterprise_solutions`. |
| `specialism` | string/null | Disclosed professional specialism. |
| `sector_type` | string/null | Public/private sector or disclosed industry. |
| `enterprise_channel` | string/null | `msp`, `rpo`, `psl`, `project_services`, or other disclosed channel. |
| `net_fees` | number/null | Net fees for the row, normally GBP millions. |
| `net_fee_share_pct` | number/null | Share of division or Group net fees. |
| `reported_growth_pct` | number/null | Actual year-on-year growth. |
| `lfl_growth_pct` | number/null | Like-for-like constant-currency growth. |
| `operating_profit` | number/null | Segment operating profit where disclosed. |
| `conversion_rate_pct` | number/null | Segment operating profit as a percentage of net fees. |

### `operational_drivers.csv`

Row grain: one row per company-period-dimension-driver observation.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source publication date. |
| `period` | string | Fiscal period or current-trading reference period. |
| `source_file` | string | Relative source markdown path. |
| `division` | string/null | Division or Group. |
| `country` | string/null | Country when disclosed. |
| `contract_type` | string/null | Temp, Contracting, Perm, or Enterprise channel. |
| `specialism` | string/null | Job category when disclosed. |
| `driver_name` | string | Normalized driver such as `volume`, `average_hours_worked`, `average_perm_fee`, `average_temp_fee`, `underlying_temp_margin`, `consultant_headcount`, `office_count`, `net_fees_per_consultant`, `job_inflow`, `time_to_hire`, or `new_order_intake`. |
| `driver_value` | number/null | Numeric value. |
| `driver_unit` | string/null | `percent`, `percentage_points`, `count`, `gbp_millions`, `gbp`, `hours`, `days`, or other explicit unit. |
| `comparison_basis` | string/null | `yoy`, `sequential`, `actual`, `lfl`, or `period_end`. |
| `direction` | string/null | `up`, `down`, `stable`, or `mixed`. |
| `quote` | string/null | Short supporting text for auditability. |

### `guidance_outlook.csv`

Row grain: one row per company-period-guidance metric or outlook statement.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source publication date. |
| `period` | string | Target period of the guidance. |
| `source_file` | string | Relative source markdown path. |
| `guidance_metric` | string | Example: `pre_exceptional_operating_profit`, `capex`, `effective_tax_rate`, `structural_cost_savings`, `net_finance_charge`, `temp_outlook`, or `perm_outlook`. |
| `division` | string/null | Relevant division, if any. |
| `contract_type` | string/null | Relevant service type, if any. |
| `value` | number/null | Point estimate. |
| `low` | number/null | Lower bound of a range. |
| `high` | number/null | Upper bound of a range. |
| `unit` | string/null | GBP millions, percent, percentage points, pence, or qualitative. |
| `basis` | string/null | Consensus, company expectation, LFL, reported, or other stated basis. |
| `status` | string | `maintained`, `raised`, `lowered`, `new`, or `qualitative`. |
| `quote` | string/null | Short supporting evidence. |

### `qualitative_signals.csv`

Row grain: one row per source-driver signal.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source publication date. |
| `period` | string | Relevant period. |
| `source_file` | string | Relative source markdown path. |
| `signal_type` | string | `demand`, `client_confidence`, `candidate_confidence`, `macro`, `pricing`, `cost`, `capacity`, `pipeline`, `portfolio`, `technology`, or `capital_allocation`. |
| `division` | string/null | Relevant division. |
| `country` | string/null | Relevant country. |
| `contract_type` | string/null | Relevant service type. |
| `direction` | string | `positive`, `negative`, `stable`, `uncertain`, or `mixed`. |
| `time_horizon` | string/null | `current_quarter`, `next_quarter`, `half_year`, `full_year`, or `long_term`. |
| `evidence` | string | Short quote or faithful paraphrase from the source. |
| `confidence` | string/null | `high`, `medium`, or `low`, based on whether the statement is an actual, explicit outlook, or management commentary. |

### `taxonomy.csv`

Row grain: one row per disclosed taxonomy value and source observation.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source publication date. |
| `period` | string/null | Period when the taxonomy was disclosed. |
| `source_file` | string | Relative source markdown path. |
| `taxonomy_level` | string | `division`, `country`, `contract_type`, `specialism`, `sector_type`, or `enterprise_channel`. |
| `category_name` | string | Normalized category value. |
| `parent_category` | string/null | Parent division or grouping. |
| `share_of_net_fees_pct` | number/null | Disclosed share, if available. |
| `category_status` | string/null | `key`, `focus`, `emerging`, `exited`, or `not_stated`. |
| `description` | string/null | Definition or source explanation. |

## Forecasting Feature Families

| Feature family | Suggested variables | Source document types | Why it matters |
|---|---|---|---|
| Net fee growth | `net_fees`, `lfl_growth_pct`, `reported_growth_pct` | Filings, trading statements, slides | Primary Hays operating outcome. |
| Volume and activity | Temp volume, Perm volume, placements, job inflow, conversion, time-to-hire | Trading statements, calls | Separates demand from fee/rate effects. |
| Price and rate realization | Average Perm fee, average Temp/Contractor fee, candidate salary, fee-rate growth | Reports, calls, slides | Captures salary inflation, role mix, and pricing. |
| Hours and utilization | Average hours worked, temps/contractors on assignment, return-to-work trends | Trading statements, calls | Critical for Germany and Temp economics. |
| Service mix | Temp & Contracting share, Perm share, MSP/RPO/Project Services | Reports, slides, calls | Temp is generally more resilient; mix affects fee and margin profile. |
| Geographic and specialism mix | Division, country, Technology, Engineering, Construction & Property, A&F, etc. | Filings, slides, calls | Hays’ growth and cyclicality vary materially by market and specialism. |
| Profitability and operating leverage | Operating profit, conversion rate, underlying Temp margin, consultant productivity, headcount | Reports, slides | Links fee recovery and cost discipline to profit drop-through. |
| Cost structure | Structural savings, payroll, office closures, non-consultant headcount, exceptional charges | Reports, calls, slides | Explains profit performance when net fees decline. |
| Enterprise pipeline | MSP/RPO fees, wins, extensions, contract losses, new order intake | Calls, reports, slides | Enterprise Solutions is a more resilient, forward-looking fee stream. |
| Balance sheet and capital allocation | Net cash/debt, cash conversion, capex, finance charge, tax rate, dividends, buybacks | Reports, filings, slides | Relevant to EPS, cash returns, and financial risk. |
| Macro and market conditions | Client confidence, candidate confidence, working days, FX, rates, sector demand, fiscal stimulus | Calls, trading statements | Management explicitly cites these as demand and reported-growth drivers. |

## Extraction Priority

1. Quarterly trading statements and corresponding filings: extract Group, division, contract-type, and country net-fee actuals, LFL growth, volumes, hours, fee/rate commentary, and current outlook.
2. Half-year/full-year reports: extract authoritative financial actuals, definitions, operating profit/conversion, headcount, cash, exceptional items, and historical segment tables.
3. Results presentations: extract structured mix, specialism/country taxonomy, productivity, offices, Enterprise Solutions, and strategy KPIs.
4. Call prepared remarks and Q&A: add auditable qualitative signals, pipeline, demand, time-to-hire, client/candidate confidence, macro, cost, and portfolio commentary.
5. Older annual reports: use for long-run taxonomy and historical comparability, but preserve changes in division structure, country portfolio, accounting definitions, and disclosed metric coverage.

## Caveats

- Hays uses a June year-end and commonly reports Q1-Q4 trading updates plus H1 and FY results. Normalize fiscal periods explicitly; do not assume calendar quarters.
- `Net fees` are the preferred revenue-like metric. `Turnover` includes temporary-worker remuneration and is not comparable to net fees without using the company’s definitions.
- LFL growth means organic year-on-year growth of continuing operations at constant currency. Keep LFL, reported/actual, FX, working-day, and disposal effects separate.
- Conversion rate is pre-exceptional operating profit divided by net fees. It is not a gross margin.
- Underlying Temp margin is a narrow Temp-placement metric and excludes certain agency/payrolling arrangements. Do not promote it to a Group gross margin.
- Hays does not consistently disclose absolute volumes, placements, fee rates, or hours for every division and period. Store unavailable values as `null`; use reported growth or qualitative direction only when that is all the source provides.
- Country portfolios, divisions, and specialism definitions change over time. Record exits, disposals, and restatements as source observations and do not backfill them as if they were unchanged operations.
- Germany’s Temp performance is sensitive to average hours worked, working days, automotive exposure, and hours-related economics. These should be modeled separately from headcount and headline volume.
- Perm outcomes depend on job inflow, client and candidate confidence, conversion to placement, time-to-hire, average salary, and average fee. A Perm volume decline is not necessarily a price decline.
- Exceptional restructuring and transformation charges should be excluded from pre-exceptional operating metrics but retained in the actuals file for EPS and reported-profit reconciliation.
- Presentations and calls contain forward-looking statements and may use consensus ranges rather than formal company guidance. Preserve the stated basis and quote, and do not convert narrative statements into numeric estimates.
