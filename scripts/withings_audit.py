from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import getpass
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from modules.config import CONFIG_FILE, Config
from modules.weight_progress.database import WeightProgressDatabase
from modules.weight_progress.withings_api import (
    WITHINGS_SCOPE,
    WithingsAuditError,
    WithingsMeasureClient,
    WithingsOAuthClient,
    build_history_measurements,
    compare_readings,
)


DEFAULT_CALLBACK = "http://127.0.0.1:8765/callback"


def main():
    parser = argparse.ArgumentParser(
        description="Configure Withings OAuth or run a read-only type-170 audit."
    )
    parser.add_argument(
        "action",
        choices=(
            "configure",
            "verify-credentials",
            "authorize",
            "audit",
            "import-history",
            "status",
        ),
    )
    parser.add_argument("--mode", choices=("direct", "signed"), default="direct")
    parser.add_argument(
        "--secret-from-clipboard",
        action="store_true",
        help="Read only the client secret from the Windows clipboard.",
    )
    parser.add_argument(
        "--expected-inserts",
        type=int,
        help=(
            "For import-history, stop unless the dry-run insert count matches "
            "this explicit value."
        ),
    )
    args = parser.parse_args()
    if args.secret_from_clipboard and args.action != "configure":
        parser.error("--secret-from-clipboard is valid only with configure")
    if args.expected_inserts is not None:
        if args.action != "import-history":
            parser.error("--expected-inserts is valid only with import-history")
        if args.expected_inserts <= 0:
            parser.error("--expected-inserts must be greater than zero")
    try:
        if args.action == "configure":
            configure(secret_from_clipboard=args.secret_from_clipboard)
        elif args.action == "verify-credentials":
            verify_credentials()
        elif args.action == "authorize":
            authorize(args.mode)
        elif args.action == "audit":
            audit()
        elif args.action == "import-history":
            import_history(expected_inserts=args.expected_inserts)
        else:
            status()
        return 0
    except (WithingsAuditError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def configure(secret_from_clipboard=False):
    config = Config()
    current = oauth_settings(config)
    if secret_from_clipboard:
        client_id = str(current.get("client_id") or "")
        callback = str(current.get("redirect_uri") or "")
        if not client_id or not callback:
            raise WithingsAuditError(
                "Client ID and callback must already be configured."
            )
        client_secret = read_windows_clipboard().rstrip("\r\n")
        validate_client_secret(client_secret)
        current["client_secret"] = client_secret
        current["access_token"] = ""
        current["refresh_token"] = ""
        current["expires_at"] = 0
        current["user_id"] = ""
        save_oauth_settings(config, current)
        print(f"saved_secret_length={len(client_secret)}")
        print("saved_secret_appears_valid=true")
        return

    client_id = input("Withings client ID: ").strip()
    client_secret = getpass.getpass("Withings client secret (hidden): ")
    callback = input(f"Callback URL [{DEFAULT_CALLBACK}]: ").strip() or DEFAULT_CALLBACK
    validate_loopback_callback(callback)
    if not client_id or not client_secret:
        raise WithingsAuditError("Client ID and client secret are required.")
    validate_client_secret(client_secret)
    current.update(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": callback,
            "scope": WITHINGS_SCOPE,
            "access_token": "",
            "refresh_token": "",
            "expires_at": 0,
            "user_id": "",
        }
    )
    save_oauth_settings(config, current)
    print("Withings application settings saved locally in ignored config.json.")


def validate_client_secret(value):
    if not value:
        raise WithingsAuditError("Client secret is empty; nothing was saved.")
    if len(value) == 1:
        raise WithingsAuditError(
            "One-character client secrets are rejected; nothing was saved."
        )
    if "*" in value:
        raise WithingsAuditError(
            "Masked client secrets containing asterisks are rejected."
        )
    if '"' in value or "'" in value:
        raise WithingsAuditError(
            "Client secret contains quotation marks; nothing was saved."
        )
    if value != value.strip() or any(char.isspace() for char in value):
        raise WithingsAuditError(
            "Client secret contains whitespace corruption; nothing was saved."
        )
    return value


