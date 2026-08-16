# Deere & Company Master Extraction Schema

This schema is based on sampled markdown documents in `challenge/offline-data/deere`. It is intended to guide CSV extraction for forecasting quarterly reported metrics.

## Scope

- Company: Deere & Company
- Ticker: DE
- Folder: `challenge/offline-data/deere`
- Documents sampled: `INDEX.md`; recent and older 10-K, 10-Q, and 8-K filings; prepared remarks and Q&A earnings-call transcripts; earnings and investor-day slide decks, including FY 2016, FY 2020, FY 2024, FY 2025, and FY 2026 outlook materials.
- Document families found: SEC filings and earnings releases, call transcripts, slide presentations.
- Coverage period: 2012-05-16 to 2026-05-28.

## Executive Summary

- Deere is best modeled around its durable reporting segments: Production & Precision Agriculture, Small Agriculture & Turf, Construction & Forestry, and Financial Services. Earlier periods combine the two agriculture businesses as Agriculture & Turf, so segment history needs a legacy/current segment flag.
- Primary reported targets are consolidated net sales and revenues, equipment net sales, net income attributable to Deere & Company, diluted EPS, segment net sales, segment operating profit, segment operating margin, Financial Services net income, equipment operations operating cash flow, and OROS when disclosed.
- The most useful forecast drivers are industry unit outlooks by region and product class, price realization, currency translation, shipment volume/mix, production costs, tariffs, warranty, SA&G/R&D, dealer inventory, used equipment inventory, order books, backlog, farm cash receipts, commodity prices, interest rates, housing, construction activity, and infrastructure spending.
- Earnings releases and 8-Ks are the best source for clean quarterly actuals and formal guidance. 10-Ks and 10-Qs are the best source for business definitions, segment history, backlog, financing portfolio disclosures, risk factors, and accounting notes.
- Slides and call transcripts add high-signal forward-looking features: industry outlook ranges, early order program commentary, production cadence, inventory posture, technology adoption, See & Spray usage, engaged acres, autonomy rollout, tariffs, and management confidence.
- Product-level unit, price, and volume data are generally not disclosed as a full time series. Use segment/region/product-class industry outlooks and driver commentary rather than SKU-level rows.

## Document Type Inventory

| Document type | Best use in forecasting | Extractable parameters | Example company-specific signals | Suggested CSV |
|---|---|---|---|---|
| Earnings release / 8-K | Clean quarterly and annual actuals plus formal company outlook | Consolidated sales, equipment net sales, net income, EPS, segment sales, segment operating profit, segment margin, industry outlooks, segment sales outlook, price realization, currency, Financial Services income outlook | Large ag cycle bottom, 2026 net income range, tariff expense, segment sales outlook, operating margin ranges | `financial_actuals.csv`, `segment_actuals.csv`, `guidance_outlook.csv`, `industry_outlook.csv` |
| 10-Q | Quarterly financial statements, segment notes, financing disclosures, backlog when included | Income statement lines, balance sheet lines, cash flow lines, segment revenue/profit, receivables, credit losses, inventories, backlog | Equipment Operations vs Financial Services, finance receivables, provision for credit losses, seasonal backlog | `financial_actuals.csv`, `segment_actuals.csv`, `financial_services_metrics.csv` |
| 10-K / annual report | Segment taxonomy, business model, full-year history, risk factors, technology strategy, backlog and portfolio descriptions | Segment products, production systems, geographies, dealer/financing model, backlog, OROS, engaged acres definitions, risks | Smart Industrial Operating Model, Leap Ambitions, PPA/SAT/CF definitions, John Deere Operations Center engaged acres | `taxonomy.csv`, `financial_actuals.csv`, `operational_drivers.csv`, `qualitative_signals.csv` |
| Prepared remarks transcript | Management framing of results and outlook | Driver direction, segment and region outlook, pricing, production plans, inventory, customer fundamentals, cash flow, capital allocation | North America large ag demand, lean production, used inventory reduction, tariff run rate, technology adoption | `operational_drivers.csv`, `qualitative_signals.csv`, `technology_adoption.csv` |
| Q&A transcript | Analyst-tested assumptions and risks | Tariff mitigation, decremental margins, price-cost, order velocity, regional demand, credit risk, production cadence, technology usage | Early order program price, PPA decrementals, Brazil interest-rate sensitivity, See & Spray adoption, government support assumptions | `qualitative_signals.csv`, `operational_drivers.csv` |
| Earnings slides | Structured actuals, guidance, industry outlook graphics, driver bridges, retail/inventory tables | Bar-chart actuals, waterfall components, unit outlooks, dealer inventory ratios, retail sales trends, technology metrics | Volume/mix, price, currency, warranty, production costs, SA&G/R&D, industry unit ranges, dealer inventories | `guidance_outlook.csv`, `segment_actuals.csv`, `industry_outlook.csv`, `operational_drivers.csv` |
| Investor day / strategy slides | Strategic taxonomy and medium-term growth drivers | Production systems, technology stack, lifecycle solutions, aftermarket, retrofit, autonomy, precision ag, margin ambitions | See & Spray, Operations Center, autonomy, aftermarket/retrofit opportunity, OROS ambitions | `taxonomy.csv`, `technology_adoption.csv`, `qualitative_signals.csv` |
| Proxy filings | Governance, incentive metrics, capital allocation context | Executive compensation metrics, share counts, governance items | OROS, ROIC, safety, sustainability or strategic compensation metrics if disclosed | Usually lower priority; optional `qualitative_signals.csv` |

