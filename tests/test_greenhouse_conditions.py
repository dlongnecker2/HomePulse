import sqlite3
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, render_template

from modules.dashboard import Dashboard
from modules.environment.database import EnvironmentStore
from modules.environment.models import EnvironmentalReading
from modules.environment.manager import EnvironmentManager


class DummyConfig:
    def __init__(self, data):
        self.data = data

    def get(self, *keys, default=None):
        value = self.data
        try:
            for key in keys:
                value = value[key]
            return value
        except Exception:
            return default


class DummyLog:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class DummyStatus:
    def __init__(self, payload):
        self.payload = payload

    def get(self):
        return dict(self.payload)


def mixed_greenhouse_payload(temperature, humidity, temperature_timestamp, humidity_timestamp, temperature_unit="Â°F"):
    states, entity_registry, device_registry, area_registry, _ = greenhouse_payload(
        temperature,
        humidity,
        temperature_timestamp,
        temperature_unit=temperature_unit,
    )
    states[1]["last_updated"] = humidity_timestamp
    states[1]["last_changed"] = humidity_timestamp
    return states, entity_registry, device_registry, area_registry, None


def build_dashboard_app(environment):
    payload = {
        "version": "2.6.2",
        "internet": {
            "status": "Healthy",
            "details": "OK",
            "last_check": "2026-07-20T02:39:05+00:00",
        },
        "router": {"status": "Monitoring", "last_reboot": None},
        "speedtest": {"download": None, "upload": None, "ping": None, "server": None, "last_run": None},
        "system": {"started_at": "2026-07-20T02:00:00+00:00", "last_update": "2026-07-20T02:39:05+00:00"},
    }
    widget_registry = SimpleNamespace(all=lambda: [])
    device_registry = SimpleNamespace(all=lambda: [])
    plugin_manager = SimpleNamespace(widget_registry=widget_registry, device_registry=device_registry)
    config = DummyConfig(
        {
            "environment": {
                "enabled": True,
                "refresh_interval_minutes": 5,
                "stale_after_minutes": 10,
            },
            "email": {},
            "router_reboot": {},
        }
    )
    return SimpleNamespace(
        config=config,
        status=DummyStatus(payload),
        db=SimpleNamespace(latest_event=lambda _name: None, recent_events=lambda limit=5: []),
        next_scheduled_speedtest=lambda: None,
        speedtest_schedule_label=lambda: "Every 30 minutes",
        internet_intelligence=lambda: {},
        plugin_manager=plugin_manager,
        environment=environment,
        health_score=SimpleNamespace(compute=lambda statuses: {"score": 99, "status_text": "Healthy", "trend": "Stable", "breakdown": {}}),
        alert_manager=SimpleNamespace(detect_alerts=lambda statuses: [], severity_priority=lambda severity: 0),
        timeline=SimpleNamespace(get_summary=lambda hours_back=24: {}, get_events=lambda limit=20, hours_back=24: []),
        solar=SimpleNamespace(get_status=lambda: {}),
        energy=SimpleNamespace(get_status=lambda: {}),
        vehicle=SimpleNamespace(get_status=lambda: {}, get_unified_status=lambda energy: {}),
        weather=SimpleNamespace(get_status=lambda: {}),
        lighting=SimpleNamespace(get_status=lambda: {}),
        garden=SimpleNamespace(get_status=lambda: {}),
        started_at=datetime.now(timezone.utc).replace(microsecond=0),
        observe_solar_status=lambda status: None,
        observe_vehicle_status=lambda status: None,
        observe_lighting_status=lambda status: None,
        observe_garden_status=lambda status: None,
        solar_alert_settings=lambda: {},
        update_solar_alert_settings=lambda payload: {},
        process_identity=lambda: {},
        health_check=lambda: None,
        daily_speed_test=lambda: None,
        maintenance_check=lambda: None,
        reload_configuration=lambda: None,
        request_shutdown=lambda delay_seconds=2: "scheduled",
        history_summary=lambda: {},
        report_summary=lambda: {},
        update_settings=lambda form: None,
        normalized_router_recovery=lambda: {},
        speedtest_schedule_mode=lambda: "daily",
        configured_speedtest_times=lambda: [],
        router_recovery_summary=lambda config=None: {},
        notification_manager=SimpleNamespace(get_notifications=lambda **kwargs: [], get_unread_count=lambda: 0, mark_read=lambda notification_id: True, clear=lambda: 0),
        log=DummyLog(),
    )