def read_windows_clipboard():
    if os.name != "nt":
        raise WithingsAuditError(
            "Clipboard secret setup is supported only on Windows."
        )
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    if not user32.OpenClipboard(None):
        raise WithingsAuditError("Windows clipboard could not be opened.")
    handle = None
    pointer = None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            raise WithingsAuditError(
                "Windows clipboard does not contain Unicode text."
            )
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise WithingsAuditError("Windows clipboard text could not be read.")
        return ctypes.wstring_at(pointer)
    finally:
        if pointer:
            kernel32.GlobalUnlock(handle)
        user32.CloseClipboard()


def verify_credentials():
    config = Config()
    settings = oauth_settings(config)
    client_id = str(settings.get("client_id") or "")
    stored_secret = str(settings.get("client_secret") or "")
    print(f"config_file={config_file_path()}")
    print(f"windows_account={getpass.getuser()}")
    print(f"client_id_present={str(bool(client_id)).lower()}")
    print(f"client_secret_present={str(bool(stored_secret)).lower()}")
    print(f"client_id_length={len(client_id)}")
    print(f"stored_secret_length={len(stored_secret)}")
    print(
        "stored_secret_leading_or_trailing_whitespace="
        f"{str(stored_secret != stored_secret.strip()).lower()}"
    )
    print(f"stored_secret_contains_asterisks={str('*' in stored_secret).lower()}")
    print(
        "stored_secret_contains_internal_whitespace="
        f"{str(any(char.isspace() for char in stored_secret[1:-1])).lower()}"
    )
    print(
        "stored_secret_is_hexadecimal="
        f"{str(bool(re.fullmatch(r'[0-9a-fA-F]+', stored_secret))).lower()}"
    )
    dashboard_secret = getpass.getpass("Current dashboard secret (hidden): ")
    print(
        "dashboard_secret_matches_stored="
        f"{str(hmac.compare_digest(dashboard_secret, stored_secret)).lower()}"
    )


def authorize(mode="direct"):
    config = Config()
    settings = oauth_settings(config)
    oauth = oauth_client(settings)
    callback = validate_loopback_callback(settings.get("redirect_uri"))
    authorization_url, state = oauth.authorization_url()
    result = {}
    handoff_dir = PROJECT_ROOT / "tmp"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    (handoff_dir / "withings_authorize_url.txt").write_text(
        authorization_url + "\n", encoding="utf-8"
    )

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != callback.path:
                self.send_error(404)
                return
            params = parse_qs(parsed.query)
            result["state"] = (params.get("state") or [""])[0]
            result["code"] = (params.get("code") or [""])[0]
            result["error"] = (params.get("error") or [""])[0]
            body = b"Authorization received. You may close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer((callback.hostname, callback.port), CallbackHandler)
    server.timeout = 180
    print("Open this URL in your browser and approve user.metrics access:")
    print(authorization_url)
    server.handle_request()
    server.server_close()
    if not result:
        raise WithingsAuditError("Authorization callback timed out.")
    if result.get("error"):
        raise WithingsAuditError("Withings authorization was declined or failed.")
    if result.get("state") != state:
        raise WithingsAuditError("Withings authorization state did not match.")
    tokens = oauth.exchange_code(result.get("code"), mode=mode)
    for line in oauth.last_diagnostics:
        print(line)
    persist_tokens(config, settings, tokens, mode=mode)
    (handoff_dir / "withings_authorize_complete.txt").write_text(
        "completed\n", encoding="utf-8"
    )
    print("Withings authorization completed and tokens were stored locally.")


