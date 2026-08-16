"""Deterministic document aggregator for the mind-the-gaap corpus."""

from .fiscal import FiscalPeriod, PeriodSpan, FiscalCalendar, Granularity
from .classify import DocClass, parse_filename, is_noise_title
from .corpus import Document, load_documents, load_challenge_targets
from . import profiler

__all__ = [
    "FiscalPeriod", "PeriodSpan", "FiscalCalendar", "Granularity",
    "DocClass", "parse_filename", "is_noise_title",
    "Document", "load_documents", "load_challenge_targets",
    "profiler",
]
