from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import math
import re
import secrets
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from modules.weight_progress.models import WeightMeasurement


WITHINGS_AUTHORIZE_ENDPOINT = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_TOKEN_ENDPOINT = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_SIGNATURE_ENDPOINT = "https://wbsapi.withings.net/v2/signature"
WITHINGS_MEASURE_ENDPOINT = "https://wbsapi.withings.net/measure"
WITHINGS_SCOPE = "user.metrics"
VISCERAL_FAT_INDEX_TYPE = 170
EARLY_RETRY_TIMESTAMP = 946684800  # 2000-01-01T00:00:00Z
EXPIRED_TOKEN_STATUSES = {100, 101, 102, 401, 4010}


class WithingsAuditError(RuntimeError):
    """An error deliberately limited to non-secret diagnostic details."""


class WithingsStatusError(WithingsAuditError):
    def __init__(self, status):
        self.status = int(status)
        super().__init__(f"Withings returned status {self.status}.")


class WithingsHttpResponseError(WithingsAuditError):
    def __init__(self, http_status, payload=None):
        self.http_status = int(http_status)
        self.payload = payload if isinstance(payload, dict) else {}
        super().__init__(f"Withings request failed (HTTP {self.http_status}).")


@dataclass(frozen=True, repr=False)
class OAuthTokens:
    access_token: str
    refresh_token: str
    user_id: str
    expires_in: int
    scope: str

    def __repr__(self):
        return "OAuthTokens(<redacted>)"


@dataclass(frozen=True)
class VisceralFatReading:
    source_id: str
    timestamp: int
    value: float

    @property
    def timestamp_utc(self):
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    @property
    def stable_key(self):
        return f"{self.source_id}:{VISCERAL_FAT_INDEX_TYPE}"

    def masked_source_id(self):
        digest = sha256(self.source_id.encode("utf-8")).hexdigest()
        return f"withings-{digest[:10]}"


@dataclass
class HistoricalAuditResult:
    pages_retrieved: int
    groups_inspected: int
    readings: list[VisceralFatReading]
    duplicate_count: int
    page_shapes: list[dict]
    rejected_startdate_status: int | None = None


