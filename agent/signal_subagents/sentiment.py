from typing import Any

from signal_subagents.abc_subagent import AbstractSignal, SignalInput


class SentimentSignal(AbstractSignal):

    def run(self, signal_input: SignalInput) -> Any:
        raise NotImplementedError
