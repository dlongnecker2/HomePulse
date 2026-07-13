import json
import sqlite3
from datetime import datetime

from modules.environment.models import EnvironmentalEntity, EnvironmentalReading


class EnvironmentStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS environment_entities (
                entity_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                area_id TEXT NOT NULL,
                area_name TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT NOT NULL,
                device_class TEXT,
                state_class TEXT,
                unit_of_measurement TEXT,
                integration TEXT,
                supported INTEGER NOT NULL DEFAULT 1,
                confidence REAL NOT NULL DEFAULT 1.0,
                label_source TEXT NOT NULL DEFAULT 'registry',
                support_reason TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                metadata_json TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_environment_entities_area_device
            ON environment_entities (area_id, device_id, entity_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_environment_entities_domain
            ON environment_entities (domain, supported)
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS environment_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                raw_state TEXT,
                raw_value TEXT,
                unit_of_measurement TEXT,
                parsed_number REAL,
                parsed_boolean INTEGER,
                availability TEXT NOT NULL,
                area_id TEXT NOT NULL,
                area_name TEXT NOT NULL,
                device_id TEXT NOT NULL,
                device_name TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                label_source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                metadata_json TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_environment_readings_entity_timestamp
            ON environment_readings (entity_id, timestamp, id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_environment_readings_area_timestamp
            ON environment_readings (area_id, timestamp, id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_environment_readings_device_timestamp
            ON environment_readings (device_id, timestamp, id)
            """
        )
        self.conn.commit()

    @staticmethod
    def _serialize_metadata(metadata):
        if not metadata:
            return None
        return json.dumps(metadata, sort_keys=True)

    @staticmethod
    def _normalize_timestamp(value=None):
        if value is None:
            return datetime.now().isoformat(timespec="seconds")
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        text = str(value).strip()
        if not text:
            return datetime.now().isoformat(timespec="seconds")
        try:
            return datetime.fromisoformat(text.replace(" ", "T")).isoformat(timespec="seconds")
        except ValueError:
            return text

    def upsert_entity(self, entity: EnvironmentalEntity):
        self.upsert_entities([entity])

    def upsert_entities(self, entities):
        rows = []
        for entity in entities or []:
            if not isinstance(entity, EnvironmentalEntity):
                continue
            rows.append(
                (
                    entity.entity_id,
                    entity.domain,
                    entity.entity_name,
                    entity.display_name,
                    entity.area_id,
                    entity.area_name,
                    entity.device_id,
                    entity.device_name,
                    entity.device_class,
                    entity.state_class,
                    entity.unit_of_measurement,
                    entity.integration,
                    1 if entity.supported else 0,
                    float(entity.confidence),
                    entity.label_source,
                    entity.support_reason,
                    entity.first_seen,
                    entity.last_seen,
                    self._serialize_metadata(entity.metadata),
                )
            )
        if not rows:
            return 0

        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO environment_entities (
                    entity_id, domain, entity_name, display_name, area_id, area_name,
                    device_id, device_name, device_class, state_class, unit_of_measurement,
                    integration, supported, confidence, label_source, support_reason,
                    first_seen, last_seen, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    domain = excluded.domain,
                    entity_name = excluded.entity_name,
                    display_name = excluded.display_name,
                    area_id = excluded.area_id,
                    area_name = excluded.area_name,
                    device_id = excluded.device_id,
                    device_name = excluded.device_name,
                    device_class = excluded.device_class,
                    state_class = excluded.state_class,
                    unit_of_measurement = excluded.unit_of_measurement,
                    integration = excluded.integration,
                    supported = excluded.supported,
                    confidence = excluded.confidence,
                    label_source = excluded.label_source,
                    support_reason = excluded.support_reason,
                    last_seen = excluded.last_seen,
                    metadata_json = excluded.metadata_json
                """,
                rows,
            )
        return len(rows)

    def record_reading(self, reading: EnvironmentalReading, dedupe=True):
        if not isinstance(reading, EnvironmentalReading):
            return 0

        timestamp = self._normalize_timestamp(reading.timestamp)
        previous = self.latest_reading(reading.entity_id)
        if dedupe and previous and self._is_duplicate(previous, reading):
            return 0

        with self.conn:
            self.conn.execute(
                """
                INSERT INTO environment_readings (
                    timestamp, entity_id, domain, raw_state, raw_value, unit_of_measurement,
                    parsed_number, parsed_boolean, availability, area_id, area_name,
                    device_id, device_name, entity_name, label_source, confidence, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    reading.entity_id,
                    reading.domain,
                    reading.raw_state,
                    reading.raw_value,
                    reading.unit_of_measurement,
                    reading.parsed_number,
                    None if reading.parsed_boolean is None else int(bool(reading.parsed_boolean)),
                    reading.availability,
                    reading.area_id,
                    reading.area_name,
                    reading.device_id,
                    reading.device_name,
                    reading.entity_name,
                    reading.label_source,
                    float(reading.confidence),
                    self._serialize_metadata(reading.metadata),
                ),
            )
        return 1

    def latest_entity(self, entity_id):
        row = self.conn.execute(
            """
            SELECT entity_id, domain, entity_name, display_name, area_id, area_name, device_id, device_name,
                   device_class, state_class, unit_of_measurement, integration, supported, confidence,
                   label_source, support_reason, first_seen, last_seen, metadata_json
            FROM environment_entities
            WHERE entity_id = ?
            """,
            (entity_id,),
        ).fetchone()
        return self._entity_row_to_dict(row) if row else None

    def all_entities(self, supported_only=True):
        query = """
            SELECT entity_id, domain, entity_name, display_name, area_id, area_name, device_id, device_name,
                   device_class, state_class, unit_of_measurement, integration, supported, confidence,
                   label_source, support_reason, first_seen, last_seen, metadata_json
            FROM environment_entities
        """
        params = []
        if supported_only:
            query += " WHERE supported = 1"
        query += " ORDER BY area_name, device_name, display_name, entity_id"
        rows = self.conn.execute(query, params).fetchall()
        return [self._entity_row_to_dict(row) for row in rows]

    def latest_reading(self, entity_id):
        row = self.conn.execute(
            """
            SELECT timestamp, entity_id, domain, raw_state, raw_value, unit_of_measurement,
                   parsed_number, parsed_boolean, availability, area_id, area_name, device_id,
                   device_name, entity_name, label_source, confidence, metadata_json
            FROM environment_readings
            WHERE entity_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (entity_id,),
        ).fetchone()
        return self._reading_row_to_dict(row) if row else None

    def latest_readings(self):
        rows = self.conn.execute(
            """
            SELECT timestamp, entity_id, domain, raw_state, raw_value, unit_of_measurement,
                   parsed_number, parsed_boolean, availability, area_id, area_name, device_id,
                   device_name, entity_name, label_source, confidence, metadata_json
            FROM environment_readings
            ORDER BY entity_id, timestamp DESC, id DESC
            """
        ).fetchall()
        latest = {}
        for row in rows:
            entity_id = row["entity_id"]
            if entity_id in latest:
                continue
            latest[entity_id] = self._reading_row_to_dict(row)
        return sorted(
            latest.values(),
            key=lambda item: (
                item.get("area_name", ""),
                item.get("device_name", ""),
                item.get("entity_name", ""),
                item.get("entity_id", ""),
            ),
        )

    def count_readings(self):
        row = self.conn.execute("SELECT COUNT(*) AS count FROM environment_readings").fetchone()
        return row["count"] if row else 0

    def history(self, entity_id, limit=None):
        query = [
            """
            SELECT timestamp, entity_id, domain, raw_state, raw_value, unit_of_measurement,
                   parsed_number, parsed_boolean, availability, area_id, area_name, device_id,
                   device_name, entity_name, label_source, confidence, metadata_json
            FROM environment_readings
            WHERE entity_id = ?
            ORDER BY timestamp ASC, id ASC
            """
        ]
        params = [entity_id]
        if limit:
            query.append("LIMIT ?")
            params.append(int(limit))
        rows = self.conn.execute(" ".join(query), params).fetchall()
        return [self._reading_row_to_dict(row) for row in rows]

    @staticmethod
    def _is_duplicate(previous, reading: EnvironmentalReading):
        return (
            previous.get("raw_state") == reading.raw_state
            and previous.get("raw_value") == reading.raw_value
            and previous.get("unit_of_measurement") == reading.unit_of_measurement
            and previous.get("parsed_number") == reading.parsed_number
            and previous.get("parsed_boolean") == reading.parsed_boolean
            and previous.get("availability") == reading.availability
        )

    @staticmethod
    def _entity_row_to_dict(row):
        if not row:
            return None
        metadata = {}
        metadata_json = row["metadata_json"]
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        return {
            "entity_id": row["entity_id"],
            "domain": row["domain"],
            "entity_name": row["entity_name"],
            "display_name": row["display_name"],
            "area_id": row["area_id"],
            "area_name": row["area_name"],
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "device_class": row["device_class"],
            "state_class": row["state_class"],
            "unit_of_measurement": row["unit_of_measurement"],
            "integration": row["integration"],
            "supported": bool(row["supported"]),
            "confidence": row["confidence"],
            "label_source": row["label_source"],
            "support_reason": row["support_reason"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "metadata": metadata,
        }

    @staticmethod
    def _reading_row_to_dict(row):
        if not row:
            return None
        metadata = {}
        metadata_json = row["metadata_json"]
        if metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                metadata = {}
        return {
            "timestamp": row["timestamp"],
            "entity_id": row["entity_id"],
            "domain": row["domain"],
            "raw_state": row["raw_state"],
            "raw_value": row["raw_value"],
            "unit_of_measurement": row["unit_of_measurement"],
            "parsed_number": row["parsed_number"],
            "parsed_boolean": None if row["parsed_boolean"] is None else bool(row["parsed_boolean"]),
            "availability": row["availability"],
            "area_id": row["area_id"],
            "area_name": row["area_name"],
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "entity_name": row["entity_name"],
            "label_source": row["label_source"],
            "confidence": row["confidence"],
            "metadata": metadata,
        }