class WithingsOAuthClient:
    def __init__(
        self,
        client_id,
        client_secret,
        redirect_uri,
        *,
        request_json: Callable[[str, dict, str | None, float], dict] | None = None,
        timeout_seconds=15,
    ):
        self.client_id = _required(client_id, "Withings client ID")
        self._client_secret = _required(client_secret, "Withings client secret")
        self.redirect_uri = _required(redirect_uri, "Withings callback URL")
        self._request_json = request_json or post_form_json
        self._timeout_seconds = timeout_seconds
        self.last_diagnostics = []

    def authorization_url(self, state=None):
        state = state or secrets.token_urlsafe(32)
        fields = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": WITHINGS_SCOPE,
            "state": state,
        }
        return f"{WITHINGS_AUTHORIZE_ENDPOINT}?{urlencode(fields)}", state

    def exchange_code(self, code, mode="direct"):
        mode = _oauth_mode(mode)
        fields = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": _required(code, "Withings authorization code"),
            "redirect_uri": self.redirect_uri,
        }
        return self._authenticated_token_request(fields, mode)

    def refresh(self, refresh_token, mode="direct"):
        mode = _oauth_mode(mode)
        fields = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": _required(refresh_token, "Withings refresh token"),
        }
        return self._authenticated_token_request(fields, mode)

    def _authenticated_token_request(self, fields, mode):
        nonce_succeeded = False
        signature_generated = False
        if mode == "direct":
            fields["client_secret"] = self._client_secret
        else:
            nonce = self._get_nonce()
            nonce_succeeded = True
            fields["nonce"] = nonce
            fields["signature"] = withings_signature(fields, self._client_secret)
            signature_generated = True
        return self._request_tokens(
            fields,
            mode=mode,
            nonce_succeeded=nonce_succeeded,
            signature_generated=signature_generated,
        )

    def _get_nonce(self):
        timestamp = int(time.time())
        fields = {
            "action": "getnonce",
            "client_id": self.client_id,
            "timestamp": str(timestamp),
        }
        fields["signature"] = withings_signature(fields, self._client_secret)
        try:
            payload = self._request_json(
                WITHINGS_SIGNATURE_ENDPOINT, fields, None, self._timeout_seconds
            )
            http_status = payload.get("_http_status", "unknown")
        except WithingsHttpResponseError as exc:
            raise self._diagnostic_error(
                mode="signed",
                endpoint=WITHINGS_SIGNATURE_ENDPOINT,
                fields=fields,
                payload=exc.payload,
                http_status=exc.http_status,
                nonce_succeeded=False,
                signature_generated=True,
                callback_matched=True,
            ) from None
        status = response_status(payload)
        diagnostic = self._diagnostic_lines(
            mode="signed",
            endpoint=WITHINGS_SIGNATURE_ENDPOINT,
            fields=fields,
            payload=payload,
            http_status=http_status,
            nonce_succeeded=status == 0,
            signature_generated=True,
            callback_matched=True,
        )
        if status != 0:
            raise WithingsAuditError("\n".join(diagnostic))
        body = payload.get("body")
        nonce = _required(
            body.get("nonce") if isinstance(body, dict) else None,
            "Withings nonce",
        )
        self.last_diagnostics.extend(diagnostic)
        return nonce

    def _request_tokens(
        self, fields, *, mode, nonce_succeeded, signature_generated
    ):
        try:
            payload = self._request_json(
                WITHINGS_TOKEN_ENDPOINT, fields, None, self._timeout_seconds
            )
        except WithingsHttpResponseError as exc:
            raise self._diagnostic_error(
                mode=mode,
                endpoint=WITHINGS_TOKEN_ENDPOINT,
                fields=fields,
                payload=exc.payload,
                http_status=exc.http_status,
                nonce_succeeded=nonce_succeeded,
                signature_generated=signature_generated,
                callback_matched=fields.get("redirect_uri", self.redirect_uri)
                == self.redirect_uri,
            ) from None
        status = response_status(payload)
        diagnostic = self._diagnostic_lines(
            mode=mode,
            endpoint=WITHINGS_TOKEN_ENDPOINT,
            fields=fields,
            payload=payload,
            http_status=payload.get("_http_status", "unknown"),
            nonce_succeeded=nonce_succeeded,
            signature_generated=signature_generated,
            callback_matched=fields.get("redirect_uri", self.redirect_uri)
            == self.redirect_uri,
        )
        if status != 0:
            raise WithingsAuditError("\n".join(diagnostic))
        body = payload.get("body")
        if not isinstance(body, dict):
            raise WithingsAuditError("Withings OAuth response body is malformed.")
        try:
            expires_in = int(body["expires_in"])
        except (KeyError, TypeError, ValueError):
            raise WithingsAuditError("Withings OAuth expiry is malformed.") from None
        access_token = _required(body.get("access_token"), "Withings access token")
        refresh_token = _required(body.get("refresh_token"), "Withings refresh token")
        user_id = _required(body.get("userid"), "Withings user identifier")
        if expires_in <= 0:
            raise WithingsAuditError("Withings OAuth expiry is malformed.")
        tokens = OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user_id,
            expires_in=expires_in,
            scope=str(body.get("scope") or WITHINGS_SCOPE),
        )
        self.last_diagnostics.extend(diagnostic)
        return tokens

    def _diagnostic_error(self, **kwargs):
        return WithingsAuditError("\n".join(self._diagnostic_lines(**kwargs)))

    def _diagnostic_lines(
        self,
        *,
        mode,
        endpoint,
        fields,
        payload,
        http_status,
        nonce_succeeded,
        signature_generated,
        callback_matched,
    ):
        withings_status = (
            payload.get("status", "unknown")
            if isinstance(payload, dict)
            else "unknown"
        )
        message = _sanitized_error_text(
            payload,
            sensitive_values=(
                fields.get("client_id"),
                fields.get("client_secret"),
                fields.get("code"),
                fields.get("refresh_token"),
                fields.get("nonce"),
                fields.get("signature"),
            ),
        )
        return [
            f"authentication_mode={mode}",
            f"endpoint={endpoint}",
            f"http_status={http_status}",
            f"withings_status={withings_status}",
            f"withings_message={message}",
            f"action_present={str(bool(fields.get('action'))).lower()}",
            f"grant_type_present={str(bool(fields.get('grant_type'))).lower()}",
            f"client_id_present={str(bool(fields.get('client_id'))).lower()}",
            f"client_secret_present={str(bool(fields.get('client_secret'))).lower()}",
            f"authorization_code_present={str(bool(fields.get('code'))).lower()}",
            f"timestamp_present={str(bool(fields.get('timestamp'))).lower()}",
            f"nonce_present={str(bool(fields.get('nonce'))).lower()}",
            f"signature_present={str(bool(fields.get('signature'))).lower()}",
            f"nonce_request_succeeded={str(bool(nonce_succeeded)).lower()}",
            f"signature_generated={str(bool(signature_generated)).lower()}",
            f"callback_matched={str(bool(callback_matched)).lower()}",
        ]


