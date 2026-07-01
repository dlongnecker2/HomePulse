from datetime import datetime, timedelta
from pathlib import Path

from modules.history.database import HistoryDatabase
from modules.history.models import MetricSnapshot
from modules.history.retention import retention_cutoff


INVALID_VALUES = {"", "unknown", "unavailable", "none", "null", "nan", "--", "—"}


class HistoryService:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self.database = HistoryDatabase(self.database_path())
        self.last_snapshot_time = None
        self.last_snapshot_count = 0

    def database_path(self):
        history = self.config.get("history", default={})
        return Path(history.get("database", "data/homepulse_history.db"))

    def refresh_config(self, config):
        self.config = config
        self.database = HistoryDatabase(self.database_path())

    def initialize(self):
        self.database.initialize()
        self.log.info(f"History database initialized: {self.database.path}")

    def enabled(self):
        return bool(self.config.get("history", "enabled", default=True))

    def snapshot_interval_minutes(self):
        return self.valid_positive_int(
            self.config.get("history", "snapshot_interval_minutes", default=5),
            default=5,
            minimum=1,
            maximum=1440,
        )

    def retention_days(self):
        return self.valid_positive_int(
            self.config.get("history", "retention_days", default=365),
            default=365,
            minimum=1,
            maximum=3650,
        )

    def record_metric(self, module, metric, value, unit=None, source=None, metadata=None):
        snapshot = self.build_snapshot(module, metric, value, unit=unit, source=source, metadata=metadata)
        if snapshot is None:
            return None
        self.database.insert_metric(snapshot)
        return snapshot

    def record_many(self, metrics):
        snapshots = []
        for metric in metrics or []:
            snapshot = self.metric_from_input(metric)
            if snapshot is not None:
                snapshots.append(snapshot)
        return self.database.insert_many(snapshots)

    def get_metrics(self, module, metric, start_time=None, end_time=None, limit=None):
        return [
            snapshot.to_dict()
            for snapshot in self.database.query_metrics(module, metric, start_time, end_time, limit)
        ]

    def get_latest(self, module, metric):
        snapshot = self.database.latest_metric(module, metric)
        return snapshot.to_dict() if snapshot else None

    def get_latest_all(self):
        return [snapshot.to_dict() for snapshot in self.database.latest_all()]

    def get_summary(self, module, period="today"):
        start_time, end_time = self.period_bounds(period)
        return self.database.summary(module, start_time=start_time, end_time=end_time)

    def prune_old_data(self, retention_days):
        cutoff = retention_cutoff(retention_days)
        pruned = self.database.prune_old_data(cutoff)
        if pruned:
            self.log.info(f"History retention pruned {pruned} old metric snapshot(s)")
        return pruned

    def snapshot(self, application):
        if not self.enabled():
            self.log.debug("History snapshot skipped because history collection is disabled")
            return 0
        metrics = self.collect_metrics(application)
        count = self.record_many(metrics)
        self.last_snapshot_time = str(datetime.now())
        self.last_snapshot_count = count
        if count:
            self.log.info(f"History snapshot recorded {count} metric(s)")
        else:
            self.log.debug("History snapshot completed with no numeric metrics to record")
        return count

    def collect_metrics(self, application):
        metrics = []
        metrics.extend(self.collect_solar(application))
        metrics.extend(self.collect_vehicle(application))
        metrics.extend(self.collect_energy(application))
        metrics.extend(self.collect_internet(application))
        return metrics

    def collect_solar(self, application):
        status = self.safe_status("solar", application.solar.get_status)
        return self.metrics_from_status(
            "solar",
            status,
            {
                "current_production_kw": ("current_production_kw", "kW"),
                "production_today_kwh": ("production_today_kwh", "kWh"),
                "production_last_7_days_kwh": ("production_last_7_days_kwh", "kWh"),
                "lifetime_production_kwh": ("lifetime_production_kwh", "kWh"),
            },
            source=status.get("source", "Solar Center") if status else "Solar Center",
        )

    def collect_vehicle(self, application):
        status = self.safe_status("vehicle", application.vehicle.get_status)
        return self.metrics_from_status(
            "vehicle",
            status,
            {
                "battery_percent": ("battery_percent", "%"),
                "ev_range_mi": ("range_mi", "mi"),
                "odometer_mi": ("odometer_mi", "mi"),
                "lifetime_energy_kwh": ("lifetime_energy_kwh", "kWh"),
                "lifetime_efficiency_mi_per_kwh": ("lifetime_efficiency_mi_per_kwh", "mi/kWh"),
            },
            source="Vehicle Center",
        )

    def collect_energy(self, application):
        status = self.safe_status("energy", application.energy.get_status)
        return self.metrics_from_status(
            "energy",
            status,
            {
                "charging_power_kw": ("power_kw", "kW"),
                "session_energy_kwh": ("session_energy_kwh", "kWh"),
                "estimated_miles_added": ("estimated_miles_added", "mi"),
                "estimated_cost": ("estimated_cost", "USD"),
            },
            source=status.get("charger_name", "Energy Center") if status else "Energy Center",
        )

    def collect_internet(self, application):
        status = application.status.get()
        internet = status.get("internet", {})
        speedtest = status.get("speedtest", {})
        rows = []
        mapping = (
            ("health_score", internet.get("score"), "score", "Internet Health"),
            ("latency_ms", internet.get("latency"), "ms", "Internet Health"),
            ("packet_loss_percent", internet.get("packet_loss"), "%", "Internet Health"),
            ("download_mbps", speedtest.get("download"), "Mbps", "Speed Test"),
            ("upload_mbps", speedtest.get("upload"), "Mbps", "Speed Test"),
        )
        for metric, value, unit, source in mapping:
            rows.append({"module": "internet", "metric": metric, "value": value, "unit": unit, "source": source})
        return rows

    def safe_status(self, module, function):
        try:
            return function() or {}
        except Exception as exc:
            self.log.warning(f"History snapshot skipped {module} metrics: {exc}")
            self.log.debug(f"History snapshot {module} traceback", exc_info=True)
            return {}

    def metrics_from_status(self, module, status, mapping, source):
        rows = []
        for metric, (status_key, unit) in mapping.items():
            rows.append({
                "module": module,
                "metric": metric,
                "value": status.get(status_key) if status else None,
                "unit": unit,
                "source": source,
            })
        return rows

    def metric_from_input(self, metric):
        if isinstance(metric, MetricSnapshot):
            return metric if self.numeric_value(metric.value) is not None else None
        if not isinstance(metric, dict):
            return None
        return self.build_snapshot(
            metric.get("module"),
            metric.get("metric"),
            metric.get("value"),
            unit=metric.get("unit"),
            source=metric.get("source"),
            metadata=metric.get("metadata"),
            timestamp=metric.get("timestamp"),
        )

    def build_snapshot(self, module, metric, value, unit=None, source=None, metadata=None, timestamp=None):
        if not module or not metric:
            return None
        number = self.numeric_value(value)
        if number is None:
            return None
        return MetricSnapshot.create(module, metric, number, unit=unit, source=source, metadata=metadata, timestamp=timestamp)

    @staticmethod
    def numeric_value(value):
        if value is None:
            return None
        text = str(value).strip()
        if text.lower() in INVALID_VALUES:
            return None
        try:
            number = float(text.replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            return None
        if number != number:
            return None
        return number

    @staticmethod
    def valid_positive_int(value, default, minimum, maximum):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        if number < minimum or number > maximum:
            return default
        return number

    @staticmethod
    def period_bounds(period):
        now = datetime.now()
        if period == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0), now
        if period == "7d":
            return now - timedelta(days=7), now
        if period == "30d":
            return now - timedelta(days=30), now
        return now - timedelta(hours=24), now
