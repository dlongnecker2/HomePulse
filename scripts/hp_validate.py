#!/usr/bin/env python3
"""Developer validation helper for reusing an existing HomePulse instance.

Default behavior:
- Reuse a running HomePulse instance if /api/status is healthy.
- If not running, report clearly and exit non-zero.

Optional behavior:
- Use --start to launch HomePulse via normal entry point (router_monitor.py),
  wait briefly for readiness, then run endpoint validation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUIRED_ENDPOINTS = (
    "/api/status",
    "/api/home/status",
    "/api/timeline/recent",
    "/api/notifications/recent",
)


@dataclass
class CheckResult:
    endpoint: str
    ok: bool
    status_code: Optional[int] = None
    error: str = ""
    elapsed_seconds: float = 0.0


def fetch_status(base_url: str, endpoint: str, timeout: float) -> CheckResult:
    start_time = time.perf_counter()
    url = f"{base_url.rstrip('/')}{endpoint}"
    request = Request(url=url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            code = int(getattr(response, "status", 200))
            _ = response.read(512)
            elapsed = time.perf_counter() - start_time
            return CheckResult(endpoint=endpoint, ok=(code == 200), status_code=code, elapsed_seconds=elapsed)
    except HTTPError as exc:
        elapsed = time.perf_counter() - start_time
        return CheckResult(
            endpoint=endpoint,
            ok=False,
            status_code=exc.code,
            error=str(exc),
            elapsed_seconds=elapsed,
        )
    except URLError as exc:
        elapsed = time.perf_counter() - start_time
        return CheckResult(
            endpoint=endpoint,
            ok=False,
            error=f"connection error: {exc.reason}",
            elapsed_seconds=elapsed,
        )
    except Exception as exc:  # pragma: no cover - defensive
        elapsed = time.perf_counter() - start_time
        return CheckResult(endpoint=endpoint, ok=False, error=str(exc), elapsed_seconds=elapsed)


def check_required_endpoints(base_url: str, timeout: float) -> tuple[bool, list[CheckResult]]:
    results = [fetch_status(base_url, endpoint, timeout) for endpoint in REQUIRED_ENDPOINTS]
    return all(item.ok for item in results), results


def print_results(results: list[CheckResult]) -> None:
    for item in results:
        duration = f", {item.elapsed_seconds:.2f}s"
        if item.ok:
            print(f"PASS {item.endpoint} (HTTP {item.status_code}{duration})")
        elif item.status_code is not None:
            print(f"FAIL {item.endpoint} (HTTP {item.status_code}{duration})")
        else:
            print(f"FAIL {item.endpoint} ({item.error or 'unknown error'}{duration})")


def start_homepulse(repo_root: Path, startup_timeout: float) -> tuple[bool, Optional[subprocess.Popen], str]:
    """Attempt to start HomePulse via normal entry point.

    Returns (ready, process, message).
    """
    command = [sys.executable, "router_monitor.py"]
    process = subprocess.Popen(
        command,
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    deadline = time.time() + startup_timeout
    buffered_output = ""
    while time.time() < deadline:
        healthy = fetch_status("http://127.0.0.1:8080", "/api/status", timeout=1.5)
        if healthy.ok:
            return True, process, f"HomePulse started or became available (pid={process.pid})."

        if process.poll() is not None:
            try:
                buffered_output = process.stdout.read() if process.stdout else ""
            except Exception:
                buffered_output = ""
            lower_output = buffered_output.lower()
            if "port 8080 is already in use" in lower_output:
                retry = fetch_status("http://127.0.0.1:8080", "/api/status", timeout=1.5)
                if retry.ok:
                    return True, None, "Port 8080 already in use, but HomePulse is healthy; reusing existing instance."
                return False, None, "Port 8080 already in use and /api/status is not healthy."
            tail = "\n".join(buffered_output.splitlines()[-6:]).strip()
            return False, None, (
                "HomePulse exited before becoming ready."
                + (f"\nLast output:\n{tail}" if tail else "")
            )

        time.sleep(0.5)

    return False, process, "Timed out waiting for HomePulse to become ready."


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate HomePulse endpoints, reusing existing instance when available.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Base URL for HomePulse")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--start",
        action="store_true",
        help="If HomePulse is not running, try starting it via router_monitor.py before validation.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for startup when --start is used.",
    )
    args = parser.parse_args()

    status = fetch_status(args.base_url, "/api/status", timeout=args.timeout)
    started_process: Optional[subprocess.Popen] = None

    if status.ok:
        print("HomePulse already running; using existing instance.")
    else:
        if not args.start:
            print("HomePulse is not running (or /api/status is unhealthy).")
            print("Tip: start HomePulse first, or run this helper with --start.")
            print(f"Status check: {'HTTP ' + str(status.status_code) if status.status_code else status.error}")
            return 2

        repo_root = Path(__file__).resolve().parents[1]
        print("HomePulse not detected; attempting start via router_monitor.py ...")
        ready, process, message = start_homepulse(repo_root, startup_timeout=args.startup_timeout)
        print(message)
        if not ready:
            if process and process.poll() is None:
                process.terminate()
            return 3
        started_process = process

    all_ok, results = check_required_endpoints(args.base_url, timeout=args.timeout)
    print_results(results)

    if started_process and started_process.poll() is not None:
        print("Warning: started HomePulse process exited during validation.")

    if all_ok:
        print("Validation passed.")
        return 0

    print("Validation failed: one or more required endpoints are unhealthy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
