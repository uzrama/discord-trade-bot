from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessSignalDTO:
    source_id: str
    channel_id: str
    message_id: str
    text: str


@dataclass(frozen=True, slots=True)
class SignalProcessingResultDTO:
    success: bool
    message_id: str
    symbol: str | None = None
    reason: str | None = None
