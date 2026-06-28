import sqlite3
from pathlib import Path


class Database:
    def __init__(self, filename):
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.conn = sqlite3.connect(filename, check_same_thread=False)

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
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO health_checks
            (timestamp, latency, packet_loss, dns_ok, score, rebooted)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (timestamp, latency, packet_loss, int(dns_ok), score, rebooted)
        )
        self.conn.commit()

    def add_speed_test(self, timestamp, download, upload, ping, server):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO speed_tests
            (timestamp, download, upload, ping, server)
            VALUES (?, ?, ?, ?, ?)
            """,
            (timestamp, download, upload, ping, server)
        )
        self.conn.commit()

    def add_event(self, timestamp, event_type, message):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO events (timestamp, event_type, message) VALUES (?, ?, ?)",
            (timestamp, event_type, message)
        )
        self.conn.commit()

    def latest_health_check(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, latency, packet_loss, dns_ok, score, rebooted
            FROM health_checks
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "timestamp": row[0],
            "latency": row[1],
            "packet_loss": row[2],
            "dns_ok": bool(row[3]),
            "score": row[4],
            "rebooted": bool(row[5])
        }

    def latest_speed_test(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, download, upload, ping, server
            FROM speed_tests
            ORDER BY id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()

        if not row:
            return None

        return {
            "timestamp": row[0],
            "download": row[1],
            "upload": row[2],
            "ping": row[3],
            "server": row[4]
        }

    def health_history(self, limit=96):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT timestamp, latency, packet_loss, dns_ok, score, rebooted
            FROM health_checks
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        )

        rows = cursor.fetchall()
        rows.reverse()

        return [
            {
                "timestamp": row[0],
                "latency": row[1],
                "packet_loss": row[2],
                "dns_ok": bool(row[3]),
                "score": row[4],
                "rebooted": bool(row[5])
            }
            for row in rows
        ]
