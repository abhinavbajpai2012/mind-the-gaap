"""Regression tests. Run: python3 -m agent.aggregator.tests.test_aggregator

No test framework dependency, matching starter/test_search.py's style.
"""

from __future__ import annotations

import re
import sys

from ..classify import DocClass
from ..facets import parse as parse_facets
from ..fiscal import FiscalPeriod
from ..panel import AmbiguousMetric, NotReported, Panel, Undefensible
from ..profiler import fit_all
from ..units import parse_cell, parse_unit_caption

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")


def close(name: str, got, want, tol=0.01) -> None:
    ok = got is not None and abs(float(got) - want) <= max(tol, abs(want) * 0.001)
    if not ok:
        FAILS.append(f"{name}: got {got!r}, want ~{want}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}  ({got})")


# ---------------------------------------------------------------------------
def test_golden_calendars():
    """The 371 filename-tokened documents are a labelled evaluation set.

    A derived calendar must predict the token from the publication date alone.
    """
    print("\n[golden set] derived calendars predict filename tokens")
    profiles = fit_all()
    total_ok = total_n = 0
    for ticker, prof in sorted(profiles.items()):
        ok, n = prof.selftest
        total_ok += ok
        total_n += n
        print(f"  {ticker:5} {ok}/{n}")
    check("golden set size is 371 tokened docs", total_n, 371)
    ratio = total_ok / total_n
    print(f"  overall {total_ok}/{total_n} = {ratio:.3%}")
    if ratio < 0.99:
        FAILS.append(f"golden set below 99%: {total_ok}/{total_n}")

    # the two fiscal-label traps must be DERIVED, never hand-written
    check("HD Q4 belongs to the prior fiscal year",
          profiles["HD"].calendar.fy_offset.get(4), -1)
    check("Hays Q1 (Oct-Dec) belongs to the next fiscal year",
          profiles["HAS"].calendar.fy_offset.get(1), 1)
    check("Hays is a half-yearly reporter",
          profiles["HAS"].calendar.granularity, "HALF_YEARLY")
    check("ADI has no fiscal-label offset", profiles["ADI"].calendar.fy_offset, {})
    check("Deere has no fiscal-label offset", profiles["DE"].calendar.fy_offset, {})


def test_facet_roundtrip():
    """Every challenge label must match the real row label in a real document."""
    print("\n[facets] challenge labels match document row labels")
    pairs = [
        ("Adjusted diluted EPS", "USD / share", "Adjusted diluted earnings per share"),
        ("Pre-exceptional basic EPS", "GBp",
         "Basic earnings per share (before exceptional items) (2)"),
        ("Net fees", "GBPm", "Net fees (1)"),
        ("Pre-exceptional operating profit", "GBPm",
         "Operating profit (before exceptional items) (2)"),
        ("Diluted EPS (GAAP)", "USD / share", "Diluted earnings per share"),
        ("Revenue", "USDm", "Revenue"),
        ("Adjusted gross margin", "%", "Adjusted gross margin percentage"),
        ("Net sales", "USDm", "Net sales"),
        ("Worldwide net sales and revenues", "USDm", "Total net sales and revenues"),
    ]
    for query, unit, row in pairs:
        q = parse_facets(query, unit_hint=unit)
        r = parse_facets(row)
        check(f"{query!r} ~ {row[:34]!r}", q.matches(r), True)

    # concept identity follows accounting identity, not synonymy
    check("net fees is not revenue",
          parse_facets("Net fees").concept != parse_facets("Revenue").concept, True)
    # a section header disambiguates identical labels
    check("'Diluted' under Per Share Data is EPS",
          parse_facets("Diluted Per Share Data").concept, "eps")
    check("'Diluted' under Average Shares Outstanding is not EPS",
          parse_facets("Diluted Average Shares Outstanding").concept != "eps", True)


