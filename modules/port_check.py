import socket


def is_port_in_use(host, port):
    """
    Return True if the given host/port is already accepting connections.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def check_dashboard_port(config, log):
    host = config.get("dashboard", "host")
    port = config.get("dashboard", "port")

    # 0.0.0.0 means "listen on all interfaces".
    # For checking locally, use localhost.
    check_host = "127.0.0.1" if host == "0.0.0.0" else host

    if is_port_in_use(check_host, port):
        log.error("=" * 60)
        log.error("HomePulse cannot start the dashboard.")
        log.error(f"Port {port} is already in use.")
        log.error("Another HomePulse instance may already be running.")
        log.error("Stop the existing instance, then start HomePulse again.")
        log.error("=" * 60)
        raise RuntimeError(
            f"Dashboard port {port} is already in use. "
            "Another HomePulse instance may already be running."
        )
