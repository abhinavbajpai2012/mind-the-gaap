# Home Depot CSV Extraction Schema Draft

This draft is based on a sample of Home Depot documents across `filings`, `call-transcripts`, and `slides`. It is meant to guide the first CSV extraction pass for forecasting quarterly metrics such as net sales, adjusted diluted EPS, comparable sales, revenue, gross margin, operating profit, and GAAP diluted EPS.

Representative files sampled:

- `INDEX.md`
- `filings/2026-05-19__hd-us-20260519-q1-8k__1038584.md`
- `filings/2026-05-19__hd-us-20260519-q1-10q__1053121.md`
- `filings/2026-03-18__hd-us-20260318-fy-10k__828355.md`
- `call-transcripts/2026-05-19__hd-us-20260519-call-pres__1039117.md`
- `call-transcripts/2026-05-19__hd-us-20260519-call-qna__1039119.md`
- `slides/2025-12-09__hd-us-20251209-slide__384215.md`
- `slides/2024-03-28__hd-us-20240328-slide__38048.md`

## Document Type Inventory

| Document type | Best use in forecasting | Extractable parameters | Example Home Depot signals | Suggested CSV |
|---|---|---|---|---|
| Earnings release / 8-K filing | Clean current-quarter actuals and management guidance | Net sales, sales growth, comparable sales, U.S. comparable sales, GAAP diluted EPS, adjusted diluted EPS, gross margin guidance, operating margin guidance, tax rate guidance, interest expense guidance, capex guidance, store count, SRS location count | Q1 2026 sales of `$41.8B`, comp sales `0.6%`, U.S. comps `0.4%`, adjusted diluted EPS `$3.43`, fiscal 2026 gross margin guidance `~33.1%` | `filing_earnings_release_quarterly.csv`, `guidance.csv` |
| 10-Q filing | Structured quarterly statements, segment/product-line sales, balance sheet and cash flow | Net sales, cost of sales, gross profit, gross margin, SG&A, D&A, operating income, operating margin, interest expense, tax provision, net earnings, EPS, inventory, cash flow, capex, segment sales, segment operating income, product-line net sales, geography sales | Primary segment net sales, Other/SRS net sales, Building Materials/Decor/Hardlines product-line sales, customer transactions, average ticket | `filing_10q_quarterly.csv`, `segment_product_line_sales.csv` |
| 10-K filing | Annual history, longer product taxonomy, definitions, strategic and risk drivers | Multi-year sales, margins, EPS, comps, transactions, average ticket, product-line sales mix, geography mix, inventory policy, revenue recognition, segment definitions, acquisition contribution | Major product lines and merchandising departments; SRS/GMS as Other segment; annual net sales and gross profit percentages | `filing_10k_annual.csv`, `product_taxonomy.csv` |
| Proxy / shareholder filing | Governance, compensation KPIs, capital allocation context | Long-term performance measures, ROIC, operating income, sales, shareholder returns, executive incentive metrics, strategic priorities | Useful for understanding what management optimizes, less useful for quarterly forecasts | `proxy_kpis.csv` |
| Earnings call prepared remarks | Driver attribution for quarter and guidance | Monthly comp cadence, category strength/weakness, Pro vs DIY, online sales growth, weather effects, FX effects, big-ticket transactions, margin drivers, inventory turns, ROIC, capex, dividends, future guidance color | Positive comps in 9 of 16 departments; comp average ticket `+2.2%`; comp transactions `-1.3%`; online comp sales `+10%+`; gross margin `33.0%` | `call_prepared_remarks_quarterly.csv`, `category_signals.csv` |
| Earnings call Q&A | Analyst-tested assumptions and management explanations | Demand drivers, large-project exposure, ticket cohorts, items per basket, storm/weather impact, tariffs, fuel/input costs, pricing actions, SRS/GMS comps, Pro initiatives, cross-sell run-rate, early-quarter commentary | Second-half comp improvement driven by normal storm activity; SRS sales `$4B`; SRS organic sales growth expected mid-single-digit; tariff price effect around `3%` | `call_qna_driver_signals.csv` |
| Investor conference / fireside transcript | Medium-term strategy and market assumptions | TAM, market share opportunity, category/platform strategy, Pro demand, digital adoption, capital allocation, cost/price philosophy | Pro TAM, HVAC opportunity, cross-sell, trade credit, delivery capabilities | `conference_strategy_signals.csv` |
| Slide deck | Product/category taxonomy, TAM, platform capabilities, acquisition metrics, visual table extraction | TAM, market share, product categories, Pro customer types, purchase occasions, platforms, branch counts, salesforce count, fleet count, acquisition revenue, adjusted EBITDA, leverage targets | Consumer TAM `~$500B`, Pro TAM `~$600B`, total TAM `~$1.1T`; SRS 2023 revenue `~$10B`, adjusted EBITDA `~$1.1B`, `760+` branches | `slide_strategy_metrics.csv`, `slide_product_taxonomy.csv` |