def test_units():
    print("\n[units] scale, currency and sign")
    check("(in thousands) scales to millions",
          parse_unit_caption("(in thousands)").scale, 1e-3)
    check("(In £s million) is GBP",
          parse_unit_caption("(In £s million)").currency, "GBP")
    check("per-share exemption is detected",
          parse_unit_caption("(in millions, except per-share amounts)").per_share_exempt,
          True)
    check("pence suffix beats the table caption", parse_cell("1.31p")[1], "GBp")
    check("parenthesised pence is negative", parse_cell("(0.49)p")[0], -0.49)
    check("percentage stays a percentage", parse_cell("62.1 %")[1], "pct")
    check("basis points are not percentages", parse_cell("540 bps")[1], "bps")
    ctx = parse_unit_caption("(in thousands)")
    close("1,789,748 thousand is 1,789.7 million", parse_cell("1,789,748", ctx)[0], 1789.748)


def test_extracted_values(panel: Panel):
    """Known values, verified by hand against the source documents."""
    print("\n[values] extraction against hand-verified figures")
    cases = [
        ("ADI", "FY2025Q3", "Adjusted diluted EPS", "USD / share", 2.05),
        ("ADI", "FY2025Q3", "Revenue", "USDm", 2880),
        ("ADI", "FY2025Q3", "Adjusted gross margin", "%", 69.2),
        ("HAS", "FY2025", "Net fees", "GBPm", 972.4),
        ("HAS", "FY2025", "Pre-exceptional operating profit", "GBPm", 45.6),
        ("HAS", "FY2025", "Pre-exceptional basic EPS", "GBp", 1.31),
        ("DE", "FY2025Q3", "Diluted EPS (GAAP)", "USD / share", 4.75),
        ("DE", "FY2025Q3", "Worldwide net sales and revenues", "USDm", 12018),
        ("HD", "FY2025Q2", "Net sales", "USDm", 45277),
        ("HD", "FY2025Q2", "Adjusted diluted EPS", "USD / share", 4.68),
    ]
    for ticker, period, metric, units, want in cases:
        try:
            got = panel.value(ticker, period, metric, units, strict=False)
        except (NotReported, AmbiguousMetric) as exc:
            FAILS.append(f"{ticker} {metric}: {exc}")
            print(f"  FAIL {ticker} {period} {metric}: {exc}")
            continue
        close(f"{ticker} {period} {metric}", got, want)


def test_ytd_trap(panel: Panel):
    """The nine-month column must be refused with a stated reason, not missed."""
    print("\n[YTD trap] nine-month and prior-year columns are rejected")
    v = panel.value("ADI", "FY2025Q3", "Adjusted diluted EPS", "USD / share", strict=False)
    reasons = " ".join(r for _, r in v.extraction.rejected)
    check("a 9-month column is rejected", "9-month column" in reasons, True)
    check("a prior-year column is rejected", "FY2024Q3" in reasons, True)
    check("no accepted value is the 9-month figure",
          all(abs(float(dp.value) - 5.53) > 0.001 for dp in v.extraction.accepted), True)
    check("every accepted point is a 3-month column",
          all(dp.span.months == 3 for dp in v.extraction.accepted), True)


def test_document_hygiene(panel: Panel):
    print("\n[documents] noise and off-cycle exclusion")
    all_has = panel._docs["HAS"]
    conf = [d for d in panel._docs["ADI"] if d.doc_class == DocClass.CONFERENCE]
    check("conferences carry no period of record",
          all(d.period is None for d in conf), True)
    check("there are conference documents to exclude", len(conf) > 0, True)
    noise = [d for d in all_has if "Major Holdings" in d.title]
    check("administrative filings carry no period",
          all(d.period is None for d in noise), True)
    check("there are noise filings to exclude", len(noise) > 0, True)

    # 'call-q4-qna' is an earnings call that happens to name its quarter, not a
    # results document. Classifying it as one hid 27 calls from kind="transcript",
    # including 4 of Deere's last 8 quarters.
    tagged = [d for company in panel._docs.values() for d in company
              if re.match(r"^call-(q[1-4]|h[12])", d.kind)]
    check("there are quarter-tagged call files", len(tagged) > 20, True)
    check("a quarter-tagged call is still an earnings call",
          {d.doc_class for d in tagged}, {DocClass.EARNINGS_CALL})

    docs = panel.docs("ADI", "FY2025Q3")
    check("every returned document is in the requested period",
          all(d.period == FiscalPeriod(2025, quarter=3) for d in docs), True)
    check("the Q3 8-K is present",
          any(d.kind == "q3-8k" for d in docs), True)


