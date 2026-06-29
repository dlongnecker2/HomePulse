import sqlite3
from pathlib import Path


class Database:
    def __init__(self, filename):
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.conn = sqlite3.connect(filename, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

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

    @staticmethod
    def _health_row_to_dict(row):
        return {
            "timestamp": row["timestamp"],
            "latency": row["latency"],
            "packet_loss": row["packet_loss"],
            "dns_ok": bool(row["dns_ok"]),
            "score": row["score"],
            "rebooted": bool(row["rebooted"]),
        }
