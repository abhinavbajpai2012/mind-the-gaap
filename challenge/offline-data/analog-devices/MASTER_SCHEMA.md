# Analog Devices Master Extraction Schema

This schema is based on sampled markdown documents in `challenge/offline-data/analog-devices`. It is intended to guide CSV extraction for forecasting quarterly reported metrics.

## Scope

- Company: Analog Devices, Inc.
- Ticker: ADI
- Folder: `challenge/offline-data/analog-devices`
- Documents sampled: `INDEX.md`; recent and older earnings releases/8-Ks; recent and older 10-Q/10-K filings; earnings call prepared remarks and Q&A; 2016, 2022, and 2025 slide decks.
- Document families found: filings, call transcripts, slides.
- Coverage period: 2015-01-29 to 2026-06-02, with 129 filings, 131 call transcripts, and 11 slide documents.

## Executive Summary

- ADI is best modeled as a high-performance analog and mixed-signal semiconductor company with one reportable segment but recurring revenue disclosure by end market: Industrial, Automotive, Communications, and Consumer.
- The most forecastable quarterly target metrics are revenue, GAAP and adjusted gross margin, GAAP and adjusted operating margin, diluted EPS, adjusted EPS, operating cash flow, free cash flow, capex, inventory, channel inventory weeks, and revenue by end market.
- Earnings releases and 8-K exhibits are the best sources for quarterly actuals, forward quarter guidance, non-GAAP reconciliations, cash return, and end-market revenue tables.
- 10-Ks and 10-Qs are the best sources for audited or reviewed financial statements, market definitions, product categories, revenue recognition caveats, inventory, backlog, geographic exposure, debt, tax, capex, and risk factors.
- Earnings calls provide the strongest forward-looking driver signals: bookings, book-to-bill, channel inventory, pricing, utilization, supply capacity, customer inventory, AI/data center demand, BMS recovery, ADAS content, ATE, aerospace and defense, energy, healthcare, and broad industrial demand.
- Slides are most useful for taxonomy and long-term feature engineering, including secular growth themes, product portfolio positioning, manufacturing model, target margins, free cash flow model, and acquisition synergies.
- Product-level units, wafer starts, ASP by product, customer-level shipments, and formal backlog dollars are generally not disclosed. Use end-market revenue, management commentary, book-to-bill, channel inventory, and application-specific signals as proxies.

## Document Type Inventory

| Document type | Best use in forecasting | Extractable parameters | Example company-specific signals | Suggested CSV |
|---|---|---|---|---|
| Earnings release / 8-K exhibit | Quarterly actuals, next-quarter guidance, end-market revenue, non-GAAP metrics, cash return | Revenue, gross margin, operating income, operating margin, EPS, adjusted metrics, OCF, capex, FCF, dividends, repurchases, end-market revenue, guidance ranges | Q2 2026 revenue of $3.62B; Q3 2026 revenue outlook of $3.9B +/- $100M; Industrial 50% of Q2 2026 revenue; Communications up 79% YoY | `financial_actuals.csv`, `end_market_revenue.csv`, `guidance_outlook.csv`, `cash_inventory_capital.csv` |
| 10-Q | Reviewed quarterly financial statements and balance sheet/cash flow details | Income statement, balance sheet, cash flow, inventory, receivables, debt, share count, tax, capex, restructuring, notes | Inventory dollars; accounts receivable; long-term debt; R&D and SG&A; tax provision; risk updates | `financial_actuals.csv`, `cash_inventory_capital.csv` |
| 10-K / annual report | Business model, market taxonomy, annual actuals, market mix, risks, accounting policies | Annual financials, end-market revenue percentages, product families, applications, customers, sales channel, distributor terms, backlog definition, seasonality | FY2025 end-market mix: Industrial 45%, Automotive 30%, Communications 13%, Consumer 13%; 75,000+ SKUs; distributor return and price adjustment rights | `product_application_taxonomy.csv`, `end_market_revenue.csv`, `market_driver_signals.csv` |
| Earnings call prepared remarks | Management explanation of quarter, next-quarter setup, demand trends, application growth | Sequential and YoY end-market commentary, bookings, order book, backlog, channel inventory weeks, utilization, pricing, AI/data center, BMS, ATE, auto, industrial subsegments | Industrial up 20% sequentially in Q2 2026; data center more than 75% of Communications revenue; free cash flow 36% of revenue TTM | `market_driver_signals.csv`, `guidance_outlook.csv` |
| Earnings call Q&A | Analyst-tested assumptions, margin bridge, pricing, capacity, inventory, segment outlook | Pricing contribution, volume vs price, utilization, outsourcing, customer inventory, book-to-bill, quarterly segment outlook | FY2026 pricing actions add a couple points to growth; Q3 Industrial and Automotive mid-to-high single-digit sequential growth; Consumer down single digits | `market_driver_signals.csv`, `guidance_outlook.csv` |
| Investor day / strategy slides | Product/application taxonomy, secular drivers, long-term model, TAM/SAM, portfolio and manufacturing architecture | Growth targets, target operating margin, target FCF margin, product rank, customer count, SKU count, manufacturing capacity mix, secular growth themes | 7-10% long-term revenue CAGR from FY22E; 42-50% adjusted operating margin target; 34-40% FCF margin target; ~70% flexible capacity | `product_application_taxonomy.csv`, `market_driver_signals.csv`, `strategic_events.csv` |
| Proxy / governance filings | Executive incentives, capital allocation governance, shareholder proposals | Compensation metrics, incentive KPIs, governance events, shareholder return references | Useful for incentive alignment but usually lower priority for quarterly revenue forecasting | `strategic_events.csv` |