## Product, Segment, And Category Taxonomy

Model Deere primarily by segment, then region/product class, then production system or technology category when disclosed. Do not force a SKU taxonomy unless a document provides a specific product metric.

| Level | Category | Examples or subcategories | Typical source | Forecasting use |
|---|---|---|---|---|
| Company | Deere & Company | Consolidated operations, Equipment Operations, Financial Services | 8-K, 10-Q, 10-K, slides | Consolidated sales, net income, EPS, cash flow, capital allocation |
| Business segment | Production & Precision Agriculture (PPA) | Large and certain mid-size tractors, combines, cotton pickers/strippers, sugarcane harvesters/loaders, tillage, seeding, application, crop care, precision ag | 10-K, 8-K, slides | Highest-cycle agriculture exposure; segment sales and margin forecast |
| Business segment | Small Agriculture & Turf (SAT) | Utility and compact tractors, forage harvesters, hay and forage, mowers, utility vehicles, golf, dairy/livestock, high-value crops, small acreage crops | 10-K, 8-K, slides | Smaller ag, livestock, turf, housing, and high-value crop exposure |
| Business segment | Construction & Forestry (CF) | Backhoes, dozers, loaders, skid steers, excavators, graders, articulated dump trucks, timber harvesting, roadbuilding, Wirtgen | 10-K, 8-K, slides | Construction, infrastructure, housing, forestry, and roadbuilding cycle |
| Business segment | Financial Services (FS) | Retail notes, wholesale receivables, revolving charge accounts, leases, extended warranties | 10-K, 10-Q, 8-K | Financing income, portfolio quality, spreads, credit losses, residual values |
| Legacy segment | Agriculture & Turf | Pre-Smart Industrial combined agriculture/turf segment | Older 10-Ks, 8-Ks, slides, calls | Required for historical comparisons before PPA/SAT split |
| Geography | Agriculture regions | U.S. & Canada, Europe/EU28, South America/Brazil/Argentina, Asia/India, Africa/Middle East/CIS | Slides, calls, 10-K | Regional industry outlooks, currency, crop and policy sensitivity |
| Product class | Agriculture equipment class | Large ag, small ag & turf, tractors over 100 hp, 4WD tractors, combines, sprayers, planters, tractors and combines in South America | Slides, calls | Unit outlooks, dealer inventory, used inventory, early order program signals |
| Product class | Construction equipment class | Earthmoving, compact construction, forestry, roadbuilding | Slides, calls, 10-K | C&F demand forecast, infrastructure and housing sensitivity |
| Production system | Ag production systems | Corn and soy, small grains, cotton, sugarcane, dairy and livestock, high-value crops, small acreage crops | 10-K, investor slides, calls | Maps technology and customer-value drivers to PPA/SAT demand |
| Technology stack | Precision and autonomy | Guidance, connectivity, digital solutions, automation/machine IQ, autonomy, Operations Center, See & Spray, Precision Essentials, JDLink Boost | Investor slides, calls, 10-K | Adoption, mix, recurring revenue, differentiation, price realization |
| Channel/inventory | Dealer and field inventory | New dealer inventory, used equipment inventory, order books, backlog, retail demand, trade ladder | Slides, calls, 10-K | Production cadence, wholesale vs retail spread, future shipment risk |

