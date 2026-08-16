# Aggregator library — design

Date: 2026-08-16
Status: proposed, awaiting approval

## 1. Purpose

The aggregator is the **"piece of code that aggregates"** box in the whiteboard sketch. It sits
below signal generation and feeds it:

```
corpus (1,139 md files)
   -> [aggregator]            <- this document
   -> [signal generation]
   -> [time series / ML model]
   -> Result
```

Contract: given `(company, period, metric)`, return **defensible data points** — every value
carries `path`, `line_no` and a verbatim `quote`. A signal generator must not be able to emit a
figure it cannot point at.

Today's output surface is 12 numbers (4 workbooks x 3 metrics, cells `C7`/`C8`/`C9` of the
`Summary` sheet). The library is **not** built for those 12. It must generalise on two axes:

- **company axis** — a fifth company is a config entry, not a code change (section 12);
- **metric axis** — an arbitrary metric ("free cash flow", "backlog", "conversion rate",
  "operating margin", a segment's revenue) is answerable without hand-authoring aliases
  (section 9).

The metric axis is the harder one and drives most of this design.

## 2. Design driver A: corpus metadata is unreliable

The `period:` frontmatter field cannot be used as a filter. Demonstrated failures:

| Document | Reality | `period:` says |
|---|---|---|
| `analog-devices/filings/2026-05-20__adi-us-20260520-q2-10q__1040607.md` | ADI Q2 FY2026 10-Q | `"Q3 2026"` |
| `hays/filings/2026-06-08__...-filing-2__1383897.md` | same day/type as sibling | `"Q3 2026"` |
| `hays/filings/2026-06-08__...-filing__1383898.md` | sibling of the above | `"June 2026"` |
| `analog-devices/call-transcripts/2026-06-02__...-call-conf-qna__1135033.md` | one event, split file | `"Q2 2026"` |
| `analog-devices/call-transcripts/2026-06-02__...-call-conf-pres__1135032.md` | same event, other half | `"FY 2026"` |

The value space is also unnormalised: bare `"Q4"` (20 docs), `"Q3"` (10 docs), `"June 2026"`,
`"H1 2021"`, `"FY 2025"`.

Consequence: `period == "Q2 2026"` **drops the actual Q2 10-Q** and admits unrelated buyback
notices. Any design trusting this field is non-deterministic by construction.

## 3. Design driver B: the period lives in the table column, not the document

This is the largest silent-error source in the pipeline, and it is measured, not assumed:

| Document | Column headers present |
|---|---|
| `adi-us-20230823-q3-10q` | **74x "Nine Months Ended"** + 70x "Three Months Ended" |
| `hd-us-20250825-q2-10q` | 27x "Six Months Ended" + 13x "Three Months Ended" + 1x "Twelve Months Ended" |
| `adi-us-20250219-q1-10q` | "Three Months Ended" only (Q1 has no YTD distinction) |

A 10-Q interleaves quarterly and year-to-date columns roughly 50/50. Extracting "ADI Q3 revenue"
by finding the `Revenue` row and taking a number has a coin-flip chance of returning the
**nine-month** figure — roughly 3x too large, and entirely plausible-looking.

Results tables additionally carry the **prior-year comparative** in an adjacent column:

```
|         | Aug. 2, 2025 | Aug. 3, 2024 | Change |
| Revenue | $ 2,880      | $ 2,312      | 25 %   |
```

Therefore: **`DataPoint.period` is a property of the column, never of the document.** A document
has one `period_of_record`; its tables contain values for several periods.

This is not only a hazard — it is an asset. One ADI Q3 10-Q legitimately yields Q3 FY2025,
Q3 FY2024, 9M FY2025 and 9M FY2024 as four separately-cited data points. That is precisely the
history the time-series stage needs, and it comes free.

## 4. What is reliable

### 4.1 Filename structure

Every document is named `YYYY-MM-DD__<ticker>-<cc>-YYYYMMDD-<KIND>__<id>.md`. `KIND` partitions
the corpus deterministically (counts over 1,139 docs):

| Class | KIND values | n | Period signal |
|---|---|---|---|
| `STRUCTURED_RESULT` | `q{1..4}-8k` (177), `q{1..4}-10q` (108), `q4-10k` (34), `h1/h2-8k` (25), `fy-10k` (18), `fy-8k` (7), `call-q{1..4}-*` (21), `call-h2-*` (2) | 371 | token is authoritative |
| `EARNINGS_CALL` | `call-pres` (225), `call-qna` (207) | 432 | date + fiscal calendar |
| `SLIDE` | `slide` | 94 | date + fiscal calendar |
| `GENERIC_FILING` | `filing`, `filing-2` | 138 | title classification required |
| `CONFERENCE` | `call-conf-pres/qna` | 43 | **no period of record** |
| `AGM` | `call-agm-pres/qna` | 34 | annual only |

### 4.2 Fiscal calendars

Derived by cross-tabulating the 371 filename tokens against publication month. Zero
cross-contamination observed (e.g. all 25 ADI `-q2-` files publish in May).

| Company | FY end | Q1 rpt | Q2 rpt | Q3 rpt | Q4/FY rpt | FY label rule |
|---|---|---|---|---|---|---|
| Analog Devices | ~1 Nov | Feb | May | Aug | Nov | `FY = year(report)` |
| Deere | ~end Oct | Feb | May | Aug | Nov | `FY = year(report)` |
| Home Depot | ~end Jan | May | Aug | Nov | Feb | `FY = year(report)`, **except Q4: `year - 1`** |
| Hays | 30 Jun | Oct | Jan-Feb (H1) | Apr | Jul-Aug (FY) | `FY = year(report)`, **except Q1 (Oct-Dec): `year + 1`** |

Verified against document bodies: `hd-us-20250819-q2-8k` says "fiscal 2025";
`hd-us-20260224-q4-8k` is FY2025 Q4 (prior-year label); `adi-us-20250820-q3-8k` says
"fiscal 2025"; `has-ln-20260227-h1-8k` is H1 FY2026.

Both forecast targets (ADI FY2026Q3, HD FY2026Q2) report ~19-20 Aug 2026, after the 2026-08-14
freeze. They are genuinely unreported. Hays FY2026 results publish ~Aug 2026, also post-freeze —
but the **2026-07-10 Q4 trading update is in-corpus** and carries FY2026 net fees commentary.

### 4.3 Known calendar outliers

`2020-07-13__adi-...-q3-8k`, `2020-10-24__adi-...-q4-10k`, `2020-10-24__adi-...-q4-8k`,
`2021-09-08__adi-...-q4-8k`. A 10-K dated 2020-10-24 precedes ADI's own FY2020 year-end, so at
least one is mis-dated in the corpus. This is why the filename token outranks the date rule, and
why conflicts are reported rather than silently resolved.

### 4.4 Unit captions are a small closed vocabulary

Table-level unit context is declared in a caption immediately above the table, and the
vocabulary is enumerable (corpus-wide counts):

| Caption | n |
|---|---|
| `(In £s million)` | 1175 |
| `(In millions of dollars)` | 750 |
| `(in thousands)` / `(In thousands)` | 459 |
| `(In millions of dollars and shares except per share amounts)` | 176 |
| `(in millions)` | 181 |
| `(in millions, except per-share amounts and percentages)` | 45 |
| `(In thousands, except per share amounts)` | 64 |

Two things follow. First, deterministic unit resolution is tractable — roughly 20 patterns cover
the corpus. Second, `(in thousands)` appears 459 times against a `USDm` output cell: an
unguarded scale factor is a silent 1000x error. Note also that the captions **declare their own
exceptions** ("except per share amounts"), so per-share rows correctly escape the scale factor.

## 4A. The interface

Sections 7-11 are the **internal** model; nobody types against them. The public object is the
**Panel** — one table the four pipelines write into and the model reads from. Single-value
lookup is the drill-down, never the main path.

### 4A.0 The Panel is the product

```python
from aggregator import Panel

p = Panel.challenge()      # the 12 targets from companies.json, history pre-filled
```

```
>>> p
Panel · 4 companies · 12 targets · corpus frozen 2026-08-14

  COMPANY  PERIOD      METRIC                        VALUE   ORIGIN     HIST
  ADI      FY2026Q3    Revenue                          —    —          24q
  ADI      FY2026Q3    Adjusted diluted EPS             —    —          24q
  ADI      FY2026Q3    Adjusted gross margin            —    —          24q
  HD       FY2026Q2    Net sales                        —    —          28q
  ...
  HAS      FY2026      Pre-exceptional basic EPS        —    —          11y

  12 targets · 0 filled · 12 gaps   ->  p.gaps()
```

One call, everything staged: every target row, every metric's cited history, nothing filled.
`assemble()` does the work once; `gaps()` names what is still missing. (The repo is called
mind-the-gaap; the gap report is the point.)

```python
p.history("ADI", "Adjusted diluted EPS")     # cited series -> the time-series/ML box
p.to_csv() / p.to_dict()                     # hand off
p.to_workbooks("submission/")                # writes all four .xlsx, C7:C9
```

### 4A.1 The four pipelines push into it

This is the write side your sketch needs — "4 pipelines assemble data for Quarter, each data
point should be defensible". A pipeline contributes a value the same way the extractor does, and
is held to the same standard:

```python
p.push("ADI", "FY2026Q3", "Adjusted diluted EPS",
       value  = 2.31,
       origin = "pipeline:sentiment",
       because= "Q2 call guided Q3 EPS to $2.28 +/- 0.10; bookings commentary skews high",
       cites  = ["adi-us-20260520-q2-8k.md:71", "adi-us-20260520-call-pres.md:212"])
```

`cites` is **required**. A push without citations raises `Undefensible` — the pipeline cannot
contribute an unsupported number, which is the constraint your sketch wrote in the margin,
enforced by the API instead of by discipline.

Pushes never overwrite. Competing values coexist and are visible:

```
>>> p
  ADI  FY2026Q3  Adjusted diluted EPS   2.31   pipeline:sentiment   24q
                                        2.28   pipeline:guidance    24q
                                        2.34   pipeline:timeseries  24q
                                          —    CONSENSUS: 3 sources disagree -> p.resolve(...)
```

Resolution is an explicit act (`p.resolve(...)`, or the ML stage writing `origin="model"`), never
a silent average.

### 4A.2 Queries return documents, not just numbers

Numbers are one output; the **document set** is the other, and it is what the signal subagents
consume. This is the original requirement — "q2 EPS, find the relevant files for it" — and it is
served by the same hard-filter machinery, so retrieval and extraction can never disagree about
what counts as a Q2 document.

```python
docs = p.docs("ADI", "FY2025Q3")
```

```
DocSet · ADI FY2025Q3 · 7 of 271 documents

  KIND        PUBLISHED    TITLE                                        CONF
  q3-8k       2025-08-20   Third Quarter Financial Results and Q4 ...   1.00
  q3-10q      2025-08-20   Quarterly Report on Form 10-Q                1.00
  call-pres   2025-08-20   Third Quarter Earnings Call                  0.95
  call-qna    2025-08-20   Earnings Call Q&A                            0.95
  slide       2025-08-20   Q3 FY25 Earnings Presentation                0.95
  ...
  264 excluded  ->  docs.excluded()
```

Filters compose, all of them hard predicates:

```python
p.docs("ADI", "FY2025Q3", kind="transcript")   # call-pres + call-qna only
p.docs("ADI", "FY2025Q3", metric="EPS")        # only docs that actually state the metric
p.docs("ADI", "FY2026Q2", kind="transcript")   # Q3 guidance lives in the Q2 call
```

Each document opens up:

```python
for d in docs:
    d.path, d.kind, d.period, d.published_at
    d.text()             # full markdown body
    d.tables()           # parsed tables, each column carrying its PeriodSpan
    d.excerpts("EPS")    # passages naming the metric, with line numbers
```

```
>>> docs["q3-8k"].excerpts("EPS")
 L61   | Diluted earnings per share | $ | 1.04 | $ 0.79 | 32 % |
 L67   | Adjusted diluted earnings per share | $ | 2.05 | $ 1.58 | 30 % |
 L21   "ADI's third-quarter revenue and earnings per share exceeded the high end of
        our expectations," stated CEO and Chair Vincent Roche.
```

Note the third hit: prose, not a table. Sentiment and guidance signals live in exactly that kind
of passage, which is why `excerpts()` spans both.

A `DocSet` hands back its own citations, so a pipeline that reads documents can push a value
without hand-assembling provenance:

```python
docs  = p.docs("ADI", "FY2026Q2", kind="transcript")
score = sentiment.score(docs.text())
p.push("ADI", "FY2026Q3", "Adjusted diluted EPS",
       value=2.31, origin="pipeline:sentiment",
       because=f"tone score {score:+.2f} on Q2 call",
       cites=docs.cites())        # <- defensibility for free
```

This is the join between the two halves of the library: `docs()` feeds the signal subagents,
`push()` takes their conclusions back, and both are anchored to the same period predicate.

### 4A.3 Drill-down: values are numbers that carry their evidence

`Value` subclasses `float`. Arithmetic works; printing shows the citation.

```python
>>> v = adi.q3(2025).eps()
>>> v * 4
8.2
>>> v
2.05 USD/share  ·  ADI FY2025Q3 (3 months to 2025-08-02)
  "Adjusted diluted earnings per share ... $ 2.05"
  adi-us-20250820-q3-8k.md:67   (corroborated x2)
```

This is how "each data point should be defensible" stops being a convention: the number and its
proof are the same object, and the proof cannot be dropped by passing it along.

```python
>>> v.why()
ADI FY2025Q3 · adjusted diluted EPS = 2.05 USD/share

ACCEPTED
  adi-us-20250820-q3-8k.md:67   2.05   "| Adjusted diluted earnings per share | $ | 2.05 | ..."
  adi-us-20250820-q3-8k.md:349  2.05   "| Adjusted diluted EPS* | $ 2.05 | $ 1.58 | $ 5.53 | ..."

REJECTED
  :349 col4   5.53   Nine Months Ended Aug. 2, 2025 - query needs 3 months
  :349 col3   1.58   prior-year comparative (FY2024Q3)
  :61         1.04   GAAP basis, not adjusted
  call-conf-qna 2026-03-03   CONFERENCE - no period of record

PERIOD  FY2025Q3 from filename token `q3` + fiscal calendar (agree). Frontmatter said
        "Q3 2025" (agrees, not used).
UNITS   caption "(in millions, except per-share amounts and percentages)" -> per-share row
        escapes the millions scale factor.
```

### 4A.4 Metrics are named, not spelled out

Facets are inferred from the metric name; keyword arguments override only when needed.

```python
adi.q3(2025).eps()                       # challenge default: adjusted, diluted
adi.q3(2025).eps(basis="gaap")           # 1.04
adi.q3(2025).gross_margin()              # 62.1  (percent)
adi.q3(2025)["free cash flow"]           # free text, same parser
de.q3(2025).operating_profit(segment="production & precision ag")
```

Named accessors are generated from `data/concepts.json`, so a new concept in JSON becomes
`adi.q3(2025).backlog()` with no Python change. That keeps section 9.5's promise honest at the
interface, not just internally.

### 4A.5 Failures explain themselves and name the fix

```python
>>> hays.fy(2025).eps()
AmbiguousMetric: 'eps' matches 2 rows in has-ln-20250821-h2-8k.md

  [1]   1.31 GBp   Basic earnings per share (before exceptional items)   L49
  [2]  -0.49 GBp   Basic earnings per share                              L50

  These differ in sign. Disambiguate:
      hays.fy(2025).eps(basis="pre_exceptional")   <- companies.json asks for this
      hays.fy(2025).eps(basis="gaap")

>>> hays.q2(2026).eps()
NotReported: Hays reports H1/FY; Q2 carries no EPS disclosure.
  Nearest available:  hays.h1(2026).eps()      (has-ln-20260227-h1-8k.md)
```

An exception that prints the corrected call is the difference between a usable library and a
frustrating one. Silence and best-effort guesses are both banned.

### 4A.6 History for the time-series stage

```python
>>> adi.history("eps", quarters=8)
ADI · adjusted diluted EPS · USD/share
  FY2024Q4  1.67   q4-8k.md:71
  FY2025Q1  1.63   q1-8k.md:66
  FY2025Q2  1.85   q2-8k.md:66
  FY2025Q3  2.05   q3-8k.md:67
  ...
  8 points · 8 cited · 0 estimated
```

Because prior-year comparative columns are separately attributed (section 3), each report
contributes more than one point, and the series states its own coverage.

### 4A.7 Discovery and CLI

```python
>>> adi.metrics("margin")          # what can I even ask for?
adjusted gross margin    62.1 %    seen 88x   q3-8k.md:59
gross margin percentage  62.1 %    seen 41x   q3-8k.md:58
operating margin         28.4 %    seen 37x   q3-8k.md:60
```

```bash
$ python -m aggregator ADI q3-2025 eps
2.05 USD/share   ADI FY2025Q3 (3 months to 2025-08-02)
  adi-us-20250820-q3-8k.md:67

$ python -m aggregator ADI q3-2025 eps --why      # full accepted/rejected trace
$ python -m aggregator ADI --list-metrics
```

### 4A.8 The escape hatch

`aggregate()` and the dataclasses of sections 7-11 remain available as `.raw`:

```python
adi.q3(2025).eps().raw          # -> DataPoint
adi.q3(2025).eps.result()       # -> AggregateResult (excluded, ambiguities, warnings)
```

The fluent layer is a facade over them, so nothing is hidden — only defaulted.

## 5. Non-goals

- Not a general full-text search engine. `starter/search.py` already does that and is explicitly
  "search leads rather than verified financial history". This library is the opposite: narrow,
  hard-filtered, cited.
- Not a forecaster. It returns evidence; the ML stage makes judgements.
- Not a workbook writer.
- Not an LLM wrapper. Query-time behaviour is deterministic and reproducible.

## 6. Architecture

```
agent/aggregator/
  fiscal.py     # FiscalPeriod, PeriodSpan; per-company calendars; date <-> period
  classify.py   # filename KIND -> DocClass; title -> noise/signal for GENERIC_FILING
  corpus.py     # walk, parse frontmatter, build + cache index (JSON)
  periods.py    # evidence-ranked period-of-record resolver
  facets.py     # metric facet grammar — parses BOTH queries and table row labels
  catalogue.py  # mines the corpus for the queryable metric vocabulary
  tables.py     # markdown table parser; column -> PeriodSpan; caption -> unit context
  units.py      # scale/currency normalisation
  extract.py    # facet match + cell read -> cited DataPoint
  query.py      # aggregate(), list_metrics() — public API
  registry.py   # declarative per-company config
  data/
    concepts.json   # concept lexicon AS DATA, not code
    modifiers.json  # adjustment / share_basis / statistic lexicons
```

Python, standard library only, matching `starter/search.py`'s dependency-free style.

Nothing under `agent/signal_subagents/` is reused: that path contains a single 0-byte file named
`sentiment`, added by commit `52e5ab9` as a placeholder. We keep the directory convention (it
matches the sketch's "signal generation" box) and write our own types.

## 7. Data model

```python
class DocClass(Enum):
    STRUCTURED_RESULT = auto(); EARNINGS_CALL = auto(); SLIDE = auto()
    GENERIC_FILING = auto();    CONFERENCE = auto();    AGM = auto()

@dataclass(frozen=True)
class FiscalPeriod:
    fy: int
    quarter: int | None = None   # None => full-year
    half: int | None = None      # Hays reports H1/FY, not Q2/Q4

@dataclass(frozen=True)
class PeriodSpan:                # what a TABLE COLUMN refers to
    end_date: date
    months: int                  # 3 | 6 | 9 | 12  <- kills the YTD trap
    fiscal: FiscalPeriod

@dataclass(frozen=True)
class MetricSpec:                # see section 9
    concept: str
    adjustment: str | None = None
    share_basis: str | None = None
    scope: str | None = None
    statistic: str = "level"
    unit_class: str = "currency_abs"

@dataclass(frozen=True)
class Evidence:
    source: str    # filename_token | fiscal_calendar | title | body | frontmatter
    rank: int      # 1 = strongest
    period: FiscalPeriod | None
    detail: str    # what matched, verbatim

@dataclass(frozen=True)
class Document:
    path: str; company: str; ticker: str
    published_at: date
    doc_class: DocClass; kind: str; title: str
    period_of_record: FiscalPeriod | None
    period_confidence: float
    evidence: tuple[Evidence, ...]
    conflicts: tuple[str, ...]

@dataclass(frozen=True)
class DataPoint:                 # "each data point should be defensible"
    metric: MetricSpec
    value: float
    unit: str                    # canonical: USDm | GBPm | GBp | per_share | pct | bps
    span: PeriodSpan             # from the COLUMN, not the document
    source_path: str
    line_no: int
    row_label: str               # verbatim label as printed
    quote: str                   # verbatim source line, unedited
    extractor: str               # which rule fired
    confidence: float

@dataclass(frozen=True)
class AggregateResult:
    query: Query
    datapoints: tuple[DataPoint, ...]
    documents: tuple[Document, ...]
    excluded: tuple[tuple[str, str], ...]   # (path, reason) — auditable
    ambiguities: tuple[str, ...]            # >1 facet-equal row; never auto-resolved
    warnings: tuple[str, ...]
```

`excluded` is not optional. Every rejected document is recorded with a reason, so "why didn't it
find X" is answerable without rerunning anything.

## 8. Period-of-record resolution

```
resolve(doc):
  1. doc_class = classify(filename KIND)
  2. CONFERENCE                      -> period_of_record = None   (off-cycle)
     AGM                             -> FY only
     GENERIC_FILING w/ noise title   -> None, marked noise
  3. gather Evidence, ranked:
       1  filename token (-q2-, -h1-, -fy-)  -> fixes QUARTER; FY from calendar rule
       2  published_at + fiscal calendar     -> fixes (FY, QUARTER)
       3  title regex  ("Fiscal Second Quarter", "Half-Year Report")
       4  body regex, first ~40 lines ("fiscal 2025 second quarter")
       5  frontmatter period:                -> RECORDED ONLY, never decides
  4. period_of_record = highest-ranked non-None evidence
  5. confidence = f(agreement among ranks 1-4)
  6. conflicts  = every disagreement, including rank 5
```

`NOISE_PATTERNS` for `GENERIC_FILING`, from observed Hays titles (~33 of 123 filings):
`Notification of Major Holdings`, `Transaction in Own Shares`, `Voting Rights and Capital
Notification`, `Total Voting Rights Notification`, `Director/PDMR Shareholding Notification`,
`PDMR Shareholding Notification`, `Change of Registered Office`, `Daily Share Buyback
Transaction Log`. No financial content; must never enter a metric query.

## 9. Metric generalisation: a facet grammar

### 9.1 Why alias lists fail

`challenge/companies.json` asks for **`Pre-exceptional basic EPS`**. The Hays document prints:

```
| Basic earnings per share (before exceptional items) (2) | 1.31p | 4.03p | (67)% |
```

Not one word in common beyond "basic". An alias table would need this mapping hand-written, for
every metric, for every company, for every phrasing — which is exactly the thing that does not
generalise to "whatever metric they're looking for next".

### 9.2 The mechanism

Decompose metrics into orthogonal facets, and run **the same parser on both sides** — the user's
query string and every table row label in the corpus. A match is facet equality.

```
"Pre-exceptional basic EPS"
    -> concept=eps, adjustment=pre_exceptional, share_basis=basic, statistic=level, unit=per_share

"Basic earnings per share (before exceptional items) (2)"
    -> concept=eps, adjustment=pre_exceptional, share_basis=basic, statistic=level, unit=per_share
                                                                                  == MATCH
```

Nobody wrote that alias. It falls out of the decomposition.

### 9.3 The lexicons

**Concepts** — open and extensible. This is the generalisation point:

```python
CONCEPTS = {
  "eps":              ["earnings per share", "eps"],
  "revenue":          ["revenue", "net sales", "turnover", "net sales and revenues"],
  "net_fees":         ["net fees"],
  "operating_profit": ["operating profit", "operating income"],
  "gross_margin":     ["gross margin"],
  "free_cash_flow":   ["free cash flow"],
  "profit_before_tax":["profit before tax", "pre-tax profit"],
  "conversion_rate":  ["conversion rate"],
  ...
}
```

**Concept identity follows accounting identity, not synonymy.** Hays reports both `Turnover` and
`Net fees`; they are different quantities, so `net_fees` is its own concept and must not be
folded into `revenue`. Getting this wrong is a category error, not a matching error.

**Modifiers** — closed lexicons, shared by every concept:

| Facet | Values |
|---|---|
| `adjustment` | `adjusted`, `non-GAAP`, `GAAP`, `reported`, `before exceptional items` / `pre-exceptional`, `underlying`, `like-for-like` / `LFL` |
| `share_basis` | `basic`, `diluted` |
| `statistic` | `level`, `margin` / `percentage`, `growth` / `change`, `pct_of_revenue` |
| `scope` | `total` / `total company`, plus segment names from the company registry |

Adding a metric means adding **one concept entry**. It composes automatically with every
adjustment, basis, statistic and scope — so `adjusted free cash flow as a percentage of revenue`
works without anyone authoring that string. That is the generalisation the metric axis needs.

### 9.4 Determinism under ambiguity

If a query's facets match more than one distinct row label within a table, the aggregator returns
**all** candidates with their verbatim labels and records the ambiguity in
`AggregateResult.ambiguities`. It never silently picks. Same principle as period conflicts:
surface, don't guess.

Unspecified facets are wildcards but are reported. Querying bare `EPS` against a table containing
both `Basic` and `Diluted` rows returns two data points and one ambiguity note — not a coin flip.

### 9.5 The queryable set is mined, not declared

The facet grammar makes *arbitrary* metrics matchable. This section makes the **set of askable
metrics** itself change over time without code changes. Three commitments:

**(a) The lexicons are data.** `data/concepts.json` and `data/modifiers.json` are loaded at
runtime. Adding `backlog`, `days sales outstanding` or `bookings` is a JSON edit — no Python
touched, no redeploy of logic. Nothing about the 12 current metrics is compiled in.

**(b) Today's targets are read, not baked.** The 12 metrics come from
`challenge/companies.json` at runtime. Change that file (or point at a different challenge) and
the targets change. The library has no notion of "the three ADI metrics".

**(c) The catalogue is discovered from the corpus.** Because `tables.py` already parses every row
label, the vocabulary can be inverted into a catalogue of what is *actually reported*. Measured
over the corpus:

| | |
|---|---|
| Row-label occurrences | 144,826 |
| Distinct labels | 10,595 |
| Seen >=10x | 2,222 |
| Seen >=25x | 1,058 |
| Seen >=100x | 237 |

The head is exactly the queryable surface one would want — `net income` (1,262), `net sales`
(1,101), `operating profit` (500), `diluted earnings per share` (343), `cost of sales` (654),
`research and development expenses` (369) — none of which anyone declared. Deere's segments
surface as row labels too (`financial services` 577, `construction and forestry` 540,
`agriculture and turf` 531), so the `scope` facet populates itself.

Mining runs **only over period-bearing document classes** (`STRUCTURED_RESULT`, `SLIDE`). This
is not an optimisation: the top raw label corpus-wide is `bnp paribas sa` at 13,467 occurrences,
an analyst roster inside call-transcript tables. The existing `DocClass` filter removes that
whole family. Caption lines misparsed as rows (`in millions`, `(in £s million)`) and bare
structural labels (`total`, `other`, `name`) are dropped by an explicit stop-list.

This yields a new public call:

```python
def list_metrics(company: str, *, period: str | None = None,
                 min_occurrences: int = 10) -> MetricCatalogue
```

returning each discovered metric with its parsed `MetricSpec`, occurrence count, the document
classes it appears in, and an example citation. Point the library at a new corpus and the
queryable set grows on its own.

**(d) Unknown concepts degrade, they do not fail.** A query naming a concept absent from
`concepts.json` falls back to deterministic string matching against the mined catalogue. Any
result is returned with `confidence` capped low, flagged in `warnings` as an unregistered
concept, and accompanied by the exact JSON snippet to add if the user wants to promote it to a
first-class concept. The fallback is ordinary string matching, so it stays reproducible — an
unregistered metric is *worse supported*, never nondeterministic.

## 10. Table extraction

1. **Segment** the document into markdown tables plus the caption line(s) above each.
2. **Resolve the unit context** from the caption (section 4.4), honouring declared exceptions.
3. **Resolve each column to a `PeriodSpan`** from the header rows: `"Three Months Ended
   Aug. 2, 2025"` -> `(end=2025-08-02, months=3)`; Hays `"Year ended 30 June ... 2025"` ->
   `(end=2025-06-30, months=12)`. Bare year headers inherit the caption's duration.
4. **Parse row labels into `MetricSpec`** via `facets.py`, stripping footnote markers `(1)`,
   `(2)` for matching while retaining them for provenance.
5. **Read the cell**, normalise the value, emit a `DataPoint` citing `line_no` and the verbatim
   row.

Value normalisation, each a named failure mode with table-driven tests:

- `$ 2,880` under `(in millions...)` -> `2880.0 USDm`
- `"$2.88 billion"` in prose -> `2880.0 USDm`
- `1.31p` -> `1.31 GBp` (**pence, not pounds** — Hays EPS units are `GBp`; a 100x trap)
- `(0.49)p` -> `-0.49 GBp` (parenthesised negative)
- `62.1 %` -> `62.1 pct` (template: "enter 4.5 for 4.5%")
- `540 bps` -> `540 bps`, never silently converted to a percentage
- any figure under `(in thousands)` -> scaled by 1/1000 to reach `USDm` (a 459-occurrence trap)

A column whose `months` does not match the query's requested duration is **excluded by hard
predicate**, not down-ranked.

## 11. Public API and determinism guarantee

```python
@dataclass(frozen=True)
class Query:
    company: str
    period: str          # "FY2026Q3" | "FY2026" | "FY2026H1"
    metric: MetricSpec

def parse_query(text: str, *, company: str) -> Query      # "q2 adjusted EPS" -> Query
def aggregate(query: Query, *, corpus: Corpus) -> AggregateResult
def list_metrics(company: str, *, period: str | None = None,
                 min_occurrences: int = 10) -> MetricCatalogue   # what CAN be asked
```

`list_metrics` is the discoverability half of the contract: a caller that does not already know
which metrics exist can enumerate them, then query them. Without it, "queryable metrics change in
future" would still require someone to know the new metric's name out of band.

**The guarantee: period and duration are hard predicates, not score terms.** A column is in the
Q2 set or it is not; no relevance weight can promote a Q3 or a nine-month column into a Q2
answer. Ranking only orders *within* an already-correct set. That is what makes "Q2 only finds
Q2" testable rather than aspirational.

Two consequences handled explicitly rather than fudged:

1. **Hays has no Q2 financials.** It reports H1 and FY, with Q1/Q3 trading updates carrying net
   fees only. `aggregate` returns an empty result with warning `NotReportedAtThisGranularity` —
   not a best-effort pile of buyback notices.
2. **Guidance lives in the prior quarter's document.** ADI's Q3 outlook is published in the Q2
   8-K. One period axis cannot express this, so `periods_mentioned` is deferred to phase 6.

## 12. Company onboarding: derived, not configured

A hand-authored `CompanyConfig` is generalisable and **dumb**: adding a company still requires a
human who already knows its fiscal calendar, segments and reporting granularity. The system would
degrade to whatever the config author happened to know.

But every company fact used in this document was derived mechanically from the corpus during
design — calendars from token/month cross-tabs, granularity from token distribution, segments
from row labels, noise from title clusters. **That analysis is the onboarding algorithm.** It
belongs in code, not in a config file.

```python
profile = Profiler.fit("challenge/offline-data/nvidia/")
```

### 12.1 What is derived

| Property | Derived from |
|---|---|
| Fiscal year end | explicit period-end statements ("year ended February 1, 2026") |
| Quarter report months | period-end dates x publication dates |
| FY label offset | company's own fiscal label co-located with a period-end date |
| Granularity | which period tokens/statements exist at all (H1/FY vs Q1-Q4) |
| Reporting lag | median (publication date - period end) |
| Segments | recurring row labels in revenue/profit tables that sum to a stated total |
| Noise titles | title clusters on documents whose bodies contain no financial table |
| Currency and scale | caption vocabulary (section 4.4) |
| House basis | which adjustment facet the company headlines (section 12.4) |

### 12.2 Evidence ranking, and why frequency-counting is wrong

Deriving the FY label by counting `fiscal YYYY` mentions is the archetypal
generalisable-but-dumb move. Measured:

| Document | Published | Dominant mention | Naive offset | Truth |
|---|---|---|---|---|
| `hd-us-20260224-q4-8k` | 2026-02-24 | `fiscal 2025` (27) vs `2026` (3) | -1 | -1 (correct) |
| `hd-us-20260519-q1-8k` | 2026-05-19 | `fiscal 2026` (21) vs `2025` (11) | 0 | 0 (correct) |
| `de-us-20251126-q4-8k` | 2025-11-26 | **`Fiscal 2026` (6)** vs `2024` (4) | **+1** | **0 (WRONG)** |

Deere's Q4 release leads with FY2026 guidance, so forward-looking text outvotes the results it
is reporting. Frequency derives Deere's calendar backwards.

The same document contains the fix: `"year ended February 1, 2026"`. Period-end **dates** are
facts; fiscal **labels** are commentary. So the profiler ranks evidence:

```
1  explicit period-end date statements ("quarter/year ended <Month D, YYYY>")
2  filename period tokens x publication month
3  fiscal label co-located with a results table or period-end statement
4  global fiscal-label frequency          <- weakest; demonstrably misleading
```

Rank 4 is retained only to flag disagreement, never to decide — the same discipline as the
frontmatter `period:` field in section 8.

### 12.3 Self-certification

A derived profile is not trusted because it was derived. It must predict held-out evidence:

```
>>> profile.report()
CompanyProfile · NVDA · derived from 214 documents

  fiscal year end     ~ last Sunday of January        conf 0.98   (61 period-end statements)
  report months       Q1 May · Q2 Aug · Q3 Nov · Q4 Feb          conf 1.00
  FY label offset     Q4: -1                          conf 0.96   (co-located labels, 23 docs)
  granularity         QUARTERLY                       conf 1.00
  reporting lag       21 days (median)                conf 0.94
  segments            Data Center, Gaming, ...        conf 0.89   (sum-to-total verified)
  house basis         non-GAAP diluted                conf 0.91
  currency / scale    USD · millions                  conf 1.00

  SELF-TEST  predicted period == filename token on 88/88 held-out docs   PASS

  UNKNOWN (1)
    noise titles — no clear cluster; all filings contain financial tables
```

The 371-document golden set of section 13 is the same test with the company axis free. It
generalises to any corpus that has period tokens; where a corpus has none, the profiler falls
back to rank-1 period-end statements and reports the lower confidence rather than hiding it.

**Anything the profiler cannot determine is `UNKNOWN`, never guessed.** An unknown fiscal
calendar makes period queries fail loudly with the reason, which is the honest failure. A guessed
calendar produces confident wrong numbers, which is the dangerous one.

### 12.4 Smart metric resolution: house convention

Companies headline different bases. `companies.json` records the consequence — ADI is asked for
`Adjusted diluted EPS`, Deere for `Diluted EPS (GAAP)`, Hays for `Pre-exceptional basic EPS` —
but that is an artefact of the challenge, not something a new company would supply.

The profiler infers it: the basis a company puts in its results-summary table and press-release
headline bullets is its house convention. So a bare query resolves to what *that company* means:

```python
adi.q3(2025).eps()      # 2.05   adjusted diluted   (ADI headlines adjusted)
de.q3(2025).eps()       #        GAAP diluted       (Deere headlines GAAP)
hays.fy(2025).eps()     # 1.31p  pre-exceptional basic
```

Explicit facets always override, and where no basis clearly dominates the query raises
`AmbiguousMetric` (section 4A.5) rather than picking. Being smart means knowing the convention;
it does not mean guessing when the evidence is genuinely split.

### 12.5 The override path

Derivation is the default, not a mandate. Any field can be pinned, and a pinned value that
contradicts strong evidence produces a warning rather than silent acceptance:

```python
profile = Profiler.fit("…/nvidia/").pin(fy_label_offset={4: -1})
```

`registry.py` therefore stores *derived* profiles as a cache, with human pins layered on top —
inverting the original design, where humans authored and code consumed.

### 12A. The stored profile

`registry.py` caches one *derived* profile per company; the literal below is the profiler's
output, not a hand-authored entry:

```python
CompanyConfig(
    ticker="ADI",
    aliases=("ADI", "Analog Devices", "adi-us"),
    fiscal=FiscalCalendar(report_months={1: 2, 2: 5, 3: 8, 4: 11}, fy_offset={}),
    granularity=Granularity.QUARTERLY,
    segments=("Industrial", "Automotive", "Communications", "Consumer"),
    noise_titles=(...),
)
```

Home Depot's `fy_offset={4: -1}` and Hays' `fy_offset={1: +1}` / `granularity=HALF_YEARLY` are
**derived** (section 12.2), not supplied. A fifth company is a `Profiler.fit()` call over its
document directory — no config entry and no code change — which is what makes this reusable for
the ongoing OpenStocks events after the hackathon.

Metrics are deliberately **not** in `CompanyConfig`. They live in the shared facet lexicons
(`data/concepts.json`), so a metric added for one company is immediately available for all — and
`segments` above is a seed for the `scope` facet, not an authority: `catalogue.py` discovers
segment labels from the corpus regardless (section 9.5c).

## 13. Test strategy — ground truth we already own

The 371 filename-tokened documents are a **labelled evaluation set at zero cost**:

```
for every tokened doc:
    resolve_from_date(published_at, company) == token_quarter
```

If the date rule scores ~100% against tokens (with the four known ADI outliers asserted as
*known* exceptions, never silently passed), it is trustworthy on the 768 untokened documents.
This catches the Home Depot Q4 year-offset immediately if the rule is wrong.

Further tests:

- **Purity:** for each company and quarter, no document or column in the result set resolves to a
  different period. Zero tolerance.
- **Duration:** no `months != 3` column ever satisfies a quarterly query. Regression-tested
  against `adi-...-q3-10q` (74 nine-month columns) and `hd-...-q2-10q` (27 six-month columns).
- **Comparative:** the prior-year column of a results table is attributed to the prior year.
- **Noise rejection:** no Hays `Notification of Major Holdings` appears in any metric query.
- **Conference exclusion:** all 43 `call-conf-*` documents have `period_of_record is None`.
- **Facet round-trip:** every one of the 12 `companies.json` labels parses to a `MetricSpec` that
  matches the corresponding real row label in a real document. This is the metric-axis
  equivalent of the golden set.
- **Units:** table-driven cases for millions, thousands, billions-in-prose, pence, parenthesised
  negatives, percentages, bps.
- **Catalogue purity:** `list_metrics()` never returns `bnp paribas sa`, `total`, `other`, `name`,
  or a caption line such as `(in £s million)`.
- **No metrics compiled in:** a test deletes every entry from `data/concepts.json` and asserts
  the 12 `companies.json` labels stop resolving as registered concepts (falling back to the mined
  catalogue). This is the executable proof that the metric set is data, not code.

TDD per `superpowers:test-driven-development` — golden-set and facet round-trip tests are written
before their implementations.

## 14. Phases

| # | Deliverable | Exit criterion |
|---|---|---|
| 1 | `fiscal.py`, `classify.py`, `periods.py` | 371/371 golden set; 4 ADI outliers asserted as known |
| 2 | `corpus.py`, hard-filter document selection | purity + noise-rejection tests pass |
| 3 | `tables.py`, `units.py` | duration + comparative + unit tests pass |
| 4 | `facets.py`, `extract.py` -> cited `DataPoint` | facet round-trip passes for all 12 labels |
| 5 | `profiler.py`, `registry.py`, lexicons moved to `data/*.json` | profiler self-test passes on all 4 companies with **no hand-written calendar**; zero metrics compiled in |
| 6 | `catalogue.py`, `list_metrics()` | catalogue of a company's reported metrics with citations; unknown-concept fallback |
| 7 | `periods_mentioned` axis | guidance retrieval for the target quarter |

Phases 1-4 are "create the aggregating library". Phases 5-6 are "make it generalizable": 5 opens
the *company* and *metric* axes to configuration, 6 makes the queryable set self-discovering so it
grows with the corpus rather than with hand-authored config. Phase 7 is deferred because the ML
stage needs history before it needs guidance.

Phase 3 is sequenced before phase 4 deliberately: the YTD/comparative column trap (section 3) is
a larger measured error source than metric matching, so it gets fixed first.

## 15. Risks

| Risk | Mitigation |
|---|---|
| YTD column read as quarterly (~3x error) | `PeriodSpan.months` hard predicate; regression test on the 74-column ADI Q3 10-Q |
| Prior-year comparative read as current | Column-level period resolution; explicit comparative test |
| `(in thousands)` read as millions (1000x) | Caption-driven unit context; 459 occurrences make this near-certain if unguarded |
| Hays EPS in pence read as pounds (100x) | `GBp` is a distinct canonical unit; `companies.json` confirms `GBp` |
| Fiscal calendar wrong for a company | Golden-set test over 371 labelled docs, phase 1 |
| Corpus contains mis-dated documents (confirmed: 4 ADI) | Filename token outranks date; conflicts surfaced |
| Hays granularity mismatch vs quarterly query | Explicit `NotReportedAtThisGranularity` |
| New metric matches several rows | `ambiguities` returned; never auto-resolved |
| Concept conflation (`net fees` vs `revenue`) | Concept identity follows accounting identity; asserted in tests |
| A future metric nobody registered | Deterministic fallback to the mined catalogue, flagged low-confidence with the JSON snippet to register it |
| Profiler derives a calendar backwards from guidance text | Period-end **dates** outrank fiscal **labels**; Deere Q4 is the regression case |
| Profiler confident but wrong on a new company | Self-test against held-out tokened docs; `UNKNOWN` over guessing; pins warn on contradiction |
| Mined catalogue polluted by non-financial tables | Mine only period-bearing doc classes; stop-list for captions and bare structural labels (`bnp paribas sa` at 13,467x is the motivating case) |
| Target quarters post-freeze and unreported | By design — that is the forecast; guidance axis (phase 6) supplies signal |

## 16. Open questions

1. **"Last Quarter only"** on the sketch — does this scope the aggregator to a single target
   quarter, or only the initial orchestration skeleton? The time-series stage needs multi-quarter
   history, so the aggregator is specified here to handle any period; confirm.
2. **"4 pipelines"** — one per company, or four signal pipelines per company
   (filings / transcripts / slides / market)? Affects call count, not `aggregate()`'s signature.