def audit():
    config = Config()
    settings = oauth_settings(config)
    oauth = oauth_client(settings)

    def refresh_access_token():
        mode = settings.get("auth_mode") or "direct"
        tokens = oauth.refresh(settings.get("refresh_token"), mode=mode)
        persist_tokens(config, settings, tokens, mode=mode)
        return tokens.access_token

    if int(settings.get("expires_at") or 0) <= int(time.time()) + 60:
        access_token = refresh_access_token()
    else:
        access_token = settings.get("access_token")
    result = WithingsMeasureClient(
        access_token, refresh_access_token=refresh_access_token
    ).fetch_visceral_fat_history()
    homepulse = load_homepulse_visceral_readings(config)
    present, new = compare_readings(result.readings, homepulse)

    print(f"pages={result.pages_retrieved}")
    print(f"measurement_groups={result.groups_inspected}")
    print(f"type_170_unique={len(result.readings)}")
    print(f"duplicates={result.duplicate_count}")
    print(f"earliest={format_date(result.readings[0]) if result.readings else '--'}")
    print(f"latest={format_date(result.readings[-1]) if result.readings else '--'}")
    print(f"homepulse_unique={len(homepulse)}")
    print(f"already_present={len(present)}")
    print(f"new_readings={len(new)}")
    print(f"new_earliest={format_date(new[0]) if new else '--'}")
    print(f"new_latest={format_date(new[-1]) if new else '--'}")
    if result.rejected_startdate_status is not None:
        print(f"startdate_zero_rejected_status={result.rejected_startdate_status}")
    for reading in result.readings[:5]:
        print(
            "sample="
            f"{reading.timestamp_utc.isoformat(timespec='seconds')},"
            f"{reading.value:g},{reading.masked_source_id()}"
        )


def import_history(expected_inserts=None):
    config = Config()
    settings = oauth_settings(config)
    oauth = oauth_client(settings)

    def refresh_access_token():
        mode = settings.get("auth_mode") or "direct"
        tokens = oauth.refresh(settings.get("refresh_token"), mode=mode)
        persist_tokens(config, settings, tokens, mode=mode)
        return tokens.access_token

    if int(settings.get("expires_at") or 0) <= int(time.time()) + 60:
        access_token = refresh_access_token()
    else:
        access_token = settings.get("access_token")
    result = WithingsMeasureClient(
        access_token, refresh_access_token=refresh_access_token
    ).fetch_visceral_fat_history()

    homepulse = load_homepulse_visceral_readings(config)
    _, new_readings = compare_readings(result.readings, homepulse)
    database_path = weight_progress_database_path(config)
    database = WeightProgressDatabase(database_path)
    existing_measurements = database.query_measurements()
    proposed = build_history_measurements(
        new_readings, existing_measurements
    )
    print(f"dry_run_proposed_inserts={len(proposed)}")
    if not proposed:
        raise WithingsAuditError(
            "Dry run did not produce any new inserts; import stopped."
        )
    if expected_inserts is not None and len(proposed) != expected_inserts:
        raise WithingsAuditError(
            "Dry-run insert count did not match --expected-inserts; import stopped."
        )

    backup_path = backup_weight_progress_database(database_path)
    print(f"backup_path={backup_path}")
    inserted = sum(
        1 for measurement in proposed if database.insert_measurement(measurement)
    )
    print(f"inserted={inserted}")
    if inserted != len(proposed):
        raise WithingsAuditError(
            "Not every proposed row was inserted; rerunning is safe."
        )

    final_measurements = database.query_measurements()
    final_visceral = [
        item for item in final_measurements if item.visceral_fat_index is not None
    ]
    _, remaining_new = compare_readings(
        result.readings, load_homepulse_visceral_readings(config)
    )
    print(f"remaining_new_readings={len(remaining_new)}")
    print(f"total_measurements={len(final_measurements)}")
    print(f"visceral_measurements={len(final_visceral)}")
    print(
        "visceral_earliest="
        f"{final_visceral[0].source_timestamp if final_visceral else '--'}"
    )
    print(
        "visceral_latest="
        f"{final_visceral[-1].source_timestamp if final_visceral else '--'}"
    )