## Target Metric Mapping

| Target field | Company availability | Normalized column | Source document types | Notes |
|---|---|---|---|---|
| Revenue / net sales and revenues | Direct | `net_sales_and_revenues_usd_m` | 8-K, 10-Q, 10-K, slides | Consolidated line includes equipment net sales plus finance/interest/other income. |
| Equipment net sales | Direct | `equipment_net_sales_usd_m` | 8-K, 10-Q, 10-K, slides, calls | Key industrial top-line metric. |
| Segment net sales | Direct | `segment_net_sales_usd_m` | 8-K, 10-Q, 10-K, slides | Use PPA, SAT, CF, FS, Other; legacy Ag & Turf before segment change. |
| Segment operating profit | Direct | `segment_operating_profit_usd_m` | 8-K, 10-Q, 10-K, slides | Operating profit definition excludes some corporate/reconciling items; FS operating profit includes interest and FX effects. |
| Segment operating margin | Direct / Derivable | `segment_operating_margin_pct` | 8-K, slides, calls | Derive from segment operating profit / segment net sales when not explicitly shown. |
| Net income attributable to Deere & Company | Direct | `net_income_attributable_usd_m` | 8-K, 10-Q, 10-K, slides | Primary company guidance metric. |
| Diluted EPS | Direct | `diluted_eps_usd` | 8-K, 10-Q, 10-K, slides | Often included in release tables. |
| Price realization | Direct / qualitative | `price_realization_pct` | 8-K, slides, calls | Often by segment or total equipment operations; sometimes described as points rather than percent. |
| Volume / shipment volume | Different label | `shipment_volume_mix_impact_usd_m` or `volume_mix_commentary` | Slides, releases, calls | Deere usually reports shipment volume or volume/mix, not end-customer unit sales by product. |
| Currency translation | Direct | `currency_translation_pct` | 8-K, slides, calls | Usually percentage points in guidance and sales bridges. |
| Gross margin | Derivable | `gross_margin_pct` | 8-K, 10-Q, 10-K | Can derive from net sales and cost of sales; less central than segment operating margin. |
| Operating return on sales | Direct / Derivable | `oros_pct` | 10-K, calls, investor slides | Equipment Operations OROS is a Deere-specific performance target. |
| Industry unit outlook | Direct | `industry_outlook_low_pct`, `industry_outlook_high_pct` | 8-K, slides, calls | By region and equipment class; highly predictive for segment sales. |
| Dealer inventory | Direct / qualitative | `dealer_inventory_pct_of_ttm_retail_sales` | Slides, calls | Often in units as percent of trailing 12-month retail sales for tractors/combines. |
| Used equipment inventory | Qualitative / partial direct | `used_inventory_change_pct` | Calls | Often given as percent change from peak, sequential change, or directional signal. |
| Backlog / order book | Direct / qualitative | `backlog_usd_m`, `order_book_commentary` | 10-K, calls | 10-K provides annual backlog dollars; calls provide months out or order velocity. |
| Financial Services net income | Direct | `financial_services_net_income_usd_m` | 8-K, 10-Q, 10-K, slides | Separate from equipment operations; affected by portfolio level, spreads, credit losses, residual values. |
| Provision for credit losses | Direct | `provision_for_credit_losses_usd_m` or `credit_loss_provision_bps` | 10-Q, 10-K, calls | Useful for FS income risk. |
| Technology adoption | Direct / qualitative | `technology_metric_value` | Calls, slides, 10-K | Includes engaged acres, highly engaged acres, See & Spray acres, kits/orders, autonomous acres. |
| Product-level SKU price / units | Not generally applicable | `null` | N/A | Deere does not disclose complete SKU-level price-volume time series; use segment/product-class proxies. |