## Product, Segment, And Category Taxonomy

ADI has one reportable segment for SEC financial reporting, so forecasting should not force a formal multi-segment operating model. The practical modeling hierarchy is end market first, then application subdriver, then product technology family where disclosed. Product families help explain margin and secular exposure, but revenue is most consistently quantified by end market.

| Level | Category | Examples or subcategories | Typical source | Forecasting use |
|---|---|---|---|---|
| Company | Analog Devices | Consolidated ADI | All documents | Top-level revenue, margins, cash flow, capital allocation |
| Reportable segment | One reportable segment | Aggregated semiconductor business | 10-K, 10-Q | Confirms segment financials are not separately disclosed |
| End market | Industrial | Industrial automation, instrumentation and measurement, aerospace/defense, healthcare, energy management, broad market, ATE, ETM | 10-K, earnings release, calls, slides | Highest-priority revenue driver; often largest and highest-margin business |
| End market | Automotive | BMS, EVs, ADAS, GMSL, A2B, functionally safe power, infotainment, intelligent power | 10-K, calls, slides | Model content gains, EV/ADAS penetration, regional demand, customer inventory |
| End market | Communications | Data center, optical, power, wireless communications, network infrastructure | 10-K, earnings release, calls, slides | Model AI/data center cycle, optical and power growth, wireless recovery |
| End market | Consumer | Portable devices, wearables, hearables, prosumer audio/video, immersive consumer experience | 10-K, calls, slides | More cyclical and sentiment-sensitive; useful for seasonality and mix |
| Product technology | Analog and mixed signal | Data converters, precision and high-speed signal chain | 10-K, slides | Explains moat, design-in stickiness, ASP premium |
| Product technology | Power management and reference | Power conversion, driver monitoring, sequencing, energy management, IVR, silicon capacitors | 10-K, calls, slides | Critical for data center, automotive, industrial, energy, gross margin mix |
| Product technology | Amplifiers, RF and microwave | Precision, instrumentation, high-speed, IF/RF/microwave, broadband amplifiers, RF signal chain | 10-K, slides | Communications, A&D, instrumentation, test, data center exposure |
| Product technology | Sensors and actuators | MEMS accelerometers, gyroscopes, IMUs, temperature, magnetic field, isolators | 10-K, slides | Automotive, healthcare, industrial automation, energy monitoring |
| Product technology | DSP, edge processors, software, AI platforms | DSPs, CodeFusion Studio, Power Studio, embedded software, physical intelligence | 10-K, slides | Longer-term product differentiation and system-level value capture |
| Go-to-market | Direct, distributor, independent rep, digital/web | Global direct sales, third-party distributors, reps, website | 10-K | Channel inventory and distributor terms can distort near-term demand |
| Manufacturing model | Hybrid internal/external | Internal manufacturing, foundry/OSAT partners, flexible capacity, die bank and finished goods buffers | Calls, slides, 10-K | Capacity, utilization, gross margin, supply resilience, capex |

