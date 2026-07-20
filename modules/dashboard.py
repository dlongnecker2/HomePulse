import ctypes
import os
import secrets
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, redirect, render_template, request, url_for, jsonify
from markupsafe import Markup, escape
from werkzeug.exceptions import RequestEntityTooLarge

from version import APP_AUTHOR, APP_COPYRIGHT, APP_NAME, APP_VERSION


class Dashboard:
    def __init__(self, application):
        self.application = application
        self.app = Flask(
            __name__,
            template_folder="../templates",
            static_folder="../static",
        )
        self.app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
        self.app.jinja_env.globals["app_name"] = APP_NAME
        self.app.jinja_env.globals["app_version"] = APP_VERSION
        self.app.jinja_env.globals["app_author"] = APP_AUTHOR
        self.app.jinja_env.globals["app_copyright"] = APP_COPYRIGHT
        self.app.jinja_env.globals["render_test_button"] = self.render_test_button
        self.admin_action_token = secrets.token_urlsafe(32)
        self.register_routes()

    def _dashboard_payload(self):
        status = self.application.status.get()
        last_reboot = self.application.db.latest_event("router_reboot")
        if last_reboot:
            status["router"]["last_reboot"] = last_reboot["timestamp"]
        next_speedtest = self.application.next_scheduled_speedtest()
        status["speedtest"]["next_run"] = str(next_speedtest) if next_speedtest else None
        status["speedtest"]["schedule_label"] = self.application.speedtest_schedule_label()
        status["intelligence"] = self.application.internet_intelligence()
        status["events"] = self.application.db.recent_events(limit=5)
        status["dashboard_widgets"] = self.application.plugin_manager.widget_registry.all()
        # NOTE: Insights are NOT generated here to avoid blocking /api/status.
        # Insights are fetched by the frontend via /api/insights/status endpoint separately.
        status["insights"] = []
        return status

    def register_routes(self):
        @self.app.route("/")
        def home():
            status = self._dashboard_payload()
            return render_template(
                "dashboard.html",
                config=self.application.config,
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                router=status["router"],
                system=status["system"],
                intelligence=status["intelligence"],
                events=status["events"],
                widgets=status["dashboard_widgets"],
                insights=status["insights"],
                now=datetime.now(),
            )

        @self.app.route("/home")
        def home_center():
            return render_template(
                "home.html",
                widgets=self.application.plugin_manager.widget_registry.all(),
                devices=self.application.plugin_manager.device_registry.all(),
                now=datetime.now(),
            )

        @self.app.route("/environment")
        def environment_center():
            return render_template(
                "environment.html",
                environment=self.application.environment.status_payload(),
                now=datetime.now(),
            )

        @self.app.route("/internet")
        def internet():
            status = self._dashboard_payload()
            return render_template(
                "internet.html",
                config=self.application.config,
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                router=status["router"],
                intelligence=status["intelligence"],
                now=datetime.now(),
            )

        @self.app.route("/energy")
        def energy_center():
            return render_template("energy.html", now=datetime.now())

        @self.app.route("/solar")
        def solar():
            return render_template(
                "solar.html",
                solar=self.application.solar.solar_config(),
                now=datetime.now(),
            )

        @self.app.route("/vehicle")
        def vehicle_center():
            return render_template("vehicle.html", now=datetime.now())

        @self.app.route("/weather")
        def weather():
            return render_template("weather.html", now=datetime.now())

        @self.app.route("/lighting")
        def lighting():
            return render_template("lighting.html", now=datetime.now())

        @self.app.route("/garden")
        def garden():
            return render_template("garden.html", now=datetime.now())

        @self.app.route("/weight-progress")
        def weight_progress():
            return render_template(
                "weight_progress.html",
                weight_progress=self.application.weight_progress.view_model(include_live=True),
                now=datetime.now(),
            )

        @self.app.route("/api/weight-progress/import/preview", methods=["POST"])
        def api_weight_progress_import_preview():
            try:
                upload = request.files.get("workbook")
                result = self.application.weight_progress.preview_weight_history_import(upload)
                return jsonify({"ok": True, "preview": result, "timestamp": str(datetime.now())})
            except RequestEntityTooLarge:
                return jsonify({"ok": False, "error": "Upload exceeds the allowed size limit."}), 413
            except Exception as exc:
                self.application.log.exception(f"Weight Progress import preview failed: {exc}")
                return jsonify({"ok": False, "error": str(exc), "timestamp": str(datetime.now())}), 400

        @self.app.route("/api/weight-progress/import", methods=["POST"])
        def api_weight_progress_import():
            try:
                payload = request.get_json(silent=True) or request.form.to_dict()
                result = self.application.weight_progress.confirm_weight_history_import(payload.get("preview_token"))
                result["timestamp"] = str(datetime.now())
                return jsonify(result)
            except RequestEntityTooLarge:
                return jsonify({"ok": False, "error": "Upload exceeds the allowed size limit."}), 413
            except Exception as exc:
                self.application.log.exception(f"Weight Progress import failed: {exc}")
                return jsonify({"ok": False, "error": str(exc), "timestamp": str(datetime.now())}), 400

        @self.app.route("/api/weight-progress/import/cancel", methods=["POST"])
        def api_weight_progress_import_cancel():
            try:
                payload = request.get_json(silent=True) or request.form.to_dict()
                result = self.application.weight_progress.cancel_weight_history_import(payload.get("preview_token"))
                result["timestamp"] = str(datetime.now())
                return jsonify(result)
            except Exception as exc:
                self.application.log.exception(f"Weight Progress import cancel failed: {exc}")
                return jsonify({"ok": False, "error": str(exc), "timestamp": str(datetime.now())}), 400

        @self.app.route("/speed-test")
        def speed_test_center():
            status = self._dashboard_payload()
            return render_template(
                "speed_test.html",
                status=status,
                speedtest=status["speedtest"],
                now=datetime.now(),
            )

        @self.app.route("/email")
        def email_center():
            return render_template(
                "email.html",
                email=self.application.config.get("email", default={}),
                email_status=self._email_center_status(),
                solar_alerts=self.application.solar_alert_settings(),
                now=datetime.now(),
            )

        @self.app.route("/api/email/notification-settings", methods=["GET", "POST"])
        def api_email_notification_settings():
            try:
                if request.method == "POST":
                    payload = request.get_json(silent=True) or request.form.to_dict()
                    settings = self.application.update_solar_alert_settings(payload)
                    return jsonify({
                        "ok": True,
                        "solar_alerts": settings,
                        "timestamp": str(datetime.now()),
                    })

                return jsonify({
                    "ok": True,
                    "solar_alerts": self.application.solar_alert_settings(),
                    "email_notifications_enabled": self.application.config.get("email", "email_notifications_enabled", default=False),
                    "timestamp": str(datetime.now()),
                })
            except Exception as exc:
                self.application.log.exception(f"Email notification settings API failed: {exc}")
                return jsonify({
                    "ok": False,
                    "error": str(exc),
                    "timestamp": str(datetime.now()),
                }), 500

        @self.app.route("/about")
        def about():
            status = self._dashboard_payload()
            return render_template(
                "about.html",
                about=self._lab_about(status),
                overview=self._lab_overview(status),
                now=datetime.now(),
            )

        @self.app.route("/history")
        def history():
            status = self._dashboard_payload()
            return render_template(
                "history.html",
                status=status,
                history=self.application.history_summary(),
                now=datetime.now(),
            )

        @self.app.route("/reports")
        def reports():
            status = self._dashboard_payload()
            return render_template(
                "reports.html",
                status=status,
                report=self.application.report_summary(),
                now=datetime.now(),
            )

        @self.app.route("/settings", methods=["GET", "POST"])
        def settings():
            error = None
            if request.method == "POST":
                try:
                    self.application.update_settings(request.form)
                    return redirect(url_for("settings", saved="1"))
                except ValueError as exc:
                    error = str(exc)

            router_recovery = self.application.normalized_router_recovery()
            weight_progress = self.application.weight_progress.weight_progress_config()
            return render_template(
                "settings.html",
                config=self.application.config,
                schedule_mode=self.application.speedtest_schedule_mode(),
                schedule_label=self.application.speedtest_schedule_label(),
                speedtest_times=self.application.configured_speedtest_times(),
                router_reboot=self.application.config.get("router_reboot", default={}),
                router_recovery_config=router_recovery,
                email=self.application.config.get("email", default={}),
                energy=self.application.energy.energy_config(),
                vehicle=self.application.vehicle.vehicle_config(),
                solar=self.application.solar.solar_config(),
                weather=self.application.weather.weather_config(),
                lighting=self.application.lighting.lighting_config(),
                garden=self.application.garden.garden_config(),
                weight_progress=weight_progress,
                diagnostic_result=self.application.diagnostics.latest_result(),
                router_recovery_status=self.application.router_recovery_summary(
                    recovery=router_recovery,
                    include_live_state=True,
                ),
                error=error,
                saved=request.args.get("saved") == "1",
                now=datetime.now(),
            )

        @self.app.route("/dev")
        def dev():
            status = self._dashboard_payload()
            return render_template(
                "dev.html",
                status=status,
                internet=status["internet"],
                speedtest=status["speedtest"],
                now=datetime.now(),
            )

        @self.app.route("/dev/run-health-check", methods=["POST"])
        def run_health_check():
            self.application.health_check()
            return redirect(url_for("dev"))

        @self.app.route("/dev/run-speedtest", methods=["POST"])
        def run_speedtest():
            self.application.daily_speed_test()
            return redirect(url_for("dev"))

        @self.app.route("/lab")
        def lab():
            return render_template(
                "lab.html",
                lab=self._lab_payload(),
                message=request.args.get("message"),
                admin_action_token=self.admin_action_token,
                now=datetime.now(),
            )

        @self.app.route("/lab/action", methods=["POST"])
        def lab_action():
            action = request.form.get("action")
            actions = {
                "run_ping": ("Ping check completed", self.application.health_check),
                "run_speedtest": ("Speed test completed", self.application.daily_speed_test),
                "run_maintenance": ("Maintenance check completed", self.application.maintenance_check),
                "reload_config": ("Configuration reloaded", self.application.reload_configuration),
            }
            label, function = actions.get(action, ("Unknown Lab action", None))
            if function:
                try:
                    function()
                except Exception as exc:
                    self.application.log.exception(f"Lab action failed: {action} - {exc}")
                    label = f"Lab action failed: {exc}"
            return redirect(url_for("lab", message=label))

        @self.app.route("/logs")
        def logs():
            log_file = Path("logs/routermonitor.log")
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                recent = lines[-150:]
            else:
                recent = ["No log file found."]
            return render_template("logs.html", lines=recent, now=datetime.now())

        @self.app.route("/api/status")
        def api_status():
            import time
            start_time = time.time()
            self.application.log.debug("[/api/status] Route started")
            
            try:
                status = self._dashboard_payload()
                internet = status["internet"]
                speedtest = status["speedtest"]
                router = status["router"]
                system = status["system"]
                intelligence = status["intelligence"]
                
                response = jsonify({
                    "version": status["version"],
                    "internet_status": internet["status"],
                    "health_score": intelligence["quality_score"],
                    "internet_quality_score": intelligence["quality_score"],
                    "isp_grade": intelligence["isp_grade"],
                    "reliability_trend": intelligence["trend"],
                    "latest_latency_ms": internet["latency"],
                    "packet_loss": internet["packet_loss"],
                    "dns_ok": internet["dns_ok"],
                    "internet_details": internet["details"],
                    "last_check": internet["last_check"],
                    "download": speedtest["download"],
                    "upload": speedtest["upload"],
                    "speedtest_ping": speedtest["ping"],
                    "speedtest_server": speedtest["server"],
                    "speedtest_status": speedtest.get("status", "Unavailable"),
                    "speedtest_error": speedtest.get("error", ""),
                    "speedtest_provider": speedtest.get("provider", ""),
                    "speedtest_error_type": speedtest.get("error_type", ""),
                    "last_speedtest": speedtest["last_run"],
                    "next_speedtest": speedtest.get("next_run"),
                    "speedtest_schedule_label": speedtest.get("schedule_label"),
                    "router_status": router.get("status", "Monitoring"),
                    "last_reboot": router.get("last_reboot"),
                    "started_at": system["started_at"],
                    "last_update": system["last_update"],
                    "timestamp": str(datetime.now()),
                })
                
                elapsed_ms = (time.time() - start_time) * 1000
                self.application.log.debug(f"[/api/status] Route completed in {elapsed_ms:.2f}ms")
                return response
            except Exception as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                self.application.log.exception(f"[/api/status] Route failed after {elapsed_ms:.2f}ms: {exc}")
                return jsonify({
                    "error": str(exc),
                    "timestamp": str(datetime.now()),
                }), 500

        @self.app.route("/api/system/status")
        def api_system_status():
            try:
                return jsonify(self.application.process_identity())
            except Exception as exc:
                self.application.log.exception(f"System status API failed: {exc}")
                return jsonify({
                    "app_name": APP_NAME,
                    "version": APP_VERSION,
                    "pid": os.getpid(),
                    "started_at": None,
                    "uptime_seconds": None,
                    "executable": sys.executable,
                    "argv": list(sys.argv),
                    "working_directory": os.getcwd(),
                    "restart_supported": False,
                    "error": str(exc),
                }), 500

        @self.app.route("/api/system/restart", methods=["POST"])
        def api_system_restart():
            if not self._valid_admin_action_request():
                return self._admin_action_forbidden()
            
            # Restart functionality is disabled due to reliability issues on Windows.
            # The app stops but does not reliably restart, leaving HomePulse down.
            # Users should stop the app and manually restart via Task Scheduler or command line.
            self.application.log.warning("[/api/system/restart] Restart endpoint called but is disabled for safety")
            
            return jsonify({
                "ok": False,
                "message": "Restart is disabled for safety. The in-app restart feature does not reliably bring the application back up on Windows.",
                "instructions": {
                    "step_1": "Stop HomePulse using the Stop button",
                    "step_2": "Wait for shutdown to complete",
                    "step_3": "Start HomePulse using one of these methods:",
                    "methods": [
                        "Task Scheduler: Open Task Scheduler, find 'HomePulse', right-click and select 'Run'",
                        "PowerShell: cd C:\\RouterMonitorV2 && python router_monitor.py",
                        "Command Prompt: cd C:\\RouterMonitorV2 && python router_monitor.py",
                        "Batch file: Double-click C:\\RouterMonitorV2\\start_monitor.bat"
                    ]
                },
                "timestamp": str(datetime.now()),
            }), 503

        @self.app.route("/api/system/shutdown", methods=["POST"])
        def api_system_shutdown():
            if not self._valid_admin_action_request():
                return self._admin_action_forbidden()
            try:
                message = self.application.request_shutdown(delay_seconds=2)
                return jsonify({
                    "ok": True,
                    "status": "shutdown_scheduled",
                    "message": message,
                    "warning": "HomePulse has no built-in login; this admin action requires the Lab page token.",
                    "timestamp": str(datetime.now()),
                })
            except Exception as exc:
                self.application.log.exception(f"System shutdown request failed: {exc}")
                return jsonify({
                    "ok": False,
                    "status": "shutdown_failed",
                    "message": f"Shutdown could not be scheduled: {exc}",
                    "timestamp": str(datetime.now()),
                }), 500

        @self.app.route("/api/home/status")
        def api_home_status():
            try:
                return jsonify(self._home_status_payload())
            except Exception as exc:
                self.application.log.exception(f"Home Center API failed: {exc}")
                return jsonify({
                    "overall_status": "Attention",
                    "last_updated": str(datetime.now()),
                    "error": str(exc),
                    "internet": {},
                    "solar": {},
                    "energy": {},
                    "vehicle": {},
                    "weather": {},
                    "lighting": self._lighting_placeholder(),
                    "garden": self._garden_placeholder(),
                    "home": self._home_placeholder(alerts=["Home Center status unavailable."]),
                }), 500

        @self.app.route("/api/environment/status")
        def api_environment_status():
            try:
                return jsonify(self.application.environment.status_payload())
            except Exception as exc:
                self.application.log.exception(f"Environment status API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "status": "Unavailable",
                    "availability": "unavailable",
                    "message": f"Environment status unavailable: {exc}",
                    "error": str(exc),
                    "timestamp": str(datetime.now()),
                    "last_successful_refresh": None,
                    "snapshot_age_seconds": None,
                    "snapshot_age_label": "never",
                    "stale": True,
                    "last_refresh_error": str(exc),
                    "summary": {
                        "areas": 0,
                        "devices": 0,
                        "supported_entities": 0,
                        "entities_with_readings": 0,
                        "readings_recorded": 0,
                        "stale_after_minutes": self.application.environment.stale_after_minutes(),
                    },
                    "areas": [],
                    "entities": [],
                    "refresh": {},
                }), 500

        @self.app.route("/api/environment/entities")
        def api_environment_entities():
            try:
                status = self.application.environment.status_payload()
                return jsonify({
                    "areas": status.get("areas", []),
                    "entities": status.get("entities", []),
                    "summary": status.get("summary", {}),
                    "last_successful_refresh": status.get("last_successful_refresh"),
                    "stale": status.get("stale"),
                    "snapshot_age_label": status.get("snapshot_age_label"),
                })
            except Exception as exc:
                self.application.log.exception(f"Environment entities API failed: {exc}")
                return jsonify({"areas": [], "entities": [], "summary": {}, "error": str(exc)}), 500

        @self.app.route("/api/environment/history/<path:entity_id>")
        def api_environment_history(entity_id):
            try:
                limit = request.args.get("limit", 200, type=int)
                history = self.application.environment.entity_history(entity_id, limit=limit)
                return jsonify({
                    "entity_id": entity_id,
                    "count": len(history),
                    "history": history,
                })
            except Exception as exc:
                self.application.log.exception(f"Environment history API failed for {entity_id}: {exc}")
                return jsonify({
                    "entity_id": entity_id,
                    "count": 0,
                    "history": [],
                    "error": str(exc),
                }), 500

        @self.app.route("/api/timeline/recent")
        def api_timeline_recent():
            """Get recent timeline events."""
            try:
                limit = request.args.get("limit", 50, type=int)
                category = request.args.get("category", None)
                severity = request.args.get("severity", None)
                hours_back = request.args.get("hours_back", 24, type=int)
                
                events = self.application.timeline.get_events(
                    category=category,
                    severity=severity,
                    limit=limit,
                    hours_back=hours_back,
                )
                return jsonify({"events": events, "count": len(events)})
            except Exception as exc:
                self.application.log.exception(f"Timeline API failed: {exc}")
                return jsonify({"events": [], "count": 0, "error": str(exc)}), 500

        @self.app.route("/api/notifications/recent")
        def api_notifications_recent():
            """Get recent notifications."""
            try:
                limit = request.args.get("limit", 50, type=int)
                unread_only = request.args.get("unread_only", False, type=lambda x: x.lower() == "true")
                severity = request.args.get("severity", None)
                hours_back = request.args.get("hours_back", 24, type=int)
                
                notifications = self.application.notification_manager.get_notifications(
                    limit=limit,
                    unread_only=unread_only,
                    severity=severity,
                    hours_back=hours_back,
                )
                unread_count = self.application.notification_manager.get_unread_count()
                return jsonify({
                    "notifications": notifications,
                    "count": len(notifications),
                    "unread_count": unread_count,
                })
            except Exception as exc:
                self.application.log.exception(f"Notifications API failed: {exc}")
                return jsonify({"notifications": [], "count": 0, "unread_count": 0, "error": str(exc)}), 500

        @self.app.route("/api/notifications/mark-read", methods=["POST"])
        def api_notifications_mark_read():
            """Mark a notification as read."""
            try:
                data = request.get_json() or {}
                notification_id = data.get("notification_id")
                if not notification_id:
                    return jsonify({"error": "notification_id required"}), 400
                
                success = self.application.notification_manager.mark_read(notification_id)
                return jsonify({"success": success})
            except Exception as exc:
                self.application.log.exception(f"Mark read failed: {exc}")
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/notifications/clear", methods=["POST"])
        def api_notifications_clear():
            """Clear all notifications."""
            try:
                count = self.application.notification_manager.clear()
                return jsonify({"cleared": count})
            except Exception as exc:
                self.application.log.exception(f"Clear notifications failed: {exc}")
                return jsonify({"error": str(exc)}), 500

        @self.app.route("/api/energy/status")
        def api_energy_status():
            try:
                return jsonify(self.application.energy_status())
            except Exception as exc:
                self.application.log.exception(f"Energy API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "availability": "unavailable",
                    "vehicle_name": "2025 Chevrolet Equinox EV",
                    "charger_name": "Juice Box",
                    "status": "Unavailable",
                    "is_charging": False,
                    "power_kw": 0,
                    "voltage": None,
                    "current": None,
                    "battery_percent": None,
                    "session_energy_kwh": 0,
                    "charging_time": None,
                    "miles_added": None,
                    "miles_per_hour_added": None,
                    "charge_cost": None,
                    "network": None,
                    "estimated_cost": 0,
                    "estimated_miles_added": 0,
                    "last_update": None,
                    "message": f"Energy Center status unavailable: {exc}",
                })

        @self.app.route("/api/vehicle/status")
        def api_vehicle_status():
            try:
                energy_status = None
                try:
                    energy_status = self.application.energy.get_status()
                except Exception:
                    pass  # vehicle still works without charger data
                return jsonify(self.application.vehicle.get_unified_status(energy_status))
            except Exception as exc:
                self.application.log.exception(f"Vehicle API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "availability": "unavailable",
                    "vehicle_name": "2025 Chevrolet Equinox EV",
                    "battery_percent": None,
                    "range_mi": None,
                    "plug_state": None,
                    "charging_state": None,
                    "plugged_in": None,
                    "charging": None,
                    "charging_power_kw": None,
                    "session_energy_kwh": None,
                    "estimated_miles_added": None,
                    "estimated_cost": None,
                    "charger_name": None,
                    "charger_status": None,
                    "charging_time": None,
                    "miles_per_hour_added": None,
                    "odometer_mi": None,
                    "lifetime_energy_kwh": None,
                    "lifetime_efficiency_mi_per_kwh": None,
                    "estimated_lifetime_cost": None,
                    "cost_per_mile": None,
                    "sources": {},
                    "last_update": None,
                    "message": f"Vehicle Center status unavailable: {exc}",
                })

        @self.app.route("/api/solar/status")
        def api_solar_status():
            try:
                return jsonify(self.application.solar.get_status(include_inverter_details=True))
            except Exception as exc:
                self.application.log.exception(f"Solar API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "name": "Solar Center",
                    "status": "Unknown",
                    "current_production_kw": None,
                    "current_production_w": None,
                    "production_today_kwh": None,
                    "production_last_7_days_kwh": None,
                    "lifetime_production_mwh": None,
                    "lifetime_production_kwh": None,
                    "production_ct_power_kw": None,
                    "production_ct_energy_delivered_mwh": None,
                    "estimated_value_today": None,
                    "estimated_value_last_7_days": None,
                    "estimated_lifetime_value": None,
                    "estimated_value_per_hour": None,
                    "electricity_rate": 0.13,
                    "last_updated": None,
                    "source": "Enphase Envoy",
                    "panel_count": None,
                    "inverter_count": None,
                    "microinverters_installed": None,
                    "microinverters_online": None,
                    "inverters": [],
                    "inverter_data_available": False,
                    "inverter_data_message": "Not reported by Envoy",
                    "error": f"Solar Center status unavailable: {exc}",
                    "message": f"Solar Center status unavailable: {exc}",
                })

        @self.app.route("/api/solar/overview")
        def api_solar_overview():
            try:
                status = self.application.solar.get_status(include_inverter_details=True)
                return jsonify({
                    "status": status,
                    "production_chart": self._solar_history_production_chart(),
                    "weather_correlation": self._solar_placeholder_weather(),
                    "weather": {
                        "sunshine_percent": None,
                        "cloud_cover_percent": None,
                        "temperature": None,
                        "uv_index": None,
                        "sunrise": None,
                        "sunset": None,
                        "message": "Weather integration is not configured yet.",
                    },
                })
            except Exception as exc:
                self.application.log.exception(f"Solar overview API failed: {exc}")
                return jsonify({
                    "status": {
                        "enabled": False,
                        "configured": False,
                        "name": "Solar Center",
                        "status": "Unknown",
                        "panel_count": None,
                        "inverter_count": None,
                        "microinverters_installed": None,
                        "microinverters_online": None,
                        "inverters": [],
                        "inverter_data_available": False,
                        "inverter_data_message": "Not reported by Envoy",
                        "error": f"Solar Center overview unavailable: {exc}",
                    },
                    "production_chart": [],
                    "weather_correlation": [],
                    "weather": {"message": "Weather integration is not configured yet."},
                })

        @self.app.route("/api/solar/inverters/performance")
        def api_solar_inverter_performance():
            try:
                range_key = request.args.get("range", "today")
                metric = request.args.get("metric", "power")
                return jsonify(self.application.solar.get_inverter_performance(self.application.db, range_key=range_key, metric=metric))
            except Exception as exc:
                self.application.log.exception(f"Solar inverter performance API failed: {exc}")
                return jsonify({
                    "data_available": False,
                    "chart_type": "none",
                    "chart_title": "Current Inverter Performance",
                    "chart_message": "Inverter performance endpoint failed.",
                    "message": f"Inverter performance unavailable: {exc}",
                    "reason": "Inverter performance endpoint failed.",
                    "timestamp": str(datetime.now()),
                    "range": "today",
                    "metric": "power",
                    "inverters": [],
                    "series": [],
                    "values": [],
                    "summary": [],
                    "insights": [],
                })

        @self.app.route("/api/weather/status")
        def api_weather_status():
            try:
                return jsonify(self.application.weather.get_status())
            except Exception as exc:
                self.application.log.exception(f"Weather API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "location_name": "Home",
                    "temperature_f": None,
                    "condition": "Unavailable",
                    "cloud_cover_percent": None,
                    "sunshine_percent": None,
                    "humidity_percent": None,
                    "wind_mph": None,
                    "uv_index": None,
                    "sunrise": None,
                    "sunset": None,
                    "last_updated": None,
                    "source": "Unavailable",
                    "error": str(exc),
                })

        @self.app.route("/api/lighting/status")
        def api_lighting_status():
            try:
                return jsonify(self.application.lighting.get_status())
            except Exception as exc:
                self.application.log.exception(f"Lighting API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "status": "Unavailable",
                    "provider": "home_assistant",
                    "source": "Unavailable",
                    "live_data": False,
                    "total_lights": 0,
                    "lights_on": 0,
                    "lights_off": 0,
                    "unavailable_lights": 0,
                    "exterior_highlight": {
                        "present": False,
                        "total": 0,
                        "on": 0,
                        "names": [],
                        "govee_present": False,
                    },
                    "lights": [],
                    "last_updated": None,
                    "error": str(exc),
                    "message": f"Lighting Center status unavailable: {exc}",
                })

        @self.app.route("/api/network/mesh")
        def api_network_mesh():
            try:
                internet = self.application.status.get().get("internet", {})
                return jsonify(self.application.network_mesh.get_status(internet_status=internet))
            except Exception as exc:
                self.application.log.exception(f"Network mesh API failed: {exc}")
                return jsonify({
                    "data_available": False,
                    "message": f"Mesh network status unavailable: {exc}",
                    "timestamp": str(datetime.now()),
                    "nodes": [],
                    "clients": [],
                    "summary": {
                        "internet_online": None,
                        "mesh_nodes_online": 0,
                        "mesh_nodes_total": 0,
                        "connected_clients": 0,
                        "current_total_down_kbps": None,
                        "current_total_up_kbps": None,
                    },
                    "insights": [],
                    "error": str(exc),
                })

        @self.app.route("/api/garden/status")
        def api_garden_status():
            try:
                return jsonify(self.application.garden.get_status())
            except Exception as exc:
                self.application.log.exception(f"Garden API failed: {exc}")
                return jsonify({
                    "enabled": False,
                    "configured": False,
                    "status": "Unavailable",
                    "provider": "bhyve",
                    "source": "Unavailable",
                    "live_data": False,
                    "controller_count": 0,
                    "controllers": [],
                    "active_watering_zone": None,
                    "next_watering_schedule": None,
                    "rain_delay_active": None,
                    "rain_delay_until": None,
                    "last_updated": None,
                    "error": str(exc),
                    "message": f"Garden Center status unavailable: {exc}",
                })

        @self.app.route("/api/insights/status")
        def api_insights_status():
            import time
            start_time = time.time()
            self.application.log.debug("[/api/insights/status] Route started")
            
            try:
                max_insights = request.args.get("max", 5, type=int)
                
                # Call get_insights with logging
                insights = self.application.analytics.get_insights(max_insights=max_insights)
                
                response = jsonify({
                    "ok": True,
                    "insights": [i.to_dict() for i in insights],
                    "count": len(insights),
                    "timestamp": str(datetime.now()),
                })
                
                elapsed_ms = (time.time() - start_time) * 1000
                self.application.log.debug(f"[/api/insights/status] Route completed in {elapsed_ms:.2f}ms")
                return response
                
            except Exception as exc:
                elapsed_ms = (time.time() - start_time) * 1000
                self.application.log.exception(f"[/api/insights/status] Route failed after {elapsed_ms:.2f}ms: {exc}")
                
                # Return safe fallback JSON
                return jsonify({
                    "ok": True,
                    "insights": [],
                    "count": 0,
                    "message": "Insights unavailable",
                    "error": str(exc),
                    "timestamp": str(datetime.now()),
                }), 200

        @self.app.route("/api/history/latest")
        def api_history_latest():
            try:
                return jsonify({
                    "enabled": self.application.history.enabled(),
                    "database": str(self.application.history.database.path),
                    "last_snapshot_time": self.application.history.last_snapshot_time,
                    "metrics": self.application.history.get_latest_all(),
                    "timestamp": str(datetime.now()),
                })
            except Exception as exc:
                self.application.log.exception(f"History latest API failed: {exc}")
                return jsonify({"enabled": False, "metrics": [], "error": str(exc)}), 500

        @self.app.route("/api/history/metrics")
        def api_history_metrics():
            module = request.args.get("module", "").strip()
            metric = request.args.get("metric", "").strip()
            if not module or not metric:
                return jsonify({"error": "module and metric are required", "points": []}), 400
            try:
                limit = request.args.get("limit")
                normalized_limit = int(limit) if limit else None
                range_key = request.args.get("range")
                if range_key:
                    points, normalized_range, aggregation = self.application.history.get_metrics_for_range(
                        module,
                        metric,
                        range_key=range_key,
                        limit=normalized_limit,
                    )
                    hours = None
                else:
                    try:
                        hours = float(request.args.get("hours", "24") or 24)
                    except ValueError:
                        hours = 24
                    start_time = datetime.now() - timedelta(hours=max(hours, 0.1))
                    points = self.application.history.get_metrics(
                        module,
                        metric,
                        start_time=start_time,
                        limit=normalized_limit,
                    )
                    normalized_range = None
                    aggregation = "raw"
                return jsonify({
                    "module": module,
                    "metric": metric,
                    "hours": hours,
                    "range": normalized_range,
                    "aggregation": aggregation,
                    "points": points,
                    "count": len(points),
                })
            except Exception as exc:
                self.application.log.exception(f"History metrics API failed: {exc}")
                return jsonify({"module": module, "metric": metric, "points": [], "error": str(exc)}), 500

        @self.app.route("/api/history/summary")
        def api_history_summary():
            module = request.args.get("module", "").strip()
            period = request.args.get("period", "today").strip() or "today"
            if not module:
                return jsonify({"error": "module is required", "metrics": []}), 400
            try:
                return jsonify({
                    "module": module,
                    "period": period,
                    "metrics": self.application.history.get_summary(module, period=period),
                    "timestamp": str(datetime.now()),
                })
            except Exception as exc:
                self.application.log.exception(f"History summary API failed: {exc}")
                return jsonify({"module": module, "period": period, "metrics": [], "error": str(exc)}), 500

        @self.app.route("/api/charts/latency")
        def api_latency_chart():
            rows = self.application.db.health_history(limit=96)
            labels = []
            values = []
            scores = []
            for row in rows:
                labels.append(row["timestamp"][11:16] if row["timestamp"] else "")
                values.append(row["latency"])
                scores.append(row["score"])
            return jsonify({"labels": labels, "values": values, "scores": scores})

        @self.app.route("/health")
        def health():
            return jsonify({"status": self._dashboard_payload(), "timestamp": str(datetime.now())})

        @self.app.route("/test/smtp", methods=["POST"])
        def test_smtp():
            return self._diagnostic_response("smtp_test")

        @self.app.route("/test/ping", methods=["POST"])
        def test_ping():
            return self._diagnostic_response("internet_ping_test")

        @self.app.route("/test/speed", methods=["POST"])
        def test_speed():
            return self._diagnostic_response("speed_test")

        @self.app.route("/test/tapo", methods=["POST"])
        def test_tapo():
            return self._diagnostic_response("home_assistant_connection_test")

        @self.app.route("/test/tapo_power_cycle", methods=["POST"])
        def test_tapo_power_cycle():
            payload = request.get_json(silent=True) or {}
            confirmed = payload.get("confirm_tapo_power_cycle") is True
            return self._diagnostic_response("home_assistant_power_cycle_test", confirmed=confirmed)

        @self.app.route("/test/home_assistant", methods=["POST"])
        def test_home_assistant():
            return self._diagnostic_response("home_assistant_connection_test")

        @self.app.route("/test/home_assistant_power_cycle", methods=["POST"])
        def test_home_assistant_power_cycle():
            payload = request.get_json(silent=True) or {}
            confirmed = payload.get("confirm_home_assistant_power_cycle") is True
            return self._diagnostic_response("home_assistant_power_cycle_test", confirmed=confirmed)

        @self.app.route("/test/full_diagnostics", methods=["POST"])
        def test_full_diagnostics():
            payload = request.get_json(silent=True) or {}
            overrides = payload.get("overrides", payload)
            return jsonify(self.application.diagnostics.run_full_diagnostics(overrides=overrides).to_dict())

        @self.app.route("/discover/tapo")
        def discover_tapo():
            return jsonify(self.application.tapo_discovery.discover())

    def _diagnostic_response(self, test_name, **kwargs):
        payload = request.get_json(silent=True) or {}
        overrides = payload.get("overrides", payload)
        return jsonify(self.application.diagnostics.run_test(test_name, overrides=overrides, **kwargs).to_dict())

    def _valid_admin_action_request(self):
        payload = request.get_json(silent=True) or {}
        token = (
            request.headers.get("X-HomePulse-Admin-Token")
            or payload.get("admin_token")
            or request.form.get("admin_token")
        )
        return bool(token and secrets.compare_digest(str(token), self.admin_action_token))

    @staticmethod
    def _admin_action_forbidden():
        return jsonify({
            "ok": False,
            "status": "forbidden",
            "message": "Admin action token is missing or invalid. Open Lab and use the in-app button.",
            "timestamp": str(datetime.now()),
        }), 403

    def _home_status_payload(self):
        dashboard_status = self._dashboard_payload()
        internet = self._home_internet_status(dashboard_status)
        solar = self._safe_center_status("solar", self.application.solar.get_status)
        self.application.observe_solar_status(solar)
        energy = self._safe_center_status("energy", self.application.energy.get_status)
        vehicle_dict = self._safe_center_status("vehicle", self.application.vehicle.get_status)
        # Get unified vehicle status (merged with charger data)
        try:
            vehicle = self.application.vehicle.get_unified_status(energy)
        except Exception:
            vehicle = vehicle_dict
        self.application.observe_vehicle_status(vehicle)
        weather = self._safe_center_status("weather", self.application.weather.get_status)
        lighting = self._safe_center_status("lighting", self.application.lighting.get_status)
        self.application.observe_lighting_status(lighting)
        garden = self._safe_center_status("garden", self.application.garden.get_status)
        self.application.observe_garden_status(garden)
        home = self._home_placeholder()
        
        # Compute health score and alerts
        statuses = {
            "internet": internet,
            "solar": solar,
            "vehicle": vehicle,
            "energy": energy,
            "weather": weather,
            "lighting": lighting,
            "garden": garden,
            "home_assistant": self._home_assistant_status(),
            "system": self._system_status(),
        }
        health_result = self.application.health_score.compute(statuses)
        alerts = self.application.alert_manager.detect_alerts(statuses)
        alerts.sort(key=lambda a: self.application.alert_manager.severity_priority(a.get("severity")))
        
        overall_status = self._overall_home_status(internet, solar, energy, vehicle, weather)
        return {
            "internet": internet,
            "solar": solar,
            "energy": energy,
            "vehicle": vehicle,
            "weather": weather,
            "lighting": lighting,
            "garden": garden,
            "home": home,
            "overall_status": overall_status,
            "health_score": health_result.get("score"),
            "health_status": health_result.get("status_text"),
            "health_trend": health_result.get("trend"),
            "health_breakdown": health_result.get("breakdown"),
            "alerts": alerts[:10],  # Top 10 alerts
            "timeline_summary": self.application.timeline.get_summary(hours_back=24),
            "timeline_recent": self.application.timeline.get_events(limit=20, hours_back=24),
            "widgets": self.application.plugin_manager.widget_registry.all(),
            "devices": self.application.plugin_manager.device_registry.all(),
            "last_updated": str(datetime.now()),
        }

    def _home_assistant_status(self):
        """Placeholder for Home Assistant integration status."""
        return {
            "enabled": True,
            "configured": True,
            "status": "Connected",
            "availability": "live",
            "message": "Home Assistant integration ready (future: entity counts, automation status)",
        }

    def _system_status(self):
        """System health (HomePulse itself)."""
        uptime_seconds = (datetime.now() - self.application.started_at).total_seconds()
        return {
            "enabled": True,
            "status": "Healthy",
            "uptime_seconds": int(uptime_seconds),
            "message": "HomePulse running normally",
        }

    def _home_internet_status(self, status):
        internet = status.get("internet", {})
        speedtest = status.get("speedtest", {})
        return {
            "status": internet.get("status", "Unavailable"),
            "health_score": status.get("intelligence", {}).get("quality_score"),
            "latency_ms": internet.get("latency"),
            "packet_loss_percent": internet.get("packet_loss"),
            "last_check": internet.get("last_check"),
            "last_speedtest": speedtest.get("last_run"),
            "download_mbps": speedtest.get("download"),
            "upload_mbps": speedtest.get("upload"),
            "message": internet.get("details", "Internet status unavailable."),
        }

    def _safe_center_status(self, name, function):
        result_holder = {"value": None, "error": None}

        def _runner():
            try:
                result_holder["value"] = function() or {"enabled": False, "status": "Unavailable"}
            except Exception as exc:
                result_holder["error"] = exc

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(timeout=1.25)

        if worker.is_alive():
            self.application.log.warning(f"Home Center {name} status timed out after 1.25s")
            return {
                "enabled": False,
                "configured": False,
                "status": "Unavailable",
                "error": "timeout",
                "message": f"{name.title()} status timed out.",
            }

        if result_holder["error"] is not None:
            exc = result_holder["error"]
            self.application.log.debug(f"Home Center {name} status unavailable: {exc}", exc_info=True)
            return {
                "enabled": False,
                "configured": False,
                "status": "Unavailable",
                "error": str(exc),
                "message": f"{name.title()} status unavailable.",
            }

        return result_holder["value"]

    @staticmethod
    def _lighting_placeholder():
        return {
            "enabled": False,
            "configured": False,
            "status": "Not configured",
            "name": "Lighting Center",
            "type": "lighting",
            "source": "Home Assistant light entities",
            "message": "Lighting Center is ready to read Home Assistant light.* entities.",
            "capabilities": ["home_assistant_provider", "vendor_neutral", "provider_failover_foundation"],
        }

    @staticmethod
    def _garden_placeholder():
        return {
            "enabled": False,
            "configured": False,
            "status": "Not configured",
            "name": "Garden Center",
            "type": "garden",
            "source": "B-hyve provider framework",
            "message": "Garden Center is ready for B-hyve provider configuration.",
            "capabilities": ["bhyve_provider", "irrigation_summary"],
        }

    @staticmethod
    def _home_placeholder(alerts=None):
        return {
            "status": "No active alerts" if not alerts else "Attention",
            "active_alerts": alerts or [],
            "garage": "Placeholder",
            "locks": "Placeholder",
            "doors": "Placeholder",
            "climate": "Placeholder",
            "cameras": "Placeholder",
            "message": "Garage, locks, doors, climate, and cameras are prepared for future plugins.",
        }

    @staticmethod
    def _overall_home_status(internet, solar, energy, vehicle, weather):
        attention_states = {"Unhealthy", "Attention", "Failed"}
        partial_states = {"Unavailable", "Unknown", "Waiting for Data", "Partial Data"}
        if internet.get("status") in attention_states:
            return "Attention"
        statuses = [
            solar.get("status"),
            energy.get("status"),
            vehicle.get("availability") or vehicle.get("status"),
            weather.get("condition"),
        ]
        if any(status in attention_states for status in statuses):
            return "Attention"
        if internet.get("status") == "Degraded" or any(status in partial_states for status in statuses):
            return "Partial"
        return "Healthy"

    @staticmethod
    def _home_health_score(internet, solar, energy, vehicle, weather):
        score = 100
        if internet.get("status") == "Degraded":
            score -= 15
        elif internet.get("status") not in ("Healthy", "Starting"):
            score -= 30
        for item in (solar, energy, vehicle, weather):
            if item.get("enabled") is False:
                score -= 5
            elif item.get("error"):
                score -= 10
        return max(0, min(100, score))

    @staticmethod
    def render_test_button(name, endpoint):
        label = escape(name)
        action = escape(endpoint)
        return Markup(
            f'<button type="button" class="diagnostic-test-button" data-endpoint="{action}">{label}</button>'
        )

    def _solar_history_production_chart(self):
        start_time = datetime.now() - timedelta(hours=24)
        points = self.application.history.get_metrics(
            "solar",
            "current_production_kw",
            start_time=start_time,
            limit=288,
        )
        return [
            {
                "label": self._short_time(point["timestamp"]),
                "timestamp": point["timestamp"],
                "value": point["value"],
                "unit": point.get("unit") or "kW",
                "mock": False,
            }
            for point in points
        ]

    @staticmethod
    def _short_time(timestamp):
        if not timestamp:
            return ""
        if isinstance(timestamp, datetime):
            return timestamp.strftime("%H:%M")
        text = str(timestamp).strip()
        if not text:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:26], fmt).strftime("%H:%M")
            except ValueError:
                continue
        if len(text) >= 16:
            return text[11:16]
        return text

    @staticmethod
    def _solar_placeholder_weather():
        return [
            {"label": "Sunshine", "solar": None, "weather": None, "placeholder": True},
            {"label": "Cloud Cover", "solar": None, "weather": None, "placeholder": True},
            {"label": "Temperature", "solar": None, "weather": None, "placeholder": True},
            {"label": "UV Index", "solar": None, "weather": None, "placeholder": True},
        ]

    def _lab_payload(self):
        status = self._dashboard_payload()
        scheduled_task_exists = self.application.scheduled_task_status()["exists"]
        return {
            "about": self._lab_about(status),
            "overview": self._lab_overview(status),
            "scheduler": self._lab_scheduler(status),
            "logs": self._recent_log_entries(),
            "database": self._database_counts(),
            "history": self._history_status(),
            "platform": self._platform_status(),
            "system_status": self._system_status_rows(),
            "reboot": self._reboot_status(),
            "reboot_events": self._recent_reboot_events(),
            "configuration": self._flatten_config(self.application.config.data),
            "actions": [
                ("run_ping", "Run Ping"),
                ("run_speedtest", "Run Speed Test"),
                ("run_maintenance", "Run Maintenance"),
                ("reload_config", "Reload Configuration"),
            ],
            "scheduled_task_exists": scheduled_task_exists,
        }

    def _system_status_rows(self):
        status = self.application.process_identity()
        last_restart = status.get("last_restart_request")
        last_restart_text = "None recorded"
        if isinstance(last_restart, dict):
            last_restart_text = (
                f"{last_restart.get('timestamp', 'Unknown')} "
                f"(PID {last_restart.get('pid', 'Unknown')})"
            )
        return [
            ("PID", status.get("pid")),
            ("Started At", status.get("started_at")),
            ("Uptime", self._format_duration_seconds(status.get("uptime_seconds"))),
            ("Version", status.get("version")),
            ("Executable", status.get("executable")),
            ("Working Directory", status.get("working_directory")),
            ("Restart Supported", self._enabled_label(status.get("restart_supported"))),
            ("Scheduled Task Name", status.get("scheduled_task_name", "HomePulse")),
            ("Scheduled Task Exists", self._enabled_label(status.get("scheduled_task_exists"))),
            ("Restart Method", status.get("restart_method", "Not available")),
            ("Scheduled Task Last Result", status.get("scheduled_task_last_result")),
            ("Last Restart Request", last_restart_text),
            ("Last Restart Method", status.get("last_restart_method") or "None"),
        ]

    def _email_center_status(self):
        email = self.application.config.get("email", default={})
        events = [
            event for event in self.application.db.recent_events(limit=50)
            if str(event.get("event_type", "")).startswith("email")
        ]
        return {
            "enabled": email.get("email_notifications_enabled", email.get("enabled", False)),
            "server": email.get("smtp_server", email.get("smtp_host", "")),
            "port": email.get("smtp_port", 587),
            "from_email": email.get("smtp_from_email", email.get("from_address", "")),
            "recipients": email.get("smtp_to_email", email.get("to_address", "")),
            "last_event": events[0] if events else None,
        }

    def _lab_about(self, status):
        return {
            "application": [
                ("Application Name", APP_NAME),
                ("Version", APP_VERSION),
                ("Author", APP_AUTHOR),
                ("Copyright", APP_COPYRIGHT),
                ("Environment", f"{sys.platform} / Python {sys.version.split()[0]}"),
                ("Runtime", f"PID {os.getpid()}"),
                ("Project Folder", str(Path.cwd())),
                ("Configuration", "Loaded" if self.application.config.data else "Unavailable"),
            ],
            "modules": self._lab_module_status(status),
            "system": [
                ("Database Status", self._sqlite_status()),
                ("Database Size", self._database_size()),
                ("Scheduler Status", self._scheduler_status()),
                ("Scheduled Jobs", len(self.application.scheduler.jobs)),
            ],
        }

    def _lab_module_status(self, status):
        config = self.application.config
        recovery = config.get("router_reboot", default={})
        email = config.get("email", default={})
        energy = config.get("energy", default={})
        solar = config.get("solar", default={})
        history = config.get("history", default={})
        weather = config.get("weather", default={})
        return [
            ("Dashboard", self._enabled_label(config.get("dashboard", "enabled", default=True))),
            ("Internet Health", self._enabled_label(bool(config.get("monitor_interval_minutes", default=0)))),
            ("Speed Test", self._enabled_label(config.get("speedtest_schedule_enabled", default=True))),
            ("Home Assistant", self._enabled_label(bool(recovery.get("home_assistant_url") and recovery.get("recovery_entity_id")))),
            ("Email Alerts", self._enabled_label(email.get("email_notifications_enabled", email.get("enabled", False)))),
            ("Energy Center", self._enabled_label(energy.get("enabled", False))),
            ("Vehicle Center", self._enabled_label(config.get("vehicle", "enabled", default=False))),
            ("Solar Center", self._enabled_label(solar.get("enabled", False))),
            ("History / Analytics", self._enabled_label(history.get("enabled", True))),
            ("Weather Center", self._enabled_label(weather.get("enabled", True))),
        ]

    @staticmethod
    def _enabled_label(value):
        return "Enabled" if value else "Disabled"

    def _recent_reboot_events(self):
        return [
            event for event in self.application.db.recent_events(limit=25)
            if event["event_type"] in ("router_reboot", "router_reboot_recommended", "router_reboot_skipped")
        ][:8]

    def _lab_overview(self, status):
        started_at = status["system"].get("started_at")
        started = self.application.parse_timestamp(started_at)
        return [
            ("Application Version", status["version"]),
            ("Start Time", started_at or "Unknown"),
            ("Uptime", self._format_uptime(started)),
            ("Python Version", sys.version.split()[0]),
            ("SQLite Status", self._sqlite_status()),
            ("Database Size", self._database_size()),
            ("Memory Usage", self._memory_usage()),
            ("Scheduler Status", self._scheduler_status()),
            ("Background Threads", max(threading.active_count() - 1, 0)),
            ("Configuration Loaded", "Loaded" if self.application.config.data else "Unavailable"),
        ]

    def _reboot_status(self):
        router_reboot = self.application.config.get("router_reboot", default={})
        email = self.application.config.get("email", default={})
        latest = self.application.latest_automatic_recovery_activity()
        status = self.application.router_rebooter.status()
        recovery_summary = self.application.router_recovery_summary()
        return [
            ("Current Method", status["label"]),
            ("Device Type", status["device_type"]),
            ("Real Reboot Enabled", "Yes" if status["real_reboot_enabled"] else "No"),
            ("Automatic Recovery", recovery_summary["mode_label"]),
            ("Dry-run Active", "Yes" if status["dry_run_active"] else "No"),
            ("Device Name", router_reboot.get("recovery_device_name") or "Not configured"),
            ("Device IP", router_reboot.get("recovery_device_ip") or "Not configured"),
            ("Home Assistant Entity", recovery_summary["recovery_entity"]),
            ("Power Off Seconds", router_reboot.get("recovery_power_off_seconds", 10)),
            ("Wait After Power On", router_reboot.get("recovery_wait_after_power_on_seconds", 180)),
            ("Dry Run Mode", self.application.config.get("dry_run", default=True)),
            ("Last Automatic Attempt", recovery_summary["last_attempt"]),
            ("Last Automatic Result", recovery_summary["last_result"]),
            ("Cooldown Status", recovery_summary["cooldown_status"]),
            ("Email Enabled", email.get("email_notifications_enabled", email.get("enabled", False))),
            ("Last Reboot Event", latest["timestamp"] if latest else "None recorded"),
        ]

    def _lab_scheduler(self, status):
        return [
            ("Next Ping", self._next_interval_run("Internet Health Check")),
            ("Next Speed Test", status["speedtest"].get("next_run") or "Disabled"),
            ("Next Maintenance", self._next_maintenance()),
            ("Last Speed Test", status["speedtest"].get("last_run") or "Never"),
            ("Last Maintenance", self._last_maintenance()),
            ("Queue Status", f"{len(self.application.scheduler.jobs)} scheduled job(s)"),
        ]

    def _scheduler_status(self):
        return "Active" if self.application.scheduler.jobs else "No jobs registered"

    def _next_interval_run(self, job_name):
        now = datetime.now()
        for job in self.application.scheduler.jobs:
            if job["name"] == job_name and job["type"] == "interval":
                last_run = job.get("last_run")
                if not last_run:
                    return "Due now"
                return str(last_run + job["interval"])
        return "Not scheduled"

    def _next_maintenance(self):
        time_value = self.application.config.get("reboot_window_time", default="04:00")
        hour, minute = self.application.parse_clock_time(time_value)
        now = datetime.now()
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return str(candidate)

    def _last_maintenance(self):
        candidates = [
            self.application.db.latest_event("maintenance_check"),
            self.application.db.latest_event("router_reboot_recommended"),
            self.application.db.latest_event("router_reboot_skipped"),
        ]
        candidates = [event for event in candidates if event]
        if not candidates:
            return "Never"
        latest = max(candidates, key=lambda event: event["timestamp"])
        return latest["timestamp"]

    def _database_counts(self):
        health_rows = self.application.db.health_history(limit=10000)
        return [
            ("Latency", self.application.db.count_rows("health_checks")),
            ("Speed Tests", self.application.db.count_rows("speed_tests")),
            ("Outages", len(self.application.outage_runs(health_rows))),
            ("Router Reboots", self.application.db.count_events("router_reboot")),
            ("Events", self.application.db.count_events()),
        ]

    def _history_status(self):
        history = self.application.history
        try:
            count = history.database.count_metrics()
            latest = history.database.latest_timestamp()
        except Exception as exc:
            count = "Unavailable"
            latest = f"Unavailable: {exc}"
        return [
            ("Enabled", "Yes" if history.enabled() else "No"),
            ("Database Path", str(history.database.path)),
            ("Snapshot Interval", f"{history.snapshot_interval_minutes()} minutes"),
            ("Retention", f"{history.retention_days()} days"),
            ("Last Snapshot", history.last_snapshot_time or latest or "None recorded"),
            ("Last Snapshot Count", history.last_snapshot_count),
            ("Metrics Recorded", count),
        ]

    def _platform_status(self):
        return [
            ("Plugins", ", ".join(plugin["display_name"] for plugin in self.application.plugin_manager.metadata())),
            ("Dashboard Widgets", ", ".join(widget["title"] for widget in self.application.plugin_manager.widget_registry.all())),
            ("Device Types", ", ".join(self.application.plugin_manager.device_registry.types())),
            ("Registered Devices", len(self.application.plugin_manager.device_registry.all())),
        ]

    def _recent_log_entries(self):
        log_file = Path("logs/routermonitor.log")
        if not log_file.exists():
            return [{"severity": "info", "line": "No log file found."}]
        lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        return [
            {"severity": self._line_severity(line), "line": line}
            for line in lines[-80:]
        ]

    @staticmethod
    def _line_severity(line):
        upper = line.upper()
        if "CRITICAL" in upper or "ERROR" in upper or "EXCEPTION" in upper:
            return "error"
        if "WARNING" in upper or "WARN" in upper:
            return "warning"
        if "DEBUG" in upper:
            return "debug"
        return "info"

    def _sqlite_status(self):
        try:
            self.application.db.conn.execute("SELECT 1").fetchone()
            return "Connected"
        except Exception as exc:
            return f"Unavailable: {exc}"

    def _database_size(self):
        path = Path(self.application.db.filename)
        if not path.exists():
            return "Not created"
        return self._format_bytes(path.stat().st_size)

    def _memory_usage(self):
        rss = self._process_memory_bytes()
        return self._format_bytes(rss) if rss else "Unavailable"

    @staticmethod
    def _process_memory_bytes():
        if os.name == "nt":
            try:
                class ProcessMemoryCounters(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = ProcessMemoryCounters()
                counters.cb = ctypes.sizeof(counters)
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
                return counters.WorkingSetSize if ok else None
            except Exception:
                return None

        try:
            import resource
        except ImportError:
            return None
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage * 1024

    @staticmethod
    def _format_bytes(value):
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} GB"

    @staticmethod
    def _format_uptime(started):
        if not started:
            return "Unknown"
        delta = datetime.now() - started
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @staticmethod
    def _format_duration_seconds(value):
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return "Unknown"
        days, remainder = divmod(max(seconds, 0), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return f"{days}d {hours}h {minutes}m"
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    @classmethod
    def _flatten_config(cls, data, prefix=""):
        rows = []
        for key in sorted(data):
            value = data[key]
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                rows.extend(cls._flatten_config(value, path))
            elif isinstance(value, list):
                rows.append((path, ", ".join(str(item) for item in value)))
            elif "password" in path.lower():
                rows.append((path, "Configured" if value else "Not configured"))
            else:
                rows.append((path, value))
        return rows

    def run(self):
        self.app.run(
            host=self.application.config.get("dashboard", "host"),
            port=self.application.config.get("dashboard", "port"),
            debug=False,
            use_reloader=False,
        )