def test_granularity(panel: Panel):
    print("\n[granularity] Hays has no Q2")
    try:
        panel.value("HAS", "FY2026Q2", "Pre-exceptional basic EPS", "GBp")
        FAILS.append("Hays Q2 should raise NotReported")
        print("  FAIL Hays Q2 did not raise")
    except NotReported as exc:
        check("Hays Q2 raises NotReported with a pointer", "H1" in str(exc), True)


def test_signal_bridge(panel: Panel):
    """Panel.signal_input() -> SignalInput -> a signal subagent, end to end.

    The seam has three ways to look fine and be useless: hand over one period's
    documents to a signal that needs history, hand over the front-matter period
    instead of the resolved one, or hand over documents the subagent then
    silently drops. Each is checked here on real corpus documents.
    """
    from ...signal_subagents.abc_subagent import SignalInput
    from ...signal_subagents.sentiment import SentimentSignal

    print("\n[bridge] aggregator -> signal subagent")

    si = panel.signal_input("ADI", "FY2026Q3")
    check("the target period is carried, not the documents'", si["period"], "Q3 2026")
    check("history comes with it, not one quarter",
          len(si["relevant_documents"]) > 40, True)
    check("a period-scoped DocSet is still one period",
          len(panel.docs("ADI", "FY2026Q2", kind="transcript")), 2)

    # The corpus labels Deere's May 2026 Q2 call "Q3 2026" in its front matter.
    call = next(d for d in panel.signal_input("DE", "FY2026Q3")["relevant_documents"]
                if "de-us-20260521-call-qna" in d["path"].name)
    check("documents carry the resolved period", call["period"], "FY2026Q2")
    check("documents carry the aggregator's class", call["doc_class"], DocClass.EARNINGS_CALL)

    # All twelve targets are for unreported periods, so every signal must produce a
    # reading rather than abstain; abstention here means the bridge starved it.
    for ticker, period in [("HD", "FY2026Q2"), ("ADI", "FY2026Q3"),
                           ("HAS", "FY2026"), ("DE", "FY2026Q3")]:
        out = SentimentSignal().run(SignalInput(**panel.signal_input(ticker, period)))
        check(f"{ticker} {period} scores rather than abstains",
              out.qa_neg is not None and out.n_baseline >= 6, True)
        check(f"{ticker} lag-1 call is dated before the print",
              out.as_of_call < "2026-08-14", True)

    # A backtest must not read the call that announced the number.
    before = SentimentSignal().run(
        SignalInput(**panel.signal_input("HD", "FY2025Q2", as_of="2025-08-19")))
    check("as_of drops the print's own call", before.as_of_call < "2025-08-19", True)

    # Wrong input fails loudly, naming what it was given.
    try:
        SentimentSignal().run(SignalInput(**panel.signal_input("ADI", "FY2026Q3",
                                                              kind="filing")))
        FAILS.append("a filing-only DocSet should raise")
        print("  FAIL filings were accepted as call transcripts")
    except ValueError as exc:
        check("filings are refused with a reason", "not a call transcript" in str(exc), True)


def test_push_requires_citations(panel: Panel):
    print("\n[push] a value without citations is refused")
    try:
        panel.push("ADI", "FY2026Q3", "Adjusted diluted EPS", 2.31,
                   origin="pipeline:test", because="no cites")
        FAILS.append("push without cites should raise Undefensible")
        print("  FAIL push without cites was accepted")
    except Undefensible:
        print("  ok   push without cites raises Undefensible")
    v = panel.push("ADI", "FY2026Q3", "Adjusted diluted EPS", 2.31,
                   origin="pipeline:test", because="test",
                   cites=["adi-us-20260520-q2-8k.md:71"])
    check("a cited push is accepted", float(v), 2.31)


def main() -> int:
    print("=" * 68)
    test_golden_calendars()
    test_facet_roundtrip()
    test_units()
    panel = Panel.challenge()
    test_extracted_values(panel)
    test_ytd_trap(panel)
    test_document_hygiene(panel)
    test_granularity(panel)
    test_signal_bridge(panel)
    test_push_requires_citations(panel)
    print("=" * 68)
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
