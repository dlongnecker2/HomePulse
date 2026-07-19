import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask, render_template

from modules.application import Application
from modules.config import Config
from modules.diagnostics import Diagnostics
from modules.email_notifier import EmailNotifier
from modules.power_adapters.base import PowerAdapterResult
from modules.router_rebooter import RouterRebooter
import modules.config as config_module


ROOT = Path(__file__).resolve().parents[1]


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


class FakeDB:
    def __init__(self, health=None, speed=None, health_history=None, latest_events=None):
        self._health = health or {}
        self._speed = speed or {}
        self._health_history = health_history or []
        self._latest_events = latest_events or {}
        self.events = []

    def latest_health_check(self):
        return self._health

    def latest_speed_test(self):
        return self._speed

    def health_history(self, limit=6):
        return list(self._health_history)[-limit:]

    def latest_event(self, event_type):
        return self._latest_events.get(event_type)

    def add_event(self, timestamp, event_type, message):
        event = {"timestamp": timestamp, "event_type": event_type, "message": message}
        self.events.append(event)
        self._latest_events[event_type] = event


class RouterRecoveryConfigTests(unittest.TestCase):
    def _config_path(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return temp_dir, Path(temp_dir.name) / "config.json"

    def _load_config(self, payload):
        temp_dir, config_path = self._config_path()
        config_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.object(config_module, "CONFIG_FILE", config_path):
            return Config(), config_path

    def test_live_recovery_defaults_to_false(self):
        cfg, _ = self._load_config({"router_reboot": {}})
        self.assertFalse(cfg.get("router_reboot", "router_recovery_live_enabled", default=True))

    def test_existing_configs_without_setting_remain_dry_run(self):
        cfg, _ = self._load_config({"router_reboot": {"real_reboot_enabled": True}})
        self.assertFalse(cfg.get("router_reboot", "router_recovery_live_enabled", default=True))

    def test_save_and_reload_preserves_live_recovery_setting(self):
        cfg, config_path = self._load_config({"router_reboot": {"router_recovery_live_enabled": True}})
        cfg.save()
        with patch.object(config_module, "CONFIG_FILE", config_path):
            reloaded = Config()
        self.assertTrue(reloaded.get("router_reboot", "router_recovery_live_enabled", default=False))


class RouterRecoveryUiTests(unittest.TestCase):
    def _render_settings(self, live_enabled):
        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.jinja_env.globals["app_name"] = "HomePulse"
        app.jinja_env.globals["render_test_button"] = lambda name, endpoint: f"<button>{name}</button>"

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
            "test_home_assistant",
            "test_home_assistant_power_cycle",
            "test_smtp",
            "test_ping",
            "test_speed",
            "test_full_diagnostics",
        ):
            app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

        context = dict(
            config=DummyConfig({"history": {}}),
            schedule_mode="every_1_hour",
            schedule_label="Every hour",
            speedtest_times=[],
            router_reboot={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": live_enabled,
            },
            router_recovery_config={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
            },
            email={"notifications": {}},
            energy={"home_assistant_entities": {}, "alerts": {}},
            vehicle={"entities": {}},
            solar={"entities": {}},
            weather={},
            lighting={},
            garden={},
            diagnostic_result=None,
            router_recovery_status={
                "mode_label": "LIVE AUTOMATIC RECOVERY" if live_enabled else "DRY RUN",
                "recovery_method": "home_assistant",
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity": "switch.office_router_plug",
                "current_state": "ON",
                "cooldown_status": "READY",
                "last_attempt": "None",
                "last_result": "None",
            },
            error=None,
            saved=False,
            now=None,
        )

        with app.test_request_context("/settings"):
            return render_template("settings.html", **context)

    def test_settings_renders_dry_run_when_disabled(self):
        html = self._render_settings(False)
        self.assertIn("Enable Automatic Router Recovery", html)
        self.assertIn("DRY RUN", html)
        self.assertNotIn("checked", html.split('name="router_recovery_live_enabled"', 1)[1].split(">", 1)[0])

    def test_settings_renders_live_mode_when_enabled(self):
        html = self._render_settings(True)
        self.assertIn("LIVE AUTOMATIC RECOVERY", html)
        self.assertIn('name="router_recovery_live_enabled" checked', html)
        self.assertIn("http://homeassistant.local:8123", html)
        self.assertIn("switch.office_router_plug", html)
        self.assertIn(">ON<", html)

    def test_settings_summary_uses_router_recovery_config_when_status_is_partial(self):
        app = Flask(__name__, template_folder=str(ROOT / "templates"))
        app.jinja_env.globals["app_name"] = "HomePulse"
        app.jinja_env.globals["render_test_button"] = lambda name, endpoint: f"<button>{name}</button>"
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
            "test_home_assistant",
            "test_home_assistant_power_cycle",
            "test_smtp",
            "test_ping",
            "test_speed",
            "test_full_diagnostics",
        ):
            app.add_url_rule(f"/{endpoint}", endpoint, lambda: "")

        context = dict(
            config=DummyConfig({"history": {}}),
            schedule_mode="every_1_hour",
            schedule_label="Every hour",
            speedtest_times=[],
            router_reboot={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": True,
            },
            router_recovery_config={
                "home_assistant_url": "http://homeassistant.local:8123",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
            },
            email={"notifications": {}},
            energy={"home_assistant_entities": {}, "alerts": {}},
            vehicle={"entities": {}},
            solar={"entities": {}},
            weather={},
            lighting={},
            garden={},
            diagnostic_result=None,
            router_recovery_status={
                "mode_label": "LIVE AUTOMATIC RECOVERY",
                "recovery_method": "home_assistant",
                "current_state": "Unknown",
                "cooldown_status": "READY",
                "last_attempt": "None",
                "last_result": "None",
            },
            error=None,
            saved=False,
            now=None,
        )

        with app.test_request_context("/settings"):
            html = render_template("settings.html", **context)

        self.assertIn("http://homeassistant.local:8123", html)
        self.assertIn("switch.office_router_plug", html)
        self.assertNotIn('id="recovery-summary-url">Not configured<', html)
        self.assertNotIn('id="recovery-summary-entity">Not configured<', html)


