"""Fan-out: run every registered signal subagent for one company and period.

This is the only module that imports both halves of the codebase. The aggregator
never learns what a signal is; a signal never learns where its documents came
from. Adding signal number two is one line in SIGNALS.

Two policies live here because they are the same for every signal:

1. **The as-of cutoff is applied once, on the aggregator side.** `Panel.signal_input`
   drops documents published on or after the cutoff before any subagent sees them.
   `SentimentSignal` also takes an `as_of` of its own; it is deliberately left
   unset. Filtering in two places means a signal that never implemented a cutoff
   silently gets un-filtered input, which is exactly the leak the cutoff exists
   to prevent.

2. **A signal that raises loses its columns, not the run.** `SentimentSignal.run`
   raises when it finds no usable Q&A among the documents it was handed — a real
   outcome for early backfill rows, where the cutoff leaves nothing behind. One
   company's thin transcript history must not take out the other eleven targets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from types import UnionType
from typing import Any, Optional, Union, get_args, get_origin

from pydantic import BaseModel

from ..signal_subagents.abc_subagent import AbstractSignal, SignalInput
from ..signal_subagents.sentiment import SentimentSignal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Registered:
    """One signal, and which slice of the corpus it is handed.

    `kind` is passed straight to `Panel.docs`: "transcript", "filing", "results",
    "slide", or None for everything. Signals select *within* what they are given
    — the call-tone signal drops prepared remarks and conference calls itself —
    so this only has to be a coarse cut.
    """

    name: str
    signal: AbstractSignal
    kind: Optional[str] = "transcript"


SIGNALS: tuple[Registered, ...] = (
    Registered("calltone", SentimentSignal(), kind="transcript"),
)


@dataclass
class FanOut:
    """What every signal returned for one (company, period, as_of)."""

    outputs: dict[str, BaseModel]
    failures: dict[str, str]

    @property
    def features(self) -> dict[str, Optional[float]]:
        """The numeric channels, flattened and name-spaced by signal."""
        flat: dict[str, Optional[float]] = {}
        for name, output in self.outputs.items():
            flat.update(numeric_features(name, output))
        return flat


def run_signals(
    panel: Any,
    company: str,
    period: Any,
    as_of: date | str | None = None,
) -> FanOut:
    """Run every registered signal for `company` forecasting `period`.

    `as_of` drops documents published on or after that date, so a backfill row
    for an already-reported period cannot read the answer off the call that
    announced it. Leave it unset only for periods that have genuinely not printed.
    """
    outputs: dict[str, BaseModel] = {}
    failures: dict[str, str] = {}

    for entry in SIGNALS:
        try:
            payload = panel.signal_input(company, period, kind=entry.kind, as_of=as_of)
            outputs[entry.name] = entry.signal.run(SignalInput(**payload))
        except Exception as exc:  # a thin signal must not take out the run
            failures[entry.name] = f"{type(exc).__name__}: {exc}"
            log.debug("signal %s abstained for %s %s: %s", entry.name, company, period, exc)

    return FanOut(outputs=outputs, failures=failures)


# --------------------------------------------------------------------------
# Flattening
#
# Only numeric channels cross into the matrix, and the annotation decides which
# those are. `CallToneOutput` carries every channel twice — `qa_neg="elevated"`
# and `qa_neg_ord=2` are one fact in two forms, and its docstring is explicit
# that a model must see one of them, never both. Keeping the numerics drops the
# word half automatically, along with `notes`, `company`, `period` and
# `as_of_call`, which belong in the audit trail rather than in a feature.
#
# None is preserved as None. It means "not measured" — the level channels
# abstain below MIN_BASELINE prior calls — and must reach the model as missing.
# Zero-filling it would encode "not measured" as "ordinary call".
# --------------------------------------------------------------------------


def numeric_features(name: str, output: BaseModel) -> dict[str, Optional[float]]:
    """Numeric fields of a signal's output, prefixed with the signal's name."""
    out: dict[str, Optional[float]] = {}
    for field, info in type(output).model_fields.items():
        if not _is_numeric(info.annotation):
            continue
        value = getattr(output, field, None)
        out[f"{name}_{field}"] = None if value is None else float(value)
    return out


def _is_numeric(annotation: Any) -> bool:
    """Is this annotation an int/float channel, allowing for Optional?"""
    origin = get_origin(annotation)
    if origin is not None:
        if origin in (Union, UnionType):
            return any(
                _is_numeric(arg) for arg in get_args(annotation) if arg is not type(None)
            )
        return False  # list[...], dict[...], and Literal[...] word channels
    return isinstance(annotation, type) and issubclass(annotation, (int, float))
