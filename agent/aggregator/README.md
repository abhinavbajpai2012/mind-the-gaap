# Aggregator — team handoff

**What it is:** the layer between the 1,139-document corpus and everything we build on top.
You ask it for a metric or a set of documents; it gives you back numbers that carry their own
citations. It does **not** forecast — that's the signal + model stages.

**Status:** working. `python3 -m agent.aggregator.tests.test_aggregator` → all checks pass.
Verified against 10 hand-checked figures across all four companies.

---

## 60-second start

```python
from agent.aggregator.panel import Panel

p = Panel.challenge()          # takes ~30s; builds the index for all 4 companies
print(p)                       # the 12 targets we have to fill
```

**Get a number:**

```python
p.value("ADI", "FY2025Q3", "Adjusted diluted EPS", "USD / share")
# 2.05 USD/share · FY2025Q3 (3 months to 2025-08-02) · adi-us-20250820-q3-8k.md:67 (corroborated x2)
```

It's a real `float` — `v * 4` works. It just prints its provenance.

**Get the documents** (this is what the signal subagents want):

```python
docs = p.docs("ADI", "FY2025Q3")                      # everything for that quarter
docs = p.docs("ADI", "FY2025Q3", kind="transcript")   # just the earnings call
docs = p.docs("ADI", "FY2026Q2", kind="transcript")   # Q3 guidance lives in the Q2 call

for d in docs:
    d.text()              # full markdown
    d.excerpts("EPS")     # just the passages that mention it, with line numbers
```

**Hand documents straight to a signal subagent** (bridges to `abc_subagent.SignalInput`):

```python
from agent.signal_subagents.abc_subagent import SignalInput
from agent.signal_subagents.sentiment import SentimentSignal

result = SentimentSignal().run(SignalInput(**p.signal_input("ADI", "FY2026Q3")))
# qa_neg='typical' · qa_neg_change='stable' · lag-1 call 2026-05-20 · baseline 8 calls
```

`signal_input(company, period)` is **not** `docs(company, period)`. It hands over the
company's whole run of transcripts and carries `period` separately as the period being
*forecast* — a signal that standardises a company against its own past needs years, not
one quarter. Give the call-tone signal a single quarter and every channel abstains,
correctly and uselessly. Each document arrives with its **resolved** period and class, so
the subagent never touches the front matter that labels Deere's May 2026 Q2 call
`"Q3 2026"`.

Backtesting a period that has already reported? Pass `as_of=` and the call that announced
the number is dropped:

```python
p.signal_input("HD", "FY2025Q2", as_of="2025-08-19")
```

The twelve challenge targets don't need it — the corpus is frozen before all twelve
prints.

**Push your pipeline's answer back:**

```python
p.push("ADI", "FY2026Q3", "Adjusted diluted EPS",
       value=2.31,
       origin="pipeline:sentiment",
       because="Q2 call guided $2.28 +/- 0.10; bookings commentary skews high",
       cites=docs.cites())          # <-- REQUIRED, or it raises Undefensible
```

**History for the model:**

```python
p.history("ADI", "Adjusted diluted EPS", "USD / share", periods=8)
```

**CLI, if you'd rather:**

```bash
python3 -m agent.aggregator --panel
python3 -m agent.aggregator ADI FY2025Q3 "Adjusted diluted EPS" --units "USD / share"
python3 -m agent.aggregator ADI FY2025Q3 x --docs --kind transcript
python3 -m agent.aggregator DE x x --list-metrics
python3 -m agent.aggregator --fit challenge/offline-data/deere
```

---

## The one thing to understand

**Everything is a hard filter, never a relevance score.** If you ask for Q2, you cannot get a Q3
document or a nine-month column. When it can't answer, it raises instead of guessing:

```python
p.value("HAS", "FY2026Q2", "eps")
# NotReported: Hays reports H1/FY; Q2 carries no eps disclosure. Nearest: FY2026H1

p.value("HAS", "FY2025", "eps")          # strict=True (default)
# AmbiguousMetric: 2 distinct values match eps: 'Basic earnings per share
#   (before exceptional items)'=1.31GBp; 'Basic earnings per share'=-0.49GBp
```

That second one is a **sign flip** — pass the full label (`"Pre-exceptional basic EPS"`) and it's
unambiguous. Pass `strict=False` if you want it to pick the best-ranked candidate anyway.

