import json
from collections import OrderedDict
from datetime import datetime
import threading
import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from modules.environment.database import EnvironmentStore
from modules.environment.models import EnvironmentalEntity, EnvironmentalReading


DEFAULT_REFRESH_INTERVAL_MINUTES = 5
DEFAULT_STALE_AFTER_MINUTES = 10
SUPPORTED_SENSOR_DEVICE_CLASSES = {
    "temperature",
    "humidity",
    "pressure",
    "illuminance",
    "carbon_dioxide",
    "carbon_monoxide",
    "aqi",
    "pm1",
    "pm10",
    "pm25",
    "voltage",
    "current",
    "power",
    "energy",
    "frequency",
    "moisture",
    "precipitation",
    "rain",
    "wind_speed",
    "wind_bearing",
    "battery",
    "signal_strength",
    "vibration",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "volatile_organic_compounds",
    "volatile_organic_compounds_parts",
    "power_factor",
}
SUPPORTED_BINARY_SENSOR_CLASSES = {
    "battery",
    "cold",
    "door",
    "garage_door",
    "gas",
    "heat",
    "light",
    "lock",
    "moisture",
    "motion",
    "occupancy",
    "opening",
    "presence",
    "problem",
    "smoke",
    "sound",
    "tamper",
    "vibration",
    "window",
    "connectivity",
    "running",
    "power",
}


