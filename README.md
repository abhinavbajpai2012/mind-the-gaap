# Agents vs Wall Street

Agents vs Wall Street is a one-day hackathon presented by Primer, OpenStocks, AI Tinkerers and OpenAI. Around 50 people will build 20–25 forecasting agents, working alone or in teams of up to four.

The challenge covers four companies: Home Depot, Analog Devices, Hays plc and Deere & Company. Your agent forecasts three reported figures for each.

The repository includes a frozen historical corpus of 1,139 filings, call-transcript sections and slide documents for the four known companies. Start at [challenge/offline-data/INDEX.md](challenge/offline-data/INDEX.md) or search the Markdown files directly.

Your agent should be able to do the research, make the financial judgements and produce completed OpenStocks workbooks with as little manual help as possible.

## What the day is for

1. **Build something real.** Create a repeatable agent that researches companies, makes financial judgements and produces completed forecast workbooks.
2. **Show what is possible.** Help us learn what works and show how powerful this technology can be when it is assembled properly.

OpenStocks offers ongoing $100 prizes for individual earnings events after the hackathon, so build an agent you can use again.

## The challenge at a glance

- Doors open at 10:00 on Sunday 16 August 2026 at Ground Floor, 33 Johns Mews, London WC1N 2QL. The competition briefing begins at 10:30 and building starts at 11:15.
- Teams can have one to four people.
- Each individual or team enters one agent.
- Each team receives $50 of Codex credit, kindly provided by OpenAI.
- Competition-specific work must be built during the event; evidence of a pre-made entry means disqualification from all prizes.
- Your agent must forecast three figures for each of four companies.
- The final run starts at 17:15 and must finish before the 18:00 deadline.
- OpenStocks opens for challenge uploads at 17:30.
- Your final command must produce all four `.xlsx` workbooks.
- Upload each workbook manually to the matching company Forecast Model on [openstocks.com](https://openstocks.com).
- If you upload more than once, the last valid workbook uploaded for each company before 18:00 is your final forecast.

## What you need to submit

1. A completed private `entry.json` with the agent name, every team member and email address, technical setup and final-run details. Upload it through openstocks.com/hackathon; no account is needed for this private team-entry form.
2. Your code repository and the commit used for the final run.
3. The completed self-contained `architecture/index.html`, uploaded through the same private form. You do not need to host it anywhere.
4. A timestamped log from a clear run of the system.
5. Four completed company workbooks in `submission/`.

Complete [ENTRY.md](ENTRY.md), then read [SUBMISSION.md](SUBMISSION.md) before the final run. The full event rules are in [RULES.md](RULES.md), the day is set out in [SCHEDULE.md](SCHEDULE.md), and the judging process is explained in [JUDGING.md](JUDGING.md).

By submitting the private team entry, your team accepts the hackathon and prize rules in [RULES.md](RULES.md).

## Expected final output

Your final command can use any language or framework, and it can run the four companies one after another or at the same time. It must finish by creating these exact files:

```text
submission/
├── ADI-FY2026Q3.xlsx
├── DE-FY2026Q3.xlsx
├── HAS-FY2026.xlsx
└── HD-FY2026Q2.xlsx
```

Start from the supplied files in `challenge/templates/`. Do not rename the `Summary` sheet, metric labels, units or fiscal-period column.

Run `npm install` and `npm run setup:entry` once. Complete the private `entry.json` and `architecture/index.html`, then use `npm run check:submission` before uploading. It checks the entry record, architecture file and four workbooks. It does not judge whether the forecasts are good.

## Running our agent

Everything is one command. It indexes the corpus, resolves every document's
fiscal period, extracts cited history, runs the call-tone signal, selects a
forecast method by backtest and writes all four workbooks.

### Requirements

- **Python 3.12+** — `numpy scipy pandas scikit-learn pydantic openpyxl`
- **Node 20.11+** *only* for the organisers' check scripts. They use
  `import.meta.dirname`, so Node 18 fails with `ERR_INVALID_ARG_TYPE` before
  reading anything. If you have nvm: `nvm use 20`.

```bash
pip3 install numpy scipy pandas scikit-learn pydantic openpyxl
```

### The final run

```bash
python3 main.py --cli --audit
```

Takes roughly two minutes from cold. It prints the twelve forecasts, writes
`submission/*.xlsx` and a timestamped run log to `logs/`. `--audit` is what
produces the log; drop it and everything else still happens.

Restrict it to one company while iterating:

```bash
python3 main.py --cli --company ADI
```

### The control room

```bash
python3 main.py
```

Serves a UI on <http://127.0.0.1:8420/> and opens a browser. Type a company (or
leave it blank for all four) and press start; stages light up as they finish.
Below the forecasts is the **backtest panel**: per target, the winning model,
its out-of-sample MAPE and the baseline it had to beat. `/architecture`
explains the design.

