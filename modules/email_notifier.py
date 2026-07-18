import smtplib
import re
from datetime import datetime
from email.message import EmailMessage

from version import APP_NAME, APP_VERSION


def parse_recipients(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        pieces = []
        for item in value:
            pieces.extend(re.split(r"[,;\n]+", str(item)))
    else:
        pieces = re.split(r"[,;\n]+", str(value))

    recipients = []
    seen = set()
    for piece in pieces:
        address = piece.strip()
        if not address:
            continue
        key = address.lower()
        if key in seen:
            continue
        recipients.append(address)
        seen.add(key)
    return recipients


class EmailNotifier:
    NOTIFICATION_DEFAULTS = {
        "recovery_started": True,
        "recovery_success": True,
        "recovery_failed": True,
        "recovery_skipped": True,
        "diagnostics_failed": True,
        "daily_summary": False,
    }

    def __init__(self, config, log, db=None):
        self.config = config
        self.log = log
        self.db = db

    def send_test_email(self, timestamp=None):
        timestamp = timestamp or str(datetime.now())
        settings = self.settings()
        subject = f"{APP_NAME} Test Email"
        body = (
            f"{APP_NAME} SMTP configuration was verified.\n\n"
            f"SMTP server: {settings.get('smtp_server')}\n"
            f"Timestamp: {timestamp}\n"
            f"{APP_NAME} version: {APP_VERSION}\n\n"
            f"This message confirms {APP_NAME} can send email using the configured SMTP server.\n"
        )
        return self.send_email(
            subject=subject,
            body=body,
            event_type="email_test",
            event_label="Test email",
            ignore_notification_toggle=True,
        )

    def send_recovery_started(self, context):
        if not self.notification_enabled("recovery_started"):
            return False
        mode_label = self._recovery_mode_label(context)
        subject = f"{APP_NAME} Recovery Started - {mode_label}"
        body = self._recovery_body(
            title=f"{mode_label} recovery started",
            context=context,
            result=None,
            end_time=None,
        )
        return self.send_email(subject, body, "email_recovery_started", "Recovery started email")

    def send_reboot_notification(self, context, result):
        notification_type = "recovery_success" if result.internet_restored else "recovery_failed"
        if not self.notification_enabled(notification_type):
            return False
        status = "Succeeded" if result.internet_restored else "Failed"
        mode_label = self._result_mode_label(result)
        subject = f"{APP_NAME} {mode_label} Recovery {status}"
        body = self._recovery_body(
            title=f"{mode_label} recovery {status.lower()}",
            context=context,
            result=result,
            end_time=context.get("end_time"),
        )
        return self.send_email(
            subject=subject,
            body=body,
            event_type=f"email_{notification_type}",
            event_label=f"Recovery {status.lower()} email",
        )

    def send_recovery_skipped(self, context, reason):
        if not self.notification_enabled("recovery_skipped"):
            return False
        subject = f"{APP_NAME} Recovery Skipped"
        body = self._recovery_body(
            title="Recovery skipped",
            context=context,
            result=None,
            end_time=context.get("end_time"),
            skip_reason=reason,
        )
        return self.send_email(subject, body, "email_recovery_skipped", "Recovery skipped email")

    def send_diagnostics_failed(self, diagnostic_result):
        if not self.notification_enabled("diagnostics_failed"):
            return False
        subject = f"{APP_NAME} Diagnostics Failed"
        body = (
            f"A {APP_NAME} diagnostic check failed.\n\n"
            f"Test: {diagnostic_result.test_name}\n"
            f"Status: {diagnostic_result.status}\n"
            f"Timestamp: {diagnostic_result.timestamp}\n"
            f"Message: {diagnostic_result.message}\n"
        )
        return self.send_email(subject, body, "email_diagnostics_failed", "Diagnostics failed email")

    def send_daily_summary(self, summary):
        if not self.notification_enabled("daily_summary"):
            return False
        subject = f"{APP_NAME} Daily Summary"
        body = "\n".join(str(line) for line in summary)
        return self.send_email(subject, body, "email_daily_summary", "Daily summary email")

    def send_energy_charging_alert(self, status, started):
        subject = "EV Charging Started" if started else "EV Charging Stopped"
        label = "EV charging started email" if started else "EV charging stopped email"
        event_type = "email_ev_charging_started" if started else "email_ev_charging_stopped"
        body = (
            f"{subject}\n\n"
            f"Charger name: {status.get('charger_name', 'Unavailable')}\n"
            f"Vehicle name: {status.get('vehicle_name', 'Unavailable')}\n"
            f"Status: {status.get('status', 'Unavailable')}\n"
            f"Power: {status.get('power_kw', 0)} kW\n"
            f"Energy added: {status.get('session_energy_kwh', 0)} kWh\n"
            f"Cost: ${float(status.get('estimated_cost') or 0):.2f}\n"
            f"Miles added: {status.get('estimated_miles_added', 0)} mi\n"
            f"Charging time: {self._friendly_duration(status.get('charging_time'))}\n"
        )
        return self.send_email(subject, body, event_type, label)

    @staticmethod
    def _friendly_duration(value):
        if value in (None, "", "unknown", "unavailable"):
            return "Unavailable"
        raw = str(value).strip()
        if ":" in raw:
            parts = [int(part or 0) for part in raw.split(":")]
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + part
            return EmailNotifier._format_seconds(seconds)
        try:
            return EmailNotifier._format_seconds(int(float(raw)))
        except ValueError:
            return raw

    @staticmethod
    def _format_seconds(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
        return f"{seconds}s"

    def send_email(self, subject, body, event_type, event_label, ignore_notification_toggle=False):
        settings = self.settings()
        if not ignore_notification_toggle and not settings.get("email_notifications_enabled"):
            return False

        missing = [
            key for key in ("smtp_server", "smtp_port", "smtp_from_email")
            if not settings.get(key)
        ]
        if missing:
            self._record_email_event(
                event_type,
                f"{event_label} not sent; missing setting(s): {', '.join(missing)}",
                success=False,
            )
            return False
        if not settings.get("smtp_recipients"):
            self._record_email_event(
                event_type,
                "No notification recipients configured.",
                success=False,
                status="WARN",
            )
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings["smtp_from_email"]
        message["To"] = settings["smtp_to_email"]
        message.set_content(body)

        try:
            self._send_message(message, settings)
            self._record_email_event(
                event_type,
                f"{event_label} sent to {settings['smtp_to_email']}.",
                success=True,
            )
            return True
        except Exception as exc:
            self.log.exception(f"{event_label} failed: {exc}")
            self._record_email_event(event_type, f"{event_label} failed: {exc}", success=False)
            return False

    def _send_message(self, message, settings):
        host = settings["smtp_server"]
        port = int(settings.get("smtp_port") or 587)
        username = settings.get("smtp_username", "")
        password = settings.get("smtp_password", "")
        use_ssl = bool(settings.get("smtp_use_ssl"))
        use_tls = bool(settings.get("smtp_use_tls"))

        smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        with smtp_class(host, port, timeout=20) as server:
            if use_tls and not use_ssl:
                server.starttls()
            if username:
                server.login(username, password)
            server.send_message(
                message,
                from_addr=settings["smtp_from_email"],
                to_addrs=settings["smtp_recipients"],
            )

    def settings(self):
        raw = dict(self.config.get("email", default={}))
        return {
            "email_notifications_enabled": raw.get(
                "email_notifications_enabled",
                raw.get("enabled", False),
            ),
            "smtp_server": raw.get("smtp_server", raw.get("smtp_host", "")),
            "smtp_port": int(raw.get("smtp_port", 587) or 587),
            "smtp_username": raw.get("smtp_username", raw.get("username", "")),
            "smtp_password": raw.get("smtp_password", raw.get("password", "")),
            "smtp_use_tls": raw.get("smtp_use_tls", raw.get("use_tls", False)),
            "smtp_use_ssl": raw.get("smtp_use_ssl", False),
            "smtp_from_email": raw.get("smtp_from_email", raw.get("from_address", "")),
            "smtp_to_email": ", ".join(parse_recipients(raw.get("smtp_to_email", raw.get("to_address", "")))),
            "smtp_recipients": parse_recipients(raw.get("smtp_to_email", raw.get("to_address", ""))),
            "notifications": self.notification_settings(raw),
        }

    def notification_settings(self, raw=None):
        raw = raw if raw is not None else self.config.get("email", default={})
        configured = dict(raw.get("notifications") or {})
        return {
            key: bool(configured.get(key, default))
            for key, default in self.NOTIFICATION_DEFAULTS.items()
        }

    def notification_enabled(self, notification_type):
        settings = self.settings()
        return (
            bool(settings.get("email_notifications_enabled"))
            and bool(settings.get("notifications", {}).get(notification_type, False))
        )

    def _recovery_body(self, title, context, result, end_time, skip_reason=None):
        recovery = self.config.get("router_reboot", default={})
        fallback_method = result.method if result else "Unavailable"
        device = (
            recovery.get("recovery_entity_id")
            or recovery.get("matter_entity_id")
            or recovery.get("recovery_device_name")
            or recovery.get("recovery_device_ip")
            or fallback_method
        )
        start_time = context.get("start_time") or context.get("timestamp", "Unavailable")
        end_time = end_time or "In progress"
        recovery_mode = self._context_mode_label({"recovery_mode": context.get("recovery_mode")})
        result_text = result.result if result else "Recovery command has started."
        if skip_reason:
            result_text = skip_reason
        duration = result.elapsed_recovery_time if result else "In progress"
        verification = self._verification_text(result)

        return (
            f"{title}\n\n"
            f"Reason: {context.get('reason', 'Unavailable')}\n"
            f"Recovery mode: {recovery_mode}\n"
            f"Recovery device/entity: {device}\n"
            f"Start time: {start_time}\n"
            f"End time: {end_time}\n"
            f"Result: {result_text}\n"
            f"Downtime/recovery duration: {duration}\n"
            f"Verification result: {verification}\n\n"
            "Network metrics\n"
            f"Latency: {context.get('latency', 'Unavailable')}\n"
            f"Download: {context.get('download', 'Unavailable')}\n"
            f"Upload: {context.get('upload', 'Unavailable')}\n"
            f"Internet quality score: {context.get('quality_score', 'Unavailable')}\n"
            f"Failed checks: {context.get('failed_checks', 'Unavailable')}\n"
            f"Last successful speed test: {context.get('last_successful_speedtest', 'Unavailable')}\n"
            f"Maintenance window: {context.get('maintenance_window', 'Unavailable')}\n"
        )

    @staticmethod
    def _verification_text(result):
        if not result:
            return "Pending"
        if result.dry_run:
            return "Dry Run only; no power command was sent."
        if result.internet_restored:
            return "Internet restored after recovery."
        if result.router_responded:
            return "Recovery command completed, but internet restoration was not confirmed."
        if result.command_sent:
            return "Recovery command was sent, but device response was not confirmed."
        return "Recovery command was not sent."

    @staticmethod
    def _context_mode_label(context):
        mode = str(context.get("recovery_mode") or "").strip().lower()
        if mode == "live":
            return "Live automatic recovery"
        if mode == "dry_run":
            return "Dry Run"
        if mode == "skipped":
            return "Recovery skipped"
        return "Recovery"

    def _recovery_mode_label(self, context):
        return self._context_mode_label(context)

    @staticmethod
    def _result_mode_label(result):
        if getattr(result, "dry_run", False):
            return "Dry Run"
        return "Live"

    def _record_email_event(self, event_type, message, success, status=None):
        status = status or ("SUCCESS" if success else "FAIL")
        level_message = f"{status} - {message}"
        if success:
            self.log.info(level_message)
        else:
            self.log.warning(level_message)
        if not self.db:
            return
        try:
            self.db.add_event(
                timestamp=str(datetime.now()),
                event_type=event_type,
                message=level_message,
            )
        except Exception as exc:
            self.log.exception(f"Could not write email event to SQLite: {exc}")