## Target Metric Mapping

| Target field | Company availability | Normalized column | Source document types | Notes |
|---|---|---|---|---|
| Revenue | Direct | `revenue_usd` | 8-K, 10-Q, 10-K, calls, slides | Available quarterly and annually |
| Revenue growth | Direct / Derivable | `revenue_yoy_pct`, `revenue_qoq_pct` | 8-K, calls, slides | Often disclosed in releases and calls; can also be calculated |
| End-market revenue | Direct | `end_market_revenue_usd`, `end_market_revenue_pct_of_total` | 8-K, 10-K, calls | Quarterly dollars in releases; annual percentages in 10-K |
| Industrial revenue | Direct | `industrial_revenue_usd` | 8-K, calls, 10-K | Core modeling dimension; includes ATE, aerospace/defense, automation, healthcare, energy, broad market |
| Automotive revenue | Direct | `automotive_revenue_usd` | 8-K, calls, 10-K | Include BMS, ADAS, GMSL, A2B, functionally safe power as subdrivers |
| Communications revenue | Direct | `communications_revenue_usd` | 8-K, calls, 10-K | Data center and wireless are key subdrivers; data center may be disclosed as share of Communications |
| Consumer revenue | Direct | `consumer_revenue_usd` | 8-K, calls, 10-K | Often seasonality and consumer sentiment driven |
| Gross margin | Direct | `gross_margin_pct` | 8-K, 10-Q, 10-K, calls | GAAP available; adjusted/non-GAAP also disclosed |
| Adjusted gross margin | Direct | `adjusted_gross_margin_pct` | 8-K, calls, slides | Useful for normalized margin model |
| Operating margin | Direct | `operating_margin_pct` | 8-K, 10-Q, 10-K, calls | GAAP and adjusted variants |
| Adjusted operating margin | Direct | `adjusted_operating_margin_pct` | 8-K, calls, slides | Common guidance metric |
| EPS / adjusted EPS | Direct | `diluted_eps_usd`, `adjusted_diluted_eps_usd` | 8-K, 10-Q, 10-K, calls | Guidance usually on adjusted EPS plus reported EPS in recent releases |
| Operating cash flow | Direct | `operating_cash_flow_usd` | 8-K, 10-Q, 10-K, calls | Quarterly, YTD, annual, or trailing-twelve-month basis |
| Free cash flow | Direct / Derivable | `free_cash_flow_usd`, `free_cash_flow_margin_pct` | 8-K, 10-Q, 10-K, calls, slides | Defined as operating cash flow less capex |
| Capex | Direct / Derivable | `capital_expenditures_usd`, `capex_pct_of_revenue` | 8-K, 10-Q, 10-K, calls | Sometimes called capital additions; long-term model 4%-6% of revenue in calls |
| Inventory | Direct | `inventory_usd`, `days_inventory` | 10-Q, 10-K, calls, slides | Days inventory and channel weeks are strong cycle signals |
| Channel inventory | Direct when stated | `channel_inventory_weeks` | Calls, slides | Often disclosed narratively or as a range, e.g. six to seven weeks |
| Bookings / book-to-bill | Different label / Partial | `bookings_signal`, `book_to_bill_signal` | Calls, 10-K | Usually qualitative or directional, not always dollarized |
| Backlog | Different label / Partial | `backlog_signal` | 10-K, calls | 10-K defines backlog as firm orders with requested delivery within thirteen weeks, but dollars usually not provided |
| Units / volume | Different label / Partial | `volume_signal` | Calls | Management may separate price vs volume, but product units are not disclosed |
| Price realization | Different label / Partial | `pricing_signal`, `pricing_growth_contribution_pct` | Calls | Pricing actions can be quantified narratively, e.g. a couple points of FY growth |
| Utilization | Different label / Partial | `utilization_signal` | Calls, 10-K | Usually qualitative; important for gross margin |
| Product-level ASP | Not applicable / Not disclosed | `asp_signal` | Calls, slides | ADI discloses relative ASP premium, not SKU-level ASP |
| Product-level shipments | Not applicable / Not disclosed | `shipment_signal` | None / calls | Use end-market revenue and demand commentary as proxies |
| Store count / ticket / transactions | Not applicable | `not_applicable` | None | Retail metrics do not apply to ADI |
| Subscriber/user counts | Not applicable | `not_applicable` | None | Not a subscription user model, despite software/platform references |
| Customer concentration | Direct / Partial | `customer_concentration_signal` | 10-K, slides | Often stated as no end customer above a threshold; useful for resiliency, not quarterly forecasting |
| Strategic acquisition event | Direct | `event_type`, `event_name`, `expected_synergy_usd`, `expected_revenue_impact` | 8-K, calls, slides, 10-K | Linear, Maxim, Empower, Hittite and smaller technology deals affect product mix and synergy assumptions |