**Every value can explain itself:**

```python
p.value("ADI","FY2025Q3","Adjusted diluted EPS","USD / share", strict=False).why()
```
```
ACCEPTED
  adi-us-20250820-q3-8k.md:349   2.05  | Adjusted diluted EPS* | $ 2.05 | $ 1.58 | $ 5.53 ...
  adi-us-20250820-q3-8k.md:67    2.05  | Adjusted diluted earnings per share | $ | 2.05 ...
REJECTED
  ...:349c3   9-month column ('Nine Months Ended Aug. 2, 2025') — query needs 3
  ...:349c2   column period FY2024Q3 != FY2025Q3
```

Use `p.audit()` to dump this for every target — that's our submission run log.

---

## Why it's built this way (the traps it exists to avoid)

These are all real, measured in this corpus. Each one produces a confident, plausible, wrong
number if you do the obvious thing:

| Trap | Reality |
|---|---|
| **`period:` frontmatter is wrong** | It labels the ADI Q2 FY2026 10-Q as `"Q3 2026"`. We never use it. |
| **YTD columns** | The ADI Q3 10-Q has 74 "Nine Months Ended" headers next to 70 "Three Months". Grabbing the wrong one is a ~3x error. |
| **Prior-year comparatives** | Every results table has last year's column right next to this year's. |
| **`(in thousands)`** | Appears 459x. Against a `USDm` cell that's a 1000x error. |
| **Hays EPS is in pence** | `1.31p` is 1.31 `GBp`, not £0.0131. A 100x error. |
| **HD's Q4 is the prior fiscal year** | The Feb 2026 8-K is *fiscal 2025* Q4. Only HD does this. |
| **Investor conferences** | 43 docs on random dates with no reporting period. Excluded. |
| **Admin filings** | ~33 Hays "Notification of Major Holdings" etc. Zero financial content. Excluded. |
| **Identical row labels** | Deere prints `Diluted` twice in one table: 4.75 (EPS) and 271.4 (share count). Only the section header tells them apart. |

---

## Adding things

**A new metric** — edit `agent/aggregator/data/concepts.json`, add one entry:

```json
"backlog": ["backlog", "order backlog"]
```

It automatically composes with every adjustment (`adjusted`, `pre-exceptional`, …), share basis,
and statistic. You don't write "adjusted backlog" or "backlog growth" — those fall out.

**A new company** — no config to write:

```python
from agent.aggregator.profiler import fit
fit("challenge/offline-data/nvidia/").report()
```

It derives the fiscal calendar, the FY label offset, granularity, reporting lag and currency from
the documents, then self-tests against the filename tokens. All four of our companies' calendars
are derived this way — nothing is hand-written, including HD's `Q4: -1` and Hays' `Q1: +1`.

**Don't know what to ask for?**

```python
from agent.aggregator.catalogue import list_metrics
list_metrics(p, "DE", min_occurrences=25)      # mined from the corpus, not declared
```

---

## Files

```
fiscal.py     periods, spans, calendars
classify.py   filename -> document class
corpus.py     walk + frontmatter
profiler.py   derives a company's calendar (no hand config)
periods.py    5-rank evidence resolution
tables.py     markdown tables; column -> period + duration
units.py      scale/currency/sign normalisation
facets.py     metric grammar (query side AND document side)
extract.py    facet match -> cited DataPoint
catalogue.py  mine the queryable metric vocabulary
panel.py      Panel, DocSet, Value   <- the public interface
```

Design doc with the full reasoning: `docs/superpowers/specs/2026-08-16-aggregator-design.md`

## Known gaps

- `p.to_workbooks()` is not written yet — the .xlsx writer is still to do.
- `segments` are not yet wired into the `scope` facet, so
  `"Production & Precision Ag operating profit"` won't resolve yet (the other 11 targets do).
- Guidance retrieval (finding Q3 guidance inside the Q2 8-K) is designed but not built.
- Hays golden-set self-test is 66/67; one October document is a genuine corpus outlier and is
  reported, not hidden.
- `history()` skips periods it can't cite — older filings (roughly pre-2023) format their tables
  differently, so ~11 of any 16 consecutive quarters resolve. It walks further back to fill your
  requested count rather than returning short, but the series can have holes. Check the returned
  periods, don't assume they're contiguous.
