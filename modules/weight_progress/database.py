import sqlite3
from pathlib import Path

from modules.weight_progress.models import WeightMeasurement


class WeightProgressDatabase:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS weight_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    source_entity TEXT NOT NULL,
                    weight_kg REAL,
                    body_fat_percent REAL,
                    fat_mass_kg REAL,
                    fat_free_mass_kg REAL,
                    muscle_mass_kg REAL,
                    bone_mass_kg REAL,
                    hydration_kg REAL,
                    heart_rate_bpm REAL,
                    scale_battery TEXT,
                    comments TEXT,
                    import_source TEXT,
                    source_label TEXT,
                    imported_at TEXT,
                    withings_goal_kg REAL,
                    reading_hash TEXT NOT NULL UNIQUE,
                    metadata_json TEXT
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_measurements)").fetchall()}
            for column, ddl in (
                ("hydration_kg", "ALTER TABLE weight_measurements ADD COLUMN hydration_kg REAL"),
                ("comments", "ALTER TABLE weight_measurements ADD COLUMN comments TEXT"),
                ("import_source", "ALTER TABLE weight_measurements ADD COLUMN import_source TEXT"),
                ("source_label", "ALTER TABLE weight_measurements ADD COLUMN source_label TEXT"),
                ("imported_at", "ALTER TABLE weight_measurements ADD COLUMN imported_at TEXT"),
                ("withings_goal_kg", "ALTER TABLE weight_measurements ADD COLUMN withings_goal_kg REAL"),
            ):
                if column not in columns:
                    conn.execute(ddl)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_weight_measurements_lookup
                ON weight_measurements (source_entity, source_timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_weight_measurements_timestamp
                ON weight_measurements (captured_at)
                """
            )
            conn.commit()
        finally:
            conn.close()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_measurement(self, measurement):
        if not measurement:
            return False
        snapshot = measurement if isinstance(measurement, WeightMeasurement) else WeightMeasurement(**measurement)
        conn = self.connect()
        try:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO weight_measurements
                (captured_at, source_timestamp, source_entity, weight_kg, body_fat_percent,
                 fat_mass_kg, fat_free_mass_kg, muscle_mass_kg, bone_mass_kg, hydration_kg,
                 heart_rate_bpm, scale_battery, comments, import_source, source_label, imported_at,
                 withings_goal_kg, reading_hash, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.captured_at,
                    snapshot.source_timestamp,
                    snapshot.source_entity,
                    snapshot.weight_kg,
                    snapshot.body_fat_percent,
                    snapshot.fat_mass_kg,
                    snapshot.fat_free_mass_kg,
                    snapshot.muscle_mass_kg,
                    snapshot.bone_mass_kg,
                    snapshot.hydration_kg,
                    snapshot.heart_rate_bpm,
                    snapshot.scale_battery,
                    snapshot.comments,
                    snapshot.import_source,
                    snapshot.source_label,
                    snapshot.imported_at,
                    snapshot.withings_goal_kg,
                    snapshot.reading_hash,
                    snapshot.metadata_json,
                ),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def latest_measurement(self):
        conn = self.connect()
        try:
            row = conn.execute(
                """
                SELECT captured_at, source_timestamp, source_entity, weight_kg, body_fat_percent,
                       fat_mass_kg, fat_free_mass_kg, muscle_mass_kg, bone_mass_kg, hydration_kg,
                       heart_rate_bpm, scale_battery, comments, import_source, source_label,
                       imported_at, withings_goal_kg, reading_hash, metadata_json
                FROM weight_measurements
                ORDER BY source_timestamp DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()
        return WeightMeasurement.from_row(row) if row else None

    def earliest_measurement(self):
        conn = self.connect()
        try:
            row = conn.execute(
                """
                SELECT captured_at, source_timestamp, source_entity, weight_kg, body_fat_percent,
                       fat_mass_kg, fat_free_mass_kg, muscle_mass_kg, bone_mass_kg, hydration_kg,
                       heart_rate_bpm, scale_battery, comments, import_source, source_label,
                       imported_at, withings_goal_kg, reading_hash, metadata_json
                FROM weight_measurements
                ORDER BY source_timestamp ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
        finally:
            conn.close()
        return WeightMeasurement.from_row(row) if row else None

    def query_measurements(self, start_time=None, end_time=None, limit=None):
        query = [
            """
            SELECT captured_at, source_timestamp, source_entity, weight_kg, body_fat_percent,
                   fat_mass_kg, fat_free_mass_kg, muscle_mass_kg, bone_mass_kg, hydration_kg,
                   heart_rate_bpm, scale_battery, comments, import_source, source_label,
                   imported_at, withings_goal_kg, reading_hash, metadata_json
            FROM weight_measurements
            WHERE 1=1
            """
        ]
        params = []
        if start_time:
            query.append("AND source_timestamp >= ?")
            params.append(str(start_time))
        if end_time:
            query.append("AND source_timestamp <= ?")
            params.append(str(end_time))
        query.append("ORDER BY source_timestamp ASC, id ASC")
        if limit:
            query.append("LIMIT ?")
            params.append(int(limit))
        conn = self.connect()
        try:
            rows = conn.execute(" ".join(query), params).fetchall()
        finally:
            conn.close()
        return [WeightMeasurement.from_row(row) for row in rows]

    def count_measurements(self):
        conn = self.connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS count FROM weight_measurements").fetchone()
        finally:
            conn.close()
        return row["count"] if row else 0