class WithingsMeasureClient:
    def __init__(
        self,
        access_token,
        *,
        refresh_access_token: Callable[[], str] | None = None,
        request_json: Callable[[str, dict, str | None, float], dict] | None = None,
        clock: Callable[[], float] = time.time,
        timeout_seconds=15,
        max_pages=1000,
    ):
        self._access_token = _required(access_token, "Withings access token")
        self._refresh_access_token = refresh_access_token
        self._request_json = request_json or post_form_json
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._max_pages = max_pages

    def fetch_visceral_fat_history(self):
        enddate = int(self._clock())
        if enddate <= 0:
            raise WithingsAuditError("Runtime enddate is invalid.")
        try:
            return self._fetch_pages(startdate=0, enddate=enddate)
        except WithingsStatusError as exc:
            if exc.status in EXPIRED_TOKEN_STATUSES:
                raise
            result = self._fetch_pages(startdate=EARLY_RETRY_TIMESTAMP, enddate=enddate)
            result.rejected_startdate_status = exc.status
            return result

    def _fetch_pages(self, *, startdate, enddate):
        pages = 0
        groups_inspected = 0
        readings = []
        page_shapes = []
        seen_keys = set()
        duplicate_count = 0
        seen_offsets = set()
        offset = None
        refreshed = False

        while True:
            if pages >= self._max_pages:
                raise WithingsAuditError("Withings pagination exceeded the safety limit.")
            fields = {
                "action": "getmeas",
                "category": "1",
                "meastypes": str(VISCERAL_FAT_INDEX_TYPE),
                "startdate": str(startdate),
                "enddate": str(enddate),
            }
            if offset is not None:
                fields["offset"] = offset
            try:
                payload = self._request_json(
                    WITHINGS_MEASURE_ENDPOINT,
                    fields,
                    self._access_token,
                    self._timeout_seconds,
                )
                status = response_status(payload)
                if status != 0:
                    raise WithingsStatusError(status)
            except WithingsStatusError as exc:
                if (
                    exc.status in EXPIRED_TOKEN_STATUSES
                    and not refreshed
                    and self._refresh_access_token is not None
                ):
                    self._access_token = _required(
                        self._refresh_access_token(), "refreshed Withings access token"
                    )
                    refreshed = True
                    continue
                raise

            body = payload.get("body")
            if not isinstance(body, dict):
                raise WithingsAuditError("Withings response body is malformed.")
            groups = body.get("measuregrps")
            if not isinstance(groups, list):
                raise WithingsAuditError("Withings measuregrps is malformed.")
            more = body.get("more", False)
            next_offset = body.get("offset")
            page_shapes.append(
                {
                    "more_type": type(more).__name__,
                    "more": bool(more),
                    "offset_present": next_offset not in (None, ""),
                    "measuregrps_type": type(groups).__name__,
                }
            )

            pages += 1
            groups_inspected += len(groups)
            for reading in parse_visceral_fat_groups(groups):
                if reading.stable_key in seen_keys:
                    duplicate_count += 1
                    continue
                seen_keys.add(reading.stable_key)
                readings.append(reading)
            if not more:
                break
            if next_offset in (None, ""):
                raise WithingsAuditError("Withings indicated more pages without an offset.")
            next_offset = str(next_offset)
            if next_offset == offset or next_offset in seen_offsets:
                raise WithingsAuditError("Withings returned a repeated pagination offset.")
            seen_offsets.add(next_offset)
            offset = next_offset

        readings.sort(key=lambda item: (item.timestamp, item.source_id))
        return HistoricalAuditResult(
            pages_retrieved=pages,
            groups_inspected=groups_inspected,
            readings=readings,
            duplicate_count=duplicate_count,
            page_shapes=page_shapes,
        )