## Product And Category Taxonomy

Home Depot is better suited to product-category forecasting than SKU-level forecasting because the public documents rarely disclose individual item prices or unit volumes. A practical first taxonomy is:

| Level | Category | Example subcategories or departments | Typical source |
|---|---|---|---|
| Segment | Primary retail | U.S., Canada, Mexico retail operations; stores and online | 10-Q, 10-K |
| Segment | Other / SRS | Roofing and building products, interior and construction products, landscape, pool | 10-Q, 10-K, slides, calls |
| Major product line | Building Materials | Building Materials, Electrical, Lumber, Millwork, Plumbing | 10-Q, 10-K, slides |
| Major product line | Decor | Appliances, Bath, Flooring, Kitchen, Lighting, Paint | 10-Q, 10-K, slides, calls |
| Major product line | Hardlines | Hardware, Indoor Garden, Outdoor Garden, Power, Storage and Organization | 10-Q, 10-K, calls |
| Customer type | DIY / Consumer | Spring projects, live goods, grills, patio, outdoor power equipment | Calls, slides |
| Customer type | Pro | Remodeler, builder, roofer, landscaper, pool contractor, MRO customer | Calls, slides |
| Purchase occasion | Simple / complex | Cash-and-carry, infill/emergency, job-site delivery, large cross-category project | Calls, slides |

## CSV Schema: Earnings Release / 8-K

Recommended file: `filing_earnings_release_quarterly.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter. |
| `ticker` | string | Ticker from front matter. |
| `published_at` | date | Document publication date. |
| `period` | string | Fiscal period from front matter or title. |
| `fiscal_year` | integer | Normalized fiscal year. |
| `fiscal_quarter` | string | Normalized fiscal quarter, if available. |
| `source_file` | string | Relative path to source markdown file. |
| `net_sales_usd_m` | number | Current-period net sales in USD millions. |
| `net_sales_yoy_pct` | number | Reported year-over-year sales growth percentage. |
| `comparable_sales_total_pct` | number | Total company comparable sales percentage. |
| `comparable_sales_us_pct` | number | U.S. comparable sales percentage. |
| `fx_comp_impact_bps` | number | FX impact on comparable sales in basis points, if disclosed. |
| `net_earnings_usd_m` | number | Net earnings in USD millions. |
| `diluted_eps_gaap_usd` | number | GAAP diluted EPS. |
| `adjusted_diluted_eps_usd` | number | Adjusted diluted EPS. |
| `stores_count` | integer | Retail store count at period end. |
| `srs_locations_count` | integer | SRS location or branch count, if disclosed. |
| `associates_count` | integer | Employee or associate count, if disclosed. |
| `guidance_reaffirmed_flag` | boolean | Whether management reaffirmed prior guidance. |

Recommended file: `guidance.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Guidance publication date. |
| `guidance_period` | string | Period covered by guidance, usually fiscal year. |
| `metric` | string | Normalized metric name, for example `total_sales_growth_pct`, `gross_margin_pct`, `adjusted_diluted_eps_growth_pct`. |
| `value_low` | number | Low end of range or point estimate. |
| `value_high` | number | High end of range or point estimate. |
| `unit` | string | `%`, `bps`, `usd_m`, `usd_per_share`, `count`, etc. |
| `basis` | string | `GAAP`, `adjusted`, `organic`, `comparable`, or `reported`. |
| `directionality` | string | `increase`, `decrease`, `flat`, `range`, `approximately`. |
| `prior_base_value` | number | Base value referenced by growth guidance, if disclosed. |
| `quote` | string | Short supporting excerpt. |
| `source_file` | string | Relative source path. |

## CSV Schema: 10-Q / 10-K Financials

