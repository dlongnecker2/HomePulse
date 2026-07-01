import sqlite3
from pathlib import Path

from modules.history.models import MetricSnapshot


class HistoryDatabase:
    def __init__(self, path):
        self.path = Path(path)

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    module TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    source TEXT,
                    metadata_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metric_snapshots_lookup
                ON metric_snapshots (module, metric, timestamp)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_metric_snapshots_timestamp
                ON metric_snapshots (timestamp)
                """
            )

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_metric(self, snapshot):
        self.insert_many([snapshot])

    def insert_many(self, snapshots):
        rows = [
            (
                item.timestamp,
                item.module,
                item.metric,
                item.value,
                item.unit,
                item.source,
                item.metadata_json,
            )
            for item in snapshots
        ]
        if not rows:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO metric_snapshots
                (timestamp, module, metric, value, unit, source, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def query_metrics(self, module, metric, start_time=None, end_time=None, limit=None):
        query = [
            """
            SELECT timestamp, module, metric, value, unit, source, metadata_json
            FROM metric_snapshots
            WHERE module = ? AND metric = ?
            """
        ]
        params = [module, metric]
        if start_time:
            query.append("AND timestamp >= ?")
            params.append(str(start_time))
        if end_time:
            query.append("AND timestamp <= ?")
            params.append(str(end_time))
        query.append("ORDER BY timestamp ASC")
        if limit:
            query.append("LIMIT ?")
            params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [MetricSnapshot.from_row(row) for row in rows]

    def latest_metric(self, module, metric):
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT timestamp, module, metric, value, unit, source, metadata_json
                FROM metric_snapshots
                WHERE module = ? AND metric = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (module, metric),
            ).fetchone()
        return MetricSnapshot.from_row(row) if row else None

    def latest_all(self):
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.timestamp, m.module, m.metric, m.value, m.unit, m.source, m.metadata_json
                FROM metric_snapshots m
                INNER JOIN (
                    SELECT module, metric, MAX(timestamp) AS timestamp
                    FROM metric_snapshots
                    GROUP BY module, metric
                ) latest
                ON latest.module = m.module
                AND latest.metric = m.metric
                AND latest.timestamp = m.timestamp
                ORDER BY m.module, m.metric
                """
            ).fetchall()
        return [MetricSnapshot.from_row(row) for row in rows]

    def summary(self, module, start_time=None, end_time=None):
        query = [
            """
            SELECT metric, COUNT(*) AS count, MIN(value) AS minimum, MAX(value) AS maximum,
                   AVG(value) AS average
            FROM metric_snapshots
            WHERE module = ?
            """
        ]
        params = [module]
        if start_time:
            query.append("AND timestamp >= ?")
            params.append(str(start_time))
        if end_time:
            query.append("AND timestamp <= ?")
            params.append(str(end_time))
        query.append("GROUP BY metric ORDER BY metric")
        with self.connect() as conn:
            rows = conn.execute(" ".join(query), params).fetchall()
        return [dict(row) for row in rows]

    def count_metrics(self):
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM metric_snapshots").fetchone()
        return row["count"] if row else 0

    def latest_timestamp(self):
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(timestamp) AS timestamp FROM metric_snapshots").fetchone()
        return row["timestamp"] if row else None

    def prune_old_data(self, cutoff):
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM metric_snapshots WHERE timestamp < ?",
                (str(cutoff),),
            )
        return cursor.rowcount