## Recommended CSV Schemas

### `financial_actuals.csv`

Row grain: one row per company-period-source with consolidated reported actuals.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period, such as `Q2 2026` or `FY 2025`. |
| `source_file` | string | Relative source markdown path. |
| `period_end_date` | date | Fiscal period end date when disclosed. |
| `fiscal_year` | integer | Fiscal year. |
| `fiscal_quarter` | string | Fiscal quarter or `FY`. |
| `duration` | string | `quarter`, `six_months`, `nine_months`, `year`, or `ttm`. |
| `currency` | string | Currency, usually `USD`. |
| `units` | string | Monetary unit used in extracted value, such as `thousands`, `millions`, or `actual`. |
| `revenue_usd` | number | Consolidated revenue. |
| `revenue_yoy_pct` | number | Year-over-year revenue growth percentage if disclosed or calculated. |
| `revenue_qoq_pct` | number | Sequential revenue growth percentage if disclosed or calculated. |
| `cost_of_sales_usd` | number | Cost of sales. |
| `gross_margin_usd` | number | GAAP gross margin dollars. |
| `gross_margin_pct` | number | GAAP gross margin as percent of revenue. |
| `adjusted_gross_margin_usd` | number | Non-GAAP adjusted gross margin dollars. |
| `adjusted_gross_margin_pct` | number | Non-GAAP adjusted gross margin percentage. |
| `rd_expense_usd` | number | Research and development expense. |
| `smga_expense_usd` | number | Selling, marketing, general and administrative expense. |
| `amortization_intangibles_usd` | number | Amortization of intangibles. |
| `special_charges_usd` | number | Special charges, restructuring, or similar items. |
| `operating_income_usd` | number | GAAP operating income. |
| `operating_margin_pct` | number | GAAP operating margin. |
| `adjusted_operating_income_usd` | number | Non-GAAP adjusted operating income. |
| `adjusted_operating_margin_pct` | number | Non-GAAP adjusted operating margin. |
| `interest_expense_usd` | number | Interest expense. |
| `interest_income_usd` | number | Interest income. |
| `other_income_expense_usd` | number | Other nonoperating income or expense. |
| `income_before_tax_usd` | number | Income before income taxes. |
| `tax_provision_usd` | number | Provision for income taxes. |
| `tax_rate_pct` | number | Effective tax rate if disclosed. |
| `net_income_usd` | number | Net income. |
| `basic_eps_usd` | number | Basic EPS. |
| `diluted_eps_usd` | number | Diluted EPS. |
| `adjusted_diluted_eps_usd` | number | Non-GAAP adjusted diluted EPS. |
| `basic_shares` | number | Basic weighted-average shares. |
| `diluted_shares` | number | Diluted weighted-average shares. |
| `is_non_gaap` | boolean | Whether row or key values are non-GAAP. |
| `non_gaap_adjustments` | string | Short description of exclusions, such as acquisition-related expenses or special charges. |

### `end_market_revenue.csv`

