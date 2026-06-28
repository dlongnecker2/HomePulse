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

    def add_event(self, timestamp, event_type, message):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO events (timestamp, event_type, message) VALUES (?, ?, ?)",
            (timestamp, event_type, message)
        )
        self.conn.commit()