## Recommended CSV Schemas

### `financial_actuals.csv`

Row grain: one row per company-period-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name from front matter or index. |
| `ticker` | string | Ticker from front matter or index. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period, such as `Q4 2025` or `FY 2025`. |
| `source_file` | string | Relative source markdown path. |
| `fiscal_year` | integer | Fiscal year represented by the row. |
| `fiscal_quarter` | string | Fiscal quarter, or `FY` for annual rows. |
| `period_end_date` | date | Period end date when disclosed. |
| `period_length` | string | `quarter`, `year`, `six_months`, or `nine_months`. |
| `net_sales_and_revenues_usd_m` | number | Consolidated net sales and revenues. |
| `equipment_net_sales_usd_m` | number | Net sales from equipment operations. |
| `finance_and_interest_income_usd_m` | number | Finance and interest income, when separately disclosed. |
| `other_income_usd_m` | number | Other income, when separately disclosed. |
| `cost_of_sales_usd_m` | number | Cost of sales. |
| `gross_profit_usd_m` | number | Net sales less cost of sales, if derivable. |
| `gross_margin_pct` | number | Gross profit divided by equipment net sales, if derivable. |
| `net_income_attributable_usd_m` | number | Net income attributable to Deere & Company. |
| `diluted_eps_usd` | number | Diluted earnings per share. |
| `equipment_operations_cash_flow_usd_m` | number | Cash flow from equipment operations. |
| `effective_tax_rate_pct` | number | Effective tax rate, if disclosed. |
| `special_items_note` | string | Text summary of special items affecting comparability. |
| `value_basis` | string | `actual`, `reported`, `restated`, or `adjusted_non_gaap`. |

### `segment_actuals.csv`

Row grain: one row per company-period-segment-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `fiscal_year` | integer | Fiscal year represented by the row. |
| `fiscal_quarter` | string | Fiscal quarter, or `FY`. |
| `segment` | string | Normalized segment: `production_precision_agriculture`, `small_agriculture_turf`, `construction_forestry`, `financial_services`, `other`, `legacy_agriculture_turf`. |
| `segment_reported_name` | string | Exact segment label in source. |
| `segment_schema_version` | string | `current_ppa_sat_cf_fs` or `legacy_ag_turf_cf_fs`. |
| `segment_net_sales_usd_m` | number | Segment net sales or revenues. |
| `segment_operating_profit_usd_m` | number | Segment operating profit. |
| `segment_operating_margin_pct` | number | Segment operating margin. |
| `sales_yoy_change_pct` | number | Reported year-over-year sales change. |
| `operating_profit_yoy_change_pct` | number | Reported year-over-year operating profit change. |
| `price_realization_pct` | number | Segment price realization when disclosed. |
| `currency_translation_pct` | number | Segment currency translation effect when disclosed. |
| `volume_mix_impact_usd_m` | number | Segment volume/mix bridge component from slides. |
| `production_cost_impact_usd_m` | number | Segment production cost bridge component from slides. |
| `warranty_impact_usd_m` | number | Segment warranty bridge component from slides. |
| `sag_rd_impact_usd_m` | number | SA&G/R&D bridge component from slides. |
| `tariff_impact_usd_m` | number | Segment tariff effect when quantified. |
| `driver_commentary` | string | Short source-grounded explanation of major drivers. |

