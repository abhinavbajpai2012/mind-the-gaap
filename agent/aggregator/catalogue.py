"""Mine the corpus for the metric vocabulary that is actually reported.

The queryable set is discovered, not declared. Mining runs only over
table-bearing document classes: the single most common row label across the
whole corpus is "bnp paribas sa" (13,467 occurrences), an analyst roster inside
call-transcript tables.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .classify import TABLE_BEARING
from .facets import parse as parse_facets
from .tables import parse_tables

#: structural labels that are not metrics
STOP_LABELS = {
    "total", "other", "name", "period", "in millions", "in thousands",
    "notes", "note", "company", "segment", "segments", "item", "items",
    "description", "date", "year", "years", "three months ended",
}
STOP_RE = re.compile(r"^\(?\s*(in|£|\$|€)\b|^page\b|^\s*$", re.I)


def list_metrics(panel, company: str, min_occurrences: int = 10,
                 contains: str | None = None, limit: int = 200) -> list[dict]:
    """What can actually be asked for, with counts and an example citation."""
    ticker = panel._ticker(company)
    profile = panel.profiles[ticker]
    docs = [d for d in panel._docs[ticker] if d.doc_class in TABLE_BEARING]

    counts: Counter = Counter()
    example: dict[str, str] = {}
    for doc in docs:
        for table in parse_tables(doc, profile):
            for row in table.rows:
                label = row.label.strip()
                low = label.casefold()
                if len(low) < 3 or len(low) > 70:
                    continue
                if low in STOP_LABELS or STOP_RE.search(low):
                    continue
                if not re.search(r"[a-z]{3}", low):
                    continue
                counts[low] += 1
                example.setdefault(low, f"{doc.short}:{row.line_no}")

    out = []
    for label, n in counts.most_common():
        if n < min_occurrences:
            break
        if contains and contains.casefold() not in label:
            continue
        spec = parse_facets(label)
        out.append({
            "label": label,
            "occurrences": n,
            "spec": spec,
            "concept": spec.concept,
            "example": example[label],
        })
        if len(out) >= limit:
            break
    return out
