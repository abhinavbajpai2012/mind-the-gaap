"""Call-tone signal: management Q&A tone, binned to words for one company and period.

 1. Finance-specific word lists (Loughran-McDonald style). No VADER/TextBlob/Harvard IV,
    which read "cost", "liability" and "tax" as negative in ordinary company language —
    and, for the same reason, no topic words in our own lists either. See NEGATIVE_WORDS.
 2. Q&A only. Prepared remarks are drafted and lawyered; answers are not.
 3. Tone *change* carries more than tone *level*, hence qa_neg_change off the prior call.
 4. Levels are standardised within the company: each issuer has its own baseline verbosity
    and house style, so Hays is never pooled with HD/ADI/DE. The baseline is a *trailing
    window* of that company's own recent calls, not its whole history — pooling 2012 with
    2026 makes the label encode the era rather than the quarter.
 5. No lookahead: the feature is the last Q&A published before the print being forecast;
    the call that accompanies the print is never used, and the call being scored is never
    part of its own baseline.
 6. Deterministic and offline — word counting only, no model asked "what is the sentiment?"
 7. Raw rates stay local. The output carries words and ordinals, so the time-series model
    never sees fake-precision floats it would treat as a continuous series. The one number
    that does escape is qa_neg_z, and only so a caller can size (and cap) the tilt it takes
    from this signal.
 8. Abstain rather than guess. With too short a baseline there is nothing to standardise
    against, and the level channels come back None instead of a confident-looking word.

What this signal deliberately does NOT do: separate management's answers from the
analysts' questions. Every turn in this corpus is labelled "Unknown speaker:", and the
blocks are transcription chunks rather than speaker turns — single questions are split
mid-sentence across several of them. Any role tagging built on that is guesswork, so the
whole Q&A is scored and the dilution from analyst wording is accepted and stated.
"""

from __future__ import annotations

import logging
import re
import statistics
from datetime import date
from math import sqrt
from pathlib import Path
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from .abc_subagent import AbstractSignal, RelevantDocument, SignalInput

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Document selection
# --------------------------------------------------------------------------------------

# Earnings Q&A. Most files are plain "call-qna"; from 2024 some carry a quarter token
# ("call-q3-qna"). H1/H2 is allowed for half-year reporters even though this corpus's UK
# issuer does not currently use it.
_QNA_RE = re.compile(r"call-(?:q[1-4]|h[12])?-?qna", re.IGNORECASE)
# Recognised only so a rejected file can be told apart from an unrecognised one.
_PRES_RE = re.compile(r"call-(?:q[1-4]|h[12])?-?pres", re.IGNORECASE)
# Two documents in this corpus (one HD, one Hays) are a whole call in one file, prepared
# remarks and Q&A together, rather than the -pres/-qna pair every other call comes as.
# Skipped rather than scored: half of one is a drafted script, and dropping that into a
# baseline built from unscripted answers makes the call incomparable with its own history.
_COMBINED_RE = re.compile(r"-call(?=__|$)", re.IGNORECASE)
# Conference appearances and AGMs are not earnings calls; they would pollute the baseline.
# Only consulted for documents that arrive without the aggregator's classification.
_NOT_EARNINGS_RE = re.compile(r"call-conf|call-agm|investor-day", re.IGNORECASE)
# agent.aggregator.classify.DocClass.EARNINGS_CALL, by value rather than by import: this
# signal reads documents, and must not depend on the thing that selected them.
_EARNINGS_CALL_CLASS = "EARNINGS_CALL"

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONT_MATTER_FIELD_RE = re.compile(r'^([a-z_]+):\s*"?(.*?)"?\s*$', re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6} .*$", re.MULTILINE)
_SAFE_HARBOUR_RE = re.compile(
    r"forward-looking|forward looking|safe harbor|safe harbour|private securities litigation",
    re.IGNORECASE,
)

# Speaker labels are stripped, not parsed: they are all "Unknown speaker:" and carry no
# information, but left in they would add ~2 tokens per block to every denominator. The
# second branch handles a named-speaker corpus; it wants Title Case words so that an
# ordinary sentence opening with a colon ("So here's the thing: ...") is not eaten.
_SPEAKER_RE = re.compile(
    r"^[ \t]*(?:Unknown speaker|(?:[A-Z][\w.'-]*[ \t]*){1,5}):[ \t]*", re.MULTILINE
)

