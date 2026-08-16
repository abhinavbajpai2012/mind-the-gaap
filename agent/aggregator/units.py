"""Value and unit normalisation.

Named failure modes, each a silent multi-order error if unguarded:
  (in thousands)  appears 459x in the corpus against USDm output cells -> 1000x
  Hays EPS quoted in pence (GBp), not pounds                           -> 100x
  "$2.88 billion" in prose against a millions column                   -> 1000x
  (1,234) parenthesised negatives read as positive                     -> sign
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# canonical units
USDM, GBPM, EURM = "USDm", "GBPm", "EURm"
PER_SHARE = "per_share"
PCT, BPS = "pct", "bps"

CURRENCY_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR"}

SCALE_WORDS = {
    "thousand": 1e-3,     # thousands -> millions
    "thousands": 1e-3,
    "million": 1.0,
    "millions": 1.0,
    "billion": 1e3,
    "billions": 1e3,
}

CAPTION_RE = re.compile(
    r"\(\s*in\s+(?P<scale>thousands?|millions?|billions?)"
    r"(?:\s+of\s+(?P<cur1>dollars|pounds|euros))?"
    r"(?P<rest>[^)]*)\)",
    re.I,
)
CAPTION_GBP_RE = re.compile(r"\(\s*in\s+£s?\s+(?P<scale>thousand|million|billion)s?\s*\)", re.I)
EXCEPT_PER_SHARE_RE = re.compile(r"except[^)]*per[- ]share", re.I)

NUMBER_RE = re.compile(r"^\(?\s*[-−]?\s*[\d,]+(?:\.\d+)?\s*\)?$")


@dataclass(frozen=True)
class UnitContext:
    """Table-level unit declaration, parsed from the caption above a table."""

    currency: str | None = None          # USD | GBP | EUR
    scale: float = 1.0                   # multiplier to reach millions
    per_share_exempt: bool = False       # caption says "except per share amounts"
    source: str = ""

    @property
    def money_unit(self) -> str:
        return {"USD": USDM, "GBP": GBPM, "EUR": EURM}.get(self.currency or "", USDM)


def parse_unit_caption(text: str) -> UnitContext | None:
    """'(in millions, except per-share amounts)' -> UnitContext."""
    m = CAPTION_GBP_RE.search(text)
    if m:
        return UnitContext(
            currency="GBP",
            scale=SCALE_WORDS[m.group("scale").lower().rstrip("s") + "s"
                              if m.group("scale").lower() + "s" in SCALE_WORDS
                              else m.group("scale").lower()],
            per_share_exempt=bool(EXCEPT_PER_SHARE_RE.search(text)),
            source=m.group(0),
        )
    m = CAPTION_RE.search(text)
    if not m:
        return None
    scale_word = m.group("scale").lower()
    scale = SCALE_WORDS.get(scale_word, SCALE_WORDS.get(scale_word + "s", 1.0))
    cur = {"dollars": "USD", "pounds": "GBP", "euros": "EUR"}.get(
        (m.group("cur1") or "").lower()
    )
    return UnitContext(
        currency=cur,
        scale=scale,
        per_share_exempt=bool(EXCEPT_PER_SHARE_RE.search(text)),
        source=m.group(0),
    )


def parse_cell(raw: str, ctx: UnitContext | None = None,
               per_share: bool = False) -> tuple[float, str] | None:
    """Parse a table cell into (value, canonical_unit).

    Cell-level suffixes always beat the table caption: a Hays table captioned
    "(In £s million)" still prints EPS as `1.31p`, which is pence.
    """
    s = (raw or "").strip()
    if not s or s in {"-", "--", "—", "n/a", "N/A"}:
        return None

    # Hays prints negative pence as "(0.49)p" — the suffix sits OUTSIDE the
    # parentheses, so a plain startswith/endswith check misses the sign.
    m = re.fullmatch(r"\(([^()]*)\)\s*([%p]|bps)?", s, re.I)
    if m:
        negative = True
        s_clean = (m.group(1) + (m.group(2) or "")).strip()
    else:
        negative = s.startswith("(") and s.endswith(")")
        s_clean = s.strip("()").strip()

    # percentage
    if s_clean.endswith("%"):
        num = _to_float(s_clean[:-1])
        return (-num if negative else num, PCT) if num is not None else None

    # basis points — never silently converted to a percentage
    m = re.fullmatch(r"([\d,.]+)\s*bps", s_clean, re.I)
    if m:
        num = _to_float(m.group(1))
        return (-num if negative else num, BPS) if num is not None else None

    # pence: cell suffix overrides any caption
    m = re.fullmatch(r"([\d,.]+)\s*p", s_clean)
    if m:
        num = _to_float(m.group(1))
        return (-num if negative else num, "GBp") if num is not None else None

    # currency symbol on the cell
    currency = None
    for sym, code in CURRENCY_SYMBOL.items():
        if sym in s_clean:
            currency = code
            s_clean = s_clean.replace(sym, "").strip()

    # inline scale word ("2.88 billion")
    inline_scale = None
    m = re.fullmatch(r"([\d,.]+)\s*(thousand|million|billion)s?", s_clean, re.I)
    if m:
        s_clean = m.group(1)
        inline_scale = SCALE_WORDS[m.group(2).lower()]

    num = _to_float(s_clean)
    if num is None:
        return None
    if negative:
        num = -num

    if per_share and (ctx is None or ctx.per_share_exempt or inline_scale is None):
        cur = currency or (ctx.currency if ctx else None) or "USD"
        return num, "GBp" if cur == "GBP" and abs(num) > 25 else f"{cur}/share"

    scale = inline_scale if inline_scale is not None else (ctx.scale if ctx else 1.0)
    unit = {"USD": USDM, "GBP": GBPM, "EUR": EURM}.get(
        currency or (ctx.currency if ctx else None) or "USD", USDM
    )
    return num * scale, unit


def _to_float(s: str) -> float | None:
    s = s.replace(",", "").replace("−", "-").strip()
    if not s or not re.fullmatch(r"-?\d*\.?\d+", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None
