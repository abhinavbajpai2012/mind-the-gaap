"""Signal subagents: one module per signal, all implementing AbstractSignal.

Import as `agent.signal_subagents.<name>`, from the repository root — the same
convention as `agent.aggregator`, so both halves can live in one process.

The individual signals are not imported here: a caller wants one of them, and
`from agent.signal_subagents.sentiment import SentimentSignal` should not pay for
the rest.
"""

from .abc_subagent import AbstractSignal, RelevantDocument, SignalInput

__all__ = ["AbstractSignal", "RelevantDocument", "SignalInput"]