Row grain: one row per company-period-end_market-source.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `period_end_date` | date | Fiscal period end date when disclosed. |
| `fiscal_year` | integer | Fiscal year. |
| `fiscal_quarter` | string | Fiscal quarter or `FY`. |
| `duration` | string | `quarter`, `six_months`, `nine_months`, `year`, or `ttm`. |
| `end_market` | string | `industrial`, `automotive`, `communications`, or `consumer`. |
| `end_market_subcategory` | string | More specific category when disclosed, such as `data_center`, `wireless`, `bms`, `ate`, `aerospace_defense`, or `healthcare`; otherwise `null`. |
| `revenue_usd` | number | Revenue for the end market or subcategory. |
| `revenue_pct_of_total` | number | Percent of total revenue. |
| `revenue_yoy_pct` | number | Year-over-year growth percentage. |
| `revenue_qoq_pct` | number | Sequential growth percentage. |
| `growth_description` | string | Text description when exact value is not disclosed, such as `mid_to_high_single_digits_sequential`. |
| `disclosure_basis` | string | `dollars`, `percent_of_revenue`, `growth_rate`, or `narrative`. |
| `quote` | string | Short supporting quote for narrative rows. |

### `guidance_outlook.csv`

Row grain: one row per company-guided_period-guidance_metric-source.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reporting period of the source document. |
| `source_file` | string | Relative source markdown path. |
| `guided_period` | string | Future period covered by guidance, such as `Q3 2026`. |
| `guidance_metric` | string | Metric name, such as `revenue`, `adjusted_operating_margin`, `reported_eps`, or `adjusted_eps`. |
| `guidance_low` | number | Low end of guidance range. |
| `guidance_midpoint` | number | Midpoint of guidance range. |
| `guidance_high` | number | High end of guidance range. |
| `guidance_units` | string | Units such as `usd`, `usd_millions`, `percent`, `basis_points`, or `eps_usd`. |
| `range_text` | string | Original range wording, such as `$3.9 billion +/- $100 million`. |
| `basis` | string | `gaap`, `adjusted`, `non_gaap`, or `operational`. |
| `assumptions` | string | Management assumptions, including segment growth, tax rate, channel inventory, pricing, or mix. |
| `supersedes_prior_guidance` | boolean | Whether the source states that guidance supersedes prior statements. |
| `quote` | string | Short supporting quote. |

### `market_driver_signals.csv`

Row grain: one row per source-driver-signal. This CSV preserves qualitative evidence for forecasting features.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period or event period. |
| `source_file` | string | Relative source markdown path. |
| `document_family` | string | `filing`, `call_prepared_remarks`, `call_qna`, `slide`, or `proxy`. |
| `signal_family` | string | `demand`, `pricing`, `volume`, `mix`, `margin`, `capacity`, `inventory`, `supply_chain`, `macro`, `technology`, `customer`, `capital_allocation`, or `risk`. |
| `end_market` | string | End market tied to the signal, or `companywide`. |
| `subcategory` | string | Application or technology, such as `data_center_power`, `optical`, `bms`, `adas`, `automation`, `ate`, `aerospace_defense`, `energy_storage`, or `healthcare`. |
| `signal_name` | string | Normalized signal name, such as `record_bookings`, `positive_book_to_bill`, `pricing_actions`, `lean_customer_inventory`, `channel_inventory_weeks_flat`, `utilization_tailwind`, or `mix_tailwind`. |
| `direction` | string | `positive`, `negative`, `mixed`, or `neutral`. |
| `magnitude_value` | number | Numeric magnitude if disclosed. |
| `magnitude_unit` | string | Unit for magnitude, such as `pct`, `bps`, `weeks`, `usd`, or `growth_points`. |
| `time_horizon` | string | `current_quarter`, `next_quarter`, `second_half`, `fy`, `multi_year`, or `long_term`. |
| `confidence` | string | `high`, `medium`, or `low` based on specificity and source type. |
| `quote` | string | Short supporting quote from the source. |
| `notes` | string | Additional extraction notes or caveats. |

### `product_application_taxonomy.csv`

Row grain: one row per company-taxonomy_level-category-source.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Source period. |
| `source_file` | string | Relative source markdown path. |
| `taxonomy_level` | string | `end_market`, `application`, `product_family`, `technology_platform`, `go_to_market`, or `manufacturing_model`. |
| `parent_category` | string | Parent category, such as `industrial` for `automation`; `null` for top-level categories. |
| `category` | string | Normalized category name. |
| `display_name` | string | Company-specific label from the source. |
| `examples` | string | Applications, products, or customer examples. |
| `forecasting_use` | string | Why this category matters for forecasting. |
| `is_quantified` | boolean | Whether revenue, percentage, TAM, or other numeric value is disclosed. |
| `metric_name` | string | Metric associated with the category, if any. |
| `metric_value` | number | Numeric value if disclosed. |
| `metric_unit` | string | Unit such as `pct_of_revenue`, `customers`, `skus`, `years`, or `usd`. |
| `quote` | string | Short supporting quote. |

