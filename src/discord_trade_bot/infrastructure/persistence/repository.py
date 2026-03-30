import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, final, override

import aiofiles
import aiosqlite
import orjson

from discord_trade_bot.core.application.common.interfaces.repository import (
    StateRepositoryProtocol,
)
from discord_trade_bot.core.domain.entities.pending_entry import PendingEntryEntity
from discord_trade_bot.core.domain.entities.position import ActivePositionEntity
from discord_trade_bot.core.domain.value_objects.trading import (
    PositionStatus,
    TPDistributionRow,
    TradeSide,
)

logger = logging.getLogger(__name__)


@final
class SqliteStateRepository(StateRepositoryProtocol):
    def __init__(self, db_file: str, trades_file: str):
        self._db_file = Path(db_file)
        self._trades_file = Path(trades_file)
        # Ensure parent dirs exist
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._trades_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def init_db(self):
        """Initialize the SQLite database schema."""
        if self._initialized:
            return
        async with aiosqlite.connect(self._db_file) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_entries (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    data TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            await db.commit()
            self._initialized = True

    def _deserialize_position(self, row: Any) -> ActivePositionEntity | None:
        """Deserialize a position from database row.

        Args:
            row: Database row containing JSON data.

        Returns:
            Deserialized position entity or None if parsing fails.
        """
        try:
            data = orjson.loads(row[0])

            # Restore types manually (Infrastructure mapping)
            if "side" in data and isinstance(data["side"], str):
                data["side"] = TradeSide(data["side"])
            if "status" in data and isinstance(data["status"], str):
                data["status"] = PositionStatus(data["status"])
            if "opened_at" in data and isinstance(data["opened_at"], str):
                data["opened_at"] = datetime.fromisoformat(data["opened_at"].replace("Z", "+00:00"))
            if "tp_distribution" in data and isinstance(data["tp_distribution"], list):
                data["tp_distribution"] = [TPDistributionRow(**tp) if isinstance(tp, dict) else tp for tp in data["tp_distribution"]]

            return ActivePositionEntity(**data)
        except Exception as e:
            logger.error(f"Error parsing position from DB: {e}")
            return None

    @override
    async def get_open_positions(self) -> list[ActivePositionEntity]:
        async with aiosqlite.connect(self._db_file) as db:
            async with db.execute("SELECT data FROM positions WHERE status = ?", (PositionStatus.OPEN.value,)) as cursor:
                rows = await cursor.fetchall()
        return [pos for row in rows if (pos := self._deserialize_position(row))]

    @override
    async def get_position_by_id(self, position_id: str) -> ActivePositionEntity | None:
        async with aiosqlite.connect(self._db_file) as db:
            async with db.execute("SELECT data FROM positions WHERE id = ? AND status = ?", (position_id, PositionStatus.OPEN.value)) as cursor:
                row = await cursor.fetchone()

        return self._deserialize_position(row) if row else None

    @override
    async def get_open_positions_by_symbol_and_exchange(self, symbol: str, exchange: str) -> list[ActivePositionEntity]:
        async with aiosqlite.connect(self._db_file) as db:
            async with db.execute(
                "SELECT data FROM positions WHERE status IN (?, ?) AND json_extract(data, '$.symbol') = ? AND json_extract(data, '$.exchange') = ?",
                (PositionStatus.OPEN.value, PositionStatus.WAITING_UPDATE.value, symbol, exchange),
            ) as cursor:
                rows = await cursor.fetchall()
        return [pos for row in rows if (pos := self._deserialize_position(row))]

    @override
    async def save_position(self, position: ActivePositionEntity) -> None:
        """Saves or updates a position in the database."""
        # If no id, generate it
        if not position.id:
            position.id = str(uuid.uuid4())
        pos_id = str(position.id)

        # orjson serializes dataclasses, enums and datetime fast!
        data_json = orjson.dumps(position, option=orjson.OPT_SERIALIZE_DATACLASS).decode("utf-8")
        async with aiosqlite.connect(self._db_file) as db:
            await db.execute(
                """
                INSERT INTO positions (id, data, status)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data=excluded.data,
                    status=excluded.status
                """,
                (pos_id, data_json, position.status.value),
            )
            await db.commit()

    @override
    async def append_trade_log(self, trade_data: dict[str, Any]) -> None:
        async with aiofiles.open(self._trades_file, mode="a", encoding="utf-8") as f:
            await f.write(orjson.dumps(trade_data).decode("utf-8") + "\n")

    def _deserialize_pending_entry(self, row: Any) -> PendingEntryEntity | None:
        """Deserialize a pending entry from database row.

        Args:
            row: Database row containing JSON data.

        Returns:
            Deserialized pending entry entity or None if parsing fails.
        """
        try:
            data = orjson.loads(row[0])

            # Restore types manually
            if "side" in data and isinstance(data["side"], str):
                data["side"] = TradeSide(data["side"])
            if "created_at" in data and isinstance(data["created_at"], str):
                data["created_at"] = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if "tp_distribution" in data and isinstance(data["tp_distribution"], list):
                data["tp_distribution"] = [TPDistributionRow(**tp) if isinstance(tp, dict) else tp for tp in data["tp_distribution"]]

            return PendingEntryEntity(**data)
        except Exception as e:
            logger.error(f"Error parsing pending entry from DB: {e}")
            return None

    @override
    async def save_pending_entry(self, entry: PendingEntryEntity) -> None:
        """Save or update a pending entry."""
        # If no id, generate it
        if not entry.id:
            entry.id = str(uuid.uuid4())
        entry_id = str(entry.id)

        # Serialize to JSON
        data_json = orjson.dumps(entry, option=orjson.OPT_SERIALIZE_DATACLASS).decode("utf-8")
        async with aiosqlite.connect(self._db_file) as db:
            await db.execute(
                """
                INSERT INTO pending_entries (id, symbol, data, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data=excluded.data,
                    status=excluded.status
                """,
                (entry_id, entry.symbol, data_json, entry.status),
            )
            await db.commit()

    @override
    async def get_pending_entry_by_symbol(self, symbol: str) -> PendingEntryEntity | None:
        """Retrieve a pending entry by symbol."""
        async with aiosqlite.connect(self._db_file) as db:
            async with db.execute("SELECT data FROM pending_entries WHERE symbol = ? AND status = ?", (symbol, "pending")) as cursor:
                row = await cursor.fetchone()

        return self._deserialize_pending_entry(row) if row else None

    @override
    async def get_all_pending_entries(self) -> list[PendingEntryEntity]:
        """Retrieve all pending entries."""
        async with aiosqlite.connect(self._db_file) as db:
            async with db.execute("SELECT data FROM pending_entries WHERE status = ?", ("pending",)) as cursor:
                rows = await cursor.fetchall()
        return [entry for row in rows if (entry := self._deserialize_pending_entry(row))]

    @override
    async def delete_pending_entry(self, symbol: str) -> None:
        """Delete a pending entry by symbol."""
        async with aiosqlite.connect(self._db_file) as db:
            await db.execute("DELETE FROM pending_entries WHERE symbol = ?", (symbol,))
            await db.commit()
