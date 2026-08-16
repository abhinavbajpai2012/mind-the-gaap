"""Interface shared by every signal subagent."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator

# companies.json says "FY2026Q3" / "FY2026"; the corpus says "Q3 2026" / "FY 2026".
_CHALLENGE_PERIOD_RE = re.compile(r"^FY\s*(\d{4})(?:Q([1-4]))?$", re.IGNORECASE)
_CORPUS_PERIOD_RE = re.compile(r"^(?:([1-4])Q|(Q[1-4]|H[12]|FY))\s+(\d{4})$", re.IGNORECASE)


class SignalInput(BaseModel):
    """What a signal subagent is given for a single run."""

    company: str
    period: str  # corpus convention, e.g. "Q3 2026" or "FY 2026"
    relevant_documents: list[Path]

    @field_validator("period")
    @classmethod
    def _normalise_period(cls, value: str) -> str:
        """Accept the companies.json form too, but always store the corpus form."""
        text = " ".join(value.split())

        challenge = _CHALLENGE_PERIOD_RE.match(text)
        if challenge:
            year, quarter = challenge.groups()
            return f"Q{quarter} {year}" if quarter else f"FY {year}"

        corpus = _CORPUS_PERIOD_RE.match(text)
        if corpus:
            leading_quarter, prefix, year = corpus.groups()
            prefix = f"Q{leading_quarter}" if leading_quarter else prefix.upper()
            return f"{prefix} {year}"

        raise ValueError(f"unrecognised period: {value!r} (expected e.g. 'Q3 2026' or 'FY 2026')")


class AbstractSignal(ABC):
    """Base class every signal subagent implements."""

    @abstractmethod
    def run(self, signal_input: SignalInput) -> Any:
        """Read the documents and return this subagent's signal."""