def status():
    settings = oauth_settings(Config())
    client_secret = str(settings.get("client_secret") or "")
    print(f"client_configured={bool(settings.get('client_id') and settings.get('client_secret'))}")
    print(f"callback_configured={bool(settings.get('redirect_uri'))}")
    print(f"redirect_uri={settings.get('redirect_uri') or '--'}")
    print(
        "client_secret_whitespace_clean="
        f"{bool(client_secret) and client_secret == client_secret.strip()}"
    )
    print(f"authorized={bool(settings.get('access_token') and settings.get('refresh_token'))}")
    print(f"scope={settings.get('scope') or WITHINGS_SCOPE}")


def oauth_settings(config):
    return dict(config.data.get("weight_progress", {}).get("withings_oauth", {}))


def save_oauth_settings(config, settings):
    config.data.setdefault("weight_progress", {})["withings_oauth"] = dict(settings)
    config.save()


def persist_tokens(config, settings, tokens, mode=None):
    settings.update(
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": int(time.time()) + tokens.expires_in,
            "user_id": tokens.user_id,
            "scope": tokens.scope,
            "auth_mode": mode or settings.get("auth_mode") or "direct",
        }
    )
    save_oauth_settings(config, settings)


def oauth_client(settings):
    return WithingsOAuthClient(
        settings.get("client_id"),
        settings.get("client_secret"),
        settings.get("redirect_uri"),
    )


def config_file_path():
    return (PROJECT_ROOT / CONFIG_FILE).resolve()


def weight_progress_database_path(config):
    relative = config.get(
        "weight_progress", "database", default="data/weight_progress.db"
    )
    path = (PROJECT_ROOT / relative).resolve()
    if path != PROJECT_ROOT and PROJECT_ROOT not in path.parents:
        raise WithingsAuditError(
            "Weight Progress database is outside the HomePulse repository."
        )
    return path


def backup_weight_progress_database(database_path):
    database_path = Path(database_path).resolve()
    backup_dir = (PROJECT_ROOT / "data" / "backups").resolve()
    if PROJECT_ROOT not in backup_dir.parents:
        raise WithingsAuditError("Backup directory is outside HomePulse.")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"weight_progress-before-withings-{timestamp}.db"
    source = sqlite3.connect(
        f"file:{database_path.as_posix()}?mode=ro", uri=True
    )
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise WithingsAuditError("Weight Progress backup integrity check failed.")
        destination.commit()
    finally:
        destination.close()
        source.close()
    return backup_path


def validate_loopback_callback(value):
    parsed = urlparse(str(value or ""))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or not parsed.port
        or not parsed.path
    ):
        raise WithingsAuditError(
            "Callback must be an HTTP loopback URL with a port and path."
        )
    return parsed


def load_homepulse_visceral_readings(config):
    relative = config.get("weight_progress", "database", default="data/weight_progress.db")
    path = (PROJECT_ROOT / relative).resolve()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT visceral_fat_index, source_timestamp, metadata_json
            FROM weight_measurements
            WHERE visceral_fat_index IS NOT NULL
            """
        ).fetchall()
    finally:
        connection.close()
    readings = set()
    for row in rows:
        timestamp = visceral_source_timestamp(row)
        if timestamp is not None:
            readings.add((timestamp, float(row["visceral_fat_index"])))
    return sorted(readings)


def visceral_source_timestamp(row):
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
        entity = (metadata.get("entities") or {}).get("visceral_fat_index") or {}
        details = entity.get("metadata") or {}
        value = (
            details.get("last_updated")
            or details.get("last_changed")
            or entity.get("source_timestamp")
            or row["source_timestamp"]
        )
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def format_date(reading):
    return reading.timestamp_utc.isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
