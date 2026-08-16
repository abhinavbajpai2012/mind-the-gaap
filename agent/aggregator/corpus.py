"""Corpus walking, frontmatter parsing and the Document record.

Frontmatter `period:` is parsed and retained but is never allowed to decide a
document's period: it is demonstrably wrong in the supplied corpus (the ADI
Q2 FY2026 10-Q is labelled "Q3 2026"). See periods.py for the resolution order.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from pathlib import Path

from .classify import FileFacts, DocClass, parse_filename, is_noise_title
from .fiscal import FiscalPeriod, PeriodSpan

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = REPO_ROOT / "challenge" / "offline-data"
DEFAULT_COMPANIES = REPO_ROOT / "challenge" / "companies.json"

SKIP_NAMES = {"INDEX.md", "README.md"}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the JSON-ish YAML header used by the supplied documents."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        try:
            meta[k.strip()] = json.loads(v)
        except json.JSONDecodeError:
            meta[k.strip()] = v
    return meta, text[end + 5:]


@dataclass
class Document:
    """One corpus document. Body text is read lazily."""

    facts: FileFacts
    company: str
    ticker: str
    title: str
    frontmatter_period: str | None
    #: resolved by periods.resolve(); None means "no period of record"
    period: FiscalPeriod | None = None
    period_confidence: float = 0.0
    evidence: tuple = ()
    conflicts: tuple[str, ...] = ()

    # --- passthroughs -----------------------------------------------------
    @property
    def path(self) -> Path:
        return self.facts.path

    @property
    def name(self) -> str:
        return self.facts.path.name

    @property
    def kind(self) -> str:
        return self.facts.kind

    @property
    def doc_class(self) -> str:
        return self.facts.doc_class

    @property
    def published_at(self) -> date:
        return self.facts.published_at

    @property
    def short(self) -> str:
        """Filename without date prefix or numeric id, for readable citations."""
        n = self.name
        n = re.sub(r"^\d{4}-\d{2}-\d{2}__", "", n)
        return re.sub(r"__\d+\.md$", ".md", n)

    # --- content ----------------------------------------------------------
    @cached_property
    def body(self) -> str:
        raw = self.path.read_text(encoding="utf-8", errors="ignore")
        _, body = parse_frontmatter(raw)
        return body

    @cached_property
    def lines(self) -> list[str]:
        """1-indexed access is via lines[n-1]; kept as a plain list."""
        return self.path.read_text(encoding="utf-8", errors="ignore").splitlines()

    def text(self) -> str:
        return self.body

    def cite(self, line_no: int | None = None) -> str:
        return f"{self.short}:{line_no}" if line_no else self.short

    def __repr__(self) -> str:
        p = str(self.period) if self.period else "-"
        return f"<Document {self.short} {self.kind} {p}>"


def _read_head(path: Path, nbytes: int = 4096) -> str:
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        return fh.read(nbytes)


def load_documents(root: Path | str = DEFAULT_DATA_ROOT) -> list[Document]:
    """Walk a corpus directory and build unresolved Document records."""
    root = Path(root)
    docs: list[Document] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in SKIP_NAMES:
            continue
        facts = parse_filename(path)
        if facts is None:
            continue
        head = _read_head(path)
        meta, body = parse_frontmatter(head)
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem
        docs.append(
            Document(
                facts=facts,
                company=str(meta.get("company", "")),
                ticker=str(meta.get("ticker", "")),
                title=title,
                frontmatter_period=(str(meta["period"]) if meta.get("period") else None),
            )
        )
    return docs


def load_challenge_targets(path: Path | str = DEFAULT_COMPANIES) -> list[dict]:
    """Read the challenge targets at runtime; nothing about them is compiled in."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for c in payload.get("companies", []):
        ticker = str(c["ticker"]).rsplit(":", 1)[-1]
        for metric in c.get("metrics", []):
            out.append(
                {
                    "ticker": ticker,
                    "company": c["company"],
                    "period": c["period"],
                    "metric": metric["label"],
                    "units": metric["units"],
                    "output_file": c["outputFile"],
                }
            )
    return out
