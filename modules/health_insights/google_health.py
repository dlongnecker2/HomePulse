"""Google Health API v4 OAuth, transport, and normalization helpers.

The integration is read-only and storage-neutral. It uses Google's documented
OAuth endpoints directly so the diagnostic has no additional runtime
dependency beyond Python's standard library.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.health_insights.models import (
    DailyActivity,
    DailyNutrition,
    DailySleep,
    ExerciseSession,
)


API_BASE = "https://health.googleapis.com/v4"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
LEGACY_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/auth"
LEGACY_TOKEN_ENDPOINT = "https://accounts.google.com/o/oauth2/token"
OFFICIAL_AUTHORIZATION_ENDPOINTS = frozenset(
    (LEGACY_AUTHORIZATION_ENDPOINT, AUTHORIZATION_ENDPOINT)
)
OFFICIAL_TOKEN_ENDPOINTS = frozenset((LEGACY_TOKEN_ENDPOINT, TOKEN_ENDPOINT))
CALLBACK_URI = "http://127.0.0.1:8765/oauth2/callback"
NUTRITION_SCOPE = "https://www.googleapis.com/auth/googlehealth.nutrition.readonly"
ACTIVITY_SCOPE = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SLEEP_SCOPE = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
ALL_SCOPES = (NUTRITION_SCOPE, ACTIVITY_SCOPE, SLEEP_SCOPE)
SCOPE_NAMES = {
    NUTRITION_SCOPE: "nutrition.readonly",
    ACTIVITY_SCOPE: "activity_and_fitness.readonly",
    SLEEP_SCOPE: "sleep.readonly",
}
DEFAULT_JOURNEY_START = date(2026, 5, 4)
LOCAL_CONFIG_DIRECTORY = Path("data") / "health_insights"
CREDENTIALS_FILENAME = "google_credentials.json"
TOKENS_FILENAME = "google_tokens.json"

DATA_TYPE_FIELDS = {
    "nutrition-log": "nutrition_log",
    "hydration-log": "hydration_log",
    "steps": "steps",
    "exercise": "exercise",
    "active-energy-burned": "active_energy_burned",
    "active-minutes": "active_minutes",
    "active-zone-minutes": "active_zone_minutes",
    "distance": "distance",
    "sleep": "sleep",
    "daily-resting-heart-rate": "daily_resting_heart_rate",
}

DAILY_ROLLUP_LIMIT_DAYS = {
    "total-calories": 14,
    "active-minutes": 14,
}
DEFAULT_DAILY_ROLLUP_LIMIT_DAYS = 90

WINDOWS_TO_IANA = {
    "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver",
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "UTC": "UTC",
}

_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "code",
    "authorization_code",
    "id_token",
}
_IDENTIFIER_KEYS = {
    "name",
    "webClientId",
    "googleWebClientId",
    "user",
    "userId",
    "healthUserId",
}


class GoogleHealthError(RuntimeError):
    """A safe exception whose string form cannot contain response secrets."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_name: str | None = None,
        description: str | None = None,
        callback_match: bool | None = None,
        credentials_present: bool | None = None,
        requested_scopes: Iterable[str] = (),
        retryable: bool = False,
    ):
        super().__init__(sanitize_text(message))
        self.status = status
        self.error_name = sanitize_text(error_name or "") or None
        self.description = sanitize_text(description or "") or None
        self.callback_match = callback_match
        self.credentials_present = credentials_present
        self.requested_scopes = tuple(scope_name(value) for value in requested_scopes)
        self.retryable = retryable

    def diagnostics(self) -> dict[str, Any]:
        return {
            "http_status": self.status,
            "oauth_error": self.error_name,
            "description": self.description or str(self),
            "callback_match": self.callback_match,
            "credentials_present": self.credentials_present,
            "requested_scopes": list(self.requested_scopes),
            "retryable": self.retryable,
        }


def project_root_from(path: str | Path | None = None) -> Path:
    start = Path(path or __file__).resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / "modules").is_dir() and (candidate / "router_monitor.py").is_file():
            return candidate
    raise GoogleHealthError("HomePulse project root could not be resolved.")


def local_credentials_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / LOCAL_CONFIG_DIRECTORY / CREDENTIALS_FILENAME


def local_tokens_path(project_root: str | Path) -> Path:
    return Path(project_root).resolve() / LOCAL_CONFIG_DIRECTORY / TOKENS_FILENAME


