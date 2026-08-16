"""Metric facet grammar.

The same parser runs on both sides — the user's query and every table row
label — and a match is facet equality. That is what makes an arbitrary metric
answerable without hand-authored aliases:

    "Pre-exceptional basic EPS"                                (companies.json)
    "Basic earnings per share (before exceptional items)"      (Hays document)

share only the word "basic", yet both decompose to
concept=eps, adjustment=pre_exceptional, share_basis=basic.

Lexicons live in data/*.json and are loaded at runtime; nothing about any
particular metric is compiled in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def _lexicons() -> tuple[dict, dict]:
    concepts = json.loads((DATA_DIR / "concepts.json").read_text())["concepts"]
    modifiers = json.loads((DATA_DIR / "modifiers.json").read_text())
    modifiers.pop("_comment", None)
    return concepts, modifiers


def reload_lexicons() -> None:
    _lexicons.cache_clear()


@dataclass(frozen=True)
class MetricSpec:
    concept: str | None = None
    adjustment: str | None = None
    share_basis: str | None = None
    scope: str | None = None
    statistic: str = "level"
    unit_class: str = "currency_abs"
    #: text that could not be attributed to any facet
    residual: str = ""

    def __str__(self) -> str:
        bits = [self.adjustment, self.share_basis, self.concept]
        if self.statistic != "level":
            bits.append(self.statistic)
        if self.scope and self.scope != "total":
            bits.append(f"[{self.scope}]")
        return " ".join(b for b in bits if b) or "?"

    def matches(self, other: "MetricSpec") -> bool:
        """Is `other` (a document row) compatible with this query spec?

        Unspecified facets on the query are wildcards; specified facets must
        agree exactly. One asymmetry is deliberate: an unmarked document row is
        the statutory basis by convention ("Diluted earnings per share" IS the
        GAAP one), so a `gaap` query matches a row with no adjustment marker.
        """
        if self.concept and self.concept != other.concept:
            return False
        if self.adjustment and self.adjustment != other.adjustment:
            if not (self.adjustment == "gaap" and other.adjustment is None):
                return False
        if self.share_basis and self.share_basis != other.share_basis:
            return False
        if self.statistic != other.statistic:
            return False
        if self.scope and not scope_matches(self.scope, other.scope):
            return False
        if self.scope and is_total_scope(self.scope) and other.scope:
            return False        # "total company" means the group, not a segment
        if not self.scope and other.scope:
            # "Worldwide net sales and revenues" is the group total; it must not
            # silently take Production & Precision Agriculture's 4,273.
            return False
        return True

    @property
    def is_per_share(self) -> bool:
        return self.unit_class == "per_share"


_SCOPE_STOP = {"and", "&", "the", "of", "segment", "segments", "operations", "business"}

#: words that name the whole company rather than one of its segments. "Net
#: sales, total company" is not scoped to a segment called "total company".
_TOTAL_WORDS = {"total", "company", "group", "worldwide", "consolidated", "overall"}

#: concepts that ARE a rate, so "level" and "growth" are not distinct readings
#: of them. A retailer's "Comparable sales" is already a percentage change, and
#: its table row says so — "Comparable sales (% change)" — while the challenge
#: label says "Comparable sales, total company". Same number, and the statistic
#: facet must not separate them.
RATE_CONCEPTS = {"comparable_sales", "conversion_rate", "operating_margin"}


def is_total_scope(text: str | None) -> bool:
    toks = scope_tokens(text or "")
    return bool(toks) and all(t in _TOTAL_WORDS for t in toks)


def scope_tokens(text: str) -> tuple[str, ...]:
    t = (text or "").casefold().replace("&", " and ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return tuple(w for w in t.split() if w and w not in _SCOPE_STOP)


def scope_matches(query_scope: str | None, doc_scope: str | None) -> bool:
    """Does a requested segment match the one a table declares?

    The challenge asks for "Production & Precision Ag"; Deere's filing says
    "Production and Precision Agriculture". Requiring string equality would
    miss it, and ignoring scope entirely would silently return a different
    segment's number. Each query token must prefix the document token in the
    same order, so "ag" matches "agriculture" but never "turf".
    """
    if not query_scope or is_total_scope(query_scope):
        return True
    if not doc_scope:
        return False           # a scoped query must not fall back to an unscoped row
    q, d = scope_tokens(query_scope), scope_tokens(doc_scope)
    if not q:
        return True
    i = 0
    for token in d:
        if i < len(q) and token.startswith(q[i]):
            i += 1
    return i == len(q)


def _normalise(text: str) -> str:
    t = text.casefold()
    t = re.sub(r"\(\d{1,2}\)", " ", t)          # footnote markers
    t = t.replace("&amp;", "&")
    t = re.sub(r"[*†‡]", " ", t)
    t = re.sub(r"[^a-z0-9%&/\- ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse(text: str, segments: tuple[str, ...] = (),
          unit_hint: str | None = None) -> MetricSpec:
    """Decompose a metric name or a table row label into facets.

    `unit_hint` is the unit the caller declares it wants (companies.json gives
    "%", "USDm", "USD / share"). It disambiguates labels that name both a
    currency amount and a ratio: ADI prints `Adjusted gross margin` = $1,995m
    on one line and `Adjusted gross margin percentage` = 69.2% on the next.
    Without the declared unit, the label alone cannot choose.
    """
    original = text
    t = _normalise(text)
    if not t:
        return MetricSpec(residual=original)

    concepts, modifiers = _lexicons()
    adjustment = share_basis = scope = None
    statistic = "level"

    # --- scope: company segments, matched before anything else ------------
    for seg in sorted(segments, key=len, reverse=True):
        s = _normalise(seg)
        if s and s in t:
            scope = s
            t = t.replace(s, " ").strip()
            break

    # --- modifiers --------------------------------------------------------
    for value, surfaces in modifiers.get("adjustment", {}).items():
        for s in sorted(surfaces, key=len, reverse=True):
            if re.search(rf"(?:^|\W){re.escape(s)}(?:\W|$)", t):
                adjustment = value
                t = re.sub(rf"(?:^|\W){re.escape(s)}(?:\W|$)", " ", t)
                break
        if adjustment:
            break

    for value, surfaces in modifiers.get("share_basis", {}).items():
        for s in surfaces:
            if re.search(rf"(?:^|\W){re.escape(s)}(?:\W|$)", t):
                share_basis = value
                t = re.sub(rf"(?:^|\W){re.escape(s)}(?:\W|$)", " ", t)
                break
        if share_basis:
            break

    t = re.sub(r"\s+", " ", t).strip()

    # --- concept BEFORE statistic ----------------------------------------
    # "gross margin percentage" must yield concept=gross_margin +
    # statistic=margin. Consuming the statistic first would eat "margin" and
    # leave "gross", destroying the concept.
    concept = None
    best_len = 0
    for name, surfaces in concepts.items():
        for s in surfaces:
            if s in t and len(s) > best_len:
                concept, best_len = name, len(s)
    residual = t
    if concept:
        for s in sorted(concepts[concept], key=len, reverse=True):
            if s in t:
                residual = re.sub(r"\s+", " ", t.replace(s, " ")).strip()
                break

    # --- statistic, from whatever the concept left behind ------------------
    for value, surfaces in modifiers.get("statistic", {}).items():
        for s in sorted(surfaces, key=len, reverse=True):
            if s in residual:
                statistic = value
                residual = re.sub(r"\s+", " ", residual.replace(s, " ")).strip()
                break
        if statistic != "level":
            break
    t = residual

    # --- rate concepts: "level" and "growth" are the same reading ----------
    if concept in RATE_CONCEPTS:
        statistic = "rate"

    # --- scope from the leftover text, but only if the company reports it ---
    # "Production & Precision Ag operating profit" leaves "production precision
    # ag" once the concept is removed. Treating any residual as a scope would
    # break "Worldwide net sales and revenues" (residual "worldwide") against a
    # row labelled "Total net sales and revenues", so it must match a segment
    # the company actually declares.
    if scope is None and residual and segments and not is_total_scope(residual):
        for seg in segments:
            if scope_matches(residual, seg):
                scope = residual
                residual = ""
                break

    # --- unit class -------------------------------------------------------
    if concept == "eps" or "per share" in _normalise(original):
        unit_class = "per_share"
    elif statistic in ("margin", "pct_of_revenue") or concept in (
        "operating_margin", "conversion_rate", "comparable_sales"
    ) or "%" in original:
        unit_class = "percent"
    else:
        unit_class = "currency_abs"

    # gross margin appears both as a currency amount and as a percentage row;
    # "gross margin percentage" is the percent one and is caught by `statistic`
    if concept == "gross_margin" and statistic == "margin":
        unit_class = "percent"

    # a declared unit is authoritative over anything inferred from the label
    if unit_hint:
        h = unit_hint.strip().casefold()
        if h in ("%", "pct", "percent"):
            unit_class = "percent"
            if statistic == "level" and concept in ("gross_margin", "operating_margin",
                                                    "revenue", "net_income"):
                statistic = "margin"
        elif "share" in h:
            unit_class = "per_share"
        elif h.endswith("m") or "million" in h:
            unit_class = "currency_abs"
            statistic = "level" if statistic == "margin" else statistic

    return MetricSpec(
        concept=concept,
        adjustment=adjustment,
        share_basis=share_basis,
        scope=scope,
        statistic=statistic,
        unit_class=unit_class,
        residual=residual,
    )


def parse_query_metric(text: str, segments: tuple[str, ...] = ()) -> MetricSpec:
    """Parse the query side. Identical grammar, kept separate for clarity."""
    return parse(text, segments)