Recommended file: `filing_financials_periodic.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Filing date. |
| `document_subtype` | string | `10-Q`, `10-K`, or other filing subtype inferred from title/body. |
| `period` | string | Fiscal period. |
| `fiscal_year` | integer | Fiscal year. |
| `fiscal_quarter` | string | Fiscal quarter, null for annual rows. |
| `period_length_months` | integer | Usually 3, 6, 9, or 12. |
| `source_file` | string | Relative source path. |
| `net_sales_usd_m` | number | Net sales. |
| `cost_of_sales_usd_m` | number | Cost of sales. |
| `gross_profit_usd_m` | number | Gross profit. |
| `gross_margin_pct` | number | Gross profit divided by net sales, or reported percentage. |
| `sga_usd_m` | number | Selling, general, and administrative expense. |
| `depreciation_amortization_usd_m` | number | Depreciation and amortization. |
| `operating_income_usd_m` | number | Operating income. |
| `operating_margin_pct` | number | Operating income divided by net sales, or reported percentage. |
| `interest_expense_usd_m` | number | Interest expense. |
| `tax_provision_usd_m` | number | Provision for income taxes. |
| `effective_tax_rate_pct` | number | Tax provision divided by pretax earnings, or reported percentage. |
| `net_earnings_usd_m` | number | Net earnings. |
| `basic_eps_usd` | number | Basic EPS. |
| `diluted_eps_gaap_usd` | number | Diluted EPS. |
| `basic_weighted_avg_shares_m` | number | Basic weighted average shares. |
| `diluted_weighted_avg_shares_m` | number | Diluted weighted average shares. |
| `cash_and_equivalents_usd_m` | number | Balance sheet cash. |
| `receivables_usd_m` | number | Receivables, net. |
| `merchandise_inventory_usd_m` | number | Merchandise inventory. |
| `capex_usd_m` | number | Capital expenditures. |
| `operating_cash_flow_usd_m` | number | Net cash provided by operating activities. |
| `dividends_paid_usd_m` | number | Cash dividends paid. |
| `long_term_debt_usd_m` | number | Long-term debt, excluding current installments. |

Recommended file: `segment_product_line_sales.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Filing date. |
| `period` | string | Fiscal period. |
| `fiscal_year` | integer | Fiscal year. |
| `fiscal_quarter` | string | Fiscal quarter, if applicable. |
| `source_file` | string | Relative source path. |
| `dimension_type` | string | `segment`, `major_product_line`, `department`, `geography`, or `customer_type`. |
| `dimension_name` | string | Example: `Primary`, `Other`, `Building Materials`, `Decor`, `Hardlines`, `U.S.`. |
| `parent_dimension_name` | string | Optional parent category. |
| `net_sales_usd_m` | number | Sales for the dimension. |
| `net_sales_mix_pct` | number | Percentage of total or segment net sales. |
| `operating_income_usd_m` | number | Operating income for segment rows, if disclosed. |
| `operating_margin_pct` | number | Segment operating margin, if computable. |
| `yoy_growth_pct` | number | Reported or computed year-over-year growth. |
| `notes` | string | Important caveats such as reclassifications or acquisition effects. |

## CSV Schema: Call Transcripts

Recommended file: `call_prepared_remarks_quarterly.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Call date. |
| `period` | string | Fiscal period. |
| `source_file` | string | Relative source path. |
| `speaker_role` | string | CEO, CFO, merchandising leader, operations leader, or unknown. |
| `metric` | string | Normalized metric or driver name. |
| `value` | number | Numeric value, if present. |
| `value_low` | number | Low end of range, if present. |
| `value_high` | number | High end of range, if present. |
| `unit` | string | `%`, `bps`, `usd_m`, `count`, `turns`, etc. |
| `time_scope` | string | Quarter, month, fiscal year, year-to-date, future period. |
| `category` | string | Product/category/customer group, if applicable. |
| `directionality` | string | Positive, negative, flat, improved, pressured, stable. |
| `quote` | string | Short supporting excerpt. |

Recommended file: `call_qna_driver_signals.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Call date. |
| `period` | string | Fiscal period. |
| `source_file` | string | Relative source path. |
| `question_topic` | string | Analyst question topic, for example `gross_margin`, `SRS`, `tariffs`, `weather`, `Pro`. |
| `driver` | string | Forecasting driver named by management. |
| `affected_metric` | string | Metric likely affected, for example `comparable_sales_total_pct`, `gross_margin_pct`, `net_sales_usd_m`. |
| `affected_category` | string | Category or customer group. |
| `impact_value` | number | Numeric impact, if disclosed. |
| `impact_unit` | string | `%`, `bps`, `usd_m`, `run_rate_usd_m`, etc. |
| `impact_direction` | string | Positive, negative, neutral, offsetting, uncertain. |
| `time_scope` | string | Quarter, month, second half, fiscal year, long term. |
| `confidence_hint` | string | `high` for explicit numeric guidance, `medium` for directional statements, `low` for qualitative color. |
| `quote` | string | Short supporting excerpt. |

Recommended file: `category_signals.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source date. |
| `period` | string | Fiscal period. |
| `source_file` | string | Relative source path. |
| `category` | string | Product category, department, segment, or customer group. |
| `taxonomy_level` | string | `department`, `major_product_line`, `segment`, `customer_type`, `purchase_occasion`. |
| `signal_type` | string | `comp`, `sales`, `demand`, `margin`, `pricing`, `volume`, `mix`, `weather`, `digital`, `inventory`. |
| `value` | number | Numeric signal if available. |
| `unit` | string | `%`, `bps`, `usd_m`, `count`, or null for qualitative rows. |
| `directionality` | string | Positive, negative, stronger, weaker, stable, pressured. |
| `quote` | string | Supporting excerpt. |

## CSV Schema: Slides

Recommended file: `slide_strategy_metrics.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Slide deck date. |
| `period` | string | Period from front matter. |
| `source_file` | string | Relative source path. |
| `slide_section` | string | Heading or inferred slide title. |
| `metric` | string | Normalized metric name. |
| `value` | number | Numeric value. |
| `unit` | string | `usd_m`, `usd_b`, `%`, `count`, `x`, etc. |
| `dimension` | string | TAM, platform, acquisition, customer type, product line, capability. |
| `dimension_name` | string | Example: `Consumer`, `Pro`, `SRS`, `Total addressable market`. |
| `time_scope` | string | Current, fiscal year, long term, target. |
| `quote` | string | Supporting text. |