class EnvironmentManager:
    def __init__(self, config, log, store: EnvironmentStore):
        self.config = config
        self.log = log
        self.store = store
        self._refresh_lock = threading.Lock()
        self._snapshot = None
        self._last_successful_refresh_at = None
        self._last_refresh_error = None
        self._load_cached_snapshot()

    def initialize(self):
        self._load_cached_snapshot()

    def enabled(self):
        environment = self.config.get("environment", default={})
        return bool(environment.get("enabled", True))

    def refresh_interval_minutes(self):
        environment = self.config.get("environment", default={})
        try:
            minutes = int(environment.get("refresh_interval_minutes", DEFAULT_REFRESH_INTERVAL_MINUTES))
        except (TypeError, ValueError):
            minutes = DEFAULT_REFRESH_INTERVAL_MINUTES
        return max(1, minutes)

    def stale_after_minutes(self):
        environment = self.config.get("environment", default={})
        try:
            minutes = int(environment.get("stale_after_minutes", DEFAULT_STALE_AFTER_MINUTES))
        except (TypeError, ValueError):
            minutes = DEFAULT_STALE_AFTER_MINUTES
        return max(self.refresh_interval_minutes(), minutes)

    def get_status(self):
        snapshot = self._snapshot_payload(self._snapshot or self._empty_snapshot())
        snapshot["read_only"] = True
        return snapshot

    def home_summary(self):
        status = self.get_status()
        summary = status.get("summary", {})
        return {
            "enabled": status.get("enabled", False),
            "configured": status.get("configured", False),
            "status": status.get("status", "Unavailable"),
            "availability": status.get("availability", "unavailable"),
            "message": status.get("message", ""),
            "entities": summary.get("supported_entities", 0),
            "areas": summary.get("areas", 0),
            "devices": summary.get("devices", 0),
            "stale": status.get("stale", True),
            "snapshot_age_seconds": status.get("snapshot_age_seconds"),
            "last_successful_refresh": status.get("last_successful_refresh"),
        }

    def entity_history(self, entity_id, limit=200):
        return self.get_entity_history(entity_id, limit=limit)

    def status_payload(self):
        return self.get_status()

    def get_entity_history(self, entity_id, limit=200):
        try:
            return self.store.history(entity_id, limit=limit)
        except Exception as exc:
            self.log.exception(f"Environment history lookup failed for {entity_id}: {exc}")
            return []

    def refresh_snapshot(self):
        now = datetime.now()
        if not self.enabled():
            self._snapshot = self._snapshot_payload(self._empty_snapshot(message="Environment monitoring is disabled."))
            return self._snapshot

        if not self._refresh_lock.acquire(blocking=False):
            self.log.debug("Environment refresh skipped because a refresh is already running")
            return self.get_status()

        try:
            states, entity_registry, device_registry, area_registry, enrichment_error = self._fetch_home_assistant_payloads()
            records, readings, discovery = self._discover_entities(states, entity_registry, device_registry, area_registry)
            if records:
                self.store.upsert_entities(records)
            stored_readings = 0
            for reading in readings:
                try:
                    stored_readings += self.store.record_reading(reading, dedupe=True)
                except Exception as exc:
                    self.log.warning(f"Environment reading skipped for {reading.entity_id}: {exc}")
                    continue

            self._load_cached_snapshot()
            snapshot = self._snapshot_payload(self._snapshot or self._empty_snapshot())
            snapshot["refresh"] = {
                "timestamp": now.isoformat(timespec="seconds"),
                "discovered_entities": discovery["supported_entities"],
                "discovered_areas": discovery["areas"],
                "discovered_devices": discovery["devices"],
                "excluded_entities": discovery["excluded"],
                "stored_readings": stored_readings,
            }
            if enrichment_error:
                snapshot["enrichment_error"] = enrichment_error
            snapshot["message"] = (
                f"Loaded {discovery['supported_entities']} supported Home Assistant entity(s) across "
                f"{discovery['areas']} area(s) and {discovery['devices']} device(s)."
            )
            snapshot["availability"] = "live"
            snapshot["status"] = "Connected"
            snapshot["stale"] = False
            snapshot["last_successful_refresh"] = now.isoformat(timespec="seconds")
            snapshot["snapshot_age_seconds"] = 0
            snapshot["snapshot_age_label"] = "just now"
            snapshot["last_refresh_error"] = None
            self._snapshot = snapshot
            self._last_successful_refresh_at = now
            self._last_refresh_error = None
            return snapshot
        except Exception as exc:
            self._last_refresh_error = str(exc)
            self.log.warning(f"Environment refresh failed; preserving cached snapshot: {exc}")
            snapshot = self._snapshot_payload(self._snapshot or self._empty_snapshot(error=str(exc)))
            snapshot["availability"] = "stale" if snapshot.get("entities") else "unavailable"
            snapshot["stale"] = True
            snapshot["last_refresh_error"] = str(exc)
            self._snapshot = snapshot
            return snapshot
        finally:
            self._refresh_lock.release()

    def _fetch_home_assistant_payloads(self):
        base_url, token = self._home_assistant_credentials()
        states = self._request_json(f"{base_url}/api/states", token, timeout_seconds=10)
        entity_registry, device_registry, area_registry, enrichment_error = self._fetch_registry_enrichment(base_url, token)
        return states, entity_registry, device_registry, area_registry, enrichment_error

    def _request_json(self, url, token, timeout_seconds):
        request = Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload

    def _fetch_registry_enrichment(self, base_url, token):
        try:
            return self._fetch_registry_enrichment_via_websocket(base_url, token)
        except HTTPError as exc:
            if exc.code == 404:
                message = f"Home Assistant registry enrichment endpoint unavailable (HTTP 404)."
            else:
                message = f"Home Assistant registry enrichment failed (HTTP {exc.code})."
            self.log.warning(message)
            return [], [], [], message
        except (URLError, TimeoutError, ConnectionError, OSError, ValueError, ssl.SSLError, socket.timeout) as exc:
            message = f"Home Assistant registry enrichment unavailable: {exc}"
            self.log.warning(message)
            return [], [], [], message
        except Exception as exc:
            message = f"Home Assistant registry enrichment unavailable: {exc}"
            self.log.warning(message)
            return [], [], [], message

    def _fetch_registry_enrichment_via_websocket(self, base_url, token):
        ws_url = self._websocket_url(base_url)
        client = self._open_websocket(ws_url)
        try:
            self._websocket_authenticate(client, token)
            area_registry = self._websocket_call(client, "config/area_registry/list")
            device_registry = self._websocket_call(client, "config/device_registry/list")
            entity_registry = self._websocket_call(client, "config/entity_registry/list")
            return entity_registry, device_registry, area_registry, None
        finally:
            client.close()

    @staticmethod
    def _websocket_url(base_url):
        parsed = urlsplit(base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        netloc = parsed.netloc or parsed.path
        if not netloc:
            raise ValueError("Invalid Home Assistant URL")
        return f"{scheme}://{netloc}/api/websocket"

    def _open_websocket(self, ws_url, timeout_seconds=10):
        parsed = urlsplit(ws_url)
        host = parsed.hostname
        if not host:
            raise ValueError("Invalid WebSocket URL")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        raw_socket = socket.create_connection((host, port), timeout=timeout_seconds)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            raw_socket = context.wrap_socket(raw_socket, server_hostname=host)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        raw_socket.sendall(request)
        response = self._read_http_headers(raw_socket)
        if "101" not in response.split("\r\n", 1)[0]:
            raise ConnectionError(f"WebSocket handshake failed: {response.splitlines()[0] if response else 'no response'}")

        accept_key = self._websocket_accept_key(key)
        headers = response.lower()
        if accept_key.lower() not in headers:
            raise ConnectionError("WebSocket handshake missing accept key")
        return HomeAssistantWebSocket(raw_socket)

    @staticmethod
    def _read_http_headers(sock):
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
        return buffer.decode("utf-8", errors="replace")

    @staticmethod
    def _websocket_accept_key(key):
        magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        digest = hashlib.sha1(f"{key}{magic}".encode("ascii")).digest()
        return base64.b64encode(digest).decode("ascii")

    def _websocket_authenticate(self, client, token):
        client.send_json({"type": "auth", "access_token": token})
        message = client.recv_json()
        if message.get("type") != "auth_ok":
            raise PermissionError(message.get("message") or "Home Assistant WebSocket authentication failed")

    def _websocket_call(self, client, command):
        message_id = client.next_id()
        client.send_json({"id": message_id, "type": command})
        message = client.recv_json(expected_id=message_id)
        if not message.get("success", False):
            raise RuntimeError(message.get("error", {}).get("message") or f"WebSocket command failed: {command}")
        result = message.get("result")
        if isinstance(result, dict):
            return result.get("data") or result.get("items") or result
        return result or []

    def _home_assistant_credentials(self):
        recovery = self.config.get("router_reboot", default={})
        base_url = str(recovery.get("home_assistant_url") or "").strip().rstrip("/")
        token = str(recovery.get("home_assistant_token") or "").strip()
        if not base_url or not token:
            ha = self.config.get("home_assistant", default={})
            base_url = base_url or str(ha.get("url") or "").strip().rstrip("/")
            token = token or str(ha.get("token") or "").strip()
        if not base_url or not token:
            raise ValueError("Home Assistant URL or token is not configured.")
        return base_url, token

    def _discover_entities(self, states, entity_registry, device_registry, area_registry):
        entity_registry_map = self._index_registry(entity_registry, "entity_id")
        device_registry_map = self._index_registry(device_registry, "id")
        area_registry_map = self._index_registry(area_registry, "area_id")

        records = []
        readings = []
        discovery = {"supported_entities": 0, "areas": set(), "devices": set(), "excluded": 0}

        for row in states or []:
            try:
                if not isinstance(row, dict):
                    discovery["excluded"] += 1
                    continue
                entity_id = str(row.get("entity_id") or "").strip()
                if not entity_id or "." not in entity_id:
                    discovery["excluded"] += 1
                    continue
                domain = entity_id.split(".", 1)[0].lower()
                entity_meta = entity_registry_map.get(entity_id, {})
                device_meta = self._resolve_device_meta(entity_meta, device_registry_map)
                area_meta = self._resolve_area_meta(entity_meta, device_meta, area_registry_map)
                normalized = self._normalize_entity(row, domain, entity_meta, device_meta, area_meta)
                if normalized is None:
                    discovery["excluded"] += 1
                    continue
                entity, reading = normalized
                records.append(entity)
                readings.append(reading)
                discovery["supported_entities"] += 1
                discovery["areas"].add(entity.area_id)
                discovery["devices"].add(entity.device_id)
            except Exception as exc:
                self.log.warning(f"Skipping malformed Home Assistant entity row: {exc}")
                continue

        discovery["areas"] = len(discovery["areas"])
        discovery["devices"] = len(discovery["devices"])
        return records, readings, discovery

    def _normalize_entity(self, row, domain, entity_meta, device_meta, area_meta):
        entity_id = str(row.get("entity_id") or "").strip()
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        raw_state = row.get("state")
        friendly_name = self._pick_friendly_name(entity_meta, attributes, entity_id)
        label_source = self._label_source(entity_meta, attributes, friendly_name, entity_id)
        confidence = 1.0 if label_source == "registry" else 0.6

        device_class = self._pick_text(
            entity_meta.get("device_class") if isinstance(entity_meta, dict) else None,
            attributes.get("device_class"),
            attributes.get("original_device_class"),
        )
        state_class = self._pick_text(
            entity_meta.get("state_class") if isinstance(entity_meta, dict) else None,
            attributes.get("state_class"),
        )
        unit = self._pick_text(
            entity_meta.get("unit_of_measurement") if isinstance(entity_meta, dict) else None,
            attributes.get("unit_of_measurement"),
        )
        integration = self._pick_text(
            entity_meta.get("platform") if isinstance(entity_meta, dict) else None,
            device_meta.get("via_device_id") if isinstance(device_meta, dict) else None,
            attributes.get("source"),
        )

        support_reason = self._support_reason(domain, device_class, state_class, unit, raw_state)
        if support_reason is None:
            return None

        area_id = self._stable_area_id(area_meta, entity_meta, device_meta)
        area_name = self._stable_area_name(area_meta, entity_meta, device_meta, area_id)
        device_id = self._stable_device_id(device_meta, entity_id, area_id)
        device_name = self._stable_device_name(device_meta, entity_meta, device_id, friendly_name)

        parsed_number = self._parse_number(raw_state)
        parsed_boolean = self._parse_boolean(raw_state) if domain == "binary_sensor" else None
        if domain == "binary_sensor" and parsed_boolean is None:
            parsed_boolean = self._parse_boolean(attributes.get("state"))

        enrichment_error = self._enrichment_error(area_meta, device_meta, entity_meta)

        reading = EnvironmentalReading(
            entity_id=entity_id,
            domain=domain,
            raw_state=None if raw_state is None else str(raw_state),
            raw_value=None if raw_state is None else str(raw_state),
            unit_of_measurement=unit,
            parsed_number=parsed_number,
            parsed_boolean=parsed_boolean,
            availability=self._availability(raw_state),
            area_id=area_id,
            area_name=area_name,
            device_id=device_id,
            device_name=device_name,
            entity_name=friendly_name,
            label_source=label_source,
            confidence=confidence,
            timestamp=self._pick_timestamp(row),
            metadata={
                "friendly_name": friendly_name,
                "device_class": device_class,
                "state_class": state_class,
                "integration": integration,
                "raw_attributes": self._trim_attributes(attributes),
                "enrichment_error": enrichment_error,
            },
        )

        entity = EnvironmentalEntity(
            entity_id=entity_id,
            domain=domain,
            entity_name=friendly_name,
            display_name=friendly_name,
            area_id=area_id,
            area_name=area_name,
            device_id=device_id,
            device_name=device_name,
            device_class=device_class,
            state_class=state_class,
            unit_of_measurement=unit,
            integration=integration,
            supported=True,
            confidence=confidence,
            label_source=label_source,
            support_reason=support_reason,
            first_seen=self._pick_timestamp(row),
            last_seen=self._pick_timestamp(row),
            metadata={
                "source_entity_id": entity_id,
                "friendly_name": friendly_name,
                "device_class": device_class,
                "state_class": state_class,
                "raw_attributes": self._trim_attributes(attributes),
                "enrichment_error": enrichment_error,
            },
        )
        return entity, reading

    def _snapshot_payload(self, source):
        if not source:
            source = self._empty_snapshot()
        entities = self.store.all_entities(supported_only=True)
        latest_readings = {row["entity_id"]: row for row in self.store.latest_readings()}
        grouped = self._group_entities(entities, latest_readings)
        summary = {
            "areas": len(grouped),
            "devices": sum(len(area["devices"]) for area in grouped),
            "supported_entities": len(entities),
            "entities_with_readings": len(latest_readings),
            "readings_recorded": self.store.count_readings(),
            "stale_after_minutes": self.stale_after_minutes(),
        }
        snapshot_time = self._snapshot_time(entities, latest_readings, source)
        age_seconds = self._snapshot_age_seconds(snapshot_time)
        stale = self._is_stale(age_seconds, source.get("stale"))
        status = source.get("status") or ("Connected" if entities else "No data")
        availability = source.get("availability") or ("live" if entities else "unavailable")
        message = source.get("message") or (
            "Environmental snapshot loaded from Home Assistant cache." if entities else "Waiting for the first Home Assistant refresh."
        )
        result = {
            "enabled": self.enabled(),
            "configured": self._configured(),
            "status": status,
            "availability": availability,
            "message": message,
            "error": source.get("error"),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "last_successful_refresh": self._last_successful_refresh_at.isoformat(timespec="seconds") if self._last_successful_refresh_at else source.get("last_successful_refresh"),
            "snapshot_age_seconds": age_seconds,
            "snapshot_age_label": self._age_label(age_seconds),
            "stale": stale,
            "last_refresh_error": self._last_refresh_error or source.get("last_refresh_error"),
            "summary": summary,
            "areas": grouped,
            "entities": self._flat_entities(grouped),
            "refresh": source.get("refresh", {}),
        }
        return result

    def _load_cached_snapshot(self):
        try:
            entities = self.store.all_entities(supported_only=True)
            latest_readings = {row["entity_id"]: row for row in self.store.latest_readings()}
            grouped = self._group_entities(entities, latest_readings)
            self._snapshot = {
                "enabled": self.enabled(),
                "configured": self._configured(),
                "status": "Connected" if entities else "No data",
                "availability": "live" if entities else "unavailable",
                "message": "Loaded from cached environmental snapshot." if entities else "No cached environmental snapshot is available yet.",
                "error": None,
                "last_successful_refresh": self._latest_timestamp(latest_readings) or None,
                "snapshot_age_seconds": self._snapshot_age_seconds(self._latest_timestamp(latest_readings)),
                "snapshot_age_label": self._age_label(self._snapshot_age_seconds(self._latest_timestamp(latest_readings))),
                "stale": self._is_stale(self._snapshot_age_seconds(self._latest_timestamp(latest_readings)), False),
                "last_refresh_error": self._last_refresh_error,
                "summary": {
                    "areas": len(grouped),
                    "devices": sum(len(area["devices"]) for area in grouped),
                    "supported_entities": len(entities),
                    "entities_with_readings": len(latest_readings),
                    "readings_recorded": self.store.count_readings(),
                    "stale_after_minutes": self.stale_after_minutes(),
                },
                "areas": grouped,
                "entities": self._flat_entities(grouped),
                "refresh": {},
            }
            self._last_successful_refresh_at = self._parse_timestamp(self._snapshot.get("last_successful_refresh"))
            if not self._last_successful_refresh_at and latest_readings:
                self._last_successful_refresh_at = self._parse_timestamp(self._latest_timestamp(latest_readings))
        except Exception as exc:
            self.log.debug(f"Environment cache load skipped: {exc}", exc_info=True)
            self._snapshot = self._empty_snapshot()

    def _empty_snapshot(self, message="Waiting for the first Home Assistant refresh.", error=None):
        return {
            "enabled": self.enabled(),
            "configured": self._configured(),
            "status": "Disabled" if not self.enabled() else "No data",
            "availability": "disabled" if not self.enabled() else "unavailable",
            "message": message,
            "error": error,
            "last_successful_refresh": None,
            "snapshot_age_seconds": None,
            "snapshot_age_label": "never",
            "stale": True,
            "last_refresh_error": error,
            "summary": {
                "areas": 0,
                "devices": 0,
                "supported_entities": 0,
                "entities_with_readings": 0,
                "readings_recorded": 0,
                "stale_after_minutes": self.stale_after_minutes(),
            },
            "areas": [],
            "entities": [],
            "refresh": {},
        }

    def _group_entities(self, entities, latest_readings):
        areas = OrderedDict()
        for entity in entities or []:
            area_id = entity.get("area_id") or "__unassigned_area__"
            area_name = entity.get("area_name") or "Unassigned Area"
            area = areas.setdefault(
                area_id,
                {
                    "area_id": area_id,
                    "area_name": area_name,
                    "display_name": area_name,
                    "fallback_group": area_id == "__unassigned_area__",
                    "devices": OrderedDict(),
                    "entity_count": 0,
                    "reading_count": 0,
                },
            )
            device_id = entity.get("device_id") or f"{area_id}::__unassigned_device__"
            device_name = entity.get("device_name") or "Unassigned Device"
            device = area["devices"].setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "device_name": device_name,
                    "display_name": device_name,
                    "fallback_group": device_id.endswith("::__unassigned_device__"),
                    "entities": [],
                    "entity_count": 0,
                    "reading_count": 0,
                },
            )
            reading = latest_readings.get(entity.get("entity_id"))
            entity_payload = dict(entity)
            entity_payload["latest_reading"] = reading
            device["entities"].append(entity_payload)
            device["entity_count"] += 1
            if reading:
                device["reading_count"] += 1
            area["entity_count"] += 1
            if reading:
                area["reading_count"] += 1

        result = []
        for area in areas.values():
            devices = list(area["devices"].values())
            devices.sort(key=lambda item: (item["display_name"].lower(), item["device_id"]))
            area["devices"] = devices
            result.append(area)
        result.sort(key=lambda item: (item["display_name"].lower(), item["area_id"]))
        return result

    def _flat_entities(self, grouped):
        rows = []
        for area in grouped or []:
            for device in area.get("devices", []):
                for entity in device.get("entities", []):
                    row = dict(entity)
                    row["area_id"] = area.get("area_id")
                    row["area_name"] = area.get("area_name")
                    row["device_id"] = device.get("device_id")
                    row["device_name"] = device.get("device_name")
                    rows.append(row)
        return rows

    def _latest_timestamp(self, readings):
        timestamps = [row.get("timestamp") for row in (readings or {}).values() if row and row.get("timestamp")]
        if not timestamps:
            return None
        return max(timestamps)

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None
        text = str(value).strip().replace(" ", "T")
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text[:19])
            except ValueError:
                return None

    def _snapshot_time(self, entities, latest_readings, source):
        timestamps = [source.get("last_successful_refresh")]
        timestamps.extend(row.get("timestamp") for row in latest_readings.values() if row)
        timestamps.extend(entity.get("last_seen") for entity in entities or [] if entity.get("last_seen"))
        timestamps = [ts for ts in timestamps if ts]
        if not timestamps:
            return None
        return max(timestamps)

    def _snapshot_age_seconds(self, snapshot_time):
        parsed = self._parse_timestamp(snapshot_time)
        if not parsed:
            return None
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo is not None else datetime.now()
        delta = now - parsed
        return max(0, int(delta.total_seconds()))

    def _is_stale(self, age_seconds, existing_stale):
        if existing_stale:
            return True
        if age_seconds is None:
            return True
        return age_seconds >= self.stale_after_minutes() * 60

    @staticmethod
    def _age_label(age_seconds):
        if age_seconds is None:
            return "never"
        if age_seconds < 60:
            return f"{age_seconds}s ago"
        minutes, seconds = divmod(age_seconds, 60)
        if minutes < 60:
            return f"{minutes}m ago"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}h {minutes}m ago"
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h ago"

    def _configured(self):
        try:
            self._home_assistant_credentials()
            return True
        except Exception:
            return False

    @staticmethod
    def _index_registry(rows, key):
        result = {}
        for row in rows or []:
            if isinstance(row, dict):
                value = row.get(key)
                if value:
                    result[str(value)] = row
        return result

    @staticmethod
    def _resolve_device_meta(entity_meta, device_registry_map):
        device_id = None
        if isinstance(entity_meta, dict):
            device_id = entity_meta.get("device_id")
        if device_id and str(device_id) in device_registry_map:
            return device_registry_map[str(device_id)]
        return {}

    @staticmethod
    def _resolve_area_meta(entity_meta, device_meta, area_registry_map):
        area_id = None
        if isinstance(entity_meta, dict):
            area_id = entity_meta.get("area_id")
        if not area_id and isinstance(device_meta, dict):
            area_id = device_meta.get("area_id")
        if area_id and str(area_id) in area_registry_map:
            return area_registry_map[str(area_id)]
        return {}

    @staticmethod
    def _enrichment_error(area_meta, device_meta, entity_meta):
        missing = []
        if not area_meta and not (isinstance(entity_meta, dict) and entity_meta.get("area_id")):
            missing.append("area")
        if not device_meta and not (isinstance(entity_meta, dict) and entity_meta.get("device_id")):
            missing.append("device")
        if missing:
            return f"Missing registry metadata: {', '.join(missing)}"
        return None

    @staticmethod
    def _pick_friendly_name(entity_meta, attributes, entity_id):
        for source in (
            entity_meta.get("name") if isinstance(entity_meta, dict) else None,
            entity_meta.get("original_name") if isinstance(entity_meta, dict) else None,
            attributes.get("friendly_name") if isinstance(attributes, dict) else None,
        ):
            text = str(source or "").strip()
            if text:
                return text
        tail = entity_id.split(".", 1)[-1].replace("_", " ").strip()
        return tail.title() if tail else entity_id

    @staticmethod
    def _label_source(entity_meta, attributes, friendly_name, entity_id):
        registry_values = (
            entity_meta.get("name") if isinstance(entity_meta, dict) else None,
            entity_meta.get("original_name") if isinstance(entity_meta, dict) else None,
            attributes.get("friendly_name") if isinstance(attributes, dict) else None,
        )
        if any(str(value or "").strip() for value in registry_values):
            return "registry"
        return "fallback"

    @staticmethod
    def _pick_text(*values):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return None

    @staticmethod
    def _stable_area_id(area_meta, entity_meta, device_meta):
        for source in (area_meta, entity_meta, device_meta):
            if isinstance(source, dict):
                value = source.get("area_id")
                if value:
                    return str(value)
        return "__unassigned_area__"

    @staticmethod
    def _stable_area_name(area_meta, entity_meta, device_meta, area_id):
        for source in (area_meta, entity_meta, device_meta):
            if isinstance(source, dict):
                value = source.get("name") or source.get("area_name")
                if value:
                    return str(value)
        return "Unassigned Area" if area_id == "__unassigned_area__" else area_id.replace("_", " ").title()

    @staticmethod
    def _stable_device_id(device_meta, entity_id, area_id):
        if isinstance(device_meta, dict) and device_meta.get("id"):
            return str(device_meta["id"])
        if isinstance(device_meta, dict) and device_meta.get("device_id"):
            return str(device_meta["device_id"])
        return f"{area_id}::__unassigned_device__"

    @staticmethod
    def _stable_device_name(device_meta, entity_meta, device_id, fallback_name):
        if not isinstance(device_meta, dict) or not device_meta:
            return "Unknown Device"
        for source in (device_meta, entity_meta):
            if isinstance(source, dict):
                for key in ("name", "name_by_user", "original_name"):
                    value = source.get(key)
                    if value:
                        return str(value)
        return fallback_name

    @staticmethod
    def _availability(raw_state):
        state = str(raw_state if raw_state is not None else "").strip().lower()
        if state in {"unavailable", "unknown", "none", "null"}:
            return "unavailable"
        return "available"

    @staticmethod
    def _parse_number(value):
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text.lower() in {"unknown", "unavailable", "none", "null", "nan"}:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_boolean(value):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"on", "open", "home", "present", "true", "yes", "1", "enabled", "detected"}:
            return True
        if text in {"off", "closed", "away", "absent", "false", "no", "0", "disabled", "clear", "not detected"}:
            return False
        return None

    @staticmethod
    def _pick_timestamp(row):
        for key in ("last_updated", "last_changed", "timestamp"):
            value = row.get(key) if isinstance(row, dict) else None
            if value:
                return str(value)
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _trim_attributes(attributes):
        if not isinstance(attributes, dict):
            return {}
        allowed = {}
        for key in (
            "device_class",
            "state_class",
            "friendly_name",
            "unit_of_measurement",
            "icon",
            "entity_category",
            "integration",
            "platform",
            "source",
        ):
            value = attributes.get(key)
            if value is not None and str(value).strip():
                allowed[key] = value
        return allowed

    def _support_reason(self, domain, device_class, state_class, unit, raw_state):
        if domain == "sensor":
            if device_class in SUPPORTED_SENSOR_DEVICE_CLASSES:
                return f"device_class:{device_class}"
            if state_class in {"measurement", "total", "total_increasing"} and self._parse_number(raw_state) is not None:
                return f"state_class:{state_class}"
            if unit and self._sensor_unit_supported(unit) and self._parse_number(raw_state) is not None:
                return "numeric_state"
            return None
        if domain == "binary_sensor":
            if device_class in SUPPORTED_BINARY_SENSOR_CLASSES:
                return f"device_class:{device_class}"
            if self._parse_boolean(raw_state) is not None:
                return "binary_state"
            return None
        return None

    @staticmethod
    def _sensor_unit_supported(unit):
        normalized = str(unit or "").strip().lower()
        return normalized in {
            "%", "c", "f", "k",
            "pa", "hpa", "mbar", "inhg", "psi",
            "lx", "lm",
            "ppm", "ppb",
            "w", "kw", "mw", "wh", "kwh", "mwh",
            "v", "kv", "a", "ma",
            "hz",
            "mm", "cm", "m", "in",
            "mph", "km/h", "kmh", "m/s", "ms", "kn", "kt",
            "deg", "degrees",
            "db", "dbm", "rssi",
            "mah", "ah",
            "g", "mg",
        }


