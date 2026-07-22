import unittest
from types import SimpleNamespace

from flask import Flask, render_template

from modules.dashboard import Dashboard
from tests.test_greenhouse_conditions import DummyConfig, ROOT


def make_garden_dashboard(greenhouse, garden=None, environment_status=None):
    garden_snapshot = garden or {
        "status": "Monitoring",
        "provider": "bhyve",
        "selected_provider": "bhyve",
        "controller_count": 1,
        "active_watering_zone": "Front Beds",
        "next_watering_schedule": "2026-07-20 04:00:00",
        "rain_delay_active": False,
        "rain_delay_until": None,
        "provider_strategy": "automatic_failover",
        "enabled_providers": ["bhyve"],
        "attempted_providers": ["bhyve"],
        "fallback_used": False,
        "last_updated": "2026-07-20T02:39:05+00:00",
        "message": "Garden Center ready.",
        "controllers": [],
    }
    greenhouse_snapshot = dict(greenhouse)
    status_snapshot = environment_status or {
        "status": "Connected",
        "message": "Loaded from cached environmental snapshot.",
        "enabled": True,
        "summary": {"supported_entities": 2, "readings_recorded": 4, "areas": 1, "devices": 1},
        "greenhouse": greenhouse_snapshot,
        "areas": [],
        "entities": [],
        "last_successful_refresh": greenhouse_snapshot.get("observed_at") or greenhouse_snapshot.get("source_timestamp"),
        "snapshot_age_label": "1m ago",
        "stale": False,
    }
    environment = SimpleNamespace(
        greenhouse_status=lambda: dict(greenhouse_snapshot),
        status_payload=lambda: dict(status_snapshot),
    )
    app = SimpleNamespace(
        config=DummyConfig(
            {
                "environment": {
                    "enabled": True,
                    "refresh_interval_minutes": 5,
                    "stale_after_minutes": 10,
                },
                "email": {},
                "router_reboot": {},
            }
        ),
        status=SimpleNamespace(
            get=lambda: {
                "version": "2.6.2",
                "greenhouse": dict(greenhouse_snapshot),
            }
        ),
        db=SimpleNamespace(latest_event=lambda _name: None, recent_events=lambda limit=5: []),
        next_scheduled_speedtest=lambda: None,
        speedtest_schedule_label=lambda: "Every 30 minutes",
        internet_intelligence=lambda: {},
        plugin_manager=SimpleNamespace(
            widget_registry=SimpleNamespace(all=lambda: []),
            device_registry=SimpleNamespace(all=lambda: []),
        ),
        environment=environment,
        garden=SimpleNamespace(get_status=lambda: dict(garden_snapshot)),
        health_score=SimpleNamespace(compute=lambda statuses: {"score": 99, "status_text": "Healthy", "trend": "Stable", "breakdown": {}}),
        alert_manager=SimpleNamespace(detect_alerts=lambda statuses: [], severity_priority=lambda severity: 0),
        timeline=SimpleNamespace(get_summary=lambda hours_back=24: {}, get_events=lambda limit=20, hours_back=24: []),
        solar=SimpleNamespace(get_status=lambda: {}),
        energy=SimpleNamespace(get_status=lambda: {}),
        vehicle=SimpleNamespace(get_status=lambda: {}, get_unified_status=lambda energy: {}),
        weather=SimpleNamespace(get_status=lambda: {}),
        lighting=SimpleNamespace(get_status=lambda: {}),
        started_at=None,
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
    )
    return Dashboard(app)