def greenhouse_payload(temperature, humidity, timestamp, temperature_unit="°F"):
    states = [
        {
            "entity_id": "sensor.greenhouse_temperature",
            "state": temperature,
            "attributes": {
                "device_class": "temperature",
                "state_class": "measurement",
                "unit_of_measurement": temperature_unit,
                "friendly_name": "Greenhouse Temperature",
            },
            "last_updated": timestamp,
            "last_changed": timestamp,
        },
        {
            "entity_id": "sensor.greenhouse_humidity",
            "state": humidity,
            "attributes": {
                "device_class": "humidity",
                "state_class": "measurement",
                "unit_of_measurement": "%",
                "friendly_name": "Greenhouse Humidity",
            },
            "last_updated": timestamp,
            "last_changed": timestamp,
        },
    ]
    entity_registry = [
        {
            "entity_id": "sensor.greenhouse_temperature",
            "name": "Greenhouse Temperature",
            "original_name": "Greenhouse Temperature",
            "device_id": "device.greenhouse",
            "area_id": "area.greenhouse",
            "platform": "homeassistant",
            "device_class": "temperature",
            "unit_of_measurement": temperature_unit,
        },
        {
            "entity_id": "sensor.greenhouse_humidity",
            "name": "Greenhouse Humidity",
            "original_name": "Greenhouse Humidity",
            "device_id": "device.greenhouse",
            "area_id": "area.greenhouse",
            "platform": "homeassistant",
            "device_class": "humidity",
            "unit_of_measurement": "%",
        },
    ]
    device_registry = [
        {
            "id": "device.greenhouse",
            "name": "Greenhouse",
            "area_id": "area.greenhouse",
        }
    ]
    area_registry = [
        {
            "area_id": "area.greenhouse",
            "name": "Greenhouse",
        }
    ]
    return states, entity_registry, device_registry, area_registry, None


def greenhouse_unknown_payload(timestamp):
    states = [
        {
            "entity_id": "sensor.greenhouse_temperature",
            "state": "unknown",
            "attributes": {
                "device_class": "temperature",
                "state_class": "measurement",
                "unit_of_measurement": "°F",
                "friendly_name": "Greenhouse Temperature",
            },
            "last_updated": timestamp,
            "last_changed": timestamp,
        },
        {
            "entity_id": "sensor.greenhouse_humidity",
            "state": "unavailable",
            "attributes": {
                "device_class": "humidity",
                "state_class": "measurement",
                "unit_of_measurement": "%",
                "friendly_name": "Greenhouse Humidity",
            },
            "last_updated": timestamp,
            "last_changed": timestamp,
        },
    ]
    _, entity_registry, device_registry, area_registry, _ = greenhouse_payload("0", "0", timestamp)
    return states, entity_registry, device_registry, area_registry, None


def seed_greenhouse_readings(store, timestamp, temperature="75.0", humidity="44.0", temperature_unit="Â°F"):
    store.record_reading(
        EnvironmentalReading(
            entity_id="sensor.greenhouse_temperature",
            domain="sensor",
            raw_state=temperature,
            raw_value=temperature,
            unit_of_measurement=temperature_unit,
            parsed_number=float(temperature),
            availability="available",
            area_id="area.greenhouse",
            area_name="Greenhouse",
            device_id="device.greenhouse",
            device_name="Greenhouse",
            entity_name="Greenhouse Temperature",
            timestamp=timestamp,
        ),
        dedupe=False,
    )
    store.record_reading(
        EnvironmentalReading(
            entity_id="sensor.greenhouse_humidity",
            domain="sensor",
            raw_state=humidity,
            raw_value=humidity,
            unit_of_measurement="%",
            parsed_number=float(humidity),
            availability="available",
            area_id="area.greenhouse",
            area_name="Greenhouse",
            device_id="device.greenhouse",
            device_name="Greenhouse",
            entity_name="Greenhouse Humidity",
            timestamp=timestamp,
        ),
        dedupe=False,
    )


class GreenhouseEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.store = EnvironmentStore(self.conn)
        self.store.initialize()
        self.config = DummyConfig(
            {
                "environment": {
                    "enabled": True,
                    "refresh_interval_minutes": 5,
                    "stale_after_minutes": 10,
                },
                "router_reboot": {
                    "home_assistant_url": "http://homeassistant.local",
                    "home_assistant_token": "token",
                },
            }
        )
        self.log = DummyLog()

    def tearDown(self):
        self.conn.close()

    def test_greenhouse_snapshot_uses_configured_entities_and_preserves_history(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payloads = [
            greenhouse_payload("75.02", "48.0", (now - timedelta(minutes=6)).isoformat()),
            greenhouse_payload("80.42", "44.0", (now - timedelta(minutes=3)).isoformat()),
            greenhouse_payload("80.42", "44.0", (now - timedelta(minutes=3)).isoformat()),
        ]

        with patch.object(manager, "_fetch_home_assistant_payloads", side_effect=payloads):
            first = manager.refresh_snapshot()
            second = manager.refresh_snapshot()
            third = manager.refresh_snapshot()

        self.assertEqual(first["greenhouse"]["temperature_entity_id"], "sensor.greenhouse_temperature")
        self.assertEqual(first["greenhouse"]["humidity_entity_id"], "sensor.greenhouse_humidity")
        self.assertEqual(second["greenhouse"]["temperature_display"], "80.4°F")
        self.assertEqual(second["greenhouse"]["humidity_display"], "44%")
        self.assertEqual(second["greenhouse"]["temperature_band"], "Normal")
        self.assertEqual(second["greenhouse"]["today_high"], "80.4°F")
        self.assertEqual(second["greenhouse"]["today_low"], "75.0°F")
        self.assertEqual(second["greenhouse"]["source_status"], "live")
        self.assertEqual(self.store.count_readings(), 4)
        self.assertEqual(len(third["greenhouse"]["history_points"]), 2)
        self.assertLessEqual(third["greenhouse"]["history_points"][0]["timestamp"], third["greenhouse"]["history_points"][1]["timestamp"])

    def test_celsius_temperature_converts_for_display(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        value, unit = manager._greenhouse_display_temperature(
            {
                "parsed_number": 22.0,
                "unit_of_measurement": "C",
            }
        )
        self.assertEqual(value, 71.6)
        self.assertEqual(unit, "°F")

    def test_last_updated_is_preferred_over_last_changed_when_available(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        row = {
            "last_updated": "2026-07-20T02:39:05+00:00",
            "last_changed": "2026-07-20T02:35:05+00:00",
            "timestamp": "2026-07-20T02:30:05+00:00",
        }

        self.assertEqual(manager._pick_timestamp(row), "2026-07-20T02:39:05+00:00")

    def test_unknown_greenhouse_states_fail_safely(self):
        manager = EnvironmentManager(self.config, self.log, self.store)

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=greenhouse_unknown_payload(datetime.now(timezone.utc).replace(microsecond=0).isoformat())):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertEqual(greenhouse["temperature_entity_id"], "sensor.greenhouse_temperature")
        self.assertEqual(greenhouse["humidity_entity_id"], "sensor.greenhouse_humidity")
        self.assertIsNone(greenhouse["temperature"])
        self.assertIsNone(greenhouse["temperature_display"])
        self.assertEqual(greenhouse["status"], "Not Available")
        self.assertEqual(greenhouse["availability"], "unavailable")
        self.assertEqual(greenhouse["source_status"], "unavailable")
        self.assertEqual(greenhouse["message"], "Greenhouse temperature is currently unavailable.")
        self.assertEqual(greenhouse["history_points"], [])

    def test_temporary_unavailable_live_response_uses_recent_stored_temperature(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        seed_greenhouse_readings(self.store, (now - timedelta(minutes=4)).isoformat(), temperature="74.0", humidity="41.0")

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=greenhouse_unknown_payload(now.isoformat())):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertTrue(str(greenhouse["temperature_display"]).startswith("74.0"))
        self.assertEqual(greenhouse["humidity_display"], "41%")
        self.assertEqual(greenhouse["source_status"], "cached")
        self.assertEqual(greenhouse["status"], "Last Known")
        self.assertEqual(greenhouse["availability"], "available")
        self.assertEqual(greenhouse["source"], "cached")
        self.assertIn("Last known reading", greenhouse["message"])

    def test_excessively_old_fallback_becomes_unavailable(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        seed_greenhouse_readings(self.store, (now - timedelta(minutes=20)).isoformat(), temperature="72.0", humidity="40.0")

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=greenhouse_unknown_payload(now.isoformat())):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertIsNone(greenhouse["temperature_display"])
        self.assertEqual(greenhouse["source_status"], "stale")
        self.assertEqual(greenhouse["status"], "Not Available")
        self.assertEqual(greenhouse["availability"], "unavailable")
        self.assertTrue(greenhouse["stale"])
        self.assertIn("not available", greenhouse["message"].lower())

    def test_sensor_measurement_timestamp_controls_staleness_not_refresh_time(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old_timestamp = (now - timedelta(minutes=20)).isoformat()
        payload = greenhouse_payload("74.0", "unavailable", old_timestamp)

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=payload):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertEqual(greenhouse["source_status"], "live")
        self.assertEqual(greenhouse["status"], "Connected")
        self.assertFalse(greenhouse["stale"])
        self.assertTrue(str(greenhouse["temperature_display"]).startswith("74.0"))
        self.assertEqual(greenhouse["source_timestamp"], old_timestamp)
        self.assertEqual(greenhouse["source"], "live")
        self.assertEqual(greenhouse["availability"], "live")
        self.assertEqual(greenhouse["observed_at"], now.isoformat())

    def test_live_numeric_humidity_remains_visible_even_when_source_timestamp_is_old(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old_timestamp = (now - timedelta(minutes=20)).isoformat()
        payload = greenhouse_payload("unavailable", "46.0", old_timestamp)

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=payload):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertEqual(greenhouse["source_status"], "live")
        self.assertEqual(greenhouse["status"], "Connected")
        self.assertFalse(greenhouse["stale"])
        self.assertTrue(str(greenhouse["humidity_display"]).startswith("46"))
        self.assertIsNone(greenhouse["temperature_display"])
        self.assertEqual(greenhouse["source_timestamp"], old_timestamp)
        self.assertEqual(greenhouse["source"], "live")
        self.assertEqual(greenhouse["availability"], "live")

    def test_twenty_successful_polls_with_unchanged_source_timestamp_keep_values_visible(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        old_timestamp = (now - timedelta(minutes=20)).isoformat()
        payload = greenhouse_payload("74.2", "45.0", old_timestamp)

        with patch.object(manager, "_fetch_home_assistant_payloads", side_effect=[payload] * 20):
            for index in range(20):
                snapshot = manager.refresh_snapshot()
                greenhouse = snapshot["greenhouse"]
                self.assertEqual(greenhouse["source_status"], "live", msg=f"source flipped on cycle {index + 1}")
                self.assertFalse(greenhouse["stale"], msg=f"stale flag flipped on cycle {index + 1}")
                self.assertTrue(str(greenhouse["temperature_display"]).startswith("74.2"), msg=f"temperature disappeared on cycle {index + 1}")
                self.assertTrue(str(greenhouse["humidity_display"]).startswith("45"), msg=f"humidity disappeared on cycle {index + 1}")

    def test_missing_humidity_does_not_erase_temperature(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        payload = greenhouse_payload("76.5", "unavailable", now.isoformat())

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=payload):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertTrue(str(greenhouse["temperature_display"]).startswith("76.5"))
        self.assertEqual(greenhouse["humidity_display"], None)

    def test_missing_temperature_does_not_erase_valid_humidity(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        seed_greenhouse_readings(self.store, (now - timedelta(minutes=2)).isoformat(), temperature="73.0", humidity="42.0")
        payload = greenhouse_unknown_payload(now.isoformat())
        payload[0][0]["state"] = "unavailable"
        payload[0][0]["last_updated"] = now.isoformat()

        with patch.object(manager, "_fetch_home_assistant_payloads", return_value=payload):
            snapshot = manager.refresh_snapshot()

        greenhouse = snapshot["greenhouse"]
        self.assertEqual(greenhouse["humidity_display"], "42%")
        self.assertTrue(str(greenhouse["temperature_display"]).startswith("73.0"))

    def test_twenty_alternating_responses_keep_recent_temperature_visible(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        good_payload = greenhouse_payload("74.2", "45.0", now.isoformat())
        bad_payload = greenhouse_unknown_payload(now.isoformat())

        side_effect = [good_payload if i % 2 == 0 else bad_payload for i in range(20)]
        with patch.object(manager, "_fetch_home_assistant_payloads", side_effect=side_effect):
            for index in range(20):
                snapshot = manager.refresh_snapshot()
                greenhouse = snapshot["greenhouse"]
                self.assertTrue(str(greenhouse["temperature_display"]).startswith("74.2"), msg=f"temperature flipped on cycle {index + 1}")

    def test_greenhouse_latest_timestamp_normalizes_mixed_timestamp_candidates(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc

        aware_utc = datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc)
        later_aware = datetime(2026, 7, 20, 11, 30, 0, tzinfo=timezone(timedelta(hours=2)))
        z_timestamp = "2026-07-20T09:15:00Z"
        naive_local = aware_utc.astimezone(local_tz).replace(tzinfo=None).isoformat(timespec="seconds")
        expected = later_aware.astimezone(timezone.utc).isoformat(timespec="seconds")

        self.assertEqual(
            manager._greenhouse_latest_timestamp(
                aware_utc.isoformat(timespec="seconds"),
                naive_local,
                later_aware.isoformat(timespec="seconds"),
            ),
            expected,
        )
        self.assertEqual(
            manager._greenhouse_latest_timestamp(
                z_timestamp,
                aware_utc.isoformat(timespec="seconds"),
            ),
            "2026-07-20T09:15:00+00:00",
        )

    def test_greenhouse_latest_timestamp_ignores_invalid_candidates(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        self.assertIsNone(manager._greenhouse_latest_timestamp(None, "", " ", "not-a-timestamp"))

    def test_greenhouse_latest_timestamp_handles_only_naive_and_only_aware_inputs(self):
        manager = EnvironmentManager(self.config, self.log, self.store)
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc

        naive_a = datetime(2026, 7, 20, 8, 0, 0)
        naive_b = datetime(2026, 7, 20, 9, 30, 0)
        aware_a = datetime(2026, 7, 20, 7, 0, 0, tzinfo=timezone.utc)
        aware_b = datetime(2026, 7, 20, 11, 0, 0, tzinfo=timezone(timedelta(hours=2)))

        self.assertEqual(
            manager._greenhouse_latest_timestamp(
                naive_a.isoformat(timespec="seconds"),
                naive_b.isoformat(timespec="seconds"),
            ),
            naive_b.replace(tzinfo=local_tz).astimezone(timezone.utc).isoformat(timespec="seconds"),
        )
        self.assertEqual(
            manager._greenhouse_latest_timestamp(
                aware_a.isoformat(timespec="seconds"),
                aware_b.isoformat(timespec="seconds"),
            ),
            aware_b.astimezone(timezone.utc).isoformat(timespec="seconds"),
        )

class GreenhouseTemplateTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(ROOT / "templates"))
        for endpoint in (
            "home",
            "home_center",
            "environment_center",
            "internet",
            "solar",
            "vehicle_center",
            "weight_progress",
            "weather",
            "lighting",
            "garden",
            "speed_test_center",
            "email_center",
            "settings",
            "lab",
            "logs",
            "about",
        ):
            self.app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

        self.context = {
            "config": DummyConfig({"monitor_interval_minutes": 5, "dry_run": True}),
            "status": {
                "version": "2.6.2",
                "greenhouse": {
                    "temperature_display": "75.0°F",
                    "humidity_display": "44%",
                    "temperature_band": "Normal",
                    "source_status": "live",
                    "source": "live",
                    "status": "Connected",
                    "last_updated": "2026-07-20T02:39:05+00:00",
                    "observed_at": "2026-07-20T02:39:05+00:00",
                    "source_timestamp": "2026-07-20T02:20:05+00:00",
                    "stale": False,
                },
            },
            "internet": {"status": "Healthy", "details": "OK", "last_check": "2026-07-20T02:39:05+00:00"},
            "speedtest": {"download": None, "upload": None, "ping": None, "server": None, "last_run": None},
            "router": {"status": "Monitoring", "last_reboot": None},
            "system": {"started_at": "2026-07-20T02:00:00+00:00", "last_update": "2026-07-20T02:39:05+00:00"},
            "intelligence": {"quality_score": 99, "isp_grade": "A"},
            "events": [],
            "widgets": [],
            "insights": [],
            "environment": {
                "status": "Connected",
                "message": "Loaded from cached environmental snapshot.",
                "enabled": True,
                "summary": {"supported_entities": 2, "readings_recorded": 4, "areas": 1, "devices": 1},
                "greenhouse": {
                    "temperature_display": "75.0°F",
                    "humidity_display": "44%",
                    "temperature_band": "Normal",
                    "source_status": "live",
                    "source": "live",
                    "status": "Connected",
                    "message": "Live greenhouse readings are available.",
                    "today_high": "80.4°F",
                    "today_low": "75.0°F",
                    "last_updated": "2026-07-20T02:39:05+00:00",
                    "observed_at": "2026-07-20T02:39:05+00:00",
                    "source_timestamp": "2026-07-20T02:20:05+00:00",
                    "history_count": 2,
                    "history_points": [
                        {"timestamp": "2026-07-20T00:00:00+00:00", "value": 75.0, "unit": "°F", "availability": "available"},
                        {"timestamp": "2026-07-20T01:00:00+00:00", "value": 80.4, "unit": "°F", "availability": "available"},
                    ],
                    "stale": False,
                },
                "areas": [],
                "entities": [],
                "last_successful_refresh": "2026-07-20T02:39:05+00:00",
                "snapshot_age_label": "1m ago",
                "stale": False,
                "greenhouse": {
                    "temperature_display": "75.0°F",
                    "humidity_display": "44%",
                    "temperature_band": "Normal",
                    "source_status": "live",
                    "source": "live",
                    "status": "Connected",
                    "message": "Live greenhouse readings are available.",
                    "today_high": "80.4°F",
                    "today_low": "75.0°F",
                    "last_updated": "2026-07-20T02:39:05+00:00",
                    "observed_at": "2026-07-20T02:39:05+00:00",
                    "source_timestamp": "2026-07-20T02:20:05+00:00",
                    "history_count": 2,
                    "history_points": [
                        {"timestamp": "2026-07-20T00:00:00+00:00", "value": 75.0, "unit": "°F", "availability": "available"},
                        {"timestamp": "2026-07-20T01:00:00+00:00", "value": 80.4, "unit": "°F", "availability": "available"},
                    ],
                    "stale": False,
                },
            },
        }
        self.context["status"]["greenhouse"].update({
            "source": "live",
            "status": "Connected",
            "observed_at": "2026-07-20T02:39:05+00:00",
            "source_timestamp": "2026-07-20T02:20:05+00:00",
            "stale": False,
        })
        self.context["environment"]["greenhouse"].update({
            "source": "live",
            "status": "Connected",
            "observed_at": "2026-07-20T02:39:05+00:00",
            "source_timestamp": "2026-07-20T02:20:05+00:00",
            "stale": False,
        })

    def test_dashboard_renders_greenhouse_card(self):
        with self.app.test_request_context("/"):
            html = render_template("dashboard.html", now=None, **self.context)

        self.assertIn("Greenhouse", html)
        self.assertIn("75.0°F", html)
        self.assertIn("Humidity 44%", html)
        self.assertIn("Connected", html)
        self.assertIn("Observed 2026-07-20T02:39:05+00:00", html)

    def test_environment_center_renders_greenhouse_section_and_chart(self):
        with self.app.test_request_context("/environment"):
            html = render_template("environment.html", now=None, environment=self.context["environment"])

        self.assertIn("Current greenhouse conditions", html)
        self.assertIn("Greenhouse temperature trend", html)
        self.assertIn("75.0°F", html)
        self.assertIn("44%", html)
        self.assertIn("Connected", html)
        self.assertIn("Observed at", html)

    def test_frontend_refresh_sequence_guard_is_present(self):
        live_dashboard = (ROOT / "static" / "js" / "live_dashboard.js").read_text(encoding="utf-8")
        self.assertIn("let homeGlanceRequestSeq = 0;", live_dashboard)
        self.assertIn("if (requestSeq !== homeGlanceRequestSeq) return;", live_dashboard)
        self.assertNotIn("updateGreenhouseCard({});", live_dashboard)

    def test_environment_center_refresh_sequence_guard_is_present(self):
        environment_center = (ROOT / "static" / "js" / "environment_center.js").read_text(encoding="utf-8")
        self.assertIn("let environmentRefreshSeq = 0;", environment_center)
        self.assertIn("if (requestSeq !== environmentRefreshSeq) return;", environment_center)


class GreenhouseSchemaAndBrowserTests(unittest.TestCase):
    def test_dashboard_and_environment_greenhouse_contract_share_the_same_core_fields(self):
        dashboard_greenhouse = {
            "temperature_display": "75.0Â°F",
            "humidity_display": "44%",
            "temperature_band": "Normal",
            "source_status": "live",
            "message": "Live greenhouse readings are available.",
            "today_high": "80.4Â°F",
            "today_low": "75.0Â°F",
            "last_updated": "2026-07-20T02:39:05+00:00",
            "history_count": 2,
            "history_points": [
                {"timestamp": "2026-07-20T00:00:00+00:00", "value": 75.0, "unit": "Â°F", "availability": "available"},
                {"timestamp": "2026-07-20T01:00:00+00:00", "value": 80.4, "unit": "Â°F", "availability": "available"},
            ],
        }
        dashboard_greenhouse.update({
            "source": "live",
            "status": "Connected",
            "observed_at": "2026-07-20T02:39:05+00:00",
            "source_timestamp": "2026-07-20T02:20:05+00:00",
            "stale": False,
        })
        environment_greenhouse = dict(dashboard_greenhouse)
        expected = {
            "temperature_display",
            "humidity_display",
            "temperature_band",
            "status",
            "source_status",
            "source",
            "message",
            "today_high",
            "today_low",
            "last_updated",
            "observed_at",
            "source_timestamp",
            "history_count",
            "history_points",
            "stale",
        }
        self.assertTrue(expected.issubset(dashboard_greenhouse.keys()))
        self.assertTrue(expected.issubset(environment_greenhouse.keys()))

    def test_frontend_refresh_sequence_guard_is_present(self):
        live_dashboard = (ROOT / "static" / "js" / "live_dashboard.js").read_text(encoding="utf-8")
        self.assertIn("let homeGlanceRequestSeq = 0;", live_dashboard)
        self.assertIn("if (requestSeq !== homeGlanceRequestSeq) return;", live_dashboard)
        self.assertNotIn("updateGreenhouseCard({});", live_dashboard)

    def test_environment_center_refresh_sequence_guard_is_present(self):
        environment_center = (ROOT / "static" / "js" / "environment_center.js").read_text(encoding="utf-8")
        self.assertIn("let environmentRefreshSeq = 0;", environment_center)
        self.assertIn("if (requestSeq !== environmentRefreshSeq) return;", environment_center)


class GreenhouseRouteTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.store = EnvironmentStore(self.conn)
        self.store.initialize()
        self.config = DummyConfig(
            {
                "environment": {
                    "enabled": True,
                    "refresh_interval_minutes": 5,
                    "stale_after_minutes": 10,
                },
                "router_reboot": {
                    "home_assistant_url": "http://homeassistant.local",
                    "home_assistant_token": "token",
                },
            }
        )
        self.log = DummyLog()
        self.manager = EnvironmentManager(self.config, self.log, self.store)

    def tearDown(self):
        self.conn.close()

    def test_main_dashboard_and_home_status_routes_return_200_with_mixed_timestamp_types(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        aware_timestamp = now.isoformat()
        naive_timestamp = now.astimezone(local_tz).replace(tzinfo=None).isoformat(timespec="seconds")
        mixed_payload = mixed_greenhouse_payload("73.2", "46.0", aware_timestamp, naive_timestamp)

        with patch.object(self.manager, "_fetch_home_assistant_payloads", return_value=mixed_payload):
            snapshot = self.manager.refresh_snapshot()

        self.assertTrue(str(snapshot["greenhouse"]["last_updated"]).endswith("+00:00"))

        dashboard_app = Dashboard(build_dashboard_app(self.manager))
        client = dashboard_app.app.test_client()

        with patch("modules.dashboard.render_template", return_value="OK"):
            home_response = client.get("/")
            environment_response = client.get("/environment")

        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(environment_response.status_code, 200)

        api_response = client.get("/api/home/status")
        self.assertEqual(api_response.status_code, 200)
        payload = api_response.get_json()
        self.assertIsInstance(payload.get("greenhouse"), dict)
        self.assertIn("source_timestamp", payload["greenhouse"])
        self.assertIn("observed_at", payload["greenhouse"])
        self.assertEqual(payload["greenhouse"]["status"], "Connected")
        self.assertEqual(payload["greenhouse"]["source"], "live")
        self.assertTrue(str(payload["greenhouse"]["last_updated"]).endswith("+00:00"))
        self.assertIn("temperature_display", payload["greenhouse"])
        self.assertIn("humidity_display", payload["greenhouse"])

if __name__ == "__main__":
    unittest.main()
ROOT = Path(__file__).resolve().parents[1]
