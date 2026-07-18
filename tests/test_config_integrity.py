import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.application import Application
from modules.config import Config
from modules.config_backup import ConfigBackupService
import modules.config as config_module
from modules.dashboard import Dashboard


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


class DummyManager:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def energy_config(self):
        return dict(self.payload)

    def vehicle_config(self):
        return dict(self.payload)

    def solar_config(self):
        return dict(self.payload)

    def weather_config(self):
        return dict(self.payload)

    def lighting_config(self):
        return dict(self.payload)

    def garden_config(self):
        return dict(self.payload)


class ConfigIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.backup_dir = Path(self.temp_dir.name) / "data" / "config_backups"
        self.original = self._fixture_config()
        self.config_path.write_text(json.dumps(self.original, indent=2), encoding="utf-8")

    def _fixture_config(self):
        return {
            "speedtest_interval_minutes": 60,
            "router_reboot": {
                "method": "home_assistant",
                "recovery_device_type": "home_assistant",
                "recovery_control_mode": "home_assistant",
                "router_recovery_live_enabled": True,
                "recovery_device_ip": "192.0.2.10",
                "recovery_device_name": "HA Switch",
                "recovery_power_off_seconds": 10,
                "recovery_wait_after_power_on_seconds": 180,
                "real_reboot_enabled": True,
                "http_url": "http://router.example",
                "ssh_host": "router.example",
                "ssh_user": "admin",
                "ssh_command": "reboot",
                "smart_plug_url": "http://plug.example",
                "home_assistant_url": "http://ha.example:8123",
                "home_assistant_token": "secret-token",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
                "kasa_device_type": "smart",
                "kasa_device_family": "SMART.TAPOPLUG",
                "kasa_encrypt_type": "KLAP",
                "kasa_login_version": 2,
                "kasa_username": "kasa-user",
                "kasa_password": "kasa-secret",
                "kasa_credentials_hash": "hash",
                "future_nested": {"keep": "me"},
            },
            "home_assistant": {
                "enabled": True,
                "url": "http://ha.example:8123",
                "token": "ha-secret",
                "default_entity": "switch.office_router_plug",
            },
            "email": {
                "email_notifications_enabled": True,
                "enabled": True,
                "smtp_server": "smtp.example.com",
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_username": "mailer",
                "username": "mailer",
                "smtp_password": "smtp-secret",
                "password": "smtp-secret",
                "smtp_use_tls": True,
                "use_tls": True,
                "smtp_use_ssl": False,
                "smtp_from_email": "homepulse@example.com",
                "from_address": "homepulse@example.com",
                "smtp_to_email": "alice@example.com, bob@example.com",
                "to_address": "alice@example.com, bob@example.com",
                "notifications": {
                    "recovery_started": True,
                    "recovery_success": True,
                    "recovery_failed": True,
                    "recovery_skipped": True,
                    "diagnostics_failed": True,
                    "daily_summary": False,
                },
                "future_nested": {"keep": "me"},
            },
            "history": {
                "enabled": True,
                "snapshot_interval_minutes": 5,
                "retention_days": 365,
                "database": "data/homepulse_history.db",
                "future_nested": {"keep": "me"},
            },
            "weather": {
                "enabled": True,
                "location_name": "Home",
                "latitude": "37.1234",
                "longitude": "-122.1234",
                "provider": "open_meteo",
                "provider_strategy": "automatic_failover",
                "provider_priority": ["national_weather_service", "open_meteo"],
                "providers": {
                    "national_weather_service": {"enabled": True},
                    "open_meteo": {"enabled": True},
                },
                "future_nested": {"keep": "me"},
            },
            "lighting": {
                "enabled": True,
                "provider_strategy": "automatic_failover",
                "provider_priority": ["home_assistant"],
                "providers": {
                    "home_assistant": {
                        "enabled": True,
                        "exterior_keywords": "front,porch",
                    }
                },
                "future_nested": {"keep": "me"},
            },
            "garden": {
                "enabled": True,
                "provider_strategy": "automatic_failover",
                "provider_priority": ["bhyve"],
                "providers": {
                    "bhyve": {
                        "enabled": True,
                        "username": "garden-user",
                        "password": "garden-secret",
                        "access_token": "garden-token",
                    }
                },
                "future_nested": {"keep": "me"},
            },
            "solar": {
                "enabled": True,
                "name": "Solar Center",
                "cost_per_kwh_override": "0.18",
                "alerts": {
                    "enabled": True,
                    "system_down_enabled": True,
                    "envoy_unreachable_enabled": True,
                    "inverter_fault_enabled": True,
                    "min_consecutive_checks": 2,
                    "cooldown_hours": 6,
                },
                "entities": {
                    "current_power_production": "sensor.current_power",
                    "energy_production_today": "sensor.today",
                    "energy_production_last_seven_days": "sensor.seven_days",
                    "lifetime_energy_production": "sensor.lifetime",
                    "production_ct_power": "sensor.ct_power",
                    "production_ct_energy_delivered": "sensor.ct_energy",
                },
                "future_nested": {"keep": "me"},
            },
            "vehicle": {
                "enabled": True,
                "name": "Vehicle",
                "cost_per_kwh_override": "0.11",
                "entities": {
                    "battery_percent": "sensor.vehicle_battery",
                    "ev_range": "sensor.vehicle_range",
                    "plug_state": "binary_sensor.vehicle_plug",
                    "charging_state": "binary_sensor.vehicle_charge",
                    "odometer": "sensor.vehicle_odometer",
                    "lifetime_energy": "sensor.vehicle_energy",
                },
                "future_nested": {"keep": "me"},
            },
            "energy": {
                "enabled": True,
                "vehicle_name": "EV",
                "charger_name": "Charger",
                "cost_per_kwh": 0.12,
                "estimated_miles_per_kwh": 3.5,
                "alerts": {
                    "enabled": True,
                    "notify_on_start": True,
                    "notify_on_stop": True,
                },
                "home_assistant_entities": {
                    "status": "sensor.energy_status",
                    "power_kw": "sensor.energy_power",
                    "voltage": "sensor.energy_voltage",
                    "current": "sensor.energy_current",
                    "session_energy_kwh": "sensor.energy_session",
                    "battery_percent": "sensor.energy_battery",
                    "charging_time": "sensor.energy_charging_time",
                    "miles_added": "sensor.energy_miles_added",
                    "miles_per_hour_added": "sensor.energy_mph",
                    "charge_cost": "sensor.energy_cost",
                    "network": "sensor.energy_network",
                },
                "future_nested": {"keep": "me"},
            },
            "custom_top_level": {"keep": "me"},
        }

    def _load_config(self, payload):
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            cfg = Config.__new__(Config)
            cfg.backup_service = ConfigBackupService(self.config_path)
            cfg.data = deepcopy(payload)
            return cfg

    def test_partial_save_preserves_unrelated_sections_and_unknown_keys(self):
        cfg = self._load_config(self.original)
        cfg.data = {"router_reboot": {"router_recovery_live_enabled": False}}

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            cfg.save()

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertFalse(saved["router_reboot"]["router_recovery_live_enabled"])
        self.assertEqual(saved["router_reboot"]["home_assistant_url"], self.original["router_reboot"]["home_assistant_url"])
        self.assertEqual(saved["email"], self.original["email"])
        self.assertEqual(saved["weather"], self.original["weather"])
        self.assertEqual(saved["lighting"], self.original["lighting"])
        self.assertEqual(saved["garden"], self.original["garden"])
        self.assertEqual(saved["solar"], self.original["solar"])
        self.assertEqual(saved["vehicle"], self.original["vehicle"])
        self.assertEqual(saved["energy"], self.original["energy"])
        self.assertEqual(saved["custom_top_level"], self.original["custom_top_level"])
        self.assertEqual(saved["router_reboot"]["future_nested"], self.original["router_reboot"]["future_nested"])

    def test_blank_secret_fields_are_preserved_by_update_settings(self):
        cfg = self._load_config(self.original)
        app = Application.__new__(Application)
        app.config = cfg
        app.log = MagicMock()
        app.router_rebooter = SimpleNamespace(config=None)
        app.history = SimpleNamespace(refresh_config=lambda config: None, valid_positive_int=lambda value, **kwargs: int(value))
        app.weather = SimpleNamespace(config=None)
        app.lighting = SimpleNamespace(config=None)
        app.garden = SimpleNamespace(config=None)
        app.email_notifier = SimpleNamespace(NOTIFICATION_DEFAULTS={
            "recovery_started": True,
            "recovery_success": True,
            "recovery_failed": True,
            "recovery_skipped": True,
            "diagnostics_failed": True,
            "daily_summary": False,
        })
        app.scheduler = SimpleNamespace(remove_jobs_by_prefix=lambda prefix: None)
        app.register_history_job = lambda: None
        app.register_speedtest_jobs = lambda: None
        app.valid_speedtest_interval = lambda value: int(value)
        app.speedtest_mode_for_interval = lambda interval: "every_1_hour"
        app.speedtest_times_for_minutes = lambda interval: ["00:00"]
        app.default_speedtest_times = ["00:00"]
        app.update_speedtest_interval = lambda *args, **kwargs: None
        app.update_speedtest_schedule = lambda *args, **kwargs: None

        form = {
            "router_recovery_live_enabled": "on",
            "recovery_device_type": "home_assistant",
            "home_assistant_url": "http://ha.example:8123",
            "recovery_entity_id": "switch.office_router_plug",
            "email_notifications_enabled": "on",
            "smtp_server": "smtp.example.com",
            "smtp_port": "587",
            "smtp_username": "mailer",
            "smtp_password": "",
            "smtp_use_tls": "on",
            "smtp_from_email": "homepulse@example.com",
            "smtp_to_email": "alice@example.com",
            "energy_enabled": "on",
            "energy_vehicle_name": "EV",
            "energy_charger_name": "Charger",
            "energy_cost_per_kwh": "0.12",
            "energy_estimated_miles_per_kwh": "3.5",
        }

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            app.update_settings(form)

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["router_reboot"]["home_assistant_token"], self.original["router_reboot"]["home_assistant_token"])
        self.assertEqual(saved["email"]["smtp_password"], self.original["email"]["smtp_password"])
        self.assertEqual(saved["email"]["password"], self.original["email"]["password"])
        self.assertEqual(saved["garden"], self.original["garden"])

    def test_backup_is_created_before_successful_write_and_retained(self):
        cfg = self._load_config(self.original)

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            cfg.data = {"router_reboot": {"router_recovery_live_enabled": False}}
            cfg.save()
            cfg.data = {"router_reboot": {"router_recovery_live_enabled": True, "recovery_power_off_seconds": 11}}
            cfg.save()

        backups = sorted(self.backup_dir.glob("config-*.json"))
        self.assertGreaterEqual(len(backups), 2)
        self.assertRegex(backups[0].name, r"^config-\d{8}-\d{6}-\d{6}(?:-\d+)?\.json$")

    def test_backup_retention_keeps_latest_twenty(self):
        cfg = self._load_config(self.original)

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            for index in range(25):
                cfg.data = {"router_reboot": {"router_recovery_live_enabled": bool(index % 2), "recovery_power_off_seconds": 10 + index}}
                cfg.save()

        backups = sorted(self.backup_dir.glob("config-*.json"))
        self.assertEqual(len(backups), 20)

    def test_backup_failure_leaves_config_unchanged(self):
        cfg = self._load_config(self.original)
        original_text = self.config_path.read_text(encoding="utf-8")
        cfg.data = {"router_reboot": {"router_recovery_live_enabled": False}}

        with patch.object(config_module, "CONFIG_FILE", self.config_path), patch.object(
            cfg.backup_service,
            "create_backup",
            side_effect=OSError("backup failed"),
        ):
            with self.assertRaises(OSError):
                cfg.save()

        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original_text)

    def test_serialization_failure_leaves_config_unchanged(self):
        cfg = self._load_config(self.original)
        original_text = self.config_path.read_text(encoding="utf-8")
        cfg.data = {"router_reboot": {"router_recovery_live_enabled": False, "bad": {1, 2, 3}}}

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            with self.assertRaises(TypeError):
                cfg.save()

        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original_text)
        self.assertEqual(list(self.config_path.parent.glob("*.tmp")), [])

    def test_atomic_replace_failure_leaves_original_recoverable(self):
        cfg = self._load_config(self.original)
        original_text = self.config_path.read_text(encoding="utf-8")
        cfg.data = {"router_reboot": {"router_recovery_live_enabled": False}}

        with patch.object(config_module, "CONFIG_FILE", self.config_path), patch(
            "modules.config_backup.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaises(OSError):
                cfg.save()

        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original_text)
        self.assertEqual(list(self.config_path.parent.glob("*.tmp")), [])

    def test_invalid_config_is_rejected(self):
        cfg = self._load_config(self.original)
        cfg.data = {"email": []}

        with patch.object(config_module, "CONFIG_FILE", self.config_path):
            with self.assertRaises(ValueError):
                cfg.save()

        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8")), self.original)