Recommended file: `slide_product_taxonomy.csv`

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Slide deck date. |
| `source_file` | string | Relative source path. |
| `taxonomy_level` | string | Segment, product line, department, subcategory, customer type, platform. |
| `name` | string | Category or platform name. |
| `parent_name` | string | Parent category, if available. |
| `description` | string | Short text description from slide. |
| `examples` | string | Comma-separated examples, if extracted from slide text. |

## Forecasting Variables To Add Beyond Price, Volume, And Margin

The files rarely provide SKU-level price or unit volume, so the first model should use publicly disclosed proxies:

| Variable family | Suggested variables | Why it matters |
|---|---|---|
| Traffic / volume | Customer transactions, comparable customer transactions, Pro vs DIY demand, big-ticket transaction growth, items per basket | Best public proxies for unit volume and project activity. |
| Price / ticket | Average ticket, comparable average ticket, tariff-driven pricing, commodity inflation/deflation, price investments | Best public proxy for price and basket mix. |
| Mix | Product-line sales mix, SRS/GMS mix, roofing share of Other net sales, Pro vs consumer, online mix, services mix | Mix explains gross margin changes even when sales are stable. |
| Weather / seasonality | Monthly comp cadence, storm activity bps, spring category engagement, regional weather commentary | Important for Home Depot quarterly comps. |
| Macro housing | Existing home sales, housing turnover, mortgage rates, home equity/HELOC availability, new construction, home age, home value appreciation | Management repeatedly ties large-project demand to housing and rates. |
| Channel / digital | Online comp sales, delivery speed, cancellation rate, on-time complete delivery, customer satisfaction | Digital engagement can support comp sales and Pro retention. |
| Pro platform | SRS organic sales growth, branch count, salesforce count, trade credit adoption, cross-sell run-rate, complex purchase growth | Pro is a strategic growth vector and may behave differently from DIY. |
| Cost inputs | Freight, fuel, tariffs, commodity input costs, labor cost, supply chain productivity | Needed for gross margin and operating margin forecasting. |
| Capital allocation | Capex as percent of sales, new stores, new SRS locations, acquisitions, buybacks, dividends, debt and interest expense | Affects sales capacity, EPS, and interest burden. |

## Normalized Target Metrics

The user's broader metric list spans multiple companies. For Home Depot, the directly extractable or derivable target metrics are:

| Requested field | Home Depot availability | Notes |
|---|---|---|
| Net sales | Direct | Primary top-line field in filings and calls. |
| Adjusted diluted EPS | Direct | Usually in 8-K and earnings calls, reconciled in release. |
| Comparable sales, total company | Direct | Found in 8-K, 10-Q/10-K, calls. |
| Revenue | Use net sales | For retailers, normalize `revenue` to `net_sales_usd_m` unless a filing uses different terminology. |
| Adjusted gross margin | Usually indirect | Gross margin is direct; adjusted gross margin may need company-specific non-GAAP definitions where disclosed. |
| Diluted EPS (GAAP) | Direct | Filings and earnings releases. |
| Net fees | Not applicable for Home Depot sample | Likely relevant to financial exchanges/payment firms. |
| Pre-exceptional basic EPS | Not applicable for Home Depot sample | Likely relevant to non-U.S. reporters using pre-exceptional measures. |
| Pre-exceptional operating profit | Not applicable for Home Depot sample | Likely relevant to non-U.S. reporters. |
| Worldwide net sales and revenues | Not applicable label, concept available | Home Depot reports consolidated net sales and geography sales. |
| Production & Precision Ag operating profit | Not applicable | Likely Deere-specific. |

## Extraction Priority

1. Start with 8-K earnings releases and 10-Q/10-K filings for numeric actuals and guidance because they have the cleanest tables.
2. Add prepared remarks for category, product, and driver attribution.
3. Add Q&A for forward-looking assumptions, especially pricing, tariffs, fuel, weather, SRS, and Pro demand.
4. Add slides for product taxonomy, TAM, strategic platforms, and acquisition variables.
5. Keep raw quotes and `source_file` in every qualitative CSV so model features can be audited later.