### `cash_inventory_capital.csv`

Row grain: one row per company-period-source with balance sheet, cash flow, inventory, and capital allocation metrics.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `period_end_date` | date | Fiscal period end date when disclosed. |
| `duration` | string | `quarter`, `six_months`, `nine_months`, `year`, or `ttm`. |
| `cash_and_equivalents_usd` | number | Cash and cash equivalents. |
| `short_term_investments_usd` | number | Short-term investments. |
| `cash_and_short_term_investments_usd` | number | Combined cash and short-term investments when disclosed. |
| `accounts_receivable_usd` | number | Accounts receivable. |
| `inventory_usd` | number | Balance sheet inventory. |
| `days_inventory` | number | Days of inventory if disclosed. |
| `channel_inventory_weeks` | number | Distributor/channel inventory weeks if disclosed. |
| `accounts_payable_usd` | number | Accounts payable. |
| `current_debt_usd` | number | Current debt. |
| `commercial_paper_usd` | number | Commercial paper notes. |
| `long_term_debt_usd` | number | Long-term debt. |
| `net_leverage_ratio` | number | Net leverage ratio if disclosed. |
| `operating_cash_flow_usd` | number | Cash from operations. |
| `capital_expenditures_usd` | number | Capital expenditures or capital additions. |
| `free_cash_flow_usd` | number | Operating cash flow less capital expenditures. |
| `free_cash_flow_margin_pct` | number | Free cash flow as percentage of revenue. |
| `dividends_paid_usd` | number | Cash dividends paid. |
| `dividend_per_share_usd` | number | Dividend per share. |
| `share_repurchases_usd` | number | Stock repurchases. |
| `total_cash_returned_usd` | number | Dividends plus repurchases. |
| `cash_return_pct_of_fcf` | number | Cash returned as percentage of free cash flow. |
| `capex_outlook_text` | string | Forward-looking capex target or range. |
| `quote` | string | Short supporting quote for narrative or forward-looking values. |

### `strategic_events.csv`

Row grain: one row per company-event-source.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Source period. |
| `source_file` | string | Relative source markdown path. |
| `event_date` | date | Event date when disclosed. |
| `event_type` | string | `acquisition`, `divestiture`, `product_launch`, `investor_day_target`, `capital_allocation`, `manufacturing_capacity`, or `governance`. |
| `event_name` | string | Name of event, such as `Linear Technology acquisition`, `Maxim acquisition`, `Empower Semiconductor acquisition`, or `2030 vision`. |
| `affected_end_market` | string | Related end market or `companywide`. |
| `affected_product_family` | string | Related product family, such as `power_management`, `rf`, `data_converters`, or `software_ai`. |
| `expected_revenue_impact_usd` | number | Expected revenue impact if disclosed. |
| `expected_synergy_usd` | number | Expected cost or revenue synergy if disclosed. |
| `expected_timing` | string | Timing described by management. |
| `status` | string | `announced`, `pending`, `closed`, `integrating`, or `target`. |
| `quote` | string | Short supporting quote. |
| `notes` | string | Additional event context. |

## Forecasting Feature Families