### `guidance_outlook.csv`

Row grain: one row per company-period-guidance metric-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Period for which guidance is issued. |
| `source_file` | string | Relative source markdown path. |
| `guidance_horizon` | string | `next_quarter`, `fiscal_year`, `multi_year`, or `cycle`. |
| `metric` | string | Normalized metric, such as `net_income`, `segment_net_sales_growth`, `segment_operating_margin`, `equipment_cash_flow`, `effective_tax_rate`, `financial_services_net_income`. |
| `segment` | string | Segment if guidance is segment-specific; otherwise `company`. |
| `geography` | string | Geography if relevant. |
| `product_class` | string | Product class if relevant. |
| `value_low` | number | Low end of guidance range. |
| `value_mid` | number | Midpoint if explicitly stated or computed from range. |
| `value_high` | number | High end of guidance range. |
| `unit` | string | `usd_m`, `usd_b`, `pct`, `bps`, `usd_per_share`, or `text`. |
| `direction` | string | `up`, `down`, `flat`, `range`, or `not_specified`. |
| `comparison_period` | string | Period compared against, if disclosed. |
| `assumptions` | string | Price, currency, tariff, tax, cost, or demand assumptions. |
| `quote` | string | Short supporting excerpt. |

### `industry_outlook.csv`

Row grain: one row per company-period-region-product class-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Forecast period. |
| `source_file` | string | Relative source markdown path. |
| `segment` | string | Associated Deere segment. |
| `geography` | string | Region, such as `us_canada`, `europe`, `south_america`, `asia`, `global`. |
| `product_class` | string | `large_ag`, `small_ag_turf`, `tractors_combines`, `construction_equipment`, `compact_construction`, `forestry`, `roadbuilding`, etc. |
| `industry_metric` | string | Usually unit sales outlook. |
| `outlook_low_pct` | number | Low end of outlook range. |
| `outlook_high_pct` | number | High end of outlook range. |
| `outlook_text` | string | Exact source wording, such as `flat to up 5%`. |
| `direction` | string | `up`, `down`, `flat`, or `mixed`. |
| `key_fundamentals` | string | Farm income, commodity price, housing, infrastructure, interest-rate, or policy context. |
| `quote` | string | Short supporting excerpt. |

### `operational_drivers.csv`

Row grain: one row per company-period-segment-driver-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Reported or forecast period. |
| `source_file` | string | Relative source markdown path. |
| `segment` | string | Segment affected by the driver, or `company`. |
| `driver_category` | string | `price`, `volume_mix`, `currency`, `production_cost`, `tariff`, `warranty`, `sag_rd`, `inventory`, `order_book`, `backlog`, `farm_fundamentals`, `construction_fundamentals`, `credit`, `technology`, `capital_allocation`. |
| `driver_name` | string | Specific driver name. |
| `direction` | string | `positive`, `negative`, `neutral`, `mixed`, or `unknown`. |
| `impact_value` | number | Numeric impact if disclosed. |
| `impact_unit` | string | `usd_m`, `pct`, `bps`, `units`, `months`, or `text`. |
| `comparison_period` | string | Prior period or reference point. |
| `driver_scope` | string | `actual`, `guidance_assumption`, `risk`, or `management_action`. |
| `quote` | string | Short supporting excerpt. |

### `financial_services_metrics.csv`

Row grain: one row per company-period-metric-source document for John Deere Financial.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Reported fiscal period. |
| `source_file` | string | Relative source markdown path. |
| `metric` | string | `net_income`, `revenues`, `operating_profit`, `portfolio_balance`, `retail_notes`, `wholesale_receivables`, `leases`, `provision_for_credit_losses`, `credit_loss_bps`, `financing_spread`, `residual_value_losses`. |
| `value` | number | Reported value. |
| `unit` | string | `usd_m`, `bps`, `pct`, or `text`. |
| `direction` | string | Direction versus prior period if disclosed. |
| `driver_commentary` | string | Commentary on spreads, credit losses, residual values, portfolio levels, or volume. |
| `quote` | string | Short supporting excerpt. |