class GardenGreenhouseTemplateTests(unittest.TestCase):
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
                    "temperature_display": "75.0\u00b0F",
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
            "garden": {
                "status": "Monitoring",
                "provider": "bhyve",
                "selected_provider": "bhyve",
                "controller_count": 1,
                "active_watering_zone": "Front Beds",
                "next_watering_schedule": "2026-07-20 04:00:00",
                "rain_delay_active": False,
                "rain_delay_until": None,
                "provider_strategy": "automatic_failover",
                "enabled_providers": ["bhyve"],
                "attempted_providers": ["bhyve"],
                "fallback_used": False,
                "last_updated": "2026-07-20T02:39:05+00:00",
                "message": "Garden Center ready.",
                "controllers": [],
            },
            "environment": {
                "status": "Connected",
                "message": "Loaded from cached environmental snapshot.",
                "enabled": True,
                "summary": {"supported_entities": 2, "readings_recorded": 4, "areas": 1, "devices": 1},
                "greenhouse": {
                    "temperature_display": "75.0\u00b0F",
                    "humidity_display": "44%",
                    "temperature_band": "Normal",
                    "source_status": "live",
                    "source": "live",
                    "status": "Connected",
                    "message": "Live greenhouse readings are available.",
                    "today_high": "80.4\u00b0F",
                    "today_low": "75.0\u00b0F",
                    "last_updated": "2026-07-20T02:39:05+00:00",
                    "observed_at": "2026-07-20T02:39:05+00:00",
                    "source_timestamp": "2026-07-20T02:20:05+00:00",
                    "history_count": 2,
                    "history_points": [
                        {"timestamp": "2026-07-20T00:00:00+00:00", "value": 75.0, "unit": "\u00b0F", "availability": "available"},
                        {"timestamp": "2026-07-20T01:00:00+00:00", "value": 80.4, "unit": "\u00b0F", "availability": "available"},
                    ],
                    "stale": False,
                },
                "areas": [],
                "entities": [],
                "last_successful_refresh": "2026-07-20T02:39:05+00:00",
                "snapshot_age_label": "1m ago",
                "stale": False,
            },
        }

    def test_dashboard_card_links_to_garden_anchor(self):
        with self.app.test_request_context("/"):
            html = render_template("dashboard.html", now=None, **self.context)

        self.assertIn("/garden#greenhouse", html)

    def test_garden_renders_greenhouse_section_and_chart(self):
        with self.app.test_request_context("/garden"):
            html = render_template("garden.html", now=None, garden=self.context["garden"], greenhouse=self.context["environment"]["greenhouse"])

        self.assertIn("Current greenhouse conditions", html)
        self.assertIn("Greenhouse temperature trend", html)
        self.assertIn("75.0", html)
        self.assertIn("44%", html)
        self.assertIn("Connected", html)
        self.assertIn("Observed at", html)
        self.assertIn("Latest reading", html)

    def test_garden_missing_humidity_is_safe(self):
        greenhouse = dict(self.context["environment"]["greenhouse"], humidity_display=None)
        with self.app.test_request_context("/garden"):
            html = render_template("garden.html", now=None, garden=self.context["garden"], greenhouse=greenhouse)

        self.assertIn("Unavailable", html)

    def test_environment_center_no_longer_renders_duplicate_greenhouse_section(self):
        with self.app.test_request_context("/environment"):
            html = render_template("environment.html", now=None, environment=self.context["environment"])

        self.assertNotIn("Current greenhouse conditions", html)
        self.assertNotIn("Greenhouse temperature trend", html)
        self.assertNotIn("greenhouse-temperature-chart", html)

    def test_garden_chart_uses_history_points_in_order(self):
        garden_js = (ROOT / "static" / "js" / "garden_center.js").read_text(encoding="utf-8")
        self.assertIn("history_points", garden_js)
        self.assertNotIn(".sort(", garden_js)

    def test_garden_route_returns_200_with_latest_reading_string(self):
        greenhouse = dict(self.context["environment"]["greenhouse"], latest_reading="2026-07-20T02:20:05+00:00")
        dashboard = make_garden_dashboard(greenhouse, self.context["garden"])

        response = dashboard.app.test_client().get("/garden")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Current greenhouse conditions", html)
        self.assertIn("75.0", html)
        self.assertIn("44%", html)
        self.assertIn("2026-07-20T02:20:05+00:00", html)

    def test_garden_route_returns_200_when_latest_reading_is_null(self):
        greenhouse = dict(self.context["environment"]["greenhouse"], latest_reading=None)
        dashboard = make_garden_dashboard(greenhouse, self.context["garden"])

        response = dashboard.app.test_client().get("/garden")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="garden-greenhouse-latest-reading">2026-07-20T02:20:05+00:00</strong>', html)

    def test_garden_uses_source_timestamp_when_latest_reading_is_null(self):
        greenhouse = dict(self.context["environment"]["greenhouse"], latest_reading=None)
        dashboard = make_garden_dashboard(greenhouse, self.context["garden"])

        response = dashboard.app.test_client().get("/garden")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="garden-greenhouse-latest-reading">2026-07-20T02:20:05+00:00</strong>', html)

    def test_garden_uses_observed_at_when_measurement_timestamps_are_missing(self):
        greenhouse = dict(self.context["environment"]["greenhouse"], latest_reading=None, source_timestamp=None)
        dashboard = make_garden_dashboard(greenhouse, self.context["garden"])

        response = dashboard.app.test_client().get("/garden")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="garden-greenhouse-latest-reading">2026-07-20T02:39:05+00:00</strong>', html)

    def test_garden_shows_unavailable_when_all_timestamps_are_missing(self):
        greenhouse = dict(
            self.context["environment"]["greenhouse"],
            latest_reading=None,
            source_timestamp=None,
            observed_at=None,
        )
        dashboard = make_garden_dashboard(greenhouse, self.context["garden"])

        response = dashboard.app.test_client().get("/garden")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="garden-greenhouse-latest-reading">Unavailable</strong>', html)
        self.assertNotIn("None", html)
        self.assertNotIn("undefined", html.lower())

    def test_garden_js_treats_latest_reading_as_string(self):
        garden_js = (ROOT / "static" / "js" / "garden_center.js").read_text(encoding="utf-8")
        self.assertIn("current.latest_reading || current.source_timestamp || current.observed_at", garden_js)
        self.assertNotIn("latest_reading?.timestamp", garden_js)
        self.assertNotIn("latest_reading.timestamp", garden_js)
        self.assertNotIn('latest_reading["timestamp"]', garden_js)


if __name__ == "__main__":
    unittest.main()