def parse_visceral_fat_groups(groups: Iterable[dict]):
    readings = []
    for group in groups:
        if not isinstance(group, dict):
            raise WithingsAuditError("Withings measurement group is malformed.")
        try:
            timestamp = int(group.get("date"))
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            raise WithingsAuditError("Withings measurement timestamp is invalid.") from None
        if timestamp <= 0 or not isinstance(group.get("measures"), list):
            raise WithingsAuditError("Withings measurement group is malformed.")
        for measure in group["measures"]:
            if not isinstance(measure, dict):
                raise WithingsAuditError("Withings measure is malformed.")
            try:
                measure_type = int(measure.get("type"))
            except (TypeError, ValueError):
                continue
            if measure_type != VISCERAL_FAT_INDEX_TYPE:
                continue
            try:
                value = float(measure["value"]) * (10 ** int(measure["unit"]))
            except (KeyError, TypeError, ValueError, OverflowError):
                raise WithingsAuditError("Withings type-170 value is invalid.") from None
            if not math.isfinite(value) or value < 0:
                raise WithingsAuditError("Withings type-170 value is implausible.")
            source_id = group.get("grpid")
            if source_id in (None, ""):
                identity = f"{timestamp}:{measure_type}:{value:.12g}"
                source_id = f"fallback-{sha256(identity.encode()).hexdigest()}"
            readings.append(VisceralFatReading(str(source_id), timestamp, value))
    return readings


def compare_readings(api_readings, homepulse_readings, tolerance_seconds=86400):
    remaining = list(homepulse_readings)
    present = []
    new = []
    for reading in api_readings:
        candidates = [
            (index, (stored_time - reading.timestamp_utc).total_seconds())
            for index, (stored_time, stored_value) in enumerate(remaining)
            if math.isclose(stored_value, reading.value, rel_tol=0, abs_tol=1e-9)
            and 0
            <= (stored_time - reading.timestamp_utc).total_seconds()
            <= tolerance_seconds
        ]
        if candidates:
            index, _ = min(candidates, key=lambda item: item[1])
            remaining.pop(index)
            present.append(reading)
        else:
            new.append(reading)
    return present, new


def build_history_measurements(readings, existing_measurements, imported_at=None):
    imported_at = imported_at or datetime.now(timezone.utc).isoformat(
        sep=" ", timespec="seconds"
    )
    existing_hashes = {
        measurement.reading_hash
        for measurement in existing_measurements
        if measurement.reading_hash
    }
    existing_timestamp_values = set()
    for measurement in existing_measurements:
        if measurement.visceral_fat_index is None:
            continue
        timestamp = _normalized_utc_timestamp(measurement.source_timestamp)
        if timestamp is not None:
            existing_timestamp_values.add(
                (timestamp, float(measurement.visceral_fat_index))
            )

    proposed = []
    proposed_hashes = set()
    proposed_timestamp_values = set()
    for reading in readings:
        source_hash = sha256(
            f"withings_public_api_history:{reading.source_id}:{VISCERAL_FAT_INDEX_TYPE}".encode(
                "utf-8"
            )
        ).hexdigest()
        timestamp = reading.timestamp_utc.isoformat(sep=" ", timespec="seconds")
        timestamp_value = (timestamp, float(reading.value))
        if (
            source_hash in existing_hashes
            or source_hash in proposed_hashes
            or timestamp_value in existing_timestamp_values
            or timestamp_value in proposed_timestamp_values
        ):
            continue
        proposed_hashes.add(source_hash)
        proposed_timestamp_values.add(timestamp_value)
        proposed.append(
            WeightMeasurement.create(
                captured_at=timestamp,
                source_timestamp=timestamp,
                source_entity="withings_public_api_history",
                visceral_fat_index=reading.value,
                import_source="withings_public_api_history",
                source_label="Withings Public API history",
                imported_at=imported_at,
                reading_hash=source_hash,
                metadata={
                    "withings_measure_type": VISCERAL_FAT_INDEX_TYPE,
                    "withings_group_id_hash": sha256(
                        reading.source_id.encode("utf-8")
                    ).hexdigest(),
                    "original_timestamp": reading.timestamp,
                },
            )
        )
    return proposed