def _assert_secret_destination(path: Path, project_root: Path) -> None:
    resolved = path.resolve()
    allowed = (project_root.resolve() / LOCAL_CONFIG_DIRECTORY).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise GoogleHealthError("Credential destination must stay under data/health_insights.") from exc
    parts = {part.lower() for part in resolved.parts}
    if "tests" in parts or "modules" in parts or "scripts" in parts:
        raise GoogleHealthError("Credential destination cannot be inside tracked source or tests.")


def read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GoogleHealthError("Configuration file was not found.") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleHealthError("Configuration file is not valid readable JSON.") from exc
    if not isinstance(payload, dict):
        raise GoogleHealthError("Configuration JSON root must be an object.")
    return payload


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _validated_client_payload(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload.get("web"), dict):
        raise GoogleHealthError(
            'Credentials JSON must contain a top-level "web" OAuth client object.'
        )
    client_type = "web"
    client = dict(payload[client_type])
    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [key for key in required if not str(client.get(key) or "").strip()]
    if missing:
        raise GoogleHealthError("Credentials JSON is missing required OAuth client information.")
    if not str(client["client_id"]).endswith(".apps.googleusercontent.com"):
        raise GoogleHealthError("Credentials JSON contains an incompatible Google OAuth client ID.")
    if str(client["auth_uri"]) not in OFFICIAL_AUTHORIZATION_ENDPOINTS:
        raise GoogleHealthError("Credentials JSON contains an incompatible authorization endpoint.")
    if str(client["token_uri"]) not in OFFICIAL_TOKEN_ENDPOINTS:
        raise GoogleHealthError("Credentials JSON contains an incompatible token endpoint.")
    project_id = str(client.get("project_id") or "").strip()
    if not project_id:
        raise GoogleHealthError("Credentials JSON does not identify its Google Cloud project.")
    redirect_uris = client.get("redirect_uris")
    if not isinstance(redirect_uris, list) or CALLBACK_URI not in map(str, redirect_uris):
        raise GoogleHealthError(
            f"Web credentials must authorize the exact callback URI {CALLBACK_URI}."
        )
    return client_type, client


