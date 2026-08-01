from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from modules.health_insights.models import DailyHealthInsight


DAILY_COLUMNS = tuple(DailyHealthInsight.__dataclass_fields__)
BOOLEAN_COLUMNS = {
    "nutrition_complete",
    "activity_complete",
    "sleep_complete",
    "weight_available",
    "is_current_day",
    "nutrition_activity_weight_complete",
}
COMPARISON_COLUMNS = tuple(
    column
    for column in DAILY_COLUMNS
    if column not in {"first_imported_at", "last_refreshed_at"}
)


class HealthInsightsDatabase:
    def __init__(self, path: str | Path = "data/health_insights.db"):
        self.path = Path(path)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS health_insight_days (
                    local_date TEXT PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    nutrition_calories REAL,
                    protein_grams REAL,
                    carbohydrate_grams REAL,
                    fat_grams REAL,
                    fiber_grams REAL,
                    sodium_milligrams REAL,
                    nutrition_complete INTEGER NOT NULL DEFAULT 0,
                    nutrition_source TEXT,
                    nutrition_platform TEXT,
                    nutrition_record_count INTEGER NOT NULL DEFAULT 0,
                    steps INTEGER,
                    total_calories_burned REAL,
                    active_energy_calories REAL,
                    active_minutes INTEGER,
                    active_zone_minutes INTEGER,
                    distance_miles REAL,
                    exercise_session_count INTEGER NOT NULL DEFAULT 0,
                    exercise_minutes REAL,
                    exercise_calories REAL,
                    activity_complete INTEGER NOT NULL DEFAULT 0,
                    activity_source TEXT,
                    sleep_minutes INTEGER,
                    sleep_hours REAL,
                    awake_minutes INTEGER,
                    sleep_session_count INTEGER NOT NULL DEFAULT 0,
                    sleep_complete INTEGER NOT NULL DEFAULT 0,
                    sleep_source TEXT,
                    weight_pounds REAL,
                    seven_day_average_weight_pounds REAL,
                    body_fat_percentage REAL,
                    muscle_percentage REAL,
                    visceral_fat_index REAL,
                    weight_available INTEGER NOT NULL DEFAULT 0,
                    weight_source TEXT,
                    is_current_day INTEGER NOT NULL DEFAULT 0,
                    nutrition_activity_weight_complete INTEGER NOT NULL DEFAULT 0,
                    data_status TEXT NOT NULL,
                    first_imported_at TEXT NOT NULL,
                    last_refreshed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_health_insight_days_status
                ON health_insight_days (data_status, local_date);

                CREATE TABLE IF NOT EXISTS health_insights_sync_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_attempt_at TEXT,
                    last_successful_sync_at TEXT,
                    last_from_date TEXT,
                    last_through_date TEXT,
                    last_status TEXT,
                    last_error TEXT
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def backup_before_first_sync(self) -> Path | None:
        if not self.path.exists() or self.has_successful_sync():
            return None
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.path.with_name(
            f"{self.path.stem}.backup-{timestamp}{self.path.suffix}"
        )
        shutil.copy2(self.path, destination)
        return destination

    def has_successful_sync(self) -> bool:
        if not self.path.exists():
            return False
        try:
            state = self.sync_state()
        except sqlite3.DatabaseError:
            return False
        return bool(state and state.get("last_successful_sync_at"))

    def upsert_days(self, records: Iterable[DailyHealthInsight]) -> dict[str, int]:
        counts = {"inserted": 0, "updated": 0, "unchanged": 0}
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                existing_row = connection.execute(
                    "SELECT * FROM health_insight_days WHERE local_date = ?",
                    (record.local_date,),
                ).fetchone()
                existing = self._row_to_dict(existing_row) if existing_row else None
                payload = record.to_dict()
                if existing is None:
                    counts["inserted"] += 1
                    self._insert(connection, payload)
                    continue
                changed = any(
                    existing.get(column) != payload.get(column)
                    for column in COMPARISON_COLUMNS
                )
                counts["updated" if changed else "unchanged"] += 1
                payload["first_imported_at"] = existing["first_imported_at"]
                self._update(connection, payload)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return counts

    def _insert(self, connection, payload):
        columns = ", ".join(DAILY_COLUMNS)
        placeholders = ", ".join("?" for _ in DAILY_COLUMNS)
        connection.execute(
            f"INSERT INTO health_insight_days ({columns}) VALUES ({placeholders})",
            tuple(self._database_value(column, payload[column]) for column in DAILY_COLUMNS),
        )

    def _update(self, connection, payload):
        assignments = ", ".join(
            f"{column} = ?" for column in DAILY_COLUMNS if column != "local_date"
        )
        values = [
            self._database_value(column, payload[column])
            for column in DAILY_COLUMNS
            if column != "local_date"
        ]
        values.append(payload["local_date"])
        connection.execute(
            f"UPDATE health_insight_days SET {assignments} WHERE local_date = ?",
            values,
        )

    def get_day(self, local_date: str) -> dict | None:
        if not self.path.exists():
            return None
        connection = self._read_connection()
        try:
            row = connection.execute(
                "SELECT * FROM health_insight_days WHERE local_date = ?",
                (local_date,),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def list_days(self, limit: int | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        query = "SELECT * FROM health_insight_days ORDER BY local_date DESC"
        params = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        connection = self._read_connection()
        try:
            rows = connection.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            connection.close()

    def count_days(self) -> int:
        return len(self.list_days())

    def count_complete_days(self) -> int:
        if not self.path.exists():
            return 0
        connection = self._read_connection()
        try:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM health_insight_days
                WHERE nutrition_activity_weight_complete = 1
                  AND is_current_day = 0
                """
            ).fetchone()
            return int(row["count"] if row else 0)
        finally:
            connection.close()

    def date_range(self) -> tuple[str | None, str | None]:
        if not self.path.exists():
            return None, None
        connection = self._read_connection()
        try:
            row = connection.execute(
                "SELECT MIN(local_date) AS earliest, MAX(local_date) AS latest FROM health_insight_days"
            ).fetchone()
            return (row["earliest"], row["latest"]) if row else (None, None)
        finally:
            connection.close()

    def record_sync_state(
        self,
        *,
        attempted_at: str,
        successful_at: str | None,
        from_date: str,
        through_date: str,
        status: str,
        error: str | None,
    ):
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT INTO health_insights_sync_state
                    (id, last_attempt_at, last_successful_sync_at, last_from_date,
                     last_through_date, last_status, last_error)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_successful_sync_at = COALESCE(
                        excluded.last_successful_sync_at,
                        health_insights_sync_state.last_successful_sync_at
                    ),
                    last_from_date = excluded.last_from_date,
                    last_through_date = excluded.last_through_date,
                    last_status = excluded.last_status,
                    last_error = excluded.last_error
                """,
                (
                    attempted_at,
                    successful_at,
                    from_date,
                    through_date,
                    status,
                    error,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def sync_state(self) -> dict:
        if not self.path.exists():
            return {}
        connection = self._read_connection()
        try:
            try:
                row = connection.execute(
                    "SELECT * FROM health_insights_sync_state WHERE id = 1"
                ).fetchone()
            except sqlite3.OperationalError:
                return {}
            return dict(row) if row else {}
        finally:
            connection.close()

    def status(self) -> dict:
        earliest, latest = self.date_range()
        state = self.sync_state()
        return {
            "database_exists": self.path.exists(),
            "stored_days": self.count_days(),
            "earliest_date": earliest,
            "latest_date": latest,
            "complete_days": self.count_complete_days(),
            "last_successful_sync": state.get("last_successful_sync_at"),
            "last_status": state.get("last_status"),
        }

    def _read_connection(self):
        uri = f"{self.path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _database_value(column, value):
        return int(value) if column in BOOLEAN_COLUMNS else value

    @staticmethod
    def _row_to_dict(row):
        if row is None:
            return None
        result = dict(row)
        for column in BOOLEAN_COLUMNS:
            result[column] = bool(result[column])
        return result