The first request builds the index and takes ~40s; every run after that is
seconds.

### Checking a figure

No number is taken on trust — each one reports what it accepted *and what it
refused*:

```python
from agent.aggregator.panel import Panel
p = Panel.challenge()

p.value("ADI", "FY2025Q3", "Adjusted diluted EPS", "USD / share")
# 2.05 USD/share · FY2025Q3 (3 months to 2025-08-02) · adi-us-20250820-q3-8k.md:67

p.value("ADI", "FY2025Q3", "Adjusted diluted EPS", "USD / share",
        strict=False).why()
# ACCEPTED  :67  2.05 …
# REJECTED  :349c3  9-month column ('Nine Months Ended Aug. 2, 2025') — needs 3
#           :349c2  column period FY2024Q3 != FY2025Q3
```

Command line equivalents:

```bash
python3 -m agent.aggregator ADI FY2025Q3 "Adjusted diluted EPS" --units "USD / share" --why
python3 -m agent.aggregator ADI FY2025Q3 x --docs --kind transcript
python3 -m agent.aggregator DE x x --list-metrics
python3 -m agent.aggregator --fit challenge/offline-data/deere
```

### CSVs and backtest

```bash
python3 -c "from agent.aggregator.panel import Panel; from agent.export_csv import export_all; export_all(Panel.challenge())"
```

Writes `output/<company>/`: `metrics_long`, `metrics_wide` (the modelling
table), `categories_master` (per segment: sales, profit, margin, mix),
`guidance`, `call_signals`, `document_inventory`. Extraction is deterministic —
the same parser the forecasts use — so no cell can be invented.

### Tests

```bash
python3 -m agent.aggregator.tests.test_aggregator
```

Includes the golden-set check: fiscal calendars are *derived* from each
company's documents, then have to predict the period token in the filenames of
371 filings. Nothing about the four companies is hand-written — Home Depot's
February Q4 belonging to the prior fiscal year, and Hays reporting half-years,
are both discovered.

### Adding a company or a metric

```python
from agent.aggregator.profiler import fit          # any directory of documents
fit("challenge/offline-data/nvidia/").report()   # derives the calendar, self-tests
```

A new metric is one entry in `agent/aggregator/data/concepts.json`; it composes
with every adjustment, share basis and statistic automatically. See
[agent/aggregator/README.md](agent/aggregator/README.md).

### Submitting

```bash
nvm use 20            # the check scripts need Node 20.11+
npm install
npm run check:submission
```

## Optional document-search helper

[`starter/search.py`](starter/search.py) is a small, dependency-free example of searching the supplied Markdown corpus and producing a cited research note. It does not make forecasts or edit a workbook.

```bash
python3 starter/search.py --company HD
less research/HD.md
```

Use `HD`, `ADI`, `HAS` or `DE` for the four challenge companies. The output contains search leads rather than verified financial history, so check each figure in its cited document. Read [starter/README.md](starter/README.md) for narrower searches and testing instructions.

## Repository map

```text
main.py                    One command: index, forecast, write the workbooks
agent/aggregator/          Deterministic, cited extraction from the corpus
agent/forecast/            Feature building and model selection
agent/signal_subagents/    Call-tone and other text signals
agent/export_csv.py        Corpus -> ML-ready CSVs in output/
ui/                        Control room and architecture pages
output/                    Generated CSVs and backtest results
challenge/                 Companies, metrics, workbooks and historical documents
architecture/index.html    Template for the required architecture explanation
entry.template.json        Template for private team and agent details
submission/                Put the four completed workbooks here
logs/                      Save the final clear-run log here
scripts/                   Local entry and workbook checks
starter/                   Optional historical-document search helper
```

## Licence

The original code and documentation in this repository are available under the [MIT License](LICENSE). The historical company documents under `challenge/offline-data/` are excluded; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