class RouterRecoveryStateTests(unittest.TestCase):
    def _fake_app(self):
        app = Application.__new__(Application)
        app.log = MagicMock()
        app.config = DummyConfig({
            "reboot_cooldown_hours": 24,
            "router_reboot": {
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "recovery_entity_id": "switch.office_router_plug",
                "matter_entity_id": "switch.office_router_plug",
            },
        })
        app.db = FakeDB()
        app.router_rebooter = SimpleNamespace(live_recovery_enabled=lambda: True)
        return app

    def test_router_recovery_summary_displays_current_state_when_available(self):
        app = self._fake_app()
        with patch("modules.application.HomeAssistantAdapter.get_state") as get_state:
            get_state.return_value = PowerAdapterResult(
                status="PASS",
                message="Connected. Entity state is on.",
                device_responded=True,
                power_restored=True,
                metadata={
                    "adapter": "home_assistant",
                    "entity_id": "switch.office_router_plug",
                    "state": "on",
                },
            )

            summary = app.router_recovery_summary(include_live_state=True)

        self.assertEqual(summary["home_assistant_url"], "http://homeassistant.local:8123")
        self.assertEqual(summary["recovery_entity"], "switch.office_router_plug")
        self.assertEqual(summary["current_state"], "ON")

    def test_router_recovery_summary_uses_unknown_when_state_lookup_fails(self):
        app = self._fake_app()
        with patch("modules.application.HomeAssistantAdapter.get_state", side_effect=RuntimeError("boom")):
            summary = app.router_recovery_summary(include_live_state=True)

        self.assertEqual(summary["current_state"], "Unknown")
        self.assertEqual(summary["state_status"], "FAIL")