class HomeAssistantWebSocket:
    def __init__(self, sock):
        self.sock = sock
        self._next_message_id = 1
        self._buffer = b""

    def next_id(self):
        message_id = self._next_message_id
        self._next_message_id += 1
        return message_id

    def send_json(self, payload):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(data, opcode=0x1)

    def recv_json(self, expected_id=None):
        while True:
            frame = self._read_frame()
            if frame is None:
                raise ConnectionError("WebSocket closed")
            opcode, payload = frame
            if opcode == 0x8:
                raise ConnectionError("WebSocket closed by remote host")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode != 0x1:
                continue
            message = json.loads(payload.decode("utf-8", errors="replace"))
            if expected_id is not None and message.get("id") != expected_id:
                continue
            return message

    def close(self):
        try:
            self._send_frame(b"", opcode=0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

    def _send_frame(self, payload, opcode=0x1):
        mask = os.urandom(4)
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_frame(self):
        while len(self._buffer) < 2:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buffer += chunk
        first, second = self._buffer[0], self._buffer[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        index = 2
        if length == 126:
            while len(self._buffer) < index + 2:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                self._buffer += chunk
            length = struct.unpack("!H", self._buffer[index:index + 2])[0]
            index += 2
        elif length == 127:
            while len(self._buffer) < index + 8:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                self._buffer += chunk
            length = struct.unpack("!Q", self._buffer[index:index + 8])[0]
            index += 8
        if masked:
            while len(self._buffer) < index + 4:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                self._buffer += chunk
            mask = self._buffer[index:index + 4]
            index += 4
        while len(self._buffer) < index + length:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buffer += chunk
        payload = self._buffer[index:index + length]
        self._buffer = self._buffer[index + length:]
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return opcode, payload