# Forward-looking sentences, for the guidance channel. Bare "will" is deliberately absent:
# it matches most management sentences and made this channel a modal-counter.
_GUIDANCE_RE = re.compile(
    r"\b(expect|expects|expecting|anticipate|anticipates|outlook|guidance|guide|guiding|"
    r"forecast|next quarter|coming quarter|going forward|remainder of|rest of the year|"
    r"second half|full year|full-year|fiscal \d{4})\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TOKEN_RE = re.compile(r"[a-z]+")

# --------------------------------------------------------------------------------------
# Dictionaries
#
# Tone words only. Topic words were removed after measuring what they were doing: across
# the 216 earnings Q&As in this corpus, "cost", "costs", "inventory" and "gap" alone
# supplied 38-61% of every company's negative hits, which made the level channel a
# how-much-did-we-discuss-inventory counter that tracked the destocking cycle rather than
# management's tone. Also dropped: "below" (overwhelmingly comparative filler — "below
# that", "below the", "below our"), "demand" and "above" from the positive list for the
# same reason, and "digestion"/"tightness" as sector jargon. "pressure" was checked and
# kept: at HD it is "cost/wage/margin pressure" in almost every occurrence.
# --------------------------------------------------------------------------------------

NEGATIVE_WORDS = frozenset(
    """decline declined delay delayed difficult risk risks uncertainty weak weaker weakest
    headwind headwinds pressure pressures inflation shortage destock destocking miss
    cautious challenged challenge challenges slow slower softness contraction unemployment
    restructuring impairment litigation adverse negatively deterioration deteriorated
    concern concerns volatile volatility inflationary bottleneck""".split()
)

POSITIVE_WORDS = frozenset(
    """strong stronger record growth grew improve improved improvement momentum upside beat
    resilient confidence confident healthy solid robust expand expansion
    opportunity""".split()
)

UNCERTAINTY_WORDS = frozenset(
    """may might could approximately roughly around visibility uncertain uncertainty unclear
    maybe perhaps possibly somewhat caution cautious depend depends depending remain subject
    volatility volatile""".split()
)

# --------------------------------------------------------------------------------------
# Codebook
# --------------------------------------------------------------------------------------

QaNeg = Literal["low", "typical", "elevated", "severe"]
QaNegChange = Literal["eased", "stable", "worsened", "jumped"]
Uncertainty = Literal["clear", "normal", "hedged", "opaque"]
GuidanceLang = Literal["cautious", "neutral", "constructive"]

QA_NEG_ORD = {"low": 0, "typical": 1, "elevated": 2, "severe": 3}
QA_NEG_CHANGE_ORD = {"eased": 0, "stable": 1, "worsened": 2, "jumped": 3}
UNCERTAINTY_ORD = {"clear": 0, "normal": 1, "hedged": 2, "opaque": 3}
GUIDANCE_ORD = {"cautious": 0, "neutral": 1, "constructive": 2}

# The baseline is the company's own recent calls: long enough to be a distribution, short
# enough that a 2026 call is not being compared with 2014. Roughly two years of quarters.
BASELINE_WINDOW = 8
# Below this there is no distribution to standardise against, so the level channels abstain
# rather than fall back to absolute cuts that were never calibrated on anything.
MIN_BASELINE = 6

# Cuts on the standardised score, in standard deviations of the company's own recent
# variation. Symmetric and interpretable: |z| < 1 is an ordinary call for this issuer.
_QA_NEG_Z_CUTS = ((-1.0, "low"), (1.0, "typical"), (2.0, "elevated"), (None, "severe"))
_UNCERTAINTY_Z_CUTS = (
    (-1.0, "clear"),
    (1.0, "normal"),
    (2.0, "hedged"),
    (None, "opaque"),
)
# guidance_raw is pos - neg, so its low end is the cautious one.
_GUIDANCE_Z_CUTS = ((-1.0, "cautious"), (1.0, "neutral"), (None, "constructive"))
# A difference of two calls carries both calls' noise, hence the sqrt(2) in _run_change.
_CHANGE_Z_CUTS = ((-1.0, "eased"), (1.0, "stable"), (2.0, "worsened"), (None, "jumped"))


class CallToneOutput(BaseModel):
    """Call-tone signal. Words are the product; ordinals are for the TS model.

    Every channel appears twice: once as a word and once as `<channel>_ord`, its
    **ordinal** — the same word re-encoded as an ordered integer. They are one fact in two
    forms, not two features: `qa_neg="elevated"` and `qa_neg_ord=2` say the same thing.
    Feed one of them to a given model, never both. The ordinal is ordered but not metric —
    3 is worse than 2, but not "1.5x" worse — so it belongs in a tree/ordinal model, and
    should be one-hot encoded rather than treated as a continuous series in a linear one.

    The level channels are None when the company's baseline was too short to standardise
    against (see n_baseline and MIN_BASELINE). None means "not measured", never "neutral".

    Intended use: a tilt on a forecast derived from the filings, or a reason to widen an
    interval — not a driver of the level. Cap how far this signal can move a number.
    """

    company: str
    period: (
        str  # the period being forecast, e.g. "Q3 2026" — NOT the period of the call
    )
    as_of_call: Optional[str] = (
        None  # published_at of the lag-1 earnings Q&A that was scored
    )
    n_history: int = (
        0  # earnings Q&As supplied for this company, the scored one included
    )
    n_baseline: int = 0  # of those, how many prior calls formed the trailing baseline

    # How negative the Q&A was, in standard deviations of this company's own recent calls.
    # low(0) < typical(1) < elevated(2) < severe(3). Higher = more negative language.
    qa_neg: Optional[QaNeg] = None
    qa_neg_ord: Optional[int] = Field(default=None, ge=0, le=3)
    # The standardised score behind qa_neg, rounded. Published only so a caller can size
    # the tilt it takes from this signal; it is not a series to feed a model.
    qa_neg_z: Optional[float] = None

    # Movement in that negativity since the company's previous earnings Q&A — the tone
    # *change*, which historically carries more than the level. eased(0) = less negative
    # than last call, stable(1) = flat, worsened(2) / jumped(3) = more negative.
    # None when this input holds no prior call: missing, never zero-filled.
    qa_neg_change: Optional[QaNegChange] = None
    qa_neg_change_ord: Optional[int] = Field(default=None, ge=0, le=3)

    # Hedging and weak modals ("may", "could", "visibility", "depends") in the Q&A.
    # clear(0) < normal(1) < hedged(2) < opaque(3). Higher = management is committing less.
    uncertainty: Optional[Uncertainty] = None
    uncertainty_ord: Optional[int] = Field(default=None, ge=0, le=3)

    # Tone of the forward-looking sentences only (expect / outlook / guidance / full year).
    # This is the one channel where positive words are informative rather than boilerplate,
    # so it runs the other way: cautious(0) < neutral(1) < constructive(2), higher = better.
    guidance_language: Optional[GuidanceLang] = None
    guidance_language_ord: Optional[int] = Field(default=None, ge=0, le=2)

    # Short strings for the judge trail: which call was scored, what it was compared with,
    # and any caveat that would otherwise be invisible (abstained channels, and why).
    notes: list[str] = []


# --------------------------------------------------------------------------------------
# Text handling
# --------------------------------------------------------------------------------------


def _parse_document(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    return dict(_FRONT_MATTER_FIELD_RE.findall(match.group(1))), text[match.end() :]


def _clean_body(body: str) -> str:
    """Drop markdown headings, speaker labels and any safe-harbour paragraph."""
    body = _HEADING_RE.sub("", body)
    body = _SPEAKER_RE.sub("", body)
    return "\n\n".join(
        paragraph
        for paragraph in body.split("\n\n")
        if paragraph.strip() and not _SAFE_HARBOUR_RE.search(paragraph)
    )


def _counts(text: str) -> tuple[int, int, int, int]:
    """(tokens, negative, positive, uncertainty) for one block of text."""
    tokens = _TOKEN_RE.findall(text.lower())
    negative = sum(1 for token in tokens if token in NEGATIVE_WORDS)
    positive = sum(1 for token in tokens if token in POSITIVE_WORDS)
    uncertain = sum(1 for token in tokens if token in UNCERTAINTY_WORDS)
    return len(tokens), negative, positive, uncertain


# --------------------------------------------------------------------------------------
# Per-call raw rates (kept internal — the output carries words and ordinals only)
# --------------------------------------------------------------------------------------


class _CallScore(BaseModel):
    published_at: str
    period: str
    source: str
    tokens: int  # the denominator, and the sampling-noise floor for this call
    qa_neg_raw: float
    uncertainty_raw: float
    guidance_raw: float


def _score_call(
    document: RelevantDocument, front: dict[str, str], body: str
) -> _CallScore:
    """Score one call. Aggregator-supplied period and date win over the front matter,
    which mislabels enough calls that it is a fallback, not a source."""
    text = _clean_body(body)
    tokens, negative, _, uncertain = _counts(text)

    guidance = " ".join(
        sentence
        for sentence in _SENTENCE_RE.split(text)
        if _GUIDANCE_RE.search(sentence)
    )
    guidance_tokens, guidance_neg, guidance_pos, _ = _counts(guidance)

    return _CallScore(
        published_at=document.published_at or front.get("published_at", ""),
        period=document.period or front.get("period", ""),
        source=document.name,
        tokens=tokens,
        qa_neg_raw=negative / tokens if tokens else 0.0,
        uncertainty_raw=uncertain / tokens if tokens else 0.0,
        guidance_raw=(guidance_pos - guidance_neg) / guidance_tokens
        if guidance_tokens
        else 0.0,
    )


# --------------------------------------------------------------------------------------
# Standardising
#
# Two sources of spread matter, and the larger one wins. A word rate measured over a few
# thousand tokens carries binomial sampling noise (sd = sqrt(p(1-p)/n), ~0.0010 here); the
# same rate also varies genuinely from call to call (~0.0025 here). Dividing by the
# sampling noise alone would call every ordinary call a two-sigma event; dividing by the
# empirical spread alone would blow up in an unusually quiet window. So: the empirical sd
# of the trailing window, floored at the sampling noise.
# --------------------------------------------------------------------------------------


def _standard_error(baseline: Sequence[float], tokens: int) -> float:
    empirical = statistics.stdev(baseline) if len(baseline) >= 2 else 0.0
    mean = statistics.fmean(baseline) if baseline else 0.0
    sampling = (
        sqrt(mean * (1.0 - mean) / tokens) if tokens and 0.0 < mean < 1.0 else 0.0
    )
    return max(empirical, sampling)


def _z_score(value: float, baseline: Sequence[float], tokens: int) -> Optional[float]:
    """Standard deviations between `value` and the trailing baseline. None if degenerate."""
    if not baseline:
        return None
    error = _standard_error(baseline, tokens)
    if error <= 0.0:
        return None
    return (value - statistics.fmean(baseline)) / error


def _z_word(z: float, cuts: Sequence[tuple[Optional[float], str]]) -> str:
    for edge, word in cuts:
        if edge is None or z < edge:
            return word
    return cuts[-1][1]


# --------------------------------------------------------------------------------------
# The signal
# --------------------------------------------------------------------------------------


class SentimentSignal(AbstractSignal):
    """Call-tone features for one company, built only from the documents it is handed.

    Selection *within* `relevant_documents` — earnings Q&A, never prepared remarks,
    conference calls or AGMs — happens here, so the orchestrator can pass a company's
    whole transcript set. Nothing is read off disk beyond those paths.

    `as_of` optionally drops calls published on or after a date, for backtesting a print
    whose accompanying call is already in the corpus. Left unset, the latest supplied Q&A
    is the lag-1 call, which is correct for this corpus: it is frozen 2026-08-14 and none
    of the challenge prints have happened yet.
    """

    def __init__(self, as_of: date | None = None) -> None:
        self._as_of = as_of

    def run(self, signal_input: SignalInput) -> CallToneOutput:
        calls, skipped_after_cutoff, rejected = self._eligible_calls(
            signal_input.relevant_documents
        )
        if not calls:
            # Say which documents were turned away and why — "no Q&A found" on its own
            # looks like a bug when the caller has just handed over a transcript.
            listed = "".join(f"\n  - {name}: {reason}" for name, reason in rejected[:5])
            if len(rejected) > 5:
                listed += f"\n  - ... and {len(rejected) - 5} more"
            raise ValueError(
                f"no earnings-call Q&A for {signal_input.company} among the "
                f"{len(signal_input.relevant_documents)} supplied documents{listed}"
            )

        latest = calls[-1]
        # The scored call is never in its own baseline, and the window stops the label from
        # encoding the era instead of the quarter.
        baseline = calls[-(BASELINE_WINDOW + 1) : -1]
        notes = [
            f"lag-1 Q&A {latest.published_at} ({latest.period or 'period unlabelled'}), "
            f"{latest.tokens} tokens; baseline = {len(baseline)} prior call(s)"
        ]
        if baseline:
            notes.append(
                f"baseline spans {baseline[0].published_at}..{baseline[-1].published_at}"
            )

        qa_neg = uncertainty = guidance = None
        qa_neg_z: Optional[float] = None

        if len(baseline) >= MIN_BASELINE:
            qa_neg_z = _z_score(
                latest.qa_neg_raw, [c.qa_neg_raw for c in baseline], latest.tokens
            )
            uncertainty_z = _z_score(
                latest.uncertainty_raw,
                [c.uncertainty_raw for c in baseline],
                latest.tokens,
            )
            guidance_z = _z_score(
                latest.guidance_raw, [c.guidance_raw for c in baseline], latest.tokens
            )
            qa_neg = _z_word(qa_neg_z, _QA_NEG_Z_CUTS) if qa_neg_z is not None else None
            uncertainty = (
                _z_word(uncertainty_z, _UNCERTAINTY_Z_CUTS)
                if uncertainty_z is not None
                else None
            )
            guidance = (
                _z_word(guidance_z, _GUIDANCE_Z_CUTS)
                if guidance_z is not None
                else None
            )
        else:
            notes.append(
                f"levels abstained: {len(baseline)} prior call(s) < MIN_BASELINE={MIN_BASELINE}, "
                "nothing to standardise against"
            )

        change_word = self._run_change(calls, baseline, notes)

        if skipped_after_cutoff:
            notes.append(
                f"{skipped_after_cutoff} Q&A(s) at/after as_of {self._as_of} excluded"
            )

        return CallToneOutput(
            company=signal_input.company,
            period=signal_input.period,
            as_of_call=latest.published_at or None,
            n_history=len(calls),
            n_baseline=len(baseline),
            qa_neg=qa_neg,
            qa_neg_ord=QA_NEG_ORD[qa_neg] if qa_neg else None,
            qa_neg_z=round(qa_neg_z, 1) if qa_neg_z is not None else None,
            qa_neg_change=change_word,
            qa_neg_change_ord=QA_NEG_CHANGE_ORD[change_word] if change_word else None,
            uncertainty=uncertainty,
            uncertainty_ord=UNCERTAINTY_ORD[uncertainty] if uncertainty else None,
            guidance_language=guidance,
            guidance_language_ord=GUIDANCE_ORD[guidance] if guidance else None,
            notes=notes[:6],
        )

    @staticmethod
    def _run_change(
        calls: Sequence[_CallScore], baseline: Sequence[_CallScore], notes: list[str]
    ) -> Optional[str]:
        """Movement since the previous Q&A, standardised on the same scale as the level.

        The two calls each carry their own noise, so the spread of the difference is the
        per-call spread times sqrt(2). Without that the cuts sit inside the noise band and
        the channel is a coin flip.
        """
        if len(calls) < 2:
            notes.append(
                "no prior Q&A in this input: qa_neg_change omitted, not zero-filled"
            )
            return None
        if len(baseline) < MIN_BASELINE:
            notes.append(
                "qa_neg_change omitted: baseline too short to scale the difference"
            )
            return None

        latest, previous = calls[-1], calls[-2]
        error = _standard_error([c.qa_neg_raw for c in baseline], latest.tokens) * sqrt(
            2.0
        )
        if error <= 0.0:
            return None
        return _z_word(
            (latest.qa_neg_raw - previous.qa_neg_raw) / error, _CHANGE_Z_CUTS
        )

    def _eligible_calls(
        self, documents: Sequence[RelevantDocument]
    ) -> tuple[list[_CallScore], int, list[tuple[str, str]]]:
        """Earnings Q&A only, oldest first.

        Returns the scored calls, how many were cut by `as_of`, and (name, reason) for
        every document that was turned away, so a caller with no usable input can be told
        what was wrong with what it passed.

        Where the aggregator has classified a document, its class decides whether the
        call is an earnings call; the filename patterns are the fallback for hand-built
        lists. Nothing but the filename tells prepared remarks from Q&A, so that split
        stays a filename test either way.
        """
        scores: list[_CallScore] = []
        skipped = 0
        rejected: list[tuple[str, str]] = []

        for document in documents:
            path = document.path
            if document.document_type != "call_transcript":
                rejected.append(
                    (path.name, f"a {document.document_type}, not a call transcript")
                )
                continue
            if document.doc_class and document.doc_class != _EARNINGS_CALL_CLASS:
                rejected.append(
                    (path.name, f"{document.doc_class}, not an earnings call")
                )
                continue
            if not document.doc_class and _NOT_EARNINGS_RE.search(path.stem):
                rejected.append(
                    (path.name, "conference or AGM call, not an earnings call")
                )
                continue
            if not _QNA_RE.search(path.stem):
                if _PRES_RE.search(path.stem):
                    reason = "prepared remarks; this signal scores the Q&A only"
                elif _COMBINED_RE.search(path.stem):
                    reason = "whole call in one file; the Q&A cannot be separated out"
                else:
                    reason = "not a recognised earnings-call Q&A file"
                rejected.append((path.name, reason))
                continue

            front, body = _parse_document(path)
            published = document.published_at or front.get("published_at", "")
            if (
                self._as_of
                and published
                and date.fromisoformat(published) >= self._as_of
            ):
                skipped += 1
                rejected.append(
                    (path.name, f"published {published}, at/after as_of {self._as_of}")
                )
                continue

            score = _score_call(document, front, body)
            log.debug(
                "%s %s: %d tokens, qa_neg=%.4f",
                score.published_at,
                score.source,
                score.tokens,
                score.qa_neg_raw,
            )
            scores.append(score)

        scores.sort(key=lambda score: (score.published_at, score.source))
        return scores, skipped, rejected


# --------------------------------------------------------------------------------------
# Smoke test: run this file against specific transcripts to eyeball the signal.
#
# Run from the repository root, as with `python -m agent.aggregator`:
#
#   python -m agent.signal_subagents.sentiment challenge/offline-data/analog-devices/call-transcripts/*.md
#   python -m agent.signal_subagents.sentiment <one-file>.md      # single call, levels abstain
#   python -m agent.signal_subagents.sentiment <dir> --period 'Q3 2026' -v
#
# This block reads paths off disk and knows nothing about resolved periods, so its notes
# show the corpus's own (unreliable) front-matter period. Going through the aggregator —
# Panel.signal_input() — is what gets the resolved one. The orchestrator calls
# run(SignalInput) directly; this exists only so a human can eyeball a few files.
# --------------------------------------------------------------------------------------


def _smoke_test(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Score the earnings-call Q&A among the given transcripts and print the signal.",
        epilog=(
            "example: python -m agent.signal_subagents.sentiment "
            "challenge/offline-data/analog-devices/call-transcripts/*.md --period 'Q3 2026'"
        ),
    )
    parser.add_argument(
        "documents", nargs="+", type=Path, help=".md transcripts, or a directory"
    )
    parser.add_argument(
        "--company", help="default: the company named in the front matter"
    )
    parser.add_argument(
        "--period", help="period being forecast, e.g. 'Q3 2026' or FY2026Q3"
    )
    parser.add_argument("--as-of", help="ISO date; drop calls published on or after it")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every call scored"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING, format="%(message)s"
    )

    paths: list[Path] = []
    for entry in args.documents:
        paths.extend(sorted(entry.glob("*.md")) if entry.is_dir() else [entry])
    if not paths:
        print("no .md files found in those arguments")
        return 1

    # Front matter of the newest file supplies whatever the caller left off. The period
    # inferred this way is the *call's* period, not the period being forecast — fine for a
    # smoke test, but pass --period when the distinction matters.
    front, _ = _parse_document(max(paths, key=lambda path: path.name))
    company = args.company or front.get("company") or "unknown"
    period = args.period or front.get("period")
    if not period:
        print("could not infer a period from the front matter — pass --period")
        return 1

    signal = SentimentSignal(
        as_of=date.fromisoformat(args.as_of) if args.as_of else None
    )
    try:
        output = signal.run(
            SignalInput(company=company, period=period, relevant_documents=paths)
        )
    except ValueError as error:
        print(f"no signal: {error}")
        return 1

    print(f"{len(paths)} document(s) supplied")
    inferred = [f"company={company!r}"] * (not args.company) + [
        f"period={period!r}"
    ] * (not args.period)
    if inferred:
        print(f"read from front matter: {', '.join(inferred)}")
    print(
        f"scored {output.company} for {output.period}: lag-1 call {output.as_of_call}, "
        f"n_history={output.n_history}, n_baseline={output.n_baseline}"
    )
    for channel in ("qa_neg", "qa_neg_change", "uncertainty", "guidance_language"):
        word = getattr(output, channel)
        ordinal = getattr(output, f"{channel}_ord")
        suffix = (
            f"  z={output.qa_neg_z}" if channel == "qa_neg" and output.qa_neg_z else ""
        )
        print(f"  {channel:<18} {str(word):<16} ord={ordinal}{suffix}")
    for note in output.notes:
        print(f"  note: {note}")
    print()
    print(output.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