class RouterRecoveryExecutionTests(unittest.TestCase):
    def _fake_app(self, live_enabled=False):
        app = Application.__new__(Application)
        app.log = MagicMock()
        app.config = DummyConfig({
            "database": "data/homepulse.db",
            "reboot_window_time": "04:00",
            "reboot_cooldown_hours": 24,
            "minimum_download_mbps": 100,
            "minimum_upload_mbps": 10,
            "maximum_latency_ms": 100,
            "thresholds": {"packet_loss": 5},
            "router_reboot": {
                "recovery_device_type": "home_assistant",
                "method": "home_assistant",
                "recovery_entity_id": "switch.office_router_plug",
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "router_recovery_live_enabled": live_enabled,
            },
        })
        app.db = FakeDB(
            health={"timestamp": "2026-07-18 08:00:00", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 55},
            speed={"timestamp": "2026-07-18 08:00:00", "download": 20, "upload": 2, "ping": 30, "server": "x"},
            health_history=[
                {"timestamp": "1", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
                {"timestamp": "2", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
                {"timestamp": "3", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
                {"timestamp": "4", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
                {"timestamp": "5", "latency": 80, "packet_loss": 0, "dns_ok": True, "score": 80},
            ],
        )
        app.email_notifier = MagicMock()
        app.router_rebooter = MagicMock()
        app.router_rebooter.live_recovery_enabled.return_value = live_enabled
        app.router_rebooter.execute.return_value = SimpleNamespace(
            method="home_assistant",
            dry_run=not live_enabled,
            command_sent=live_enabled,
            router_responded=live_enabled,
            internet_restored=live_enabled,
            result="ok" if live_enabled else "Dry run only",
            elapsed_recovery_time="0s",
            router_uptime_before="Unavailable",
            details="details",
        )
        app.timeline = SimpleNamespace(
            SEV_WARNING="warning",
            SEV_SUCCESS="success",
            SEV_INFO="info",
            CAT_RECOVERY="recovery",
        )
        app.record_timeline_event = MagicMock()
        app._router_recovery_lock = threading.Lock()
        return app

    def test_disabled_mode_uses_dry_run_adapter(self):
        config = DummyConfig({
            "router_reboot": {
                "recovery_device_type": "home_assistant",
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "recovery_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": False,
            }
        })
        log = MagicMock()
        rebooter = RouterRebooter(config, log)
        live_adapter = MagicMock(adapter_type="home_assistant", label="Home Assistant")
        live_adapter.cycle.return_value = PowerAdapterResult(
            status="PASS",
            message="live",
            command_sent=True,
            device_responded=True,
            power_restored=True,
        )
        dry_adapter = MagicMock()
        dry_adapter.adapter_type = "dry_run"
        dry_adapter.label = "Dry Run"
        dry_adapter.cycle.return_value = PowerAdapterResult(
            status="PASS",
            message="Dry run only - simulated cycle_power; no power command sent.",
            command_sent=False,
            device_responded=False,
            power_restored=False,
        )

        with patch("modules.router_rebooter.PowerAdapterFactory.create", return_value=live_adapter), patch(
            "modules.router_rebooter.DryRunAdapter", return_value=dry_adapter
        ):
            result = rebooter.execute("outage")

        self.assertTrue(result.dry_run)
        self.assertEqual(result.method, "dry_run")
        live_adapter.cycle.assert_not_called()
        dry_adapter.cycle.assert_called_once()

    def test_enabled_mode_calls_live_adapter(self):
        config = DummyConfig({
            "router_reboot": {
                "recovery_device_type": "home_assistant",
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "recovery_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": True,
            }
        })
        log = MagicMock()
        rebooter = RouterRebooter(config, log)
        live_adapter = MagicMock(adapter_type="home_assistant", label="Home Assistant")
        live_adapter.cycle.return_value = PowerAdapterResult(
            status="PASS",
            message="live",
            command_sent=True,
            device_responded=True,
            power_restored=True,
        )

        with patch("modules.router_rebooter.PowerAdapterFactory.create", return_value=live_adapter), patch(
            "modules.router_rebooter.DryRunAdapter"
        ) as dry_adapter:
            result = rebooter.execute("outage")

        self.assertFalse(result.dry_run)
        live_adapter.cycle.assert_called_once()
        dry_adapter.assert_not_called()

    def test_live_gate_blocks_when_home_assistant_validation_fails(self):
        app = self._fake_app(live_enabled=True)
        context = app.reboot_context(datetime.now(), ["reason"])
        context["timestamp"] = datetime.now().isoformat(sep=" ")
        with patch(
            "modules.power_adapters.home_assistant.HomeAssistantAdapter._validate_settings",
            return_value={"status": "WARN", "message": "Home Assistant URL is required.", "metadata": {}},
        ), patch(
            "modules.power_adapters.home_assistant.HomeAssistantAdapter.test_connection"
        ) as test_connection:
            ready, blocked_reason = app.router_recovery_live_gate(context, True)

        self.assertFalse(ready)
        self.assertIn("required", blocked_reason)
        test_connection.assert_not_called()

    def test_live_gate_allows_execution_when_ready(self):
        app = self._fake_app(live_enabled=True)
        with patch.object(app, "router_recovery_live_gate", return_value=(True, None)):
            app.execute_router_reboot(datetime.now(), ["reason"])

        app.router_rebooter.execute.assert_called_once()
        app.email_notifier.send_reboot_notification.assert_called_once()

    def test_consecutive_failures_still_required(self):
        app = self._fake_app(live_enabled=True)
        app.db._health_history = [
            {"timestamp": "1", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
            {"timestamp": "2", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
            {"timestamp": "3", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40},
        ]

        self.assertIsNone(app.sustained_health_problem())

        app.db._health_history.append({"timestamp": "4", "latency": 120, "packet_loss": 0, "dns_ok": True, "score": 40})
        self.assertIsNotNone(app.sustained_health_problem())

    def test_cooldown_prevents_overlapping_live_recovery(self):
        app = self._fake_app(live_enabled=True)
        app.db._latest_events["router_reboot"] = {
            "timestamp": str(datetime.now() - timedelta(hours=1)),
            "event_type": "router_reboot",
            "message": "previous live recovery",
        }

        with patch.object(app, "is_maintenance_window", return_value=True), patch.object(
            app, "execute_router_reboot"
        ) as execute_router_reboot:
            app.maintenance_check()

        execute_router_reboot.assert_not_called()
        self.assertEqual(app.db.events[-1]["event_type"], "router_reboot_skipped")

    def test_failed_action_releases_lock_and_records_failure(self):
        app = self._fake_app(live_enabled=True)
        app._router_recovery_lock.acquire()
        app._router_recovery_lock.release()
        with patch.object(app, "router_recovery_live_gate", return_value=(True, None)), patch.object(
            app.router_rebooter, "execute", side_effect=RuntimeError("boom")
        ):
            app.execute_router_reboot(datetime.now(), ["reason"])

        self.assertFalse(app._router_recovery_lock.locked())
        self.assertEqual(app.db.events[-1]["event_type"], "router_reboot")
        self.assertIn("Recovery failed", app.db.events[-1]["message"])

    def test_overlapping_attempts_are_skipped(self):
        app = self._fake_app(live_enabled=True)
        app._router_recovery_lock.acquire()
        try:
            app.execute_router_reboot(datetime.now(), ["reason"])
        finally:
            app._router_recovery_lock.release()

        app.router_rebooter.execute.assert_not_called()
        self.assertEqual(app.db.events[-1]["event_type"], "router_reboot_skipped")

    def test_manual_test_power_cycle_remains_independent(self):
        app = Application.__new__(Application)
        app.config = DummyConfig({
            "router_reboot": {
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "recovery_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": False,
            }
        })
        app.log = MagicMock()
        app.db = MagicMock()
        app.email_notifier = MagicMock()
        diagnostics = Diagnostics(app)
        adapter = MagicMock()
        adapter.adapter_type = "home_assistant"
        adapter.cycle_power.return_value = PowerAdapterResult(
            status="PASS",
            message="Manual test ok",
            command_sent=True,
            device_responded=True,
            power_restored=True,
            metadata={"on": {"service": "turn_on"}, "elapsed_recovery_time": "15s"},
        )

        with patch.object(diagnostics, "_power_diagnostic_adapter", return_value=adapter), patch.object(
            diagnostics, "_record_home_assistant_power_cycle", return_value=None
        ):
            result = diagnostics.home_assistant_power_cycle_test(datetime.now(), confirmed=True)

        self.assertEqual(result.status, "PASS")
        adapter.cycle_power.assert_called_once()

    def test_router_recovery_summary_uses_live_state_lookup_without_rebooting(self):
        app = self._fake_app(live_enabled=True)
        with patch("modules.application.HomeAssistantAdapter.get_state", return_value=PowerAdapterResult(
            status="PASS",
            message="Home Assistant entity switch.office_router_plug is on.",
            device_responded=True,
            power_restored=True,
            metadata={"state": "on", "entity_id": "switch.office_router_plug"},
        )):
            summary = app.router_recovery_summary(include_live_state=True)

        self.assertEqual(summary["home_assistant_url"], "http://homeassistant.local:8123")
        self.assertEqual(summary["recovery_entity"], "switch.office_router_plug")
        self.assertEqual(summary["current_state"], "ON")
        app.router_rebooter.execute.assert_not_called()

    def test_router_recovery_summary_normalizes_failed_state_lookup(self):
        app = self._fake_app(live_enabled=True)
        original_config = dict(app.config.data["router_reboot"])
        with patch("modules.application.HomeAssistantAdapter.get_state", side_effect=RuntimeError("boom")):
            summary = app.router_recovery_summary(include_live_state=True)

        self.assertEqual(summary["current_state"], "Unknown")
        self.assertEqual(app.config.data["router_reboot"], original_config)
        app.router_rebooter.execute.assert_not_called()


class RouterRecoveryNotificationTests(unittest.TestCase):
    def test_notifications_distinguish_dry_run_and_live_recovery(self):
        config = DummyConfig({
            "router_reboot": {
                "home_assistant_url": "http://homeassistant.local:8123",
                "home_assistant_token": "token",
                "recovery_entity_id": "switch.office_router_plug",
                "router_recovery_live_enabled": True,
            },
            "email": {
                "email_notifications_enabled": True,
                "smtp_server": "smtp.example.com",
                "smtp_port": 587,
                "smtp_from_email": "homepulse@example.com",
                "smtp_to_email": "user@example.com",
            },
        })
        notifier = EmailNotifier(config, MagicMock())
        sent = []

        def fake_send_email(subject, body, event_type, event_label, ignore_notification_toggle=False):
            sent.append((subject, body, event_type, event_label))
            return True

        dry_context = {"reason": "outage", "recovery_mode": "dry_run", "start_time": "now"}
        live_context = {"reason": "outage", "recovery_mode": "live", "start_time": "now", "end_time": "later"}
        dry_result = SimpleNamespace(
            method="dry_run",
            dry_run=True,
            command_sent=False,
            router_responded=False,
            internet_restored=False,
            result="Dry run only",
            elapsed_recovery_time="0s",
            router_uptime_before="Unavailable",
            details="",
        )
        live_result = SimpleNamespace(
            method="home_assistant",
            dry_run=False,
            command_sent=True,
            router_responded=True,
            internet_restored=True,
            result="Recovered",
            elapsed_recovery_time="5m",
            router_uptime_before="Unavailable",
            details="",
        )

        with patch.object(notifier, "send_email", side_effect=fake_send_email):
            notifier.send_recovery_started(dry_context)
            notifier.send_reboot_notification(live_context, live_result)
            notifier.send_reboot_notification(dry_context, dry_result)
            notifier.send_recovery_skipped({"reason": "outage", "recovery_mode": "skipped"}, "Cooldown is active.")

        subjects = [item[0] for item in sent]
        bodies = [item[1] for item in sent]
        self.assertTrue(any("Dry Run" in subject for subject in subjects))
        self.assertTrue(any("Live Recovery" in subject for subject in subjects))
        self.assertTrue(any("Recovery Skipped" in subject for subject in subjects))
        self.assertTrue(any("Recovery mode: Dry Run" in body for body in bodies))
        self.assertTrue(any("Recovery mode: Live automatic recovery" in body for body in bodies))
        self.assertTrue(any("Recovery mode: Recovery skipped" in body for body in bodies))


if __name__ == "__main__":
    unittest.main()