### `technology_adoption.csv`

Row grain: one row per company-period-technology metric-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Period referenced by the metric. |
| `source_file` | string | Relative source markdown path. |
| `technology_category` | string | `guidance`, `connectivity`, `digital`, `automation`, `autonomy`, `aftermarket_retrofit`, `alternative_power`. |
| `technology_name` | string | Operations Center, See & Spray, Precision Essentials, JDLink Boost, harvest settings automation, predictive ground speed automation, autonomous tillage, etc. |
| `metric` | string | `engaged_acres`, `highly_engaged_acres`, `acres_covered`, `orders`, `kits`, `organizations`, `take_rate`, `savings_pct`, `throughput_increase_pct`, `autonomous_acres`. |
| `value` | number | Reported value. |
| `unit` | string | `acres`, `orders`, `kits`, `organizations`, `pct`, or `text`. |
| `geography` | string | Geography if disclosed. |
| `segment` | string | Segment or production system if disclosed. |
| `growth_rate_pct` | number | Year-over-year growth rate if disclosed. |
| `customer_value_claim` | string | Reported customer benefit, such as herbicide savings or labor flexibility. |
| `quote` | string | Short supporting excerpt. |

### `taxonomy.csv`

Row grain: one row per taxonomy item-source document.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Source period. |
| `source_file` | string | Relative source markdown path. |
| `taxonomy_level` | string | `segment`, `legacy_segment`, `geography`, `product_class`, `production_system`, `technology_stack`, `channel`, or `customer_type`. |
| `parent_category` | string | Parent category, if any. |
| `category` | string | Normalized category name. |
| `reported_label` | string | Exact label in source. |
| `examples` | string | Product, customer, or technology examples. |
| `forecasting_use` | string | Why the item matters for forecasts. |

### `qualitative_signals.csv`

Row grain: one row per source-driver signal.

| Column | Type | Description |
|---|---|---|
| `company` | string | Company name. |
| `ticker` | string | Ticker. |
| `published_at` | date | Source document date. |
| `period` | string | Period discussed. |
| `source_file` | string | Relative source markdown path. |
| `signal_category` | string | `demand`, `pricing`, `cost`, `inventory`, `production`, `tariff`, `credit`, `technology`, `policy`, `macro`, `competition`, `capital_allocation`, or `risk`. |
| `segment` | string | Affected segment, or `company`. |
| `geography` | string | Affected geography, if applicable. |
| `product_class` | string | Product class, if applicable. |
| `signal_direction` | string | `positive`, `negative`, `neutral`, or `mixed`. |
| `time_horizon` | string | `current_quarter`, `next_quarter`, `fiscal_year`, `multi_year`, or `cycle`. |
| `summary` | string | Concise normalized signal. |
| `evidence` | string | Short quote or evidence text from the document. |
| `analyst_question_topic` | string | Topic of the analyst question for Q&A rows, if relevant. |

## Forecasting Feature Families