class SettingsRouteFailureTests(unittest.TestCase):
    def test_settings_route_displays_error_when_persistence_fails(self):
        application = SimpleNamespace(
            config=DummyConfig({
                "history": {},
                "router_reboot": {"router_recovery_live_enabled": False},
                "email": {},
            }),
            speedtest_schedule_mode=lambda: "every_1_hour",
            speedtest_schedule_label=lambda: "Every hour",
            configured_speedtest_times=lambda: [],
            update_settings=MagicMock(side_effect=ValueError("Settings could not be saved.")),
            energy=DummyManager(),
            vehicle=DummyManager(),
            solar=DummyManager(),
            weather=DummyManager(),
            lighting=DummyManager(),
            garden=DummyManager(),
            diagnostics=SimpleNamespace(latest_result=lambda: None),
            router_recovery_summary=lambda include_live_state=True: {
                "mode_label": "DRY RUN",
                "recovery_method": "home_assistant",
                "home_assistant_url": "http://ha.example:8123",
                "recovery_entity": "switch.office_router_plug",
                "current_state": "UNKNOWN",
                "cooldown_status": "READY",
                "last_attempt": "None",
                "last_result": "None",
            },
        )

        dashboard = Dashboard(application)
        client = dashboard.app.test_client()
        response = client.post("/settings", data={"router_recovery_live_enabled": "on"})
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Settings could not be saved.", body)
        self.assertNotIn("Settings saved.", body)