| Feature family | Suggested variables | Source document types | Why it matters |
|---|---|---|---|
| Consolidated sales growth | `revenue_usd`, `revenue_yoy_pct`, `revenue_qoq_pct`, guidance midpoint | 8-K, 10-Q, 10-K, calls | Core target variable for quarterly forecast |
| End-market mix | Industrial, Automotive, Communications, Consumer revenue dollars and mix percentages | 8-K, 10-K, calls | Mix affects growth durability and margin; Industrial and Communications can be above corporate average |
| Industrial subdrivers | ATE, ETM, aerospace/defense, automation, healthcare, energy, broad market signals | Calls, 10-K, slides | Industrial is large, high-margin, and diversified; subdrivers explain cycle and secular growth |
| Automotive content | BMS, ADAS, GMSL, A2B, functionally safe power, regional signals, customer inventory | Calls, 10-K, slides | ADI growth can come from content/share gains even if auto units are weak |
| Communications/data center | Data center share of Communications, optical, power, wireless growth, AI infrastructure demand | Calls, slides, 10-K | Data center and AI power/optical are major recent growth accelerators |
| Pricing and ASP | Pricing actions, expected growth contribution, ASP premium, value capture language | Calls, slides | Pricing affects revenue growth and gross margin; exact ASP by product is not disclosed |
| Volume and demand | Record bookings, book-to-bill, order rates, backlog commentary, customer visibility | Calls, 10-K | Volume often explains upside beyond price |
| Inventory and channel | Inventory dollars, days inventory, channel inventory weeks, customer inventory, distributor return terms | 10-Q, 10-K, calls, slides | Semiconductor cycles are heavily affected by inventory digestion or restocking |
| Margin bridge | Gross margin, adjusted gross margin, mix, utilization, outsourcing, pricing, channel repricing | 8-K, calls, slides | Margin variance often comes from mix, utilization, and pricing rather than revenue alone |
| Capacity and supply | Hybrid manufacturing capacity, internal/external capacity, capex, supply constraints | Calls, 10-K, slides | Determines ability to satisfy demand and margin ceiling |
| Cash generation | OCF, capex, FCF, FCF margin, dividend, repurchase, leverage | 8-K, 10-Q, 10-K, calls, slides | ADI emphasizes FCF return and shareholder returns |
| Macro and policy | Tariffs, export controls, China, consumer sentiment, interest rates, supply chain constraints | 10-K, calls | External shocks can affect demand, pricing, sourcing, and regional performance |
| Strategic portfolio | Acquisitions, revenue synergies, new products, power platform, software/AI initiatives | Slides, calls, filings | Portfolio changes affect medium-term growth and mix |

## Extraction Priority

1. Earnings releases and 8-K exhibits: highest priority for quarterly actuals, guidance, non-GAAP metrics, end-market revenue, cash return, and directly comparable history.
2. Earnings call prepared remarks and Q&A: highest priority for forward-looking signals, especially bookings, inventory, pricing, utilization, end-market outlook, application drivers, and management assumptions behind guidance.
3. 10-Q and 10-K filings: highest priority for audited/reviewed statements, balance sheet, cash flow, product taxonomy, end-market definitions, revenue recognition, backlog definition, distributor terms, and risk factors.
4. Investor day and strategy slides: high priority for taxonomy, long-term model, secular growth drivers, target margins, manufacturing architecture, TAM/SAM, and acquisition or synergy context.
5. Proxy and governance filings: lower priority unless extracting incentive metrics, capital allocation governance, shareholder proposals, or executive compensation KPIs.

## Caveats

- ADI reports as one reportable segment, so end-market revenue is the best practical operating cut but not a formal segment P&L.
- Revenue by end market can be reclassified over time as product categorization systems evolve; preserve source period and source file for auditability.
- Product categories are broad technology families, not reliable product-level revenue lines. Do not infer SKU-level revenue, shipments, or ASP.
- Management often describes bookings, book-to-bill, backlog, lead times, utilization, and customer inventory qualitatively. Store the quote and use `null` for missing numeric values.
- Backlog is defined in the 10-K as firm orders with requested delivery within thirteen weeks, but backlog dollars are generally not disclosed and orders can be canceled or delayed.
- Distributor agreements can include price adjustment credits and return rights; channel inventory and sell-through should be treated as demand-quality indicators.
- Non-GAAP metrics exclude acquisition-related expenses, amortization, special charges, and tax items. Keep GAAP and adjusted fields separate.
- Recent large acquisitions and portfolio additions, including Linear Technology, Maxim, and Empower Semiconductor, can change growth, margin, product mix, and comparability over time.
- ADI's fiscal year ends on the Saturday closest to the last day in October, and some years include 53 weeks. Capture period end dates when available.
- Retail-specific fields such as stores, average ticket, transactions, and comparable sales are not applicable to ADI.