| Feature family | Suggested variables | Source document types | Why it matters |
|---|---|---|---|
| Consolidated actuals | Net sales and revenues, equipment net sales, net income, EPS, cash flow, tax rate | 8-K, 10-Q, 10-K, slides | Core forecast targets and model anchors. |
| Segment performance | Segment sales, operating profit, margin, year-over-year change, OROS | 8-K, 10-Q, 10-K, slides | Deere's cycle exposure and margin profile differ materially by segment. |
| Industry demand | Region/product-class unit outlooks, retail sales, order velocity, backlog, housing/construction indicators | Slides, calls, 10-K | End-market unit cycles drive shipment volume and production planning. |
| Agriculture fundamentals | Farm cash receipts, commodity prices, crop yields, stocks-to-use, acreage, biofuel demand, government payments, farmer liquidity | Calls, slides, 10-K | PPA and SAT demand depends on grower economics and policy support. |
| Construction fundamentals | Housing, home sales, construction spending, infrastructure, rental fleet investment, data centers, forestry, roadbuilding | Calls, slides, 10-K | Main drivers of CF retail demand and channel inventory. |
| Price and currency | Price realization, list price, incentives, pool funds, currency translation | 8-K, slides, calls | Explains sales growth and margin bridge independent of volume. |
| Cost and margin | Production costs, tariffs, material costs, labor, warranty, SA&G/R&D, cost reductions, mix | 8-K, slides, calls | Deere margins are highly sensitive to production absorption, tariffs, warranty, and geographic/product mix. |
| Channel inventory | Dealer inventory ratios, used inventory, trade ladder, underproduction/overproduction, production cadence | Slides, calls | Inventory condition affects wholesale shipments and future demand pull-forward/risk. |
| Financial Services | FS net income, spreads, portfolio levels, credit loss provision, lease residual values | 8-K, 10-Q, 10-K, calls | Financing can stabilize or pressure consolidated earnings and equipment demand. |
| Technology adoption | Engaged acres, highly engaged acres, See & Spray acres, autonomy acres, kit orders, take rates, savings, organizations | Calls, slides, 10-K | Measures Smart Industrial progress, pricing power, recurring revenue potential, and customer value. |
| Capital allocation | Dividends, buybacks, capex, R&D, rating/liquidity priorities | Slides, calls, 10-K | Useful for EPS, cash deployment, and through-cycle investment assumptions. |

## Extraction Priority

1. Extract 8-K earnings releases and earnings slides first. They provide the cleanest quarterly actuals, segment actuals, operating bridges, industry outlooks, and formal guidance.
2. Extract prepared remarks and Q&A transcripts next. They add the assumptions behind the numbers: price-cost, tariffs, production cadence, inventory, regional demand, order books, technology adoption, and management confidence.
3. Extract 10-Q and 10-K filings for accounting-quality actuals, segment definitions, backlog, Financial Services portfolio metrics, risk factors, and legacy-to-current segment mapping.
4. Extract investor-day and strategy slides for taxonomy and longer-horizon features around production systems, technology stack, autonomy, aftermarket, retrofit, and margin ambitions.
5. Use proxy filings only for compensation metric context or capital allocation/governance signals; they are lower priority for quarterly forecasting.

## Caveats

- Segment definitions changed over time. Older documents report Agriculture & Turf as a combined segment, while current documents split Production & Precision Agriculture and Small Agriculture & Turf. Keep legacy and current segment labels rather than forcing a false historical split.
- Deere fiscal quarters use company-specific period end dates, often late October/early November for fiscal year end. Store both fiscal period and period end date when disclosed.
- Earnings releases often duplicate content and may include OCR artifacts or repeated pages. Prefer structured tables and cross-check with slides or 10-Q/10-K values.
- Operating profit is a segment measure with Deere-specific reconciliation items. Do not treat it as GAAP operating income without preserving the source definition.
- Price realization, currency translation, volume/mix, and production cost are sometimes reported in percentage points and sometimes as waterfall dollars. Preserve units exactly and normalize only when clear.
- Industry outlooks are usually unit-demand ranges, not Deere revenue guidance. Keep `industry_metric` and `unit` explicit.
- Product-level price, product-level unit volume, and SKU mix are not consistently available. Use segment, product class, region, inventory, and early order program proxies.
- Financial Services metrics follow a different economic model from equipment manufacturing. Model portfolio levels, spreads, credit losses, and residual values separately from equipment sales.
- Technology adoption metrics are powerful but inconsistently reported. Capture exact definitions, geography, and whether values are cumulative, annual, or current-period.
- Management commentary is forward-looking and often conditional on commodity prices, tariffs, trade policy, interest rates, weather, and government support. Preserve quotes and assumptions for auditability.