def _normalized_utc_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat(sep=" ", timespec="seconds")


def response_status(payload):
    if not isinstance(payload, dict) or isinstance(payload.get("status"), bool):
        raise WithingsAuditError("Withings response status is malformed.")
    try:
        return int(payload.get("status"))
    except (TypeError, ValueError):
        raise WithingsAuditError("Withings response status is malformed.") from None


def post_form_json(endpoint, fields, access_token=None, timeout_seconds=15):
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(
        endpoint,
        data=urlencode(fields).encode("ascii"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            http_status = getattr(response, "status", 200)
    except HTTPError as exc:
        if endpoint in {WITHINGS_TOKEN_ENDPOINT, WITHINGS_SIGNATURE_ENDPOINT}:
            try:
                payload = json.loads(exc.read())
            except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            raise WithingsHttpResponseError(exc.code, payload) from None
        if exc.code == 429:
            raise WithingsAuditError("Withings rate limit reached (HTTP 429).") from None
        if exc.code == 401:
            raise WithingsStatusError(401) from None
        try:
            payload = json.loads(exc.read())
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        raise WithingsHttpResponseError(exc.code, payload) from None
    except (TimeoutError, URLError):
        raise WithingsAuditError("Withings request timed out or could not connect.") from None
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WithingsAuditError("Withings response was not valid JSON.") from None
    if isinstance(payload, dict):
        payload["_http_status"] = http_status
    return payload


def _required(value, label):
    text = str(value or "").strip()
    if not text:
        raise WithingsAuditError(f"{label} is not configured.")
    return text


def withings_signature(fields, client_secret):
    selected = {
        key: str(fields[key])
        for key in ("action", "client_id", "nonce", "timestamp")
        if fields.get(key) not in (None, "")
    }
    if "action" not in selected or "client_id" not in selected:
        raise WithingsAuditError("Withings signature parameters are incomplete.")
    if ("nonce" in selected) == ("timestamp" in selected):
        raise WithingsAuditError(
            "Withings signature requires exactly one nonce or timestamp."
        )
    message = ",".join(selected[key] for key in sorted(selected))
    return hmac.new(
        _required(client_secret, "Withings client secret").encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()


def _oauth_mode(value):
    mode = str(value or "").strip().lower()
    if mode not in {"direct", "signed"}:
        raise WithingsAuditError("OAuth mode must be direct or signed.")
    return mode


def _sanitized_error_text(payload, sensitive_values=()):
    messages = []
    if isinstance(payload, dict):
        for container in (payload, payload.get("body")):
            if not isinstance(container, dict):
                continue
            for key in ("error", "error_description", "message", "error_message"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    messages.append(value.strip())
                elif isinstance(value, dict):
                    nested = value.get("message") or value.get("error")
                    if isinstance(nested, str) and nested.strip():
                        messages.append(nested.strip())
    text = " | ".join(dict.fromkeys(messages)) or "--"
    for value in sensitive_values:
        if value:
            text = text.replace(str(value), "<redacted>")
    text = re.sub(
        r"(?i)\b(access_token|refresh_token|client_secret|authorization_code|code|userid|user_id)"
        r"\s*[:=]\s*[\"']?[^,\s\"'}]+",
        r"\1=<redacted>",
        text,
    )
    text = " ".join(text.split())
    return text[:500]
