import sqlite3
import unittest

from modules.environment.database import EnvironmentStore
from modules.environment.models import EnvironmentalEntity, EnvironmentalReading


class EnvironmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.store = EnvironmentStore(self.conn)
        self.store.initialize()

    def tearDown(self):
        self.conn.close()

    def test_history_starts_empty_for_new_entity(self):
        self.assertEqual(self.store.history("sensor.new_sensor"), [])

    def test_record_reading_deduplicates_identical_samples(self):
        entity = EnvironmentalEntity(
            entity_id="sensor.living_room_temp",
            domain="sensor",
            entity_name="Living Room Temperature",
            display_name="Living Room Temperature",
            area_id="area.living_room",
            area_name="Living Room",
            device_id="device.thermostat",
            device_name="Thermostat",
            device_class="temperature",
            unit_of_measurement="C",
        )
        reading = EnvironmentalReading(
            entity_id="sensor.living_room_temp",
            domain="sensor",
            raw_state="21.5",
            raw_value="21.5",
            unit_of_measurement="C",
            parsed_number=21.5,
            parsed_boolean=None,
            availability="available",
            area_id="area.living_room",
            area_name="Living Room",
            device_id="device.thermostat",
            device_name="Thermostat",
            entity_name="Living Room Temperature",
        )

        self.store.upsert_entity(entity)
        self.assertEqual(self.store.record_reading(reading), 1)
        self.assertEqual(self.store.record_reading(reading), 0)
        self.assertEqual(self.store.count_readings(), 1)
        self.assertEqual(len(self.store.history("sensor.living_room_temp")), 1)


if __name__ == "__main__":
    unittest.main()
