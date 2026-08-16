"""Regression tests. Run: python3 -m agent.aggregator.tests.test_aggregator

No test framework dependency, matching starter/test_search.py's style.
"""

from __future__ import annotations

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
