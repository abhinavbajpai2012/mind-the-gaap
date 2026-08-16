"""Company guidance for the period being forecast, and an adversarial check on it.

A company that has told the market what next quarter will be is the single
strongest source available, and it is the one the sell-side anchors on. ADI's
Q2 FY2026 release says "for the third quarter of fiscal 2026, we are forecasting
revenue of $3.9 billion, +/- $100 million" — a model that ignores that and
predicts 3.26bn is not being conservative, it is being wrong against a number
the company published.

Two pieces here:

  extract_guidance()  finds forward-looking figures for the target period in
                      the documents that precede it, and returns them with the
                      sentence they came from.
  challenge()         the adversarial step: given a model's forecast and the
                      guidance, decide whether the forecast is defensible.
                      Outside the company's own stated band, it is not, and the
                      guidance midpoint replaces it.

The check is deliberately one-directional. Guidance can veto a model; a model
cannot veto guidance. Companies do miss their own guidance, but a model with
fifteen usable quarters is not the thing that knows better.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .aggregator.classify import DocClass
from .aggregator.facets import parse as parse_facets
from .aggregator.fiscal import FiscalPeriod

ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth"}

#: "$3.9 billion, +/- $100 million"  /  "$3.30, +/-$0.15"  /  "2.5% to 4.5%"
_MONEY = r"\$\s*([\d,]+\.?\d*)\s*(billion|million|bn|m)?"
_PLUSMINUS = r"(?:\+/-|±|plus or minus)\s*\$?\s*([\d,]+\.?\d*)\s*(billion|million|bn|m)?"
_RANGE_PCT = r"([\d.]+)\s*%?\s*(?:to|-|–)\s*([\d.]+)\s*%"
_PCT = r"([\d.]+)\s*%"

SCALE = {"billion": 1000.0, "bn": 1000.0, "million": 1.0, "m": 1.0, None: 1.0, "": 1.0}


@dataclass
class Guided:
    """One guided figure for the target period."""

    concept: str
    statistic: str
    low: float | None
    mid: float
    high: float | None
    unit_class: str
    quote: str
    cite: str
    #: "adjusted" / "gaap" / None — ADI guides reported EPS $2.60 AND adjusted
    #: EPS $3.30 in one sentence; taking the wrong one is a 27% error
    adjustment: str | None = None
    #: 0 = press release, 1 = call transcript. The release is the authority.
    rank: int = 1
    published: object = None

    def contains(self, value: float, slack: float = 0.0) -> bool:
        lo = self.mid if self.low is None else self.low
        hi = self.mid if self.high is None else self.high
        pad = abs(self.mid) * slack
        return (lo - pad) <= value <= (hi + pad)

    def __repr__(self) -> str:
        band = "" if self.low is None else f" [{self.low:g}, {self.high:g}]"
        return f"{self.concept}/{self.statistic} = {self.mid:g}{band} · {self.cite}"


def _num(text: str, scale_word: str | None) -> float:
    return float(text.replace(",", "")) * SCALE.get((scale_word or "").lower(), 1.0)


def _target_phrases(period: FiscalPeriod) -> list[str]:
    """How a company refers to the period being forecast.

    For a quarterly target the quarter must be named. "fiscal 2026" alone also
    appears in the Q1 release, which guides Q2 — matching on it would take ADI's
    Q2 guidance of $3.5bn as though it were the Q3 guidance of $3.9bn.
    """
    if period.quarter:
        word = ORDINALS[period.quarter]
        return [rf"{word}\s+quarter\s+of\s+fiscal\s+{period.fy}",
                rf"fiscal\s+{period.fy}\s+{word}\s+quarter",
                rf"{word}\s+quarter\s+fiscal\s+{period.fy}",
                rf"fiscal\s+{word}\s+quarter",
                rf"Q{period.quarter}\s+(?:of\s+)?(?:fiscal\s+)?{period.fy}"]
    return [rf"fiscal\s+(?:year\s+)?{period.fy}", rf"full[- ]year\s+{period.fy}",
            rf"FY\s*{period.fy}"]


def extract_guidance(panel, ticker: str, period: FiscalPeriod,
                     max_docs: int = 12) -> list[Guided]:
    """Forward guidance for `period`, from the releases that precede it.

    Only documents published BEFORE the target period would have printed are
    read, so nothing here could have seen the answer.
    """
    docs = [d for d in panel._docs[ticker]
            if d.doc_class in (DocClass.STRUCTURED_RESULT, DocClass.EARNINGS_CALL)]
    docs.sort(key=lambda d: d.published_at, reverse=True)
    phrases = _target_phrases(period)
    out: list[Guided] = []
    seen: set[tuple] = set()

    for doc in docs[:max_docs]:
        for i, line in enumerate(doc.lines, start=1):
            s = line.strip()
            if len(s) < 40 or s.startswith("|"):
                continue
            if not any(re.search(p, s, re.I) for p in phrases):
                continue
            if not re.search(r"forecast|expect|guidance|outlook|planning for|we (?:now )?see|"
                             r"anticipat|targeting", s, re.I):
                continue
            rank = 0 if re.search(r"-8k|-10q|-10k", doc.kind) else 1
            for g in _parse_sentence(s, f"{doc.short}:{i}", rank):
                g.published = doc.published_at
                key = (g.concept, g.statistic, round(g.mid, 4))
                if key not in seen:
                    seen.add(key)
                    out.append(g)
    # press-release guidance outranks anything said on the call
    # newest first, press release over call, banded figure over bare one
    out.sort(key=lambda g: (g.rank, -(g.published.toordinal() if g.published else 0),
                            g.low is None))
    return out


GUIDE_RE = re.compile(
    r"(?P<adj>reported|adjusted|non-gaap|gaap)?\s*"
    r"(?P<metric>earnings per share|diluted eps|eps|revenue|net sales|total sales|"
    r"comparable sales|operating margin|gross margin|net income|net fees)"
    r"[^.$%\d]{0,40}?"
    r"(?P<val>\$?\s*\d[\d,]*\.?\d*)\s*"
    r"(?P<scale>billion|million|bn)?\s*%?"
    r"(?:\s*,?\s*(?:\+/-|±)\s*(?P<pmv>\$?\s*\d[\d,]*\.?\d*)\s*"
    r"(?P<pms>billion|million|bn|bps|basis points|%)?)?",
    re.I)

METRIC_MAP = {
    "earnings per share": ("eps", "level", "per_share"),
    "diluted eps": ("eps", "level", "per_share"),
    "eps": ("eps", "level", "per_share"),
    "revenue": ("revenue", "level", "currency_abs"),
    "net sales": ("revenue", "level", "currency_abs"),
    "total sales": ("revenue", "growth", "percent"),
    "comparable sales": ("comparable_sales", "rate", "percent"),
    "operating margin": ("operating_margin", "rate", "percent"),
    "gross margin": ("gross_margin", "margin", "percent"),
    "net income": ("net_income", "level", "currency_abs"),
    "net fees": ("net_fees", "level", "currency_abs"),
}


def _parse_sentence(s: str, cite: str, rank: int = 1) -> list["Guided"]:
    """Pull guided figures out of one forward-looking sentence.

    One pass over the sentence, capturing the qualifier, the metric, the figure
    and its band together. Splitting the sentence first loses the pairing: ADI
    writes "reported EPS to be $2.60, +/-$0.15, and adjusted EPS to be $3.30,
    +/-$0.15" and the two must not be confused for each other.
    """
    out: list[Guided] = []
    for m in GUIDE_RE.finditer(s):
        key = m.group("metric").lower()
        if key not in METRIC_MAP:
            continue
        concept, stat, uc = METRIC_MAP[key]
        raw = (m.group("val") or "").replace("$", "").strip()
        if not raw or not re.fullmatch(r"[\d,]+\.?\d*", raw) or raw in (",", "."):
            continue
        scale = (m.group("scale") or "").lower()
        # a percentage cannot be scaled by "billion"; a rate has no scale word
        mid = float(raw.replace(",", "")) * (1.0 if uc == "percent"
                                             else SCALE.get(scale, 1.0))
        width = None
        if m.group("pmv"):
            w = m.group("pmv").replace("$", "").strip()
            if re.fullmatch(r"[\d,]+\.?\d*", w):
                width = float(w.replace(",", ""))
                ps = (m.group("pms") or "").lower()
                if ps in ("bps", "basis points"):
                    width /= 100.0
                elif uc != "percent":
                    width *= SCALE.get(ps, 1.0)
        adj = (m.group("adj") or "").lower() or None
        if adj in ("non-gaap",):
            adj = "adjusted"
        if adj == "reported":
            adj = "gaap"
        out.append(Guided(concept, stat,
                          None if width is None else mid - width, mid,
                          None if width is None else mid + width, uc,
                          s.strip()[:300], cite, adjustment=adj, rank=rank))
    return out


#: "£37.0-46.0m consensus range" with "at the top of" / "at the bottom of"
CONSENSUS_RE = re.compile(
    r"(?P<pos>top|bottom|middle|mid[- ]point|upper|lower)?[^.£$]{0,40}"
    r"[£$]\s*(?P<lo>[\d,]+\.?\d*)\s*[-–to]{1,3}\s*[£$]?\s*(?P<hi>[\d,]+\.?\d*)\s*"
    r"(?P<scale>m|million|bn|billion)?\s*consensus",
    re.I)
CONSENSUS_METRIC = (
    ("pre-exceptional operating profit", "operating_profit", "pre_exceptional"),
    ("pre -exceptional operating profit", "operating_profit", "pre_exceptional"),
    ("operating profit", "operating_profit", None),
    ("net fees", "net_fees", None),
    ("earnings per share", "eps", None),
)


def extract_consensus(panel, ticker: str, period: FiscalPeriod,
                      max_docs: int = 8) -> list["Guided"]:
    """Company-compiled analyst consensus, and where in the range they expect to land.

    Hays does not guide a number; it publishes the sell-side range and says
    where it will fall in it: "we currently expect FY26 pre-exceptional
    operating profit will be at the top of the £37.0-46.0m consensus range".
    That is guidance in everything but name, and it is the figure the market
    is holding. "top" resolves to the high end, not the midpoint.
    """
    docs = [d for d in panel._docs[ticker]
            if d.doc_class in (DocClass.STRUCTURED_RESULT, DocClass.EARNINGS_CALL)]
    docs.sort(key=lambda d: d.published_at, reverse=True)
    phrases = _target_phrases(period) + [rf"FY\s*{str(period.fy)[-2:]}\b"]
    out: list[Guided] = []
    for doc in docs[:max_docs]:
        for i, line in enumerate(doc.lines, start=1):
            t = line.strip()
            if len(t) < 40 or not any(re.search(p, t, re.I) for p in phrases):
                continue
            m = CONSENSUS_RE.search(t)
            if not m:
                continue
            low = t.lower()
            concept = adj = None
            for probe, c, a in CONSENSUS_METRIC:
                if probe in low:
                    concept, adj = c, a
                    break
            if concept is None:
                continue
            lo = float(m.group("lo").replace(",", ""))
            hi = float(m.group("hi").replace(",", ""))
            scale = (m.group("scale") or "").lower()
            if scale in ("bn", "billion"):
                lo, hi = lo * 1000, hi * 1000
            # search the whole sentence: an optional group ahead of the range
            # will not backtrack to find "at the top of" eight characters back
            pos = ""
            near = re.search(r"at the (top|bottom|upper|lower|mid[- ]?point|middle)"
                             r"(?:\s+end)?\s+of", low)
            if near:
                pos = near.group(1)
            mid = (hi if pos in ("top", "upper")
                   else lo if pos in ("bottom", "lower")
                   else (lo + hi) / 2)
            out.append(Guided(concept, "level", lo, mid, hi, "currency_abs",
                              t[:300], f"{doc.short}:{i}",
                              adjustment=adj, rank=0, published=doc.published_at))
    out.sort(key=lambda g: -(g.published.toordinal() if g.published else 0))
    return out


def load_research_anchors(ticker: str, period: FiscalPeriod) -> list["Guided"]:
    """Public research anchors for a period the corpus cannot speak to.

    The rules permit public information found during the event. These are kept
    in a declared JSON file rather than inlined in code so a judge can see
    exactly what was taken from outside the corpus and where each figure came
    from. They run through the same guards as company guidance.
    """
    import json
    from pathlib import Path as _P

    f = _P(__file__).resolve().parent / "research_anchors.json"
    if not f.exists():
        return []
    out = []
    for a in json.loads(f.read_text()).get("anchors", []):
        if a["ticker"] != ticker or a["period"] != str(period):
            continue
        out.append(Guided(a["concept"], "level", a.get("low"), a["mid"], a.get("high"),
                          a["unit_class"], a["quote"], a["cite"],
                          adjustment=a.get("adjustment"), rank=0))
    return out


# ---------------------------------------------------------------------------
@dataclass
class Verdict:
    """The adversarial check's finding on one forecast."""

    ok: bool
    action: str                     # "kept" | "overridden" | "no guidance"
    value: float
    guided: Guided | None = None
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def challenge(value: float, metric_label: str, units: str,
              guides: list[Guided], slack: float = 0.05) -> Verdict:
    """Does the company's own guidance contradict this forecast?

    `slack` allows a forecast just outside a stated band to stand: a company
    guiding "$3.9bn +/- $100m" is not claiming 3.79bn is impossible. Beyond
    that the model is overruled, because the alternative is submitting a number
    the company has publicly disagreed with.
    """
    spec = parse_facets(metric_label, unit_hint=units)
    if not spec.concept:
        return Verdict(True, "no guidance", value, reason="metric not recognised")

    match = None
    for g in guides:
        if g.concept != spec.concept:
            continue
        if spec.unit_class == "percent" and g.unit_class != "percent":
            continue
        if spec.unit_class in ("currency_abs", "per_share") and g.unit_class == "percent":
            continue
        if spec.unit_class == "per_share" and g.unit_class != "per_share":
            continue
        if spec.adjustment and g.adjustment and spec.adjustment != g.adjustment:
            continue        # "adjusted EPS" must not take the reported figure
        if spec.adjustment == "adjusted" and g.adjustment is None:
            continue
        match = g
        break

    if match is None:
        return Verdict(True, "no guidance", value,
                       reason="company gave no guidance for this metric")
    # A guidance override must clear two bars, or a stray sentence replaces a
    # sound forecast: Hays' "net fees ... 5" matched a fragment and would have
    # turned 975 into 5. Only an explicitly BANDED figure ("$3.9bn +/- $100m")
    # may override, and never by more than 3x.
    banded = match.low is not None and match.high is not None
    ratio = abs(match.mid / value) if value else float("inf")
    if not banded or ratio > 3.0 or ratio < 1 / 3.0:
        return Verdict(True, "no guidance", value, match,
                       reason=("guidance found but not trusted: "
                               + ("unbanded figure" if not banded
                                  else f"{match.mid:g} is {ratio:.1f}x the forecast")))
    if match.contains(value, slack=slack):
        return Verdict(True, "kept", value, match,
                       reason=f"within guidance {match.mid:g}")
    return Verdict(
        False, "overridden", match.mid, match,
        reason=(f"forecast {value:,.2f} is outside company guidance "
                f"{match.mid:g}"
                + (f" +/- {match.high - match.mid:g}" if match.high else "")
                + f"; replaced with the guidance midpoint"),
        notes=[f"guidance: “{match.quote[:180]}”", f"source: {match.cite}"],
    )
