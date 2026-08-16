"""Interface shared by every signal subagent."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

# companies.json says "FY2026Q3" / "FY2026"; the corpus says "Q3 2026" / "FY 2026".
_CHALLENGE_PERIOD_RE = re.compile(r"^FY\s*(\d{4})(?:Q([1-4]))?$", re.IGNORECASE)
_CORPUS_PERIOD_RE = re.compile(r"^(?:([1-4])Q|(Q[1-4]|H[12]|FY))\s+(\d{4})$", re.IGNORECASE)

# The corpus front matter declares the type; the directory layout mirrors it.
_FRONT_MATTER_TYPE_RE = re.compile(r'^document_type:\s*"?([A-Za-z_]+)"?', re.MULTILINE)
_DIRECTORY_TYPES = {
    "call-transcripts": "call_transcript",
    "filings": "filing",
    "slides": "slide",
}
_FRONT_MATTER_CHARS = 2048

DocumentType = Literal["call_transcript", "filing", "slide"]


class RelevantDocument(BaseModel):
    """One corpus document handed to a subagent, with what kind of document it is."""

    path: Path
    document_type: DocumentType

    @model_validator(mode="before")
    @classmethod
    def _infer_type(cls, value: Any) -> Any:
        """Accept a bare path and read its type off the document."""
        if isinstance(value, (str, Path)):
            path = Path(value)
            return {"path": path, "document_type": _document_type_for(path)}
        if isinstance(value, dict) and "document_type" not in value and "path" in value:
            return {**value, "document_type": _document_type_for(Path(value["path"]))}
        return value

    @field_validator("document_type", mode="before")
    @classmethod
    def _normalise_type(cls, value: str) -> str:
        """The corpus writes 'CALL_TRANSCRIPT'; store the lower-case form."""
        return str(value).strip().lower().replace("-", "_")

    @property
    def name(self) -> str:
        return self.path.name


def _document_type_for(path: Path) -> str:
    """Front matter is authoritative; fall back to the corpus directory layout."""
    try:
        head = path.open(encoding="utf-8").read(_FRONT_MATTER_CHARS)
    except OSError:
        head = ""

    match = _FRONT_MATTER_TYPE_RE.search(head)
    if match:
        return match.group(1)

    directory = _DIRECTORY_TYPES.get(path.parent.name)
    if directory:
        return directory

    raise ValueError(
        f"cannot tell what kind of document {str(path)!r} is — no 'document_type' front "
        "matter and not under a call-transcripts/filings/slides directory. Pass "
        "RelevantDocument(path=..., document_type=...) explicitly."
    )


class SignalInput(BaseModel):
    """What a signal subagent is given for a single run."""

    company: str
    period: str  # corpus convention, e.g. "Q3 2026" or "FY 2026"
    relevant_documents: list[RelevantDocument]

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
