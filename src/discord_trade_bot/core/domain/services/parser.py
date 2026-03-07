import re
from collections.abc import Callable
from typing import Any, final

from discord_trade_bot.core.domain.entities.signal import ParsedSignalEntity
from discord_trade_bot.core.domain.value_objects.formatters import dedupe_float_levels
from discord_trade_bot.core.domain.value_objects.trading import EntryMode, SignalType, TradeSide
from discord_trade_bot.core.shared.utils.parsing import safe_float
from discord_trade_bot.core.shared.utils.text import normalize_symbol, sha1_text


@final
class SignalParserService:
    """
    Stateless domain service responsible for parsing text into a ParsedSignalEntity.
    """

    BANNED_WORDS = frozenset(
        {
            "SIGNAL",
            "TRADE",
            "ENTRY",
            "PENDING",
            "ACTIVE",
            "PRICE",
            "TARGET",
            "TARGETS",
            "STOP",
            "LOSS",
            "UPDATED",
            "CALLER",
            "CURRENT",
            "PROFIT",
            "LEVERAGE",
            "TRADER",
            "NEXT",
            "TRIGGERED",
            "STATUS",
            "STATS",
            "RATE",
            "WIN",
            "HISTORICAL",
            "DATA",
            "PAST",
            "PERFORMANCE",
            "FUTURE",
            "RESULTS",
            "AUTOMATED",
            "SYSTEM",
            "LOW",
            "RISK",
            "RECOMMENDED",
            "ADVICE",
            "TODAY",
            "BYBIT",
            "MEXC",
            "BLOFIN",
            "BITGET",
            "ALGO",
            "SHORTS",
            "LONGS",
            "TP",
            "SL",
            "NOW",
        }
    )

    # Pre-compile regex patterns for performance
    _RE_HEADLINE = re.compile(r"^([A-Z][A-Z0-9]{2,19})\s+(LONG|SHORT)\b")
    _RE_SIDE_SYMBOL_1 = re.compile(r"\b(LONG|SHORT)\s+SIGNAL\s*[-:•]?\s*([A-Z0-9]{2,20})(?:/USDT\b|USDT\b|\b)")
    _RE_SYMBOL_SIDE_1 = re.compile(r"\b([A-Z0-9]{2,20})(?:/USDT|USDT)?\s+(LONG|SHORT)\s+SIGNAL\b")
    _RE_SIDE_SYMBOL_2 = re.compile(r"\b(BUY|SELL|LONG|SHORT)\s+([A-Z0-9]{2,20})(?:/USDT\b|USDT\b|\b)")
    _RE_NEW_SIGNAL = re.compile(r"NEW\s+SIGNAL\s*[•\-\|:]\s*([A-Z0-9]{2,20})\s*[•\-\|:]\s*ENTRY\s*\$?([0-9]+(?:\.[0-9]+)?)")
    _RE_ENTRY = re.compile(r"\bENTRY(?:\s+PRICE)?\s*[:\-]?\s*\$?([0-9]+(?:\.[0-9]+)?)")

    _RE_EXPLICIT_HEADERS = (
        re.compile(r"NEW\s+SIGNAL\s*[•\-\|:]\s*([A-Z0-9]{2,20})\s*[•\-\|:]\s*ENTRY"),
        re.compile(r"(?:LONG|SHORT)\s+SIGNAL\s*[-:•]?\s*([A-Z0-9]{2,20})/USDT"),
        re.compile(r"\b([A-Z0-9]{2,20})/USDT\b"),
    )

    _RE_GENERIC_PATTERNS = (
        re.compile(r"NEW\s+SIGNAL\s*[•\-\|:]\s*([A-Z0-9]{2,20})\s*[•\-\|:]\s*ENTRY"),
        re.compile(r"\b(LONG|SHORT)\s+SIGNAL\s*[-:•]?\s*([A-Z0-9]{2,20})(?:/USDT|\b)"),
        re.compile(r"\b([A-Z0-9]{2,20})\s+(LONG|SHORT)\s+SIGNAL\b"),
        re.compile(r"\b([A-Z0-9]{2,20})\s+(LONG|SHORT)\b"),
        re.compile(r"\b(BUY|LONG|SELL|SHORT)\s+([A-Z0-9]{2,20})(?:\b|/)"),
        re.compile(r"\b(?:COIN|PAIR|SYMBOL)\s*[:\-]\s*([A-Z0-9]{2,20})(?:/USDT|\b)"),
    )

    _RE_FALLBACK_SYMBOL_USDT = re.compile(r"\b([A-Z]{2,20})/USDT\b")
    _RE_FALLBACK_SYMBOL = re.compile(r"\b([A-Z]{2,15})USDT\b")

    _RE_ENTRY_CMP = re.compile(r"ENTRY\s*[:\-]\s*CMP\b")
    _RE_ENTRY_PATTERNS = (
        re.compile(r"\bENTRY(?:\s+PRICE)?\s*[:\-]?\s*\$?([0-9]+(?:\.[0-9]+)?)"),
        re.compile(r"\bENTRY\s+FILLED\s+AT\s*\$?([0-9]+(?:\.[0-9]+)?)"),
        re.compile(r"\bTRIGGERED\s+AT\s*\$?([0-9]+(?:\.[0-9]+)?)"),
        re.compile(r"NEW\s+SIGNAL\s*[•\-\|:]\s*[A-Z0-9]{2,20}\s*[•\-\|:]\s*ENTRY\s*\$?([0-9]+(?:\.[0-9]+)?)"),
    )

    _RE_LEVERAGE = re.compile(r"\b([0-9]{1,3})\s*X\b")
    _RE_SL = re.compile(r"\b(?:SL|STOP\s*LOSS|STOP-LOSS)\s*[:\-]?\s*\$?([0-9]+(?:\.[0-9]+)?)")
    _RE_TP_1 = re.compile(r"\b(?:TP|TARGET|TAKE\s*PROFIT)\s*[0-9]+\s*[:\-]?\s*\$?([0-9]+(?:\.[0-9]+)?)")
    _RE_TP_2 = re.compile(r"\bTP[L]?[0-9]*\s*[:\-]?\s*\$?([0-9]+(?:\.[0-9]+)?)")
    _RE_TP_HIT = re.compile(r"\b(TP1\s*HIT|TARGET\s*1\s*REACHED|NEXT\s*TARGET\s*[:\-]\s*TP2)\b")
    _RE_TRIGGERED = re.compile(r"\bENTRY\b[\s\S]{0,40}\bTRIGGERED\b|\bENTRY\s+TRIGGERED\b|\bACTIVE\s+TRADE\b|\bBREAKEVEN\b")

    def parse(self, source_id: str, message_id: str, text: str) -> ParsedSignalEntity:
        raw = text or ""
        text_up = raw.upper()
        msg_hash = sha1_text(raw)

        sig = ParsedSignalEntity(
            source_id=source_id,
            message_id=message_id,
            message_hash=msg_hash,
            message_text=raw,
        )

        if not raw.strip():
            return sig

        context = {"symbol_rank": -1, "side_rank": -1}

        self._parse_headline(raw, sig, context)
        self._parse_lines(raw, sig, context)
        self._parse_headers(text_up, sig, context)
        self._parse_generic_patterns(text_up, sig, context)
        self._parse_fallback_symbols(text_up, sig, context)
        self._parse_entry(text_up, sig)
        self._parse_leverage_and_stops(text_up, sig)
        self._finalize_signal_type(text_up, sig)

        return sig

    def _set_field_with_rank(
        self,
        sig: ParsedSignalEntity,
        context: dict[str, int],
        field_name: str,
        value: Any,
        rank: int = 0,
        normalizer: Callable[[Any], Any] | None = None,
    ) -> None:
        """Generic method to set a field with ranking logic."""
        if not value:
            return

        normalized = normalizer(value) if normalizer else value

        rank_key = f"{field_name}_rank"
        if getattr(sig, field_name, None) and context.get(rank_key, -1) > rank:
            return

        setattr(sig, field_name, normalized)
        context[rank_key] = rank
        sig.is_signal = True
        if sig.signal_type == SignalType.UNKNOWN:
            sig.signal_type = SignalType.PRIMARY_SIGNAL

    def _set_symbol(self, sig: ParsedSignalEntity, context: dict[str, int], symbol_raw: str | None, rank: int = 0) -> None:
        if not symbol_raw:
            return

        # Clean and validate symbol
        candidate = str(symbol_raw).strip().upper().replace("$", "")
        candidate = re.sub(r"[^A-Z0-9/]", "", candidate)
        if not candidate:
            return
        if candidate.endswith("/USDT"):
            candidate = candidate[:-5]
        if candidate.endswith("USDT"):
            candidate = candidate[:-4]
        if not candidate or candidate in self.BANNED_WORDS:
            return
        self._set_field_with_rank(sig, context, "symbol", candidate, rank, normalizer=normalize_symbol)

    def _set_side(self, sig: ParsedSignalEntity, context: dict[str, int], side_word: str | None, rank: int = 0) -> None:
        if not side_word:
            return

        # Normalize side word
        word = str(side_word).strip().upper()
        if word in {"BUY", "LONG"}:
            normalized = TradeSide.LONG
        elif word in {"SELL", "SHORT"}:
            normalized = TradeSide.SHORT
        else:
            return

        # Use generic setter
        self._set_field_with_rank(sig, context, "side", normalized, rank)

    def _parse_headline(self, raw: str, sig: ParsedSignalEntity, context: dict[str, int]) -> None:
        for line in raw.splitlines():
            line_up = line.upper().strip()
            if "•" not in line_up or (" LONG" not in line_up and " SHORT" not in line_up):
                continue
            parts = [p.strip() for p in line_up.split("•") if p.strip()]
            for part in parts:
                m = self._RE_HEADLINE.match(part)
                if m:
                    self._set_symbol(sig, context, m.group(1), rank=100)
                    self._set_side(sig, context, m.group(2))
                    break
            if sig.symbol and sig.side:
                break

    def _parse_lines(self, raw: str, sig: ParsedSignalEntity, context: dict[str, int]) -> None:
        for line in raw.splitlines():
            line_up = " ".join(line.upper().strip().split())
            if not line_up:
                continue

            if m := self._RE_SIDE_SYMBOL_1.search(line_up):
                self._set_side(sig, context, m.group(1), rank=40)
                self._set_symbol(sig, context, m.group(2), rank=40)

            if m := self._RE_SYMBOL_SIDE_1.search(line_up):
                self._set_symbol(sig, context, m.group(1), rank=85)
                self._set_side(sig, context, m.group(2), rank=85)

            if m := self._RE_SIDE_SYMBOL_2.search(line_up):
                self._set_side(sig, context, m.group(1))
                self._set_symbol(sig, context, m.group(2))

            if m := self._RE_NEW_SIGNAL.search(line_up):
                self._set_symbol(sig, context, m.group(1), rank=20)
                if sig.entry_price is None:
                    sig.entry_price = safe_float(m.group(2))
                    sig.entry_mode = sig.entry_mode or EntryMode.EXACT_PRICE
                    sig.is_signal = True
                    if sig.signal_type == SignalType.UNKNOWN:
                        sig.signal_type = SignalType.PRIMARY_SIGNAL

            if m := self._RE_ENTRY.search(line_up):
                if sig.entry_price is None:
                    sig.entry_price = safe_float(m.group(1))
                    sig.entry_mode = sig.entry_mode or EntryMode.EXACT_PRICE
                    sig.is_signal = True
                    if sig.signal_type == SignalType.UNKNOWN:
                        sig.signal_type = SignalType.PRIMARY_SIGNAL

    def _parse_headers(self, text_up: str, sig: ParsedSignalEntity, context: dict[str, int]) -> None:
        for pattern in self._RE_EXPLICIT_HEADERS:
            if m := pattern.search(text_up):
                # Pattern 0 is the NEW SIGNAL one
                rank = 100 if pattern == self._RE_EXPLICIT_HEADERS[0] else 95
                self._set_symbol(sig, context, m.group(1), rank=rank)
                break

    def _parse_generic_patterns(self, text_up: str, sig: ParsedSignalEntity, context: dict[str, int]) -> None:
        for pattern in self._RE_GENERIC_PATTERNS:
            if m := pattern.search(text_up):
                g1 = m.group(1).strip()
                g2 = m.group(2).strip() if m.lastindex and m.lastindex >= 2 else None

                # Check which group is side and which is symbol based on the regex structure
                is_new_signal = pattern == self._RE_GENERIC_PATTERNS[0]

                if is_new_signal:
                    symbol_raw, side_word = g1, None
                elif g1 in {"BUY", "LONG", "SELL", "SHORT"}:
                    side_word, symbol_raw = g1, g2
                elif g2 in {"LONG", "SHORT"}:
                    symbol_raw, side_word = g1, g2
                else:
                    symbol_raw, side_word = g1, None

                self._set_symbol(sig, context, symbol_raw, rank=30)
                self._set_side(sig, context, side_word, rank=30)
                if sig.symbol and sig.side:
                    break

    def _parse_fallback_symbols(self, text_up: str, sig: ParsedSignalEntity, context: dict[str, int]) -> None:
        if not sig.symbol:
            if m := self._RE_FALLBACK_SYMBOL_USDT.search(text_up):
                self._set_symbol(sig, context, m.group(1))
            elif m := self._RE_FALLBACK_SYMBOL.search(text_up):
                self._set_symbol(sig, context, m.group(1), rank=20)

    def _parse_entry(self, text_up: str, sig: ParsedSignalEntity) -> None:
        if self._RE_ENTRY_CMP.search(text_up):
            sig.entry_mode = EntryMode.CMP
            sig.is_signal = True
            if sig.signal_type == SignalType.UNKNOWN:
                sig.signal_type = SignalType.PRIMARY_SIGNAL
        elif sig.entry_price is not None:
            sig.entry_mode = EntryMode.EXACT_PRICE
            sig.is_signal = True
            if sig.signal_type == SignalType.UNKNOWN:
                sig.signal_type = SignalType.PRIMARY_SIGNAL
        else:
            for pattern in self._RE_ENTRY_PATTERNS:
                if m := pattern.search(text_up):
                    sig.entry_mode = EntryMode.EXACT_PRICE
                    sig.entry_price = safe_float(m.group(1))
                    sig.is_signal = True
                    if sig.signal_type == SignalType.UNKNOWN:
                        sig.signal_type = SignalType.PRIMARY_SIGNAL
                    break

    def _parse_leverage_and_stops(self, text_up: str, sig: ParsedSignalEntity) -> None:
        if m := self._RE_LEVERAGE.search(text_up):
            sig.leverage = int(m.group(1))

        if m := self._RE_SL.search(text_up):
            sig.stop_loss = safe_float(m.group(1))

        tp_matches = []
        tp_matches.extend(self._RE_TP_1.findall(text_up))
        tp_matches.extend(self._RE_TP_2.findall(text_up))

        sig.take_profits = dedupe_float_levels([v for v in (safe_float(m) for m in tp_matches) if v is not None])
        sig.contains_tp1_hit = bool(self._RE_TP_HIT.search(text_up))
        sig.entry_triggered = bool(self._RE_TRIGGERED.search(text_up))

    def _finalize_signal_type(self, text_up: str, sig: ParsedSignalEntity) -> None:
        # Simplified logic - process all signals with symbol and side
        if (sig.stop_loss or sig.take_profits or sig.contains_tp1_hit) and not sig.is_signal:
            sig.signal_type = SignalType.SIGNAL_UPDATE

        card_keywords = ["NEW SIGNAL", "ACTIVE TRADE", "ENTRY FILLED", "TP1", "SL:", "PROFIT TARGETS", "TRIGGERED"]
        if any(k in text_up for k in card_keywords):
            sig.is_signal = sig.is_signal or bool(sig.symbol)
            if sig.signal_type == SignalType.UNKNOWN:
                sig.signal_type = SignalType.SIGNAL_UPDATE if (sig.stop_loss or sig.take_profits) else SignalType.PRIMARY_SIGNAL
