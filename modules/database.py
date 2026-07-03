import sqlite3
from pathlib import Path
from datetime import datetime


class Database:
    def __init__(self, filename):
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.conn = sqlite3.connect(filename, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    @staticmethod
    def _normalize_timestamp(ts):
        """Convert datetime or string to ISO format string for SQLite."""
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts.isoformat()
        if isinstance(ts, str):
            # Already a string; ensure it's ISO format if it's from str(datetime)
            # str(datetime) produces "2026-06-02 12:34:56.123456"
            # We want "2026-06-02T12:34:56" for comparison
            if " " in ts and "T" not in ts:
                # Convert "YYYY-MM-DD HH:MM:SS.ffffff" to "YYYY-MM-DDTHH:MM:SS"
                try:
                    dt = datetime.fromisoformat(ts.replace(" ", "T"))
                    return dt.replace(microsecond=0).isoformat()
                except (ValueError, TypeError):
                    pass
            return ts
        return str(ts)

    def initialize(self):
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                latency REAL,
                packet_loss REAL,
                dns_ok INTEGER,
                score INTEGER DEFAULT 0,
                rebooted INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS speed_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                download REAL,
                upload REAL,
                ping REAL,
                server TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT
            )
        """)
        self.conn.commit()

    def add_health_check(self, timestamp, latency, packet_loss, dns_ok, score, rebooted=0):
        self.conn.execute(
            """
            INSERT INTO health_checks
            (timestamp, latency, packet_loss, dns_ok, score, rebooted)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, latency, packet_loss, int(dns_ok), score, rebooted),
        )
        self.conn.commit()

    def add_speed_test(self, timestamp, download, upload, ping, server):
        self.conn.execute(
            """
            INSERT INTO speed_tests (timestamp, download, upload, ping, server)
            VALUES (?, ?, ?, ?, ?)
            """,
            (timestamp, download, upload, ping, server),
        )
        self.conn.commit()

    def add_event(self, timestamp, event_type, message):
        self.conn.execute(
            "INSERT INTO events (timestamp, event_type, message) VALUES (?, ?, ?)",
            (timestamp, event_type, message),
        )
        self.conn.commit()

    def latest_health_check(self):
        row = self.conn.execute(
            """
            SELECT timestamp, latency, packet_loss, dns_ok, score, rebooted
            FROM health_checks ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        return self._health_row_to_dict(row) if row else None

    def latest_speed_test(self):
        row = self.conn.execute(
            """
            SELECT timestamp, download, upload, ping, server
            FROM speed_tests ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return {
            "timestamp": row["timestamp"],
            "download": row["download"],
            "upload": row["upload"],
            "ping": row["ping"],
            "server": row["server"],
        }

    def latest_event(self, event_type=None):
        if event_type:
            row = self.conn.execute(
                "SELECT timestamp, event_type, message FROM events WHERE event_type = ? ORDER BY id DESC LIMIT 1",
                (event_type,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT timestamp, event_type, message FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"timestamp": row["timestamp"], "event_type": row["event_type"], "message": row["message"]}

    def recent_events(self, limit=10):
        rows = self.conn.execute(
            """
            SELECT timestamp, event_type, message
            FROM events
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {"timestamp": row["timestamp"], "event_type": row["event_type"], "message": row["message"]}
            for row in rows
        ]

    def count_rows(self, table_name):
        allowed_tables = {"health_checks", "speed_tests", "events"}
        if table_name not in allowed_tables:
            raise ValueError("Unsupported table")
        row = self.conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return row["count"] if row else 0

    def count_events(self, event_type=None):
        if event_type:
            row = self.conn.execute(
                "SELECT COUNT(*) AS count FROM events WHERE event_type = ?",
                (event_type,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return row["count"] if row else 0

    def health_history(self, limit=96):
        rows = self.conn.execute(
            """
            SELECT timestamp, latency, packet_loss, dns_ok, score, rebooted
            FROM health_checks ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        rows.reverse()
        return [self._health_row_to_dict(row) for row in rows]

    def health_history_since(self, timestamp):
        ts = self._normalize_timestamp(timestamp)
        try:
            rows = self.conn.execute(
                """
                SELECT timestamp, latency, packet_loss, dns_ok, score, rebooted
                FROM health_checks
                WHERE timestamp >= ?
                ORDER BY id ASC
                """,
                (ts,),
            ).fetchall()
            return [self._health_row_to_dict(row) for row in rows if row]
        except (sqlite3.InterfaceError, sqlite3.OperationalError, IndexError):
            return []

    def speed_tests_since(self, timestamp):
        ts = self._normalize_timestamp(timestamp)
        try:
            rows = self.conn.execute(
                """
                SELECT timestamp, download, upload, ping, server
                FROM speed_tests
                WHERE timestamp >= ?
                ORDER BY id ASC
                """,
                (ts,),
            ).fetchall()
            result = []
            for row in rows:
                if not row:
                    continue
                try:
                    result.append({
                        "timestamp": row["timestamp"] if isinstance(row, dict) else row[0],
                        "download": row["download"] if isinstance(row, dict) else row[1],
                        "upload": row["upload"] if isinstance(row, dict) else row[2],
                        "ping": row["ping"] if isinstance(row, dict) else row[3],
                        "server": row["server"] if isinstance(row, dict) else row[4],
                    })
                except (IndexError, TypeError, KeyError):
                    continue
            return result
        except (sqlite3.InterfaceError, sqlite3.OperationalError, IndexError):
            return []

    def events_since(self, timestamp, event_type=None):
        ts = self._normalize_timestamp(timestamp)
        try:
            if event_type:
                rows = self.conn.execute(
                    """
                    SELECT timestamp, event_type, message
                    FROM events
                    WHERE timestamp >= ? AND event_type = ?
                    ORDER BY id ASC
                    """,
                    (ts, event_type),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """
                    SELECT timestamp, event_type, message
                    FROM events
                    WHERE timestamp >= ?
                    ORDER BY id ASC
                    """,
                    (ts,),
                ).fetchall()
            return [
                {"timestamp": row["timestamp"], "event_type": row["event_type"], "message": row["message"]}
                for row in rows if row
            ]
        except (sqlite3.InterfaceError, sqlite3.OperationalError, IndexError):
            return []

    @staticmethod
    def _health_row_to_dict(row):
        try:
            # Handle both sqlite3.Row objects and tuples
            if isinstance(row, dict) or hasattr(row, '__getitem__'):
                try:
                    return {
                        "timestamp": row["timestamp"],
                        "latency": row["latency"],
                        "packet_loss": row["packet_loss"],
                        "dns_ok": bool(row["dns_ok"]),
                        "score": row["score"],
                        "rebooted": bool(row["rebooted"]),
                    }
                except (KeyError, TypeError):
                    # Row is a tuple, not dict-like
                    return {
                        "timestamp": row[0] if len(row) > 0 else None,
                        "latency": row[1] if len(row) > 1 else None,
                        "packet_loss": row[2] if len(row) > 2 else None,
                        "dns_ok": bool(row[3]) if len(row) > 3 else False,
                        "score": row[4] if len(row) > 4 else None,
                        "rebooted": bool(row[5]) if len(row) > 5 else False,
                    }
            return {}
        except Exception:
            return {}
