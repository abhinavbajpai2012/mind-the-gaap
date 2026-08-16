"""CLI: python -m agent.aggregator ..."""

from __future__ import annotations

import argparse
import sys

from .panel import AmbiguousMetric, NotReported, Panel
from .profiler import fit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent.aggregator")
    ap.add_argument("company", nargs="?", help="ticker, e.g. ADI")
    ap.add_argument("period", nargs="?", help="e.g. FY2025Q3")
    ap.add_argument("metric", nargs="?", help="e.g. 'Adjusted diluted EPS'")
    ap.add_argument("--units", default=None, help="declared unit, e.g. '%%' or USDm")
    ap.add_argument("--why", action="store_true", help="full accepted/rejected trace")
    ap.add_argument("--docs", action="store_true", help="list matching documents")
    ap.add_argument("--kind", default=None, help="transcript | results | slide | filing")
    ap.add_argument("--list-metrics", action="store_true")
    ap.add_argument("--fit", metavar="DIR", help="derive a company profile from a directory")
    ap.add_argument("--panel", action="store_true", help="show the challenge panel")
    args = ap.parse_args(argv)

    if args.fit:
        print(fit(args.fit).report())
        return 0

    panel = Panel.challenge()

    if args.panel or not args.company:
        print(panel)
        return 0

    if args.docs:
        print(panel.docs(args.company, args.period, kind=args.kind))
        return 0

    if args.list_metrics:
        from .catalogue import list_metrics

        for entry in list_metrics(panel, args.company)[:40]:
            print(f"  {entry['label'][:44]:<46} seen {entry['occurrences']:>5}x   "
                  f"{entry['example']}")
        return 0

    if not (args.period and args.metric):
        ap.error("need PERIOD and METRIC (or --docs / --list-metrics / --panel)")

    try:
        value = panel.value(args.company, args.period, args.metric,
                            args.units, strict=not args.why)
    except (NotReported, AmbiguousMetric) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(value.why() if args.why else repr(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