def configure_credentials(
    source_path: str | Path,
    project_root: str | Path,
    *,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source = Path(source_path).expanduser().resolve()
    try:
        source.relative_to(root)
    except ValueError:
        pass
    else:
        raise GoogleHealthError(
            "For safety, import the downloaded credentials from outside the HomePulse project."
        )

    payload = read_json(source)
    client_type, client = _validated_client_payload(payload)
    destination = local_credentials_path(root)
    _assert_secret_destination(destination, root)
    existing_project = None
    if destination.exists():
        try:
            existing_project = read_json(destination).get("project_id")
        except GoogleHealthError:
            existing_project = None
    incoming_project = client["project_id"]
    if existing_project and existing_project != incoming_project:
        raise GoogleHealthError(
            "Credentials belong to a different Google Cloud project than the configured HomePulse integration."
        )

    resolved_timezone = timezone_name or detect_homepulse_timezone(root)
    try:
        ZoneInfo(resolved_timezone)
    except ZoneInfoNotFoundError as exc:
        raise GoogleHealthError("The HomePulse timezone is not a valid IANA timezone.") from exc

    normalized = {
        "client_type": client_type,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "project_id": incoming_project,
        "auth_uri": AUTHORIZATION_ENDPOINT,
        "token_uri": TOKEN_ENDPOINT,
        "callback_uri": CALLBACK_URI,
        "timezone": resolved_timezone,
        "configured_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(destination, normalized)
    return {
        "credential_file_recognized": True,
        "client_type": client_type,
        "client_id_present": True,
        "client_secret_present": True,
        "configured_callback_uri": CALLBACK_URI,
        "destination_configuration_path": str(destination),
        "timezone": resolved_timezone,
    }


def load_local_credentials(project_root: str | Path) -> dict[str, Any]:
    path = local_credentials_path(project_root)
    payload = read_json(path)
    required = (
        "client_type",
        "client_id",
        "client_secret",
        "project_id",
        "auth_uri",
        "token_uri",
        "callback_uri",
        "timezone",
    )
    if any(not payload.get(key) for key in required):
        raise GoogleHealthError("Local Google Health credentials are incomplete.")
    if payload["client_type"] != "web":
        raise GoogleHealthError("Local Google Health credentials are not a Web OAuth client.")
    if str(payload["auth_uri"]) not in OFFICIAL_AUTHORIZATION_ENDPOINTS:
        raise GoogleHealthError("Local credentials contain an incompatible authorization endpoint.")
    if str(payload["token_uri"]) not in OFFICIAL_TOKEN_ENDPOINTS:
        raise GoogleHealthError("Local credentials contain an incompatible token endpoint.")
    if payload["callback_uri"] != CALLBACK_URI:
        raise GoogleHealthError("Configured callback URI does not match this HomePulse diagnostic.")
    normalized = dict(payload)
    normalized["auth_uri"] = AUTHORIZATION_ENDPOINT
    normalized["token_uri"] = TOKEN_ENDPOINT
    return normalized


def load_local_tokens(project_root: str | Path, *, required: bool = True) -> dict[str, Any]:
    path = local_tokens_path(project_root)
    if not path.exists() and not required:
        return {}
    payload = read_json(path)
    return payload


def save_tokens(project_root: str | Path, response: dict[str, Any]) -> dict[str, Any]:
    root = Path(project_root).resolve()
    destination = local_tokens_path(root)
    _assert_secret_destination(destination, root)
    existing = load_local_tokens(root, required=False)
    merged = dict(existing)
    merged.update({key: value for key, value in response.items() if value is not None})
    if not response.get("refresh_token") and existing.get("refresh_token"):
        merged["refresh_token"] = existing["refresh_token"]
    expires_in = _optional_int(response.get("expires_in"))
    if expires_in is not None:
        merged["expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
    refresh_expires_in = _optional_int(response.get("refresh_token_expires_in"))
    if refresh_expires_in is not None:
        merged["refresh_token_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=refresh_expires_in)
        ).isoformat()
    merged["stored_at"] = datetime.now(timezone.utc).isoformat()
    atomic_write_json(destination, merged)
    return merged


class GoogleOAuthClient:
    def __init__(
        self,
        credentials: dict[str, Any],
        *,
        scopes: Iterable[str] = ALL_SCOPES,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: int = 30,
    ):
        self.credentials = dict(credentials)
        if str(self.credentials.get("auth_uri") or "") not in OFFICIAL_AUTHORIZATION_ENDPOINTS:
            raise GoogleHealthError("OAuth credentials contain an incompatible authorization endpoint.")
        if str(self.credentials.get("token_uri") or "") not in OFFICIAL_TOKEN_ENDPOINTS:
            raise GoogleHealthError("OAuth credentials contain an incompatible token endpoint.")
        self.credentials["auth_uri"] = AUTHORIZATION_ENDPOINT
        self.credentials["token_uri"] = TOKEN_ENDPOINT
        self.scopes = tuple(scopes)
        self.opener = opener
        self.timeout_seconds = timeout_seconds

    def authorization_url(
        self,
        state: str,
        *,
        code_challenge: str | None = None,
    ) -> str:
        params = {
            "client_id": self.credentials["client_id"],
            "redirect_uri": self.credentials["callback_uri"],
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.credentials['auth_uri']}?{urlencode(params)}"

    def exchange_code(self, code: str, *, code_verifier: str | None = None) -> dict[str, Any]:
        fields = {
            "client_id": self.credentials["client_id"],
            "client_secret": self.credentials["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.credentials["callback_uri"],
        }
        if code_verifier:
            fields["code_verifier"] = code_verifier
        return self._token_request(fields)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._token_request(
            {
                "client_id": self.credentials["client_id"],
                "client_secret": self.credentials["client_secret"],
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )

    def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        request = Request(
            self.credentials["token_uri"],
            data=urlencode(fields).encode("ascii"),
            method="POST",
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                payload = _decode_json_response(response.read())
        except HTTPError as exc:
            payload = _read_http_error(exc)
            raise _oauth_http_error(exc.code, payload, self.scopes) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise GoogleHealthError(
                "Google OAuth token request failed.",
                description=type(exc).__name__,
                credentials_present=True,
                requested_scopes=self.scopes,
                retryable=isinstance(exc, (URLError, TimeoutError)),
            ) from None
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise GoogleHealthError(
                "Google OAuth token response was incomplete.",
                credentials_present=True,
                requested_scopes=self.scopes,
            )
        return payload


class GoogleHealthClient:
    def __init__(
        self,
        project_root: str | Path,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.project_root = Path(project_root).resolve()
        self.credentials = load_local_credentials(self.project_root)
        self.tokens = load_local_tokens(self.project_root)
        self.opener = opener
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.sleeper = sleeper
        self.request_count = 0

    def ensure_access_token(self) -> str:
        access_token = str(self.tokens.get("access_token") or "")
        expires_at = parse_datetime(self.tokens.get("expires_at"))
        if access_token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(seconds=60):
            return access_token
        refresh_token = str(self.tokens.get("refresh_token") or "")
        if not refresh_token:
            raise GoogleHealthError("Google Health authorization is required.")
        response = GoogleOAuthClient(
            self.credentials,
            opener=self.opener,
            timeout_seconds=self.timeout_seconds,
        ).refresh(refresh_token)
        self.tokens = save_tokens(self.project_root, response)
        return str(self.tokens["access_token"])

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{API_BASE}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(self.max_retries + 1):
            token = self.ensure_access_token()
            request = Request(
                url,
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            self.request_count += 1
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    payload = _decode_json_response(response.read())
                if not isinstance(payload, dict):
                    raise GoogleHealthError("Google Health API returned malformed JSON.")
                return payload
            except HTTPError as exc:
                payload = _read_http_error(exc)
                if exc.code == 401 and attempt == 0 and self.tokens.get("refresh_token"):
                    self.tokens["expires_at"] = "1970-01-01T00:00:00+00:00"
                    continue
                retryable = exc.code in (429, 500, 502, 503, 504)
                if retryable and attempt < self.max_retries:
                    retry_after = _retry_after_seconds(exc, attempt)
                    self.sleeper(retry_after)
                    continue
                raise _api_http_error(exc.code, payload, retryable=retryable) from None
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.max_retries:
                    self.sleeper(min(2**attempt, 8))
                    continue
                raise GoogleHealthError(
                    "Google Health API request failed.",
                    description=type(exc).__name__,
                    retryable=True,
                ) from None
        raise GoogleHealthError("Google Health API request retry limit was reached.")

    def list_data_points(
        self,
        data_type: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        field = DATA_TYPE_FIELDS[data_type]
        if page_size is None:
            page_size = 25 if data_type in {"exercise", "sleep"} else 10000
        query: dict[str, Any] = {"pageSize": page_size}
        if start_date is not None and end_date is not None:
            exclusive_end = end_date + timedelta(days=1)
            if data_type == "sleep":
                filter_field = "sleep.interval.civil_end_time"
            elif data_type == "daily-resting-heart-rate":
                filter_field = "dailyRestingHeartRate.date"
            else:
                filter_field = f"{field}.interval.civil_start_time"
            query["filter"] = (
                f'{filter_field} >= "{start_date.isoformat()}" AND '
                f'{filter_field} < "{exclusive_end.isoformat()}"'
            )
        points: list[dict[str, Any]] = []
        pages = 0
        seen_tokens: set[str] = set()
        while True:
            payload = self.request_json(
                "GET",
                f"users/me/dataTypes/{data_type}/dataPoints",
                query=query,
            )
            pages += 1
            points.extend(payload.get("dataPoints") or [])
            next_token = str(payload.get("nextPageToken") or "")
            if not next_token:
                break
            if next_token in seen_tokens:
                raise GoogleHealthError("Google Health API repeated a pagination token.")
            seen_tokens.add(next_token)
            query["pageToken"] = next_token
        return points, {"pages": pages, "requests": pages}

    def daily_rollups(
        self,
        data_type: str,
        start_date: date,
        end_date: date,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        limit = DAILY_ROLLUP_LIMIT_DAYS.get(data_type, DEFAULT_DAILY_ROLLUP_LIMIT_DAYS)
        output: list[dict[str, Any]] = []
        request_start = self.request_count
        chunks = 0
        cursor = start_date
        while cursor <= end_date:
            chunk_end_exclusive = min(cursor + timedelta(days=limit), end_date + timedelta(days=1))
            chunk_last_day = chunk_end_exclusive - timedelta(days=1)
            body_base = {
                "range": {
                    "start": civil_datetime(cursor),
                    "end": civil_datetime(chunk_last_day, end_of_day=True),
                },
                "windowSizeDays": 1,
            }
            page_token = ""
            seen_tokens: set[str] = set()
            chunks += 1
            while True:
                body = dict(body_base)
                if page_token:
                    body["pageToken"] = page_token
                payload = self.request_json(
                    "POST",
                    f"users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
                    body=body,
                )
                output.extend(payload.get("rollupDataPoints") or [])
                page_token = str(payload.get("nextPageToken") or "")
                if not page_token:
                    break
                if page_token in seen_tokens:
                    raise GoogleHealthError("Google Health API repeated a rollup pagination token.")
                seen_tokens.add(page_token)
            cursor = chunk_end_exclusive
        return output, {
            "requests": self.request_count - request_start,
            "chunks": chunks,
            "maximum_range_days": limit,
        }

    def get_data_point(self, resource_name: str) -> dict[str, Any]:
        if not resource_name.startswith("users/") or "/dataTypes/food/dataPoints/" not in resource_name:
            raise GoogleHealthError("Linked food resource name is invalid.")
        return self.request_json("GET", resource_name)


def detect_homepulse_timezone(project_root: str | Path) -> str:
    root = Path(project_root)
    config_path = root / "config.json"
    if config_path.exists():
        try:
            config = read_json(config_path)
            candidates = (
                config.get("timezone"),
                config.get("time_zone"),
                (config.get("system") or {}).get("timezone")
                if isinstance(config.get("system"), dict)
                else None,
                (config.get("weather") or {}).get("timezone")
                if isinstance(config.get("weather"), dict)
                else None,
            )
            for candidate in candidates:
                if candidate:
                    ZoneInfo(str(candidate))
                    return str(candidate)
        except (GoogleHealthError, ZoneInfoNotFoundError):
            pass
    environment_timezone = str(os.environ.get("TZ") or "").strip()
    if environment_timezone:
        try:
            ZoneInfo(environment_timezone)
            return environment_timezone
        except ZoneInfoNotFoundError:
            pass
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tzutil", "/g"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            windows_name = result.stdout.strip()
            if windows_name in WINDOWS_TO_IANA:
                return WINDOWS_TO_IANA[windows_name]
        except (OSError, subprocess.SubprocessError):
            pass
    local = datetime.now().astimezone()
    key = getattr(local.tzinfo, "key", None)
    if key:
        return str(key)
    raise GoogleHealthError(
        "HomePulse timezone could not be verified; rerun configure with --timezone."
    )


def scope_name(scope: str) -> str:
    return SCOPE_NAMES.get(scope, str(scope).rsplit("/", 1)[-1])


def granted_scopes(tokens: dict[str, Any]) -> set[str]:
    value = tokens.get("scope") or ""
    if isinstance(value, list):
        return {str(item) for item in value}
    return {item for item in str(value).split() if item}


def missing_scopes(tokens: dict[str, Any], requested: Iterable[str] = ALL_SCOPES) -> set[str]:
    return set(requested) - granted_scopes(tokens)


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def validate_callback(
    callback_path: str,
    *,
    expected_state: str,
    expected_path: str = "/oauth2/callback",
) -> dict[str, str]:
    from urllib.parse import parse_qs, urlsplit

    parsed = urlsplit(callback_path)
    if parsed.path != expected_path:
        raise GoogleHealthError(
            "OAuth callback path did not match.",
            callback_match=False,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    values = parse_qs(parsed.query, keep_blank_values=True)
    received_state = (values.get("state") or [""])[0]
    if not received_state or not secrets.compare_digest(received_state, expected_state):
        raise GoogleHealthError(
            "OAuth state validation failed.",
            error_name="state_mismatch",
            callback_match=True,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    if values.get("error"):
        raise GoogleHealthError(
            "Google authorization was not completed.",
            error_name=(values.get("error") or ["oauth_error"])[0],
            description=(values.get("error_description") or ["Authorization was declined."])[0],
            callback_match=True,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    code = (values.get("code") or [""])[0]
    if not code:
        raise GoogleHealthError(
            "OAuth callback did not contain an authorization code.",
            callback_match=True,
            credentials_present=True,
            requested_scopes=ALL_SCOPES,
        )
    return {"code": code}


def source_identity(point: dict[str, Any]) -> dict[str, str]:
    source = point.get("dataSource") or {}
    application = source.get("application") or {}
    application_identifier = (
        application.get("packageName")
        or application.get("googleWebClientId")
        or application.get("webClientId")
        or ""
    )
    return {
        "platform": str(source.get("platform") or "PLATFORM_UNSPECIFIED"),
        "recording_method": str(
            source.get("recordingMethod") or "RECORDING_METHOD_UNSPECIFIED"
        ),
        "package_name": str(application.get("packageName") or ""),
        "application_id_hash": (
            hashlib.sha256(str(application_identifier).encode("utf-8")).hexdigest()[:12]
            if application_identifier
            else ""
        ),
        "application_kind": (
            "google_web"
            if application.get("googleWebClientId")
            else "legacy_fitbit_web"
            if application.get("webClientId")
            else "mobile"
            if application.get("packageName")
            else "unspecified"
        ),
    }


def stable_record_key(point: dict[str, Any]) -> str:
    name = str(point.get("name") or "")
    if name:
        material = name
    else:
        material = json.dumps(point, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_nutrition_point(
    point: dict[str, Any],
    timezone_name: str,
) -> dict[str, Any]:
    payload = point.get("nutritionLog") or {}
    interval = payload.get("interval") or {}
    local_date = interval_local_date(interval, timezone_name, prefer_end=False)
    nutrients = {}
    for item in payload.get("nutrients") or []:
        nutrient = str(item.get("nutrient") or "")
        grams = _nested_number(item, "quantity", "grams")
        if nutrient and grams is not None:
            nutrients[nutrient] = nutrients.get(nutrient, 0.0) + grams
    sodium_g = nutrients.get("SODIUM")
    return {
        "record_key": stable_record_key(point),
        "local_date": local_date,
        "start_time": interval.get("startTime"),
        "end_time": interval.get("endTime"),
        "meal_type": payload.get("mealType"),
        "calories_kcal": _nested_number(payload, "energy", "kcal"),
        "protein_g": nutrients.get("PROTEIN"),
        "carbohydrates_g": _first_not_none(
            _nested_number(payload, "totalCarbohydrate", "grams"),
            nutrients.get("CARBOHYDRATES"),
        ),
        "fat_g": _nested_number(payload, "totalFat", "grams"),
        "fiber_g": nutrients.get("DIETARY_FIBER"),
        "sodium_mg": sodium_g * 1000.0 if sodium_g is not None else None,
        "food_reference": payload.get("food"),
        "food_name_present": bool(payload.get("foodDisplayName")),
        "source": source_identity(point),
    }


def aggregate_daily_nutrition(
    points: Iterable[dict[str, Any]],
    timezone_name: str,
    start_date: date,
    end_date: date,
) -> list[DailyNutrition]:
    fields = (
        "calories_kcal",
        "protein_g",
        "carbohydrates_g",
        "fat_g",
        "fiber_g",
        "sodium_mg",
    )
    days: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        normalized = normalize_nutrition_point(point, timezone_name)
        if normalized["local_date"]:
            days.setdefault(normalized["local_date"], []).append(normalized)
    output = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.isoformat()
        rows = days.get(key, [])
        values: dict[str, float | None] = {}
        for field_name in fields:
            present = [row[field_name] for row in rows if row[field_name] is not None]
            values[field_name] = sum(present) if present else None
        present_count = sum(values[name] is not None for name in fields)
        completeness = (
            "no data"
            if not rows
            else "complete"
            if present_count == len(fields)
            else "partial"
            if present_count
            else "unknown"
        )
        platforms = sorted(
            {
                row["source"]["platform"]
                for row in rows
                if row["source"]["platform"]
            }
        )
        output.append(
            DailyNutrition(
                local_date=key,
                record_count=len(rows),
                completeness=completeness,
                source_platforms=platforms,
                **values,
            )
        )
        cursor += timedelta(days=1)
    return output


def normalize_exercise_point(
    point: dict[str, Any],
    timezone_name: str,
) -> ExerciseSession:
    payload = point.get("exercise") or {}
    interval = payload.get("interval") or {}
    metrics = payload.get("metricsSummary") or {}
    exercise_type = str(payload.get("exerciseType") or "") or None
    duration_seconds = parse_duration_seconds(payload.get("activeDuration"))
    return ExerciseSession(
        record_key=stable_record_key(point),
        local_date=interval_local_date(interval, timezone_name, prefer_end=False),
        start_time=interval.get("startTime"),
        end_time=interval.get("endTime"),
        exercise_type=exercise_type,
        category=classify_exercise(exercise_type),
        active_minutes=duration_seconds / 60.0 if duration_seconds is not None else None,
        calories_kcal=_optional_float(metrics.get("caloriesKcal")),
        distance_meters=(
            _optional_float(metrics.get("distanceMillimeters")) / 1000.0
            if metrics.get("distanceMillimeters") is not None
            else None
        ),
        steps=_optional_int(metrics.get("steps")),
        active_zone_minutes=_optional_int(metrics.get("activeZoneMinutes")),
        source_platform=source_identity(point)["platform"],
        update_time=payload.get("updateTime"),
    )


def classify_exercise(exercise_type: str | None) -> str:
    value = str(exercise_type or "").upper()
    if value in {
        "WEIGHTLIFTING",
        "WEIGHT_MACHINES",
        "WEIGHTS",
        "STRENGTH_TRAINING",
        "CALISTHENICS",
        "CIRCUIT_TRAINING",
        "TRX",
    }:
        return "strength"
    if value in {"WALKING", "TREADMILL_WALK", "WALK_WITH_WEIGHTS"}:
        return "walking"
    cardio_terms = (
        "RUN",
        "CYCL",
        "SWIM",
        "ROW",
        "ELLIPTICAL",
        "CARDIO",
        "AEROBIC",
        "STAIR",
        "HIIT",
    )
    if any(term in value for term in cardio_terms):
        return "cardio"
    if not value or value.endswith("UNSPECIFIED") or value == "WORKOUT":
        return "unknown"
    return "other"


def normalize_sleep_point(
    point: dict[str, Any],
    timezone_name: str,
) -> DailySleep:
    payload = point.get("sleep") or {}
    interval = payload.get("interval") or {}
    summary = payload.get("summary") or {}
    stages = {
        str(item.get("type") or ""): _optional_int(item.get("minutes"))
        for item in summary.get("stagesSummary") or []
    }
    return DailySleep(
        local_date=interval_local_date(interval, timezone_name, prefer_end=True) or "",
        sleep_minutes=_optional_int(summary.get("minutesAsleep")),
        start_time=interval.get("startTime"),
        end_time=interval.get("endTime"),
        deep_minutes=stages.get("DEEP"),
        light_minutes=stages.get("LIGHT"),
        rem_minutes=stages.get("REM"),
        awake_minutes=_first_not_none(
            stages.get("AWAKE"),
            _optional_int(summary.get("minutesAwake")),
        ),
        source_platforms=[source_identity(point)["platform"]],
    )


def rollup_local_date(point: dict[str, Any]) -> str | None:
    start = (
        point.get("civilStartTime")
        or point.get("start")
        or point.get("startTime")
    )
    if isinstance(start, dict):
        date_value = start.get("date") or {}
        try:
            return date(
                int(date_value["year"]),
                int(date_value["month"]),
                int(date_value["day"]),
            ).isoformat()
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(start, str):
        parsed = parse_datetime(start)
        return parsed.date().isoformat() if parsed else None
    return None


def normalize_rollup_value(data_type: str, point: dict[str, Any]) -> Any:
    keys = {
        "nutrition-log": "nutritionLog",
        "steps": "steps",
        "active-energy-burned": "activeEnergyBurned",
        "total-calories": "totalCalories",
        "active-minutes": "activeMinutes",
        "active-zone-minutes": "activeZoneMinutes",
        "distance": "distance",
    }
    payload = point.get(keys[data_type]) or {}
    if data_type == "steps":
        return _optional_int(payload.get("countSum"))
    if data_type in {"active-energy-burned", "total-calories"}:
        return _optional_float(payload.get("kcalSum"))
    if data_type == "distance":
        millimeters = _optional_float(payload.get("millimetersSum"))
        return millimeters / 1000.0 if millimeters is not None else None
    if data_type == "active-zone-minutes":
        values = [
            _optional_int(payload.get("sumInCardioHeartZone")),
            _optional_int(payload.get("sumInPeakHeartZone")),
            _optional_int(payload.get("sumInFatBurnHeartZone")),
        ]
        present = [value for value in values if value is not None]
        return sum(present) if present else None
    if data_type == "active-minutes":
        values = [
            _optional_int(item.get("activeMinutesSum"))
            for item in payload.get("activeMinutesRollupByActivityLevel") or []
        ]
        present = [value for value in values if value is not None]
        return sum(present) if present else None
    if data_type == "nutrition-log":
        if not payload:
            return None
        nutrients = {}
        for item in payload.get("nutrients") or []:
            value = _nested_number(item, "quantity", "gramsSum")
            if value is not None:
                nutrients[str(item.get("nutrient") or "")] = value
        sodium = nutrients.get("SODIUM")
        normalized = {
            "calories_kcal": _nested_number(payload, "energy", "kcalSum"),
            "protein_g": nutrients.get("PROTEIN"),
            "carbohydrates_g": _first_not_none(
                _nested_number(payload, "totalCarbohydrate", "gramsSum"),
                nutrients.get("CARBOHYDRATES"),
            ),
            "fat_g": _nested_number(payload, "totalFat", "gramsSum"),
            "fiber_g": nutrients.get("DIETARY_FIBER"),
            "sodium_mg": sodium * 1000.0 if sodium is not None else None,
        }
        return normalized if any(value is not None for value in normalized.values()) else None
    return None


def sanitized_shape(value: Any) -> Any:
    """Describe response structure without emitting identifiers or health values."""
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if key in _SECRET_KEYS or key in _IDENTIFIER_KEYS or key == "foodDisplayName":
                output[key] = "<redacted>"
            else:
                output[key] = sanitized_shape(item)
        return output
    if isinstance(value, list):
        return [sanitized_shape(value[0])] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"([?&](?:code|token|client_secret|state)=)[^&\s]+", r"\1<redacted>", text, flags=re.I)
    text = re.sub(r"\busers/[^/\s]+", "users/<redacted>", text, flags=re.I)
    text = re.sub(
        r"(/dataPoints/)[A-Za-z0-9._~-]+",
        r"\1<redacted>",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<redacted-email>", text)
    text = re.sub(r"\b(?:ya29\.|1//)[A-Za-z0-9._~+/=-]+\b", "<redacted-token>", text)
    text = re.sub(r"\b[A-Za-z0-9_-]{40,}\b", "<redacted-value>", text)
    return text[:800]


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def interval_local_date(
    interval: dict[str, Any],
    timezone_name: str,
    *,
    prefer_end: bool,
) -> str | None:
    civil_key = "civilEndTime" if prefer_end else "civilStartTime"
    civil = interval.get(civil_key)
    if isinstance(civil, dict):
        date_value = civil.get("date") or {}
        try:
            return date(
                int(date_value["year"]),
                int(date_value["month"]),
                int(date_value["day"]),
            ).isoformat()
        except (KeyError, TypeError, ValueError):
            pass
    physical_key = "endTime" if prefer_end else "startTime"
    parsed = parse_datetime(interval.get(physical_key))
    if not parsed:
        return None
    return parsed.astimezone(ZoneInfo(timezone_name)).date().isoformat()


def parse_duration_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text.endswith("s"):
        return None
    try:
        return float(text[:-1])
    except ValueError:
        return None


def civil_datetime(value: date, *, end_of_day: bool = False) -> dict[str, Any]:
    return {
        "date": {"year": value.year, "month": value.month, "day": value.day},
        "time": {
            "hours": 23 if end_of_day else 0,
            "minutes": 59 if end_of_day else 0,
            "seconds": 59 if end_of_day else 0,
            "nanos": 0,
        },
    }


def _decode_json_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleHealthError("Remote service returned invalid JSON.") from exc
    return payload


def _read_http_error(exc: HTTPError) -> dict[str, Any]:
    try:
        return _decode_json_response(exc.read())
    except (GoogleHealthError, OSError):
        return {}
    finally:
        exc.close()


def _oauth_http_error(
    status: int,
    payload: dict[str, Any],
    requested_scopes: Iterable[str],
) -> GoogleHealthError:
    return GoogleHealthError(
        "Google OAuth request failed.",
        status=status,
        error_name=str(payload.get("error") or "oauth_error"),
        description=str(payload.get("error_description") or "No safe error description was returned."),
        callback_match=True,
        credentials_present=True,
        requested_scopes=requested_scopes,
        retryable=status in (429, 500, 502, 503, 504),
    )


def _api_http_error(
    status: int,
    payload: dict[str, Any],
    *,
    retryable: bool,
) -> GoogleHealthError:
    error = payload.get("error") if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        error = {}
    return GoogleHealthError(
        "Google Health API request failed.",
        status=status,
        error_name=str(error.get("status") or "api_error"),
        description=str(error.get("message") or "No safe error description was returned."),
        retryable=retryable,
    )


def _retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    try:
        return min(max(float(exc.headers.get("Retry-After", "")), 0.0), 60.0)
    except (TypeError, ValueError):
        return float(min(2**attempt, 8))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nested_number(payload: dict[str, Any], *keys: str) -> float | None:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return _optional_float(value)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
