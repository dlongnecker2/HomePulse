import os
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from modules.config import Config
from modules.core import PluginManager
from modules.core.analytics import AnalyticsService
from modules.dashboard import Dashboard
from modules.database import Database
from modules.diagnostics import Diagnostics
from modules.email_notifier import EmailNotifier
from modules.energy import EnergyManager
from modules.history import HistoryService
from modules.home import TimelineService, HealthScoreEngine, AlertManager
from modules.lighting import LightingManager
from modules.logger import get_logger
from modules.network import NetworkMonitor
from modules.notifications import NotificationManager
from modules.port_check import check_dashboard_port
from modules.router_rebooter import RouterRebooter
from modules.scheduler import Scheduler
from modules.solar import SolarManager
from modules.speedtest_engine import SpeedTestEngine
from modules.status import StatusManager
from modules.tapo_discovery import TapoDiscovery
from modules.vehicle import VehicleManager
from modules.weather import WeatherManager
from modules.garden import GardenManager
from modules.network_mesh import NetworkMeshManager
from version import APP_NAME, APP_VERSION


class Application:
    def __init__(self):
        self.started_at = datetime.now()
        self.log = get_logger()
        self.config = Config()
        self.db = Database(self.config.get("database"))
        self.scheduler = Scheduler(self.log)
        self.network = NetworkMonitor(self.config, self.log)
        self.speedtest = SpeedTestEngine(self.log)
        self.router_rebooter = RouterRebooter(self.config, self.log)
        self.email_notifier = EmailNotifier(self.config, self.log, self.db)
        self.energy = EnergyManager(self.config, self.log)
        self.vehicle = VehicleManager(self.config, self.log)
        self.solar = SolarManager(self.config, self.log)
        self.weather = WeatherManager(self.config, self.log)
        self.lighting = LightingManager(self.config, self.log)
        self.garden = GardenManager(self.config, self.log)
        self.network_mesh = NetworkMeshManager(self.config, self.log)
        self.history = HistoryService(self.config, self.log)
        self.timeline = TimelineService()
        self.health_score = HealthScoreEngine()
        self.alert_manager = AlertManager(self.log)
        self.notification_manager = NotificationManager()
        self.plugin_manager = PluginManager(self, self.log)
        self.plugin_manager.register_compatibility_plugins()
        self._last_energy_charging_state = None
        self.status = StatusManager()
        self.diagnostics = Diagnostics(self)
        self.tapo_discovery = TapoDiscovery(self.log)
        self.analytics = AnalyticsService(self, self.log)
        self._last_restart_method = None
        self._scheduled_task_name = "HomePulse"
        self._restart_exit_delay_seconds = 4
        self._solar_alert_state_path = Path("logs/solar_alert_state.json")
        
        # State tracking for event recording (de-duplicated by timeline service)
        self._last_internet_status = None
        self._last_vehicle_plugged_in = None
        self._last_vehicle_charging = None
        self._last_solar_available = None
        self._last_solar_producing = None
        self._last_energy_charger_available = None
        self._last_home_assistant_available = None
        self._last_lighting_device_state = {}
        self._last_garden_watering_state = None
        self._last_garden_rain_delay_state = None
        
        # Record startup event
        self.timeline.record_event(
            category=self.timeline.CAT_SYSTEM,
            title="HomePulse Started",
            description=f"Version {APP_VERSION}",
            severity=self.timeline.SEV_SUCCESS,
            source="system",
        )

    def process_identity(self):
        task_status = self.scheduled_task_status()
        return {
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "pid": os.getpid(),
            "started_at": str(self.started_at),
            "uptime_seconds": max(0, int((datetime.now() - self.started_at).total_seconds())),
            "executable": sys.executable,
            "argv": list(sys.argv),
            "working_directory": os.getcwd(),
            "restart_supported": task_status["exists"],
            "last_restart_request": self.latest_restart_request(),
            "scheduled_task_exists": task_status["exists"],
            "scheduled_task_name": self._scheduled_task_name,
            "scheduled_task_last_result": task_status["last_result"],
            "restart_method": "Task Scheduler" if task_status["exists"] else "Not installed",
            "last_restart_method": self._last_restart_method,
        }

    def startup_message(self):
        identity = self.process_identity()
        self.log.info("=" * 60)
        self.log.info(
            f"{APP_NAME} startup beginning | timestamp={self.started_at} | pid={identity['pid']} | "
            f"version={APP_VERSION}"
        )
        self.log.info("Home Reliability Dashboard")
        self.log.info(f"Version: {APP_VERSION}")
        self.log.info(f"PID: {identity['pid']}")
        self.log.info(f"Executable: {identity['executable']}")
        self.log.info(f"Argv: {identity['argv']}")
        self.log.info(f"Working directory: {identity['working_directory']}")
        self.log.info(f"Startup time: {self.started_at}")
        self.log.info("Dashboard: http://localhost:8080")
        self.log.info("Lab: http://localhost:8080/lab")
        self.log.info("Developer Console: http://localhost:8080/dev")
        self.log.info("Logs: http://localhost:8080/logs")
        self.log.info("=" * 60)

    def initialize(self):
        self.startup_message()
        self.db.initialize()
        self.log.info("Database initialized successfully")
        self.history.initialize()
        self.plugin_manager.initialize_plugins()
        self.load_latest_speedtest()
        self.load_latest_health_check()
        self.register_jobs()
        self.write_restart_marker("restart_completed.json", {
            "timestamp": str(datetime.now()),
            "pid": os.getpid(),
            "started_at": str(self.started_at),
            "argv": list(sys.argv),
            "executable": sys.executable,
            "working_directory": os.getcwd(),
        })
        self.log.info(
            f"{APP_NAME} startup completed | timestamp={datetime.now()} | pid={os.getpid()} | "
            f"started_at={self.started_at}"
        )

    def load_latest_speedtest(self):
        latest = self.db.latest_speed_test()
        if latest:
            failed = latest["download"] is None
            error = latest["server"] or "Speed test provider unavailable"
            self.status.update_speedtest(
                download=latest["download"],
                upload=latest["upload"],
                ping=latest["ping"],
                server=latest["server"],
                last_run=latest["timestamp"],
                status="Unavailable" if failed else "Available",
                error="" if not failed else error,
            )

    def load_latest_health_check(self):
        latest = self.db.latest_health_check()
        if latest:
            status = "Healthy" if latest["score"] >= 90 else "Degraded" if latest["score"] >= 60 else "Unhealthy"
            self.status.update_internet(
                status=status,
                score=latest["score"],
                latency=latest["latency"],
                packet_loss=latest["packet_loss"],
                dns_ok=latest["dns_ok"],
                details="Loaded from latest SQLite health check",
                last_check=latest["timestamp"],
            )

    def register_jobs(self):
        self.scheduler.every_minutes(
            name="Internet Health Check",
            minutes=self.config.get("monitor_interval_minutes"),
            function=self.health_check,
        )
        self.register_speedtest_jobs()
        self.register_history_job()
        self.register_solar_alert_job()
        self.register_maintenance_job()

    def register_solar_alert_job(self):
        interval = self.config.get("monitor_interval_minutes", default=5)
        try:
            minutes = max(5, int(interval or 5))
        except (TypeError, ValueError):
            minutes = 5
        self.scheduler.every_minutes(
            name="Solar Health Alert Check",
            minutes=minutes,
            function=self.solar_health_alert_check,
        )
        self.log.info(f"Solar health alert checks scheduled every {minutes} minutes")

    def register_speedtest_jobs(self):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            self.log.info("Scheduled speed tests are disabled")
            return
        interval = self.speedtest_interval_minutes()
        self.scheduler.every_minutes(
            name="Scheduled Speed Test",
            minutes=interval,
            function=self.daily_speed_test,
        )
        self.log.info(f"Scheduled speed test interval: {interval} minutes")

    def register_maintenance_job(self):
        time_value = self.config.get("reboot_window_time", default="04:00")
        hour, minute = self.parse_clock_time(time_value)
        self.scheduler.daily(
            name=f"Maintenance Check {time_value}",
            hour=hour,
            minute=minute,
            function=self.maintenance_check,
        )
        self.log.info(f"Maintenance check scheduled for {time_value}")

    def register_history_job(self):
        if not self.config.get("history", "enabled", default=True):
            self.log.info("History snapshots are disabled")
            return
        interval = self.history.snapshot_interval_minutes()
        self.scheduler.every_minutes(
            name="History Snapshot",
            minutes=interval,
            function=self.history_snapshot,
        )
        self.log.info(f"History snapshot interval: {interval} minutes")

    def configured_speedtest_times(self):
        default_times = self.default_speedtest_times()
        configured = self.config.get("speedtest_times", default=default_times)
        if not isinstance(configured, list) or not configured:
            self.log.warning("Invalid speedtest_times config; using 30-minute defaults")
            configured = default_times

        valid_times = []
        seen = set()
        for time_value in configured:
            try:
                normalized = self.normalize_clock_time(time_value)
            except ValueError as exc:
                self.log.warning(f"Ignoring invalid speed test time {time_value!r}: {exc}")
                continue
            if normalized not in seen:
                valid_times.append(normalized)
                seen.add(normalized)

        if valid_times:
            return valid_times

        self.log.warning("No valid speedtest_times configured; using 30-minute defaults")
        return default_times

    @staticmethod
    def default_speedtest_times():
        return [f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)]

    @staticmethod
    def speedtest_times_for_interval(hours):
        return [f"{hour:02d}:00" for hour in range(0, 24, hours)]

    def speedtest_schedule_mode(self):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            return "disabled"
        mode = self.config.get("speedtest_schedule_mode", default=None)
        if mode:
            return mode

        times = self.configured_speedtest_times()
        presets = {
            "every_30_minutes": self.default_speedtest_times(),
            "every_1_hour": self.speedtest_times_for_interval(1),
            "every_3_hours": self.speedtest_times_for_interval(3),
            "every_6_hours": self.speedtest_times_for_interval(6),
        }
        for preset, preset_times in presets.items():
            if times == preset_times:
                return preset
        return "custom"

    def speedtest_schedule_label(self):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            return "Disabled"
        interval = self.speedtest_interval_minutes()
        if interval == 30:
            return "Every 30 minutes"
        if interval % 60 == 0:
            hours = interval // 60
            return f"Every {hours} hour" if hours == 1 else f"Every {hours} hours"
        return f"Every {interval} minutes"

    def speedtest_interval_minutes(self):
        return self.valid_speedtest_interval(self.config.get("speedtest_interval_minutes", default=60))

    @staticmethod
    def valid_speedtest_interval(value):
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return 60
        if minutes < 30 or minutes > 1440:
            return 60
        return minutes

    def speedtest_interval_label(self):
        return self.speedtest_schedule_label()

    def update_speedtest_interval(self, interval_minutes):
        interval = self.valid_speedtest_interval(interval_minutes)
        self.config.data["speedtest_interval_minutes"] = interval
        self.config.data["speedtest_schedule_enabled"] = True
        self.config.data["speedtest_schedule_mode"] = self.speedtest_mode_for_interval(interval)
        self.config.data["speedtest_times"] = self.speedtest_times_for_minutes(interval)
        self.config.save()
        self.scheduler.remove_jobs_by_prefix("Scheduled Speed Test")
        self.register_speedtest_jobs()

    @staticmethod
    def speedtest_mode_for_interval(interval):
        return {
            30: "every_30_minutes",
            60: "every_1_hour",
            180: "every_3_hours",
            360: "every_6_hours",
        }.get(interval, "interval")

    @staticmethod
    def speedtest_times_for_minutes(interval):
        times = []
        for minute_of_day in range(0, 24 * 60, interval):
            hour = minute_of_day // 60
            minute = minute_of_day % 60
            times.append(f"{hour:02d}:{minute:02d}")
        return times

    def legacy_speedtest_schedule_label(self):
        labels = {
            "disabled": "Disabled",
            "every_30_minutes": "Every 30 minutes",
            "every_1_hour": "Every 1 hour",
            "every_3_hours": "Every 3 hours",
            "every_6_hours": "Every 6 hours",
            "custom": "Custom scheduled times",
        }
        return labels.get(self.speedtest_schedule_mode(), "Custom scheduled times")

    def update_speedtest_schedule(self, mode, custom_times=None):
        mode_times = {
            "every_30_minutes": self.default_speedtest_times,
            "every_1_hour": lambda: self.speedtest_times_for_interval(1),
            "every_3_hours": lambda: self.speedtest_times_for_interval(3),
            "every_6_hours": lambda: self.speedtest_times_for_interval(6),
        }
        mode_intervals = {
            "every_30_minutes": 30,
            "every_1_hour": 60,
            "every_3_hours": 180,
            "every_6_hours": 360,
        }

        if mode == "disabled":
            self.config.data["speedtest_schedule_enabled"] = False
            self.config.data["speedtest_schedule_mode"] = "disabled"
        elif mode == "custom":
            times = self.normalize_custom_speedtest_times(custom_times or "")
            self.config.data["speedtest_schedule_enabled"] = True
            self.config.data["speedtest_schedule_mode"] = "custom"
            self.config.data["speedtest_times"] = times
            self.config.data["speedtest_interval_minutes"] = 60
        elif mode in mode_times:
            self.config.data["speedtest_schedule_enabled"] = True
            self.config.data["speedtest_schedule_mode"] = mode
            self.config.data["speedtest_times"] = mode_times[mode]()
            self.config.data["speedtest_interval_minutes"] = mode_intervals[mode]
        else:
            raise ValueError("Unknown speed test schedule mode")

        self.config.save()
        self.scheduler.remove_jobs_by_prefix("Scheduled Speed Test")
        self.register_speedtest_jobs()

    def reload_configuration(self):
        self.config = Config()
        self.network.config = self.config
        self.router_rebooter.config = self.config
        self.email_notifier.config = self.config
        self.email_notifier.db = self.db
        self.energy.config = self.config
        self.vehicle.config = self.config
        self.solar.config = self.config
        self.weather.config = self.config
        self.lighting.config = self.config
        self.garden.config = self.config
        self.network_mesh.config = self.config
        self.history.refresh_config(self.config)
        self.scheduler.remove_jobs_by_prefix("Scheduled Speed Test")
        self.scheduler.remove_jobs_by_prefix("History Snapshot")
        self.scheduler.remove_jobs_by_prefix("Solar Health Alert Check")
        self.scheduler.remove_jobs_by_prefix("Maintenance Check")
        self.register_speedtest_jobs()
        self.register_history_job()
        self.register_solar_alert_job()
        self.register_maintenance_job()
        self.log.info("Configuration reloaded from config.json")

    def update_settings(self, form):
        if "speedtest_interval_minutes" in form:
            self.update_speedtest_interval(form.get("speedtest_interval_minutes"))
        if "speedtest_schedule_mode" in form:
            self.update_speedtest_schedule(
                form.get("speedtest_schedule_mode", "every_30_minutes"),
                form.get("custom_speedtest_times", ""),
            )
        history_form_keys = (
            "history_enabled",
            "history_snapshot_interval_minutes",
            "history_retention_days",
        )
        if any(key in form for key in history_form_keys):
            history = self.config.data.setdefault("history", {})
            history["enabled"] = form.get("history_enabled") == "on"
            history["snapshot_interval_minutes"] = self.history.valid_positive_int(
                form.get("history_snapshot_interval_minutes"),
                default=5,
                minimum=1,
                maximum=1440,
            )
            history["retention_days"] = self.history.valid_positive_int(
                form.get("history_retention_days"),
                default=365,
                minimum=1,
                maximum=3650,
            )
            self.history.refresh_config(self.config)
            self.scheduler.remove_jobs_by_prefix("History Snapshot")
            self.register_history_job()

        weather_form_keys = (
            "weather_enabled",
            "weather_location_name",
            "weather_latitude",
            "weather_longitude",
            "weather_provider",
            "weather_provider_national_weather_service_enabled",
            "weather_provider_open_meteo_enabled",
        )
        if any(key in form for key in weather_form_keys):
            weather = self.config.data.setdefault("weather", {})
            weather["enabled"] = form.get("weather_enabled") == "on"
            weather["location_name"] = form.get("weather_location_name", "Home").strip() or "Home"
            weather["latitude"] = form.get("weather_latitude", "").strip()
            weather["longitude"] = form.get("weather_longitude", "").strip()
            providers = weather.setdefault("providers", {})
            providers.setdefault("national_weather_service", {})
            providers.setdefault("open_meteo", {})
            providers["national_weather_service"]["enabled"] = (
                form.get("weather_provider_national_weather_service_enabled") == "on"
            )
            providers["open_meteo"]["enabled"] = (
                form.get("weather_provider_open_meteo_enabled") == "on"
            )

            # Keep a selected-provider key for diagnostics/backward compatibility,
            # but strategy is framework-based automatic failover.
            legacy_provider = form.get("weather_provider", "").strip().lower()
            if legacy_provider in ("national_weather_service", "open_meteo", "manual", "placeholder"):
                weather["provider"] = legacy_provider
            weather["provider_strategy"] = "automatic_failover"
            weather["provider_priority"] = ["national_weather_service", "open_meteo"]
            self.weather.config = self.config

        lighting_form_keys = (
            "lighting_enabled",
            "lighting_provider_home_assistant_enabled",
            "lighting_exterior_keywords",
        )
        if any(key in form for key in lighting_form_keys):
            lighting = self.config.data.setdefault("lighting", {})
            lighting["enabled"] = form.get("lighting_enabled") == "on"
            providers = lighting.setdefault("providers", {})
            home_assistant = providers.setdefault("home_assistant", {})
            home_assistant["enabled"] = form.get("lighting_provider_home_assistant_enabled") == "on"
            home_assistant["exterior_keywords"] = form.get(
                "lighting_exterior_keywords",
                "govee,h706b,exterior,outdoor,porch,driveway,deck,spot,side light,back deck,back spot",
            ).strip()
            lighting["provider_strategy"] = "automatic_failover"
            lighting["provider_priority"] = ["home_assistant"]
            self.lighting.config = self.config

        garden_form_keys = (
            "garden_enabled",
            "garden_provider_bhyve_enabled",
            "bhyve_username",
            "bhyve_password",
            "bhyve_access_token",
        )
        if any(key in form for key in garden_form_keys):
            garden = self.config.data.setdefault("garden", {})
            garden["enabled"] = form.get("garden_enabled") == "on"
            providers = garden.setdefault("providers", {})
            bhyve = providers.setdefault("bhyve", {})
            bhyve["enabled"] = form.get("garden_provider_bhyve_enabled") == "on"
            bhyve["username"] = form.get("bhyve_username", "").strip()
            new_bhyve_password = form.get("bhyve_password", "")
            if new_bhyve_password:
                bhyve["password"] = new_bhyve_password
            new_bhyve_token = form.get("bhyve_access_token", "")
            if new_bhyve_token:
                bhyve["access_token"] = new_bhyve_token
            garden["provider_strategy"] = "automatic_failover"
            garden["provider_priority"] = ["bhyve"]
            self.garden.config = self.config

        router_reboot = self.config.data.setdefault("router_reboot", {})
        device_type = form.get(
            "recovery_device_type",
            form.get("router_reboot_method", router_reboot.get("recovery_device_type", "home_assistant")),
        )
        control_mode = form.get("recovery_control_mode")
        if not control_mode:
            if device_type in ("home_assistant", "tapo_p125m_matter", "matter", "matter_bridge"):
                control_mode = "home_assistant"
            elif device_type in ("kasa_tapo", "kasa_legacy"):
                control_mode = "kasa_legacy"
            else:
                control_mode = "dry_run"
        router_reboot["method"] = device_type
        router_reboot["recovery_device_type"] = device_type
        router_reboot["recovery_control_mode"] = control_mode
        router_reboot["recovery_device_ip"] = form.get("recovery_device_ip", "").strip()
        router_reboot["recovery_device_name"] = form.get("recovery_device_name", "").strip()
        router_reboot["recovery_power_off_seconds"] = int(form.get("recovery_power_off_seconds", "10") or 10)
        router_reboot["recovery_wait_after_power_on_seconds"] = int(
            form.get("recovery_wait_after_power_on_seconds", "180") or 180
        )
        router_reboot["real_reboot_enabled"] = False
        router_reboot["http_url"] = form.get("router_http_url", "").strip()
        router_reboot["ssh_host"] = form.get("router_ssh_host", "").strip()
        router_reboot["ssh_user"] = form.get("router_ssh_user", "").strip()
        router_reboot["ssh_command"] = form.get("router_ssh_command", "reboot").strip() or "reboot"
        router_reboot["smart_plug_url"] = form.get("smart_plug_url", "").strip()
        router_reboot["home_assistant_url"] = form.get("home_assistant_url", "").strip()
        entity_id = form.get("recovery_entity_id", form.get("matter_entity_id", "")).strip()
        router_reboot["recovery_entity_id"] = entity_id
        router_reboot["matter_entity_id"] = entity_id
        new_ha_token = form.get("home_assistant_token", "")
        if new_ha_token:
            router_reboot["home_assistant_token"] = new_ha_token
        router_reboot["kasa_device_type"] = form.get("kasa_device_type", "smart").strip() or "smart"
        router_reboot["kasa_device_family"] = form.get("kasa_device_family", "SMART.TAPOPLUG").strip() or "SMART.TAPOPLUG"
        router_reboot["kasa_encrypt_type"] = form.get("kasa_encrypt_type", "KLAP").strip() or "KLAP"
        router_reboot["kasa_login_version"] = int(form.get("kasa_login_version", "2") or 2)
        router_reboot["kasa_username"] = form.get("kasa_username", "").strip()
        new_kasa_password = form.get("kasa_password", "")
        if new_kasa_password:
            router_reboot["kasa_password"] = new_kasa_password
        router_reboot["kasa_credentials_hash"] = form.get("kasa_credentials_hash", "").strip()

        email_form_keys = (
            "email_notifications_enabled",
            "smtp_server",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_use_tls",
            "smtp_use_ssl",
            "smtp_from_email",
            "smtp_to_email",
            "email_enabled",
            "smtp_host",
        )
        if any(key in form for key in email_form_keys):
            email = self.config.data.setdefault("email", {})
            enabled = form.get("email_notifications_enabled") == "on" or form.get("email_enabled") == "on"
            email["email_notifications_enabled"] = enabled
            email["enabled"] = enabled
            email["smtp_server"] = form.get("smtp_server", form.get("smtp_host", "")).strip()
            email["smtp_host"] = email["smtp_server"]
            email["smtp_port"] = int(form.get("smtp_port", "587") or 587)
            email["smtp_username"] = form.get("smtp_username", "").strip()
            email["username"] = email["smtp_username"]
            email["smtp_use_tls"] = form.get("smtp_use_tls") == "on"
            email["use_tls"] = email["smtp_use_tls"]
            email["smtp_use_ssl"] = form.get("smtp_use_ssl") == "on"
            new_password = form.get("smtp_password", "")
            if new_password:
                email["smtp_password"] = new_password
                email["password"] = new_password
            email["smtp_from_email"] = form.get("smtp_from_email", form.get("email_from_address", "")).strip()
            email["from_address"] = email["smtp_from_email"]
            email["smtp_to_email"] = form.get("smtp_to_email", form.get("email_to_address", "")).strip()
            email["to_address"] = email["smtp_to_email"]
            notifications = email.setdefault("notifications", {})
            for key in self.email_notifier.NOTIFICATION_DEFAULTS:
                notifications[key] = form.get(f"notify_{key}") == "on"
        energy_form_keys = (
            "energy_enabled",
            "energy_vehicle_name",
            "energy_charger_name",
            "energy_cost_per_kwh",
            "energy_estimated_miles_per_kwh",
            "energy_entity_status",
            "energy_entity_power_kw",
            "energy_entity_voltage",
            "energy_entity_current",
            "energy_entity_session_energy_kwh",
            "energy_entity_battery_percent",
            "energy_entity_charging_time",
            "energy_entity_miles_added",
            "energy_entity_miles_per_hour_added",
            "energy_entity_charge_cost",
            "energy_entity_network",
            "energy_alerts_enabled",
            "energy_alert_notify_on_start",
            "energy_alert_notify_on_stop",
        )
        if any(key in form for key in energy_form_keys):
            energy = self.config.data.setdefault("energy", {})
            energy["enabled"] = form.get("energy_enabled") == "on"
            energy["vehicle_name"] = form.get("energy_vehicle_name", "2025 Chevrolet Equinox EV").strip()
            energy["charger_name"] = form.get("energy_charger_name", "Juice Box").strip()
            energy["cost_per_kwh"] = float(form.get("energy_cost_per_kwh", "0.13") or 0.13)
            energy["estimated_miles_per_kwh"] = float(form.get("energy_estimated_miles_per_kwh", "3.5") or 3.5)
            entities = energy.setdefault("home_assistant_entities", {})
            entities["status"] = form.get("energy_entity_status", "").strip()
            entities["power_kw"] = form.get("energy_entity_power_kw", "").strip()
            entities["voltage"] = form.get("energy_entity_voltage", "").strip()
            entities["current"] = form.get("energy_entity_current", "").strip()
            entities["session_energy_kwh"] = form.get("energy_entity_session_energy_kwh", "").strip()
            entities["battery_percent"] = form.get("energy_entity_battery_percent", "").strip()
            entities["charging_time"] = form.get("energy_entity_charging_time", "").strip()
            entities["miles_added"] = form.get("energy_entity_miles_added", "").strip()
            entities["miles_per_hour_added"] = form.get("energy_entity_miles_per_hour_added", "").strip()
            entities["charge_cost"] = form.get("energy_entity_charge_cost", "").strip()
            entities["network"] = form.get("energy_entity_network", "").strip()
            alerts = energy.setdefault("alerts", {})
            alerts["enabled"] = form.get("energy_alerts_enabled") == "on"
            alerts["notify_on_start"] = form.get("energy_alert_notify_on_start") == "on"
            alerts["notify_on_stop"] = form.get("energy_alert_notify_on_stop") == "on"
        vehicle_form_keys = (
            "vehicle_enabled",
            "vehicle_name",
            "vehicle_cost_per_kwh_override",
            "vehicle_entity_battery_percent",
            "vehicle_entity_ev_range",
            "vehicle_entity_plug_state",
            "vehicle_entity_charging_state",
            "vehicle_entity_odometer",
            "vehicle_entity_lifetime_energy",
        )
        if any(key in form for key in vehicle_form_keys):
            vehicle = self.config.data.setdefault("vehicle", {})
            vehicle["enabled"] = form.get("vehicle_enabled") == "on"
            vehicle["name"] = form.get("vehicle_name", "2025 Chevrolet Equinox EV").strip()
            vehicle["cost_per_kwh_override"] = form.get("vehicle_cost_per_kwh_override", "").strip()
            entities = vehicle.setdefault("entities", {})
            entities["battery_percent"] = form.get("vehicle_entity_battery_percent", "").strip()
            entities["ev_range"] = form.get("vehicle_entity_ev_range", "").strip()
            entities["plug_state"] = form.get("vehicle_entity_plug_state", "").strip()
            entities["charging_state"] = form.get("vehicle_entity_charging_state", "").strip()
            entities["odometer"] = form.get("vehicle_entity_odometer", "").strip()
            entities["lifetime_energy"] = form.get("vehicle_entity_lifetime_energy", "").strip()
        solar_form_keys = (
            "solar_enabled",
            "solar_name",
            "solar_cost_per_kwh_override",
            "solar_entity_current_power_production",
            "solar_entity_energy_production_today",
            "solar_entity_energy_production_last_seven_days",
            "solar_entity_lifetime_energy_production",
            "solar_entity_production_ct_power",
            "solar_entity_production_ct_energy_delivered",
        )
        if any(key in form for key in solar_form_keys):
            solar = self.config.data.setdefault("solar", {})
            solar["enabled"] = form.get("solar_enabled") == "on"
            solar["name"] = form.get("solar_name", "Solar Center").strip() or "Solar Center"
            solar["cost_per_kwh_override"] = form.get("solar_cost_per_kwh_override", "").strip()
            entities = solar.setdefault("entities", {})
            entities["current_power_production"] = form.get("solar_entity_current_power_production", "").strip()
            entities["energy_production_today"] = form.get("solar_entity_energy_production_today", "").strip()
            entities["energy_production_last_seven_days"] = form.get(
                "solar_entity_energy_production_last_seven_days", ""
            ).strip()
            entities["lifetime_energy_production"] = form.get("solar_entity_lifetime_energy_production", "").strip()
            entities["production_ct_power"] = form.get("solar_entity_production_ct_power", "").strip()
            entities["production_ct_energy_delivered"] = form.get(
                "solar_entity_production_ct_energy_delivered", ""
            ).strip()
        self.config.save()

    def history_snapshot(self):
        try:
            count = self.history.snapshot(self)
            self.history.prune_old_data(self.history.retention_days())
            return count
        except Exception as exc:
            self.log.exception(f"History snapshot failed: {exc}")
            return 0

    def solar_health_alert_check(self):
        try:
            if not self.config.get("solar", "enabled", default=False):
                return

            observation = self.solar.read_envoy_alert_observation()
            status = self.solar.get_status(include_inverter_details=True)
            inverters = status.get("inverters") if isinstance(status, dict) else []
            self.solar.record_inverter_history(self.db, inverters, timestamp=datetime.now())
            self._evaluate_solar_alerts(status, observation)
        except Exception as exc:
            self.log.exception(f"Solar health alert check failed: {exc}")

    def solar_alert_settings(self):
        solar_cfg = self.config.get("solar", default={})
        alerts = dict(solar_cfg.get("alerts") or {})
        return {
            "enabled": bool(alerts.get("enabled", True)),
            "system_down_enabled": bool(alerts.get("system_down_enabled", True)),
            "envoy_unreachable_enabled": bool(alerts.get("envoy_unreachable_enabled", True)),
            "inverter_fault_enabled": bool(alerts.get("inverter_fault_enabled", True)),
            "cooldown_hours": float(alerts.get("cooldown_hours", 6) or 6),
            "min_consecutive_checks": int(alerts.get("min_consecutive_checks", 2) or 2),
        }

    def update_solar_alert_settings(self, payload):
        def _bool(key, default):
            value = payload.get(key, default)
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return bool(default)

        def _int(key, default, minimum, maximum):
            try:
                value = int(payload.get(key, default))
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        solar = self.config.data.setdefault("solar", {})
        alerts = solar.setdefault("alerts", {})
        alerts["enabled"] = _bool("enabled", True)
        alerts["system_down_enabled"] = _bool("system_down_enabled", True)
        alerts["envoy_unreachable_enabled"] = _bool("envoy_unreachable_enabled", True)
        alerts["inverter_fault_enabled"] = _bool("inverter_fault_enabled", True)
        alerts["cooldown_hours"] = _int("cooldown_hours", 6, 1, 168)
        alerts["min_consecutive_checks"] = _int("min_consecutive_checks", 2, 1, 10)
        self.config.save()
        return self.solar_alert_settings()

    def _evaluate_solar_alerts(self, solar_status, observation):
        now = datetime.now()
        state = self._load_solar_alert_state()
        alert_cfg = self.solar_alert_settings()
        if not alert_cfg.get("enabled", True):
            return

        min_hits = int(alert_cfg.get("min_consecutive_checks", 2) or 2)
        cooldown_hours = float(alert_cfg.get("cooldown_hours", 6) or 6)

        system_problem, system_reason, system_kind = self._solar_system_problem(solar_status, observation)
        system_enabled = (
            alert_cfg.get("system_down_enabled", True)
            if system_kind == "system_down"
            else alert_cfg.get("envoy_unreachable_enabled", True)
        )
        self._evaluate_solar_alert_slot(
            slots=state.setdefault("slots", {}),
            key="system",
            is_problem=bool(system_problem and system_enabled),
            reason=system_reason,
            now=now,
            min_hits=min_hits,
            cooldown_hours=cooldown_hours,
            send_func=lambda: self._send_solar_system_down_email(solar_status, observation, system_reason, now),
        )

        slots = state.setdefault("slots", {})
        inverter_rows = solar_status.get("inverters") if isinstance(solar_status, dict) else []
        if not isinstance(inverter_rows, list):
            inverter_rows = []

        active_keys = set()
        for row in inverter_rows:
            if not isinstance(row, dict):
                continue
            inverter_id = str(row.get("id") or "").strip()
            status_text = str(row.get("status") or "").strip().lower()
            if not inverter_id:
                continue
            slot_key = f"inverter:{inverter_id}"
            active_keys.add(slot_key)
            is_problem = status_text == "offline"
            reason = f"Envoy explicitly reports inverter {inverter_id} as offline/faulted/disabled." if is_problem else ""
            self._evaluate_solar_alert_slot(
                slots=slots,
                key=slot_key,
                is_problem=bool(is_problem and alert_cfg.get("inverter_fault_enabled", True)),
                reason=reason,
                now=now,
                min_hits=min_hits,
                cooldown_hours=cooldown_hours,
                send_func=lambda iid=inverter_id, irow=row, ireason=reason: self._send_solar_inverter_issue_email(
                    solar_status,
                    irow,
                    ireason,
                    now,
                    iid,
                ),
            )

        for key in list(slots.keys()):
            if key.startswith("inverter:") and key not in active_keys:
                self._evaluate_solar_alert_slot(
                    slots=slots,
                    key=key,
                    is_problem=False,
                    reason="",
                    now=now,
                    min_hits=min_hits,
                    cooldown_hours=cooldown_hours,
                    send_func=lambda: False,
                )

        state["last_check_at"] = str(now)
        self._save_solar_alert_state(state)

    def _solar_system_problem(self, solar_status, observation):
        if isinstance(observation, dict) and observation.get("explicit_system_problem"):
            summary = observation.get("problem_summary") or "Envoy system explicitly reports unavailable/down/faulted status."
            return True, str(summary), "system_down"

        if isinstance(observation, dict) and observation.get("reachable") is False:
            error_text = observation.get("error") or "Envoy could not be reached."
            return True, f"Envoy reachability failure: {error_text}", "envoy_unreachable"

        if isinstance(solar_status, dict):
            error_text = str(solar_status.get("error") or "").strip().lower()
            if "home assistant unreachable" in error_text:
                return True, "Envoy reachability failure: Home Assistant is unreachable.", "envoy_unreachable"
        return False, "", ""

    def _evaluate_solar_alert_slot(self, slots, key, is_problem, reason, now, min_hits, cooldown_hours, send_func):
        slot = slots.setdefault(
            key,
            {
                "consecutive_hits": 0,
                "alert_active": False,
                "last_alert_at": None,
                "last_reason": "",
            },
        )

        if is_problem:
            slot["consecutive_hits"] = int(slot.get("consecutive_hits", 0) or 0) + 1
            slot["last_reason"] = reason
            if slot.get("alert_active"):
                return
            if slot["consecutive_hits"] < max(1, int(min_hits)):
                return
            if not self._alert_cooldown_elapsed(slot.get("last_alert_at"), cooldown_hours, now):
                return
            sent = bool(send_func())
            if sent:
                slot["alert_active"] = True
                slot["last_alert_at"] = str(now)
            return

        slot["consecutive_hits"] = 0
        slot["last_reason"] = ""
        if slot.get("alert_active"):
            slot["alert_active"] = False
            slot["last_cleared_at"] = str(now)

    @staticmethod
    def _alert_cooldown_elapsed(last_alert_at, cooldown_hours, now):
        if not last_alert_at:
            return True
        last = Application.parse_timestamp(last_alert_at)
        if not last:
            return True
        return (now - last) >= timedelta(hours=float(cooldown_hours or 0))

    def _send_solar_system_down_email(self, solar_status, observation, reason, detected_at):
        subject = "HomePulse Alert: Solar system down"
        body = (
            "Solar system health alert\n\n"
            f"Time detected: {detected_at}\n"
            "Problem type: Solar system down\n"
            f"Envoy/system status: {reason or 'Unavailable'}\n"
            "Inverter ID: N/A\n"
            f"Current production: {self._metric_text(solar_status.get('current_production_kw') if isinstance(solar_status, dict) else None, 'kW')}\n"
            f"Lifetime production: {self._metric_text(solar_status.get('lifetime_production_kwh') if isinstance(solar_status, dict) else None, 'kWh')}\n"
            "Reminder: HomePulse only alerts on explicit Envoy fault/offline states or repeated Envoy reachability failures.\n"
        )
        return self.email_notifier.send_email(
            subject=subject,
            body=body,
            event_type="email_solar_system_down",
            event_label="Solar system down email",
        )

    def _send_solar_inverter_issue_email(self, solar_status, inverter_row, reason, detected_at, inverter_id):
        subject = "HomePulse Alert: Solar inverter issue"
        inverter_status = str((inverter_row or {}).get("status") or "Offline")
        body = (
            "Solar inverter health alert\n\n"
            f"Time detected: {detected_at}\n"
            "Problem type: Solar inverter issue\n"
            f"Envoy/system status: {reason or inverter_status}\n"
            f"Inverter ID: {inverter_id}\n"
            f"Current production: {self._metric_text(solar_status.get('current_production_kw') if isinstance(solar_status, dict) else None, 'kW')}\n"
            f"Lifetime production: {self._metric_text(solar_status.get('lifetime_production_kwh') if isinstance(solar_status, dict) else None, 'kWh')}\n"
            "Reminder: HomePulse only alerts on explicit Envoy fault/offline states or repeated Envoy reachability failures.\n"
        )
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", inverter_id or "unknown")
        return self.email_notifier.send_email(
            subject=subject,
            body=body,
            event_type=f"email_solar_inverter_issue_{safe_id}",
            event_label="Solar inverter issue email",
        )

    @staticmethod
    def _metric_text(value, unit):
        if value is None:
            return "Unavailable"
        try:
            number = float(value)
            return f"{number:.2f} {unit}"
        except (TypeError, ValueError):
            return f"{value} {unit}"

    def _load_solar_alert_state(self):
        default = {"slots": {}, "last_check_at": None}
        path = self._solar_alert_state_path
        try:
            if not path.exists():
                return default
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return default
            payload.setdefault("slots", {})
            payload.setdefault("last_check_at", None)
            return payload
        except Exception as exc:
            self.log.debug(f"Could not read solar alert state: {exc}", exc_info=True)
            return default

    def _save_solar_alert_state(self, state):
        path = self._solar_alert_state_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
                handle.write("\n")
        except Exception as exc:
            self.log.debug(f"Could not persist solar alert state: {exc}", exc_info=True)

    def energy_status(self):
        status = self.energy.get_status()
        self.observe_energy_status(status)
        return status

    def observe_energy_status(self, status):
        try:
            energy = self.config.get("energy", default={})
            alerts = energy.get("alerts", {})
            if not energy.get("enabled") or not alerts.get("enabled", False):
                self._last_energy_charging_state = None
                return

            current = bool(status.get("is_charging"))
            previous = self._last_energy_charging_state
            self._last_energy_charging_state = current
            if previous is None or previous == current:
                return
            if current and not alerts.get("notify_on_start", True):
                return
            if not current and not alerts.get("notify_on_stop", True):
                return
            self.email_notifier.send_energy_charging_alert(status, started=current)
        except Exception as exc:
            self.log.exception(f"Energy charging alert failed: {exc}")

    def record_timeline_event(
        self,
        category,
        title,
        description="",
        severity="info",
        source="application",
        check_dedup=True,
        metadata=None,
    ):
        """Safely record a timeline event without interrupting core flows."""
        try:
            return self.timeline.record_event(
                category=category,
                title=title,
                description=description,
                severity=severity,
                source=source,
                check_dedup=check_dedup,
                metadata=metadata,
            )
        except Exception as exc:
            self.log.debug(f"Timeline record failed ({title}): {exc}", exc_info=True)
            return None

    def publish_internet_status_change(self, previous_status, current_status, details="", score=None):
        """Publish internet status transitions only when state changes."""
        previous = str(previous_status or "").strip()
        current = str(current_status or "").strip()
        if not previous or not current or previous == current:
            return

        severity = self.timeline.SEV_SUCCESS if current.lower() in {"healthy", "available", "up"} else self.timeline.SEV_WARNING
        description = f"Internet status changed from {previous} to {current}."
        if details:
            description = f"{description} {details}"

        self.record_timeline_event(
            category=self.timeline.CAT_INTERNET,
            title="Internet Status Changed",
            description=description,
            severity=severity,
            source="network",
            metadata={"previous_status": previous, "current_status": current, "score": score},
        )

    def publish_router_reboot_timeline(self, event_type, message, result=None):
        """Mirror key router reboot DB events into the Home timeline."""
        title_map = {
            "router_reboot": "Router Reboot Executed",
            "router_reboot_recommended": "Router Reboot Recommended",
            "router_reboot_skipped": "Router Reboot Skipped",
        }
        severity = self.timeline.SEV_WARNING
        if event_type == "router_reboot" and result is not None:
            severity = self.timeline.SEV_SUCCESS if getattr(result, "internet_restored", False) else self.timeline.SEV_WARNING

        self.record_timeline_event(
            category=self.timeline.CAT_RECOVERY,
            title=title_map.get(event_type, "Router Recovery Event"),
            description=message,
            severity=severity,
            source="router_rebooter",
            metadata={"event_type": event_type},
        )

    def observe_vehicle_status(self, vehicle_status):
        """Record vehicle plug/charging state transitions for Home timeline."""
        if not isinstance(vehicle_status, dict):
            return

        plugged_in = vehicle_status.get("plugged_in")
        if plugged_in is None:
            plugged_in = vehicle_status.get("plug_state") == "Plugged In"

        charging = vehicle_status.get("charging")
        if charging is None:
            charging = vehicle_status.get("charging_state") == "Charging"

        if self._last_vehicle_plugged_in is None:
            self._last_vehicle_plugged_in = bool(plugged_in)
        elif bool(plugged_in) != self._last_vehicle_plugged_in:
            now_plugged = bool(plugged_in)
            self.record_timeline_event(
                category=self.timeline.CAT_VEHICLE,
                title="Vehicle Plug State Changed",
                description=(
                    "Vehicle is now plugged in."
                    if now_plugged
                    else "Vehicle is now unplugged."
                ),
                severity=self.timeline.SEV_INFO,
                source="vehicle",
                metadata={"plugged_in": now_plugged},
            )
            self._last_vehicle_plugged_in = now_plugged

        if self._last_vehicle_charging is None:
            self._last_vehicle_charging = bool(charging)
        elif bool(charging) != self._last_vehicle_charging:
            now_charging = bool(charging)
            self.record_timeline_event(
                category=self.timeline.CAT_VEHICLE,
                title="Vehicle Charging State Changed",
                description=(
                    "Vehicle charging started."
                    if now_charging
                    else "Vehicle charging stopped."
                ),
                severity=self.timeline.SEV_SUCCESS if now_charging else self.timeline.SEV_INFO,
                source="vehicle",
                metadata={"charging": now_charging},
            )
            self._last_vehicle_charging = now_charging

    def publish_solar_production_transition(self, was_producing, is_producing, raw_status=None):
        """Publish a single solar production transition event."""
        self.record_timeline_event(
            category=self.timeline.CAT_SOLAR,
            title="Solar Production State Changed",
            description=(
                "Solar production started (Producing)."
                if is_producing
                else "Solar production is now standby/not producing."
            ),
            severity=self.timeline.SEV_SUCCESS if is_producing else self.timeline.SEV_INFO,
            source="solar",
            metadata={
                "was_producing": bool(was_producing),
                "is_producing": bool(is_producing),
                "status": raw_status,
            },
        )

    def observe_solar_status(self, solar_status):
        """Record solar producing vs standby transitions only."""
        if not isinstance(solar_status, dict):
            return

        status_text = str(solar_status.get("status") or "").strip()
        normalized = status_text.lower()
        if not normalized:
            return

        if normalized == "producing":
            is_producing = True
        elif normalized in {"standby / night", "standby", "not producing"}:
            is_producing = False
        else:
            return

        if self._last_solar_producing is None:
            self._last_solar_producing = is_producing
            return

        if is_producing == self._last_solar_producing:
            return

        was_producing = self._last_solar_producing
        self._last_solar_producing = is_producing
        self.publish_solar_production_transition(
            was_producing=was_producing,
            is_producing=is_producing,
            raw_status=status_text,
        )

    def observe_lighting_status(self, lighting_status):
        """Record lighting device online/power transitions for Home timeline."""
        if not isinstance(lighting_status, dict):
            return

        lights = lighting_status.get("lights")
        if not isinstance(lights, list):
            return

        current = {}
        for light in lights:
            if not isinstance(light, dict):
                continue
            light_key = str(light.get("entity_id") or light.get("friendly_name") or "").strip()
            if not light_key:
                continue
            current[light_key] = {
                "name": str(light.get("friendly_name") or light.get("entity_id") or "Light"),
                "state": str(light.get("state") or "").strip().lower(),
            }

        for light_key, state in current.items():
            previous = self._last_lighting_device_state.get(light_key)
            if previous is None:
                continue

            previous_state = str(previous.get("state") or "")
            current_state = str(state.get("state") or "")
            if previous_state and current_state and previous_state != current_state:
                self.record_timeline_event(
                    category=self.timeline.CAT_LIGHTING,
                    title="Lighting Power State Changed",
                    description=f"{state.get('name')} changed state to {current_state}.",
                    severity=self.timeline.SEV_INFO,
                    source="lighting",
                    metadata={"light": state.get("name"), "state": current_state},
                )

        self._last_lighting_device_state = current

    def observe_garden_status(self, garden_status):
        """Record garden watering/rain-delay transitions for Home timeline."""
        if not isinstance(garden_status, dict):
            return

        current_zone = str(garden_status.get("active_watering_zone") or "").strip()
        if not current_zone:
            current_zone = None
        rain_delay_active = garden_status.get("rain_delay_active")
        if rain_delay_active not in (True, False):
            rain_delay_active = None

        if self._last_garden_watering_state is None:
            self._last_garden_watering_state = current_zone
        elif current_zone != self._last_garden_watering_state:
            if current_zone:
                self.record_timeline_event(
                    category=self.timeline.CAT_GARDEN,
                    title="Irrigation Watering Started",
                    description=f"Active watering zone: {current_zone}",
                    severity=self.timeline.SEV_INFO,
                    source="garden",
                    metadata={"active_watering_zone": current_zone},
                )
            elif self._last_garden_watering_state:
                self.record_timeline_event(
                    category=self.timeline.CAT_GARDEN,
                    title="Irrigation Watering Stopped",
                    description="No active watering zones.",
                    severity=self.timeline.SEV_SUCCESS,
                    source="garden",
                    metadata={"active_watering_zone": None},
                )
            self._last_garden_watering_state = current_zone

        if self._last_garden_rain_delay_state is None:
            self._last_garden_rain_delay_state = rain_delay_active
        elif rain_delay_active in (True, False) and rain_delay_active != self._last_garden_rain_delay_state:
            self.record_timeline_event(
                category=self.timeline.CAT_GARDEN,
                title="Irrigation Rain Delay Changed",
                description=("Rain delay enabled." if rain_delay_active else "Rain delay cleared."),
                severity=self.timeline.SEV_INFO,
                source="garden",
                metadata={"rain_delay_active": rain_delay_active, "rain_delay_until": garden_status.get("rain_delay_until")},
            )
            self._last_garden_rain_delay_state = rain_delay_active

    def normalize_custom_speedtest_times(self, raw_times):
        pieces = raw_times.replace(",", "\n").splitlines()
        normalized = []
        seen = set()
        for piece in pieces:
            value = piece.strip()
            if not value:
                continue
            time_value = self.normalize_clock_time(value)
            if time_value not in seen:
                normalized.append(time_value)
                seen.add(time_value)
        if not normalized:
            raise ValueError("Enter at least one custom time")
        return normalized

    def next_scheduled_speedtest(self, now=None):
        if not self.config.get("speedtest_schedule_enabled", default=True):
            return None

        now = now or datetime.now()
        for job in self.scheduler.jobs:
            if job["name"] == "Scheduled Speed Test" and job["type"] == "interval":
                last_run = job.get("last_run")
                if last_run is None:
                    return now
                return last_run + job["interval"]

        candidates = []
        for time_value in self.configured_speedtest_times():
            hour, minute = self.parse_clock_time(time_value)
            candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            candidates.append(candidate)

        if not candidates:
            return None
        return min(candidates)

    @classmethod
    def normalize_clock_time(cls, value):
        hour, minute = cls.parse_clock_time(value)
        return f"{hour:02d}:{minute:02d}"

    @staticmethod
    def parse_clock_time(value):
        if not isinstance(value, str) or ":" not in value:
            raise ValueError("expected HH:MM")
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("time must be between 00:00 and 23:59")
        return hour, minute

    def health_check(self):
        previous_status = self.status.get().get("internet", {}).get("status")
        result = self.network.check()
        now = str(datetime.now())
        self.status.update_internet(
            status=result.status,
            score=result.score,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            details=result.details,
            last_check=now,
        )
        self.db.add_health_check(
            timestamp=now,
            latency=result.latency,
            packet_loss=result.packet_loss,
            dns_ok=result.dns_ok,
            score=result.score,
            rebooted=0,
        )
        self.log.info(
            f"Internet Health: {result.status} | Score={result.score} | "
            f"Latency={result.latency}ms | PacketLoss={result.packet_loss}% | "
            f"DNS={result.dns_ok} | {result.details}"
        )
        self.publish_internet_status_change(
            previous_status=previous_status,
            current_status=result.status,
            details=result.details,
            score=result.score,
        )

    def daily_speed_test(self):
        result = self.speedtest.run()
        self.record_speedtest_result(result)

    def record_speedtest_result(self, result):
        status = "Unavailable" if result.failed else "Available"
        error = result.error_message or result.error
        self.status.update_speedtest(
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=result.server,
            last_run=result.timestamp,
            status=status,
            error=error,
            provider=result.provider,
            error_type=result.error_type,
        )
        self.db.add_speed_test(
            timestamp=result.timestamp,
            download=result.download,
            upload=result.upload,
            ping=result.ping,
            server=f"Speed test provider unavailable: {error}" if result.failed else result.server,
        )
        if result.failed:
            message = (
                f"Speed test provider unavailable"
                f" ({result.provider or 'unknown'}/{result.error_type or 'provider_error'}): {error}"
            )
            self.db.add_event(timestamp=result.timestamp, event_type="speed_test_failed", message=message)
        else:
            self.db.add_event(
                timestamp=result.timestamp,
                event_type="speed_test",
                message=f"Speed test complete: {result.download} down / {result.upload} up",
            )
        return result

    def maintenance_check(self):
        now = datetime.now()
        window_time = self.config.get("reboot_window_time", default="04:00")
        if not self.is_maintenance_window(now, window_time):
            self.log.info(f"Maintenance check skipped outside reboot window {window_time}")
            return

        reasons = self.reboot_recommendation_reasons()
        if not reasons:
            self.log.info("Maintenance check complete: reboot not recommended")
            self.db.add_event(
                timestamp=str(now),
                event_type="maintenance_check",
                message="No reboot recommended during maintenance window",
            )
            return

        recent_reboot = self.recent_router_reboot(now)
        if recent_reboot:
            message = (
                "Reboot recommendation skipped because router reboot cooldown is active. "
                f"Reasons: {'; '.join(reasons)}"
            )
            self.log.info(message)
            self.db.add_event(timestamp=str(now), event_type="router_reboot_skipped", message=message)
            return

        self.execute_router_reboot(now, reasons)

    def reboot_recommendation_reasons(self):
        reasons = []
        latest_speed = self.db.latest_speed_test()
        if latest_speed and self.speed_below_thresholds(latest_speed):
            reasons.append(
                "latest speed test below thresholds "
                f"({latest_speed['download']} down / {latest_speed['upload']} up)"
            )

        sustained_reason = self.sustained_health_problem()
        if sustained_reason:
            reasons.append(sustained_reason)

        return reasons

    def speed_below_thresholds(self, speed_result):
        minimum_download = self.config.get("minimum_download_mbps", default=100)
        minimum_upload = self.config.get("minimum_upload_mbps", default=10)
        download = speed_result.get("download")
        upload = speed_result.get("upload")
        return (
            download is not None
            and upload is not None
            and (download < minimum_download or upload < minimum_upload)
        )

    def sustained_health_problem(self):
        recent_checks = self.db.health_history(limit=6)
        if len(recent_checks) < 3:
            return None

        maximum_latency = self.config.get("maximum_latency_ms", default=100)
        maximum_packet_loss = self.config.get("thresholds", "packet_loss", default=5)
        poor_checks = [
            row for row in recent_checks
            if (
                row["latency"] is not None
                and row["latency"] > maximum_latency
            )
            or (
                row["packet_loss"] is not None
                and row["packet_loss"] > maximum_packet_loss
            )
        ]

        if len(poor_checks) >= 4:
            return (
                "latency or packet loss poor for sustained period "
                f"({len(poor_checks)} of {len(recent_checks)} recent checks)"
            )
        return None

    def recent_router_reboot(self, now):
        latest_reboot = self.latest_reboot_activity()
        if not latest_reboot:
            return None

        rebooted_at = self.parse_timestamp(latest_reboot["timestamp"])
        if not rebooted_at:
            return None

        cooldown_hours = self.config.get("reboot_cooldown_hours", default=24)
        if now - rebooted_at < timedelta(hours=cooldown_hours):
            return latest_reboot
        return None

    def latest_reboot_activity(self):
        events = [
            event for event in (
                self.db.latest_event("router_reboot"),
                self.db.latest_event("router_reboot_recommended"),
            )
            if event and self.parse_timestamp(event["timestamp"])
        ]
        if not events:
            return None
        return max(events, key=lambda event: self.parse_timestamp(event["timestamp"]))

    def recommend_router_reboot(self, now, reasons):
        message = (
            "Router reboot recommended during maintenance window. "
            "No reboot command was executed. "
            f"Reasons: {'; '.join(reasons)}"
        )
        self.log.warning(message)
        self.db.add_event(timestamp=str(now), event_type="router_reboot_recommended", message=message)
        self.publish_router_reboot_timeline("router_reboot_recommended", message)

    def execute_router_reboot(self, now, reasons):
        context = self.reboot_context(now, reasons)
        context["start_time"] = str(now)
        self.email_notifier.send_recovery_started(context)
        result = self.router_rebooter.execute(context["reason"])
        context["end_time"] = str(datetime.now())
        message = self.reboot_event_message(context, result)
        self.db.add_event(timestamp=str(now), event_type="router_reboot", message=message)
        self.log.warning(message)
        self.publish_router_reboot_timeline("router_reboot", message, result=result)
        self.email_notifier.send_reboot_notification(context, result)

    def reboot_context(self, now, reasons):
        latest_health = self.db.latest_health_check() or {}
        latest_speed = self.db.latest_speed_test() or {}
        return {
            "timestamp": str(now),
            "reason": "; ".join(reasons),
            "quality_score": latest_health.get("score", "Unavailable"),
            "download": self.metric_text(latest_speed.get("download"), "Mbps"),
            "upload": self.metric_text(latest_speed.get("upload"), "Mbps"),
            "latency": self.metric_text(latest_health.get("latency"), "ms"),
            "packet_loss": self.metric_text(latest_health.get("packet_loss"), "%"),
            "failed_checks": self.failed_check_count(),
            "last_successful_speedtest": self.last_successful_speedtest_text(latest_speed),
            "maintenance_window": self.config.get("reboot_window_time", default="04:00"),
        }

    def reboot_event_message(self, context, result):
        return (
            f"Router reboot {result.method}: {result.result}. "
            f"Reason: {context['reason']}. "
            f"Quality={context['quality_score']}; "
            f"Download={context['download']}; Upload={context['upload']}; "
            f"Latency={context['latency']}; PacketLoss={context['packet_loss']}; "
            f"FailedChecks={context['failed_checks']}; "
            f"CommandSent={result.command_sent}; RouterResponded={result.router_responded}; "
            f"InternetRestored={result.internet_restored}; Recovery={result.elapsed_recovery_time}"
        )

    def failed_check_count(self):
        maximum_latency = self.config.get("maximum_latency_ms", default=100)
        maximum_packet_loss = self.config.get("thresholds", "packet_loss", default=5)
        failed = 0
        for row in self.db.health_history(limit=6):
            if (
                row["score"] is not None and row["score"] < 60
            ) or (
                row["latency"] is not None and row["latency"] > maximum_latency
            ) or (
                row["packet_loss"] is not None and row["packet_loss"] > maximum_packet_loss
            ) or row["dns_ok"] is False:
                failed += 1
        return failed

    @staticmethod
    def metric_text(value, unit):
        if value is None:
            return "Unavailable"
        return f"{value} {unit}"

    @staticmethod
    def last_successful_speedtest_text(latest_speed):
        if not latest_speed:
            return "Unavailable"
        timestamp = latest_speed.get("timestamp", "Unknown time")
        download = latest_speed.get("download")
        upload = latest_speed.get("upload")
        if download is None or upload is None:
            return "Unavailable"
        return f"{timestamp} ({download} Mbps down / {upload} Mbps up)"

    @classmethod
    def is_maintenance_window(cls, now, window_time):
        hour, minute = cls.parse_clock_time(window_time)
        return now.hour == hour and now.minute >= minute

    @staticmethod
    def parse_timestamp(value):
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def internet_intelligence(self):
        try:
            now = datetime.now()
            since = now - timedelta(days=30)
            since_text = since.isoformat()  # Use ISO format for consistency
            
            health_rows = self.db.health_history_since(since_text)
            speed_rows = self.db.speed_tests_since(since_text)
            reboot_events = self.db.events_since(since_text, "router_reboot")
            latest_speed = self.db.latest_speed_test()

            quality_score = self.internet_quality_score(health_rows, latest_speed)
            reliability = self.reliability_summary(health_rows, reboot_events)
            grade = self.isp_grade(quality_score)
            trend = self.reliability_trend(health_rows)
            recommendations = self.internet_recommendations(
                health_rows=health_rows,
                speed_rows=speed_rows,
                latest_speed=latest_speed,
                reliability=reliability,
                quality_score=quality_score,
                trend=trend,
            )

            return {
                "quality_score": quality_score,
                "isp_grade": grade,
                "trend": trend,
                "reliability": reliability,
                "recommendations": recommendations,
                "sample_count": len(health_rows),
            }
        except Exception as exc:
            self.log.exception(f"Internet intelligence computation failed: {exc}")
            return {
                "quality_score": None,
                "isp_grade": "Unknown",
                "trend": "Insufficient data",
                "reliability": {
                    "uptime_percent": None,
                    "outages": 0,
                    "longest_outage": "No data",
                    "router_reboots": 0,
                },
                "recommendations": [],
                "sample_count": 0,
            }

    def internet_quality_score(self, health_rows, latest_speed):
        health_scores = [row["score"] for row in health_rows if row["score"] is not None]
        if health_scores:
            health_score = mean(health_scores)
        else:
            current = self.status.get()["internet"].get("score")
            health_score = current if current is not None else None

        speed_score = self.speed_quality_score(latest_speed)
        if health_score is None and speed_score is None:
            return None
        if health_score is None:
            return round(speed_score)
        if speed_score is None:
            return round(health_score)
        return round((health_score * 0.75) + (speed_score * 0.25))

    def speed_quality_score(self, latest_speed):
        if not latest_speed:
            return None
        minimum_download = self.config.get("minimum_download_mbps", default=100)
        minimum_upload = self.config.get("minimum_upload_mbps", default=10)
        download = latest_speed.get("download")
        upload = latest_speed.get("upload")
        if download is None or upload is None:
            return None
        download_score = min(download / minimum_download * 100, 100) if minimum_download else 100
        upload_score = min(upload / minimum_upload * 100, 100) if minimum_upload else 100
        return max(0, min(100, (download_score * 0.65) + (upload_score * 0.35)))

    def reliability_summary(self, health_rows, reboot_events):
        if not health_rows:
            return {
                "uptime_percent": None,
                "outages": 0,
                "longest_outage": "No data",
                "router_reboots": len(reboot_events),
            }

        total = len(health_rows)
        outage_flags = [self.is_outage_row(row) for row in health_rows]
        outage_samples = sum(1 for flag in outage_flags if flag)
        uptime_percent = round((total - outage_samples) / total * 100, 2)

        outages = 0
        longest_run = 0
        current_run = 0
        for is_outage in outage_flags:
            if is_outage:
                current_run += 1
                if current_run == 1:
                    outages += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0

        interval = self.config.get("monitor_interval_minutes", default=5)
        longest_minutes = longest_run * interval
        return {
            "uptime_percent": uptime_percent,
            "outages": outages,
            "longest_outage": self.format_duration(longest_minutes),
            "router_reboots": len(reboot_events),
        }

    @staticmethod
    def format_duration(minutes):
        if minutes <= 0:
            return "0 min"
        hours = minutes // 60
        remaining = minutes % 60
        if hours and remaining:
            return f"{hours}h {remaining}m"
        if hours:
            return f"{hours}h"
        return f"{minutes} min"

    @staticmethod
    def is_outage_row(row):
        return (
            row["score"] is not None and row["score"] < 60
        ) or (
            row["latency"] is not None and row["latency"] >= 999
        ) or (
            row["packet_loss"] is not None and row["packet_loss"] >= 100
        ) or row["dns_ok"] is False

    @staticmethod
    def isp_grade(score):
        if score is None:
            return "Collecting Data"
        if score >= 90:
            return "Excellent"
        if score >= 75:
            return "Good"
        if score >= 60:
            return "Fair"
        return "Poor"

    def reliability_trend(self, health_rows):
        if len(health_rows) < 6:
            return "Collecting Data"
        midpoint = len(health_rows) // 2
        early = [row["score"] for row in health_rows[:midpoint] if row["score"] is not None]
        recent = [row["score"] for row in health_rows[midpoint:] if row["score"] is not None]
        if not early or not recent:
            return "Collecting Data"
        delta = mean(recent) - mean(early)
        if delta > 3:
            return "Improving"
        if delta < -3:
            return "Declining"
        return "Stable"

    def internet_recommendations(self, health_rows, speed_rows, latest_speed, reliability, quality_score, trend):
        recommendations = []
        maximum_latency = self.config.get("maximum_latency_ms", default=100)
        minimum_download = self.config.get("minimum_download_mbps", default=100)
        minimum_upload = self.config.get("minimum_upload_mbps", default=10)

        if not health_rows:
            return [f"Keep {APP_NAME} running to build a 30-day reliability baseline."]

        latencies = [row["latency"] for row in health_rows if row["latency"] is not None]
        packet_losses = [row["packet_loss"] for row in health_rows if row["packet_loss"] is not None]

        if reliability["uptime_percent"] is not None and reliability["uptime_percent"] < 99:
            recommendations.append("Reliability is below 99%; review outage timing before contacting the ISP.")
        if reliability["outages"] > 0:
            recommendations.append(f"{reliability['outages']} outage window(s) were detected in the last 30 days.")
        if latencies and mean(latencies) > maximum_latency:
            recommendations.append("Average latency is above the configured threshold.")
        if packet_losses and mean(packet_losses) > self.config.get("thresholds", "packet_loss", default=5):
            recommendations.append("Packet loss is elevated across recent health checks.")
        if latest_speed and self.speed_below_thresholds(latest_speed):
            recommendations.append(
                f"Latest speed test is below threshold ({minimum_download} down / {minimum_upload} up)."
            )
        if reliability["router_reboots"] > 0:
            recommendations.append("Router reboot events exist in the 30-day window; compare them with outage timing.")
        if trend == "Declining":
            recommendations.append("Reliability trend is declining; watch the next few scheduled checks closely.")
        if not speed_rows:
            recommendations.append("No speed tests are available in the 30-day window yet.")
        if quality_score is not None and quality_score >= 90 and not recommendations:
            recommendations.append("Internet quality is strong; no action is recommended right now.")

        return recommendations[:5]

    def history_summary(self):
        now = datetime.now()
        since = now - timedelta(hours=24)
        since_text = str(since)
        health_rows = self.db.health_history_since(since_text)
        speed_rows = self.db.speed_tests_since(since_text)
        events = self.db.events_since(since_text)
        reboot_events = [
            event for event in events
            if event["event_type"] in ("router_reboot", "router_reboot_recommended", "router_reboot_skipped")
        ]
        outage_runs = self.outage_runs(health_rows)
        latencies = [row["latency"] for row in health_rows if row["latency"] is not None]
        scores = [row["score"] for row in health_rows if row["score"] is not None]
        downloads = [row["download"] for row in speed_rows if row["download"] is not None]
        uploads = [row["upload"] for row in speed_rows if row["upload"] is not None]

        return {
            "health_rows": health_rows,
            "speed_tests": list(reversed(speed_rows[-10:])),
            "events": list(reversed((reboot_events + self.outage_events_from_runs(outage_runs))[-10:])),
            "outage_reboot_history": list(reversed((reboot_events + self.outage_events_from_runs(outage_runs))[-20:])),
            "quality_average": round(mean(scores), 1) if scores else None,
            "average_latency": round(mean(latencies), 1) if latencies else None,
            "maximum_latency": round(max(latencies), 1) if latencies else None,
            "average_download": round(mean(downloads), 1) if downloads else None,
            "average_upload": round(mean(uploads), 1) if uploads else None,
            "quality_trend": self.reliability_trend(health_rows),
            "average_quality": round(mean(scores), 1) if scores else None,
            "outage_count": len(outage_runs),
            "router_reboot_count": len(reboot_events),
            "charts": {
                "speed": {
                    "labels": [self.short_time(row["timestamp"]) for row in speed_rows],
                    "download": [row["download"] for row in speed_rows],
                    "upload": [row["upload"] for row in speed_rows],
                    "latency": [row["ping"] for row in speed_rows],
                },
                "quality": {
                    "labels": [self.short_time(row["timestamp"]) for row in health_rows],
                    "values": [row["score"] for row in health_rows],
                },
                "latency": {
                    "labels": [self.short_time(row["timestamp"]) for row in health_rows],
                    "values": [row["latency"] for row in health_rows],
                },
            },
        }

    def report_summary(self):
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        since_text = str(month_start)
        health_rows = self.db.health_history_since(since_text)
        speed_rows = self.db.speed_tests_since(since_text)
        reboot_events = self.db.events_since(since_text, "router_reboot")
        reliability = self.reliability_summary(health_rows, reboot_events)
        latencies = [row["latency"] for row in health_rows if row["latency"] is not None]
        downloads = [row["download"] for row in speed_rows if row["download"] is not None]
        uploads = [row["upload"] for row in speed_rows if row["upload"] is not None]
        quality_score = self.internet_quality_score(health_rows, self.db.latest_speed_test())

        return {
            "month_label": month_start.strftime("%B %Y"),
            "uptime_percent": reliability["uptime_percent"],
            "average_latency": round(mean(latencies), 1) if latencies else None,
            "average_download": round(mean(downloads), 1) if downloads else None,
            "average_upload": round(mean(uploads), 1) if uploads else None,
            "outage_count": reliability["outages"],
            "router_reboot_count": reliability["router_reboots"],
            "isp_grade": self.isp_grade(quality_score),
            "sample_count": len(health_rows),
            "speedtest_count": len(speed_rows),
        }

    def outage_runs(self, health_rows):
        runs = []
        current = []
        for row in health_rows:
            if self.is_outage_row(row):
                current.append(row)
            elif current:
                runs.append(current)
                current = []
        if current:
            runs.append(current)
        return runs

    def outage_events_from_runs(self, outage_runs):
        return [
            {
                "timestamp": run[0]["timestamp"],
                "event_type": "outage",
                "message": f"Internet quality outage detected across {len(run)} sample(s)",
            }
            for run in outage_runs[-10:]
        ]

    @staticmethod
    def short_time(timestamp):
        if not timestamp:
            return ""
        if len(timestamp) >= 16:
            return timestamp[5:16]
        return timestamp

    def start_dashboard(self):
        check_dashboard_port(self.config, self.log)
        dashboard = Dashboard(self)
        dashboard_thread = threading.Thread(target=dashboard.run, daemon=True)
        dashboard_thread.start()
        self.log.info("Dashboard started on http://localhost:8080")

    def start(self):
        self.initialize()
        if self.config.get("dashboard", "enabled"):
            self.start_dashboard()
        self.scheduler.run_forever(sleep_seconds=10)

    def request_restart(self, delay_seconds=2):
        """Request a restart using only Windows Task Scheduler."""
        timestamp = str(datetime.now())
        message = f"{APP_NAME} restart requested from Lab"
        detail = f"{message} | timestamp={timestamp} | pid={os.getpid()} | argv={list(sys.argv)}"
        
        # Check if the scheduled task exists
        task_status = self.scheduled_task_status()
        if not task_status["exists"]:
            error_msg = f"HomePulse scheduled task '{self._scheduled_task_name}' not found on this system"
            self.log.error(error_msg)
            self.db.add_event(timestamp=str(datetime.now()), event_type="system_restart_rejected", message=error_msg)
            raise RuntimeError(error_msg)
        
        self._last_restart_method = None
        self.log.warning(detail)
        self.db.add_event(timestamp=str(datetime.now()), event_type="system_restart_requested", message=message)
        self.write_restart_marker("restart_requested.json", {
            "timestamp": timestamp,
            "pid": os.getpid(),
            "argv": list(sys.argv),
            "executable": sys.executable,
            "working_directory": os.getcwd(),
            "delay_seconds": delay_seconds,
            "restart_method": "Task Scheduler",
        })
        self.log.warning(
            f"{APP_NAME} restart scheduled via Task Scheduler | timestamp={datetime.now()} | pid={os.getpid()} | "
            f"delay_seconds={delay_seconds} | task_name={self._scheduled_task_name}"
        )
        thread = threading.Thread(target=self._delayed_restart, args=(delay_seconds,), daemon=True)
        thread.start()
        return f"{message}; restart scheduled in {delay_seconds} seconds using Task Scheduler."

    def request_shutdown(self, delay_seconds=2):
        timestamp = str(datetime.now())
        message = f"{APP_NAME} shutdown requested from Lab"
        self.log.warning(
            f"{message} | timestamp={timestamp} | pid={os.getpid()} | argv={list(sys.argv)}"
        )
        self.db.add_event(timestamp=str(datetime.now()), event_type="system_shutdown_requested", message=message)
        thread = threading.Thread(target=self._delayed_shutdown, args=(delay_seconds,), daemon=True)
        thread.start()
        return f"{message}; shutdown scheduled in {delay_seconds} seconds."

    def _delayed_restart(self, delay_seconds):
        """Execute restart using Windows Task Scheduler only."""
        time.sleep(delay_seconds)
        try:
            self.log.warning(
                f"{APP_NAME} restart execution | timestamp={datetime.now()} | pid={os.getpid()}"
            )
            self.db.add_event(
                timestamp=str(datetime.now()),
                event_type="system_restart_attempt",
                message=f"Restarting process {os.getpid()} via Task Scheduler",
            )

            # Use Task Scheduler to restart the application
            self.log.warning(f"Executing: schtasks /Run /TN {self._scheduled_task_name}")
            try:
                completed = subprocess.run(
                    ["schtasks", "/Run", "/TN", self._scheduled_task_name],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            except FileNotFoundError:
                self.log.error("schtasks.exe not found on this system")
                self.db.add_event(
                    timestamp=str(datetime.now()),
                    event_type="system_restart_failed",
                    message="schtasks.exe not found; cannot execute restart",
                )
                os._exit(1)
            except subprocess.TimeoutExpired:
                self.log.error("schtasks command timed out")
                self.db.add_event(
                    timestamp=str(datetime.now()),
                    event_type="system_restart_failed",
                    message="schtasks command timed out",
                )
                os._exit(1)

            # Log the result
            self.log.warning(f"Task Scheduler return code: {completed.returncode}")
            if completed.stdout:
                self.log.warning(f"stdout: {completed.stdout.strip()}")
            if completed.stderr:
                self.log.warning(f"stderr: {completed.stderr.strip()}")

            if completed.returncode == 0:
                self._last_restart_method = "Task Scheduler"
                self.log.warning(
                    f"{APP_NAME} exiting current process for Task Scheduler restart | "
                    f"wait_seconds={self._restart_exit_delay_seconds}"
                )
                self.db.add_event(
                    timestamp=str(datetime.now()),
                    event_type="system_restart_success",
                    message=f"Task Scheduler restart initiated; exiting process {os.getpid()}",
                )
                time.sleep(self._restart_exit_delay_seconds)
                os._exit(0)
            else:
                self.log.error(f"Task Scheduler restart failed with code {completed.returncode}")
                self.db.add_event(
                    timestamp=str(datetime.now()),
                    event_type="system_restart_failed",
                    message=f"Task Scheduler restart command failed with code {completed.returncode}",
                )
                os._exit(1)

        except Exception as exc:
            self.log.exception(f"{APP_NAME} restart failed: {exc}")
            self.db.add_event(
                timestamp=str(datetime.now()),
                event_type="system_restart_failed",
                message=f"Restart exception: {exc}",
            )
            os._exit(1)

    def _delayed_shutdown(self, delay_seconds):
        time.sleep(delay_seconds)
        self.log.warning(
            f"{APP_NAME} process exiting for shutdown | timestamp={datetime.now()} | pid={os.getpid()}"
        )
        os._exit(0)

    def scheduled_task_status(self):
        task_name = getattr(self, "_scheduled_task_name", "HomePulse")
        if os.name != "nt":
            return {
                "exists": False,
                "last_result": None,
                "preferred_restart_method": "Batch launcher",
                "task_name": task_name,
            }

        try:
            completed = subprocess.run(
                ["schtasks", "/Query", "/TN", task_name, "/FO", "LIST"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return {
                "exists": False,
                "last_result": None,
                "preferred_restart_method": "Batch launcher",
                "task_name": task_name,
            }

        output = "\n".join([completed.stdout or "", completed.stderr or ""]).strip()
        exists = completed.returncode == 0 and task_name.lower() in output.lower()
        last_result = None
        if exists:
            match = re.search(r"Last Result:\s*(.+)", output, re.IGNORECASE)
            if match:
                last_result = match.group(1).strip()
        return {
            "exists": exists,
            "last_result": last_result,
            "preferred_restart_method": "Task Scheduler" if exists else "Batch launcher",
            "task_name": task_name,
        }

    def spawn_restart_launcher(self):
        launcher = Path("scripts/start_homepulse.bat").resolve()
        if not launcher.exists():
            return False
        command = f'timeout /t 2 /nobreak >nul & "{launcher}"'
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["cmd.exe", "/c", command],
            cwd=str(Path.cwd()),
            creationflags=flags,
            close_fds=True,
        )
        self.log.warning(
            f"{APP_NAME} detached restart launcher spawned | timestamp={datetime.now()} | "
            f"pid={os.getpid()} | launcher={launcher}"
        )
        return True

    @staticmethod
    def marker_path(filename):
        return Path("logs") / filename

    def write_restart_marker(self, filename, payload):
        try:
            Path("logs").mkdir(exist_ok=True)
            payload = dict(payload)
            payload["app_name"] = APP_NAME
            payload["version"] = APP_VERSION
            self.marker_path(filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log.warning(f"Could not write restart marker {filename}: {exc}")

    def latest_restart_request(self):
        marker = self.marker_path("restart_requested.json")
        if marker.exists():
            try:
                return json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"error": "restart marker could not be read"}
        return None
