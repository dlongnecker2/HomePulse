import smtplib
from email.message import EmailMessage


class EmailNotifier:
    def __init__(self, config, log):
        self.config = config
        self.log = log

    def send_reboot_notification(self, context, result):
        if not self.config.get("email", "enabled", default=False):
            return False

        message = EmailMessage()
        message["Subject"] = "HomePulse - Router Automatically Rebooted"
        message["From"] = self.config.get("email", "from_address", default="")
        message["To"] = self.config.get("email", "to_address", default="")
        message.set_content(self._body(context, result))

        try:
            host = self.config.get("email", "smtp_host")
            port = int(self.config.get("email", "smtp_port", default=587))
            username = self.config.get("email", "username", default="")
            password = self.config.get("email", "password", default="")
            use_tls = self.config.get("email", "use_tls", default=True)
            with smtplib.SMTP(host, port, timeout=20) as server:
                if use_tls:
                    server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(message)
            self.log.info("Router reboot email notification sent")
            return True
        except Exception as exc:
            self.log.exception(f"Router reboot email notification failed: {exc}")
            return False

    @staticmethod
    def _body(context, result):
        return (
            f"Date/Time: {context['timestamp']}\n"
            f"Reason for reboot: {context['reason']}\n"
            f"Internet Quality Score: {context['quality_score']}\n"
            f"Download speed: {context['download']}\n"
            f"Upload speed: {context['upload']}\n"
            f"Latency: {context['latency']}\n"
            f"Packet loss: {context['packet_loss']}\n"
            f"Number of failed checks: {context['failed_checks']}\n"
            f"Last successful speed test: {context['last_successful_speedtest']}\n"
            f"Router uptime before reboot (if available): {result.router_uptime_before}\n"
            f"Maintenance window: {context['maintenance_window']}\n"
            "Result:\n"
            f"    • Reboot command sent: {result.command_sent}\n"
            f"    • Router responded: {result.router_responded}\n"
            f"    • Internet restored: {result.internet_restored}\n"
            f"    • {result.result}\n"
            f"Elapsed recovery time: {result.elapsed_recovery_time}\n"
        )
