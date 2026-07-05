import json
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MESH_CACHE_SECONDS = 30
UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}
ONLINE_STATES = {"on", "online", "connected", "home", "true"}
OFFLINE_STATES = {"off", "offline", "disconnected", "not_home", "away", "false"}


class NetworkMeshManager:
    def __init__(self, config, log):
        self.config = config
        self.log = log
        self._cache = None
        self._cache_at = None

    def get_status(self, internet_status=None):
        now = datetime.now()
        if self._cache and self._cache_at:
            age = (now - self._cache_at).total_seconds()
            if age < MESH_CACHE_SECONDS:
                cached = dict(self._cache)
                cached["timestamp"] = str(now)
                self._apply_internet_summary(cached, internet_status)
                return cached

        try:
            rows = self._fetch_home_assistant_states(timeout_seconds=3)
            payload = self._normalize_payload(rows)
            payload["timestamp"] = str(now)
            self._apply_internet_summary(payload, internet_status)
            self._cache = dict(payload)
            self._cache_at = now
            return payload
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            return self._unavailable_payload(str(exc), internet_status)
        except Exception as exc:
            self.log.exception(f"Network mesh collection failed: {exc}")
            return self._unavailable_payload(str(exc), internet_status)

    def _unavailable_payload(self, error_text, internet_status):
        payload = {
            "data_available": False,
            "message": "Mesh data is unavailable right now.",
            "timestamp": str(datetime.now()),
            "nodes": [],
            "clients": [],
            "summary": {
                "internet_online": None,
                "mesh_nodes_online": 0,
                "mesh_nodes_total": 0,
                "connected_clients": 0,
                "current_total_down_kbps": None,
                "current_total_up_kbps": None,
            },
            "insights": [],
            "error": error_text,
        }
        self._apply_internet_summary(payload, internet_status)
        return payload

    def _apply_internet_summary(self, payload, internet_status):
        summary = payload.setdefault("summary", {})
        if isinstance(internet_status, dict):
            state = str(internet_status.get("status") or "").strip().lower()
            if state in {"healthy", "degraded", "starting", "available", "up"}:
                summary["internet_online"] = True
            elif state in {"unhealthy", "down", "unavailable"}:
                summary["internet_online"] = False

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

    def _fetch_home_assistant_states(self, timeout_seconds):
        base_url, token = self._home_assistant_credentials()
        request = Request(
            f"{base_url}/api/states",
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, list):
            raise ValueError("Home Assistant /api/states returned a non-list payload.")
        return payload

    def _normalize_payload(self, rows):
        nodes = {}
        clients = []
        totals = {"down": None, "up": None}

        for row in rows:
            if not isinstance(row, dict):
                continue

            node = self._normalize_node(row)
            if node:
                key = str(node.get("node_key") or node.get("name") or node.get("entity_id") or "").strip().lower()
                if key:
                    existing = nodes.get(key)
                    nodes[key] = self._merge_node(existing, node)
                continue

            client = self._normalize_client(row)
            if client:
                clients.append(client)
                continue

            total_down = self._extract_rate_kbps(row, direction="down")
            total_up = self._extract_rate_kbps(row, direction="up")
            entity_id = str(row.get("entity_id") or "").strip().lower()
            if self._is_total_traffic_entity(entity_id):
                if total_down is not None:
                    totals["down"] = total_down
                if total_up is not None:
                    totals["up"] = total_up

        node_list = sorted(nodes.values(), key=lambda item: str(item.get("name") or "").lower())
        client_list = sorted(clients, key=lambda item: str(item.get("friendly_name") or item.get("name") or "").lower())

        if totals["down"] is None:
            totals["down"] = self._sum_number(node.get("down_kbps") for node in node_list)
        if totals["up"] is None:
            totals["up"] = self._sum_number(node.get("up_kbps") for node in node_list)

        self._backfill_node_client_counts(node_list, client_list)

        summary = {
            "internet_online": None,
            "mesh_nodes_online": sum(1 for node in node_list if node.get("online") is True),
            "mesh_nodes_total": len(node_list),
            "connected_clients": len(client_list),
            "current_total_down_kbps": totals["down"],
            "current_total_up_kbps": totals["up"],
        }

        insights = self._build_insights(node_list, client_list)
        data_available = bool(node_list or client_list or totals["down"] is not None or totals["up"] is not None)
        message = "Mesh data loaded from Home Assistant Deco entities." if data_available else "No Deco mesh entities were found in Home Assistant."

        return {
            "data_available": data_available,
            "message": message,
            "timestamp": str(datetime.now()),
            "nodes": node_list,
            "clients": client_list,
            "summary": summary,
            "insights": insights,
        }

    def _normalize_node(self, row):
        entity_id = str(row.get("entity_id") or "").strip()
        lowered = entity_id.lower()
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        friendly_name = str(attributes.get("friendly_name") or "").strip()
        marker = f"{lowered} {friendly_name.lower()}"
        node_key = self._node_key_from_entity(entity_id)

        has_node_signals = any(
            key in attributes
            for key in (
                "connected_clients",
                "client_count",
                "clients",
                "node_model",
                "firmware",
                "firmware_version",
            )
        )
        has_node_entity_id = bool(node_key)
        has_deco_marker = "deco" in marker and "client" not in marker and "device_tracker" not in lowered
        if not has_node_signals and not has_deco_marker and not has_node_entity_id:
            return None

        if self._looks_like_client(attributes):
            return None

        raw_state = str(row.get("state") or "").strip().lower()
        online = None
        if raw_state in ONLINE_STATES:
            online = True
        elif raw_state in OFFLINE_STATES:
            online = False
        elif raw_state in UNAVAILABLE_STATES:
            online = False

        connected_clients = self._to_int(
            attributes.get("connected_clients")
            if attributes.get("connected_clients") is not None
            else attributes.get("client_count", attributes.get("clients"))
        )
        if connected_clients is None and "connected_clients" in lowered:
            connected_clients = self._to_int(row.get("state"))

        down = self._extract_rate_kbps(row, "down")
        up = self._extract_rate_kbps(row, "up")
        if down is None and any(token in lowered for token in ("_down", "download", "downstream", "_rx")):
            down = self._to_number(row.get("state"), unit=attributes.get("unit_of_measurement"))
        if up is None and any(token in lowered for token in ("_up", "upload", "upstream", "_tx")):
            up = self._to_number(row.get("state"), unit=attributes.get("unit_of_measurement"))

        name = self._friendly_node_name(node_key) or friendly_name or self._friendly_entity_name(entity_id)
        return {
            "node_key": node_key,
            "entity_id": entity_id,
            "name": name,
            "model": self._clean_text(attributes.get("model") or attributes.get("node_model") or attributes.get("hardware")),
            "online": online,
            "connected_clients": connected_clients,
            "down_kbps": down,
            "up_kbps": up,
            "total_down_kbps": self._to_number(attributes.get("total_down_kbps") or attributes.get("total_download_kbps")),
            "total_up_kbps": self._to_number(attributes.get("total_up_kbps") or attributes.get("total_upload_kbps")),
            "firmware": self._clean_text(attributes.get("firmware") or attributes.get("firmware_version")),
            "last_updated": row.get("last_updated"),
        }

    def _normalize_client(self, row):
        entity_id = str(row.get("entity_id") or "").strip()
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        if not self._looks_like_client(attributes):
            return None

        friendly_name = self._clean_text(attributes.get("friendly_name"))
        if self._looks_like_node_client_alias(friendly_name):
            return None
        host_name = self._clean_text(attributes.get("host_name") or attributes.get("hostname") or attributes.get("name"))
        name = host_name or friendly_name or self._friendly_entity_name(entity_id)
        raw_state = str(row.get("state") or "").strip().lower()
        connection_type = self._clean_text(
            attributes.get("connection_type")
            or attributes.get("interface")
            or attributes.get("link_type")
        )
        band = self._normalize_band(attributes.get("band") or attributes.get("wifi_band") or connection_type)

        return {
            "name": name,
            "friendly_name": friendly_name or name,
            "state": raw_state or "unknown",
            "ip": self._clean_text(attributes.get("ip") or attributes.get("ip_address")),
            "mac": self._normalize_mac(attributes.get("mac") or attributes.get("mac_address")),
            "deco_node": self._clean_text(
                attributes.get("connected_deco_node")
                or attributes.get("connected_node")
                or attributes.get("node")
                or attributes.get("ap")
            ),
            "connection_type": connection_type,
            "band": band,
            "device_type": self._guess_device_type(name),
            "down_kbps": self._extract_rate_kbps(row, "down"),
            "up_kbps": self._extract_rate_kbps(row, "up"),
            "last_changed": row.get("last_changed"),
            "last_updated": row.get("last_updated"),
        }

    @staticmethod
    def _looks_like_client(attributes):
        if not isinstance(attributes, dict):
            return False
        has_identity = bool(attributes.get("mac") or attributes.get("mac_address") or attributes.get("ip") or attributes.get("ip_address"))
        has_connection = any(
            attributes.get(key)
            for key in ("connected_deco_node", "connected_node", "node", "ap", "band", "wifi_band", "connection_type")
        )
        return has_identity and has_connection

    @staticmethod
    def _looks_like_node_client_alias(friendly_name):
        text = str(friendly_name or "").strip().lower()
        if not text:
            return False
        if text.endswith(" deco"):
            return True
        if text.endswith(" deco mini"):
            return True
        return False

    @staticmethod
    def _node_key_from_entity(entity_id):
        text = str(entity_id or "").strip().lower()
        if "." in text:
            text = text.split(".", 1)[1]
        tokens = [token for token in text.split("_") if token]
        if "deco" not in tokens:
            return None
        deco_index = tokens.index("deco")
        if deco_index < 0:
            return None
        return "_".join(tokens[: deco_index + 1]) if deco_index + 1 <= len(tokens) else None

    @staticmethod
    def _friendly_node_name(node_key):
        text = str(node_key or "").strip()
        if not text:
            return None
        return text.replace("_", " ").title()

    def _build_insights(self, nodes, clients):
        insights = []
        if nodes:
            with_clients = [node for node in nodes if isinstance(node.get("connected_clients"), int)]
            if with_clients:
                busiest_clients = max(with_clients, key=lambda row: row.get("connected_clients", 0))
                insights.append({
                    "type": "busiest_node_by_clients",
                    "message": f"Busiest node by clients: {busiest_clients.get('name')} ({busiest_clients.get('connected_clients')} clients).",
                })

            traffic_nodes = []
            for node in nodes:
                down = self._to_number(node.get("down_kbps")) or 0
                up = self._to_number(node.get("up_kbps")) or 0
                traffic_nodes.append((node, down + up))
            traffic_nodes = [item for item in traffic_nodes if item[1] > 0]
            if traffic_nodes:
                busiest_traffic = max(traffic_nodes, key=lambda item: item[1])
                insights.append({
                    "type": "busiest_node_by_traffic",
                    "message": f"Busiest node by traffic: {busiest_traffic[0].get('name')} ({round(busiest_traffic[1], 1)} KB/s).",
                })

        if clients:
            counts = {"2.4 GHz": 0, "5 GHz": 0, "6 GHz": 0, "Unknown": 0}
            for client in clients:
                band = self._normalize_band(client.get("band"))
                if band in counts:
                    counts[band] += 1
                else:
                    counts["Unknown"] += 1
            known_total = counts["2.4 GHz"] + counts["5 GHz"] + counts["6 GHz"]
            if known_total > 0:
                insights.append({
                    "type": "band_distribution",
                    "message": (
                        f"Client band distribution: 2.4 GHz={counts['2.4 GHz']}, "
                        f"5 GHz={counts['5 GHz']}, 6 GHz={counts['6 GHz']}."
                    ),
                })

        return insights

    def _backfill_node_client_counts(self, nodes, clients):
        counts = {}
        for client in clients:
            node_name = str(client.get("deco_node") or "").strip().lower()
            if node_name:
                counts[node_name] = counts.get(node_name, 0) + 1

        for node in nodes:
            existing = node.get("connected_clients")
            if isinstance(existing, int):
                continue
            node_name = str(node.get("name") or "").strip().lower()
            if node_name in counts:
                node["connected_clients"] = counts[node_name]

    @staticmethod
    def _merge_node(existing, incoming):
        if not existing:
            return incoming
        merged = dict(existing)
        for key, value in incoming.items():
            if value is None:
                continue
            if key == "connected_clients":
                merged[key] = value if merged.get(key) is None else max(int(merged.get(key) or 0), int(value or 0))
            elif key in ("down_kbps", "up_kbps", "total_down_kbps", "total_up_kbps"):
                merged[key] = value if merged.get(key) is None else max(float(merged.get(key) or 0), float(value or 0))
            elif key == "online":
                if merged.get(key) is None:
                    merged[key] = value
                elif value is True:
                    merged[key] = True
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _sum_number(values):
        total = 0.0
        seen = False
        for value in values:
            if value is None:
                continue
            total += float(value)
            seen = True
        return round(total, 1) if seen else None

    @staticmethod
    def _friendly_entity_name(entity_id):
        name = str(entity_id or "").split(".")[-1].replace("_", " ").strip()
        return name.title() if name else "Unknown"

    @staticmethod
    def _clean_text(value):
        text = str(value or "").strip()
        return text if text and text.lower() not in UNAVAILABLE_STATES else None

    @staticmethod
    def _normalize_mac(value):
        text = str(value or "").strip().lower().replace("-", ":")
        if not text:
            return None
        if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", text):
            return text
        return text

    @staticmethod
    def _normalize_band(value):
        text = str(value or "").strip().lower()
        if not text:
            return None
        if "2.4" in text:
            return "2.4 GHz"
        if "5" in text:
            return "5 GHz"
        if "6" in text:
            return "6 GHz"
        return value

    @staticmethod
    def _guess_device_type(name):
        text = str(name or "").strip().lower()
        if not text:
            return "unknown"
        if any(token in text for token in ("iphone", "android", "pixel", "phone", "galaxy")):
            return "phone"
        if any(token in text for token in ("laptop", "macbook", "desktop", "pc", "computer")):
            return "computer"
        if any(token in text for token in ("printer", "hp ", "epson", "brother")):
            return "printer"
        if any(token in text for token in ("roku", "apple tv", "chromecast", "fire tv", "stream")):
            return "streaming"
        if any(token in text for token in ("nest", "ring", "thermostat", "camera", "switch", "plug", "bulb", "echo", "alexa")):
            return "smart home"
        if any(token in text for token in ("tesla", "vehicle", "car", "ev")):
            return "vehicle"
        return "unknown"

    def _extract_rate_kbps(self, row, direction):
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        keys = (
            ("down_kbps", "download_kbps", "current_download_kbps", "download_rate", "download", "rx_kbps")
            if direction == "down"
            else ("up_kbps", "upload_kbps", "current_upload_kbps", "upload_rate", "upload", "tx_kbps")
        )
        for key in keys:
            value = attributes.get(key)
            parsed = self._to_number(value)
            if parsed is not None:
                return parsed

        entity_id = str(row.get("entity_id") or "").lower()
        if direction == "down" and any(token in entity_id for token in ("download", "downstream", "rx")):
            return self._to_number(row.get("state"), unit=attributes.get("unit_of_measurement"))
        if direction == "up" and any(token in entity_id for token in ("upload", "upstream", "tx")):
            return self._to_number(row.get("state"), unit=attributes.get("unit_of_measurement"))
        return None

    @staticmethod
    def _is_total_traffic_entity(entity_id):
        if "deco" not in entity_id:
            return False
        return any(token in entity_id for token in ("total", "aggregate", "overall")) and any(
            token in entity_id for token in ("download", "upload", "throughput", "traffic", "rx", "tx")
        )

    def _to_int(self, value):
        number = self._to_number(value)
        if number is None:
            return None
        return int(round(number))

    def _to_number(self, value, unit=None):
        if value in (None, ""):
            return None
        text = str(value).strip().replace(",", "")
        if not text or text.lower() in UNAVAILABLE_STATES:
            return None

        match = re.search(r"-?\d+(\.\d+)?", text)
        if not match:
            return None
        number = float(match.group(0))

        unit_text = str(unit or "").strip().lower()
        source = f"{text} {unit_text}".lower()
        if "mb/s" in source or "mbps" in source or unit_text == "mb/s":
            number *= 1024
        elif "gb/s" in source or "gbps" in source or unit_text == "gb/s":
            number *= 1024 * 1024
        elif "b/s" in source and "kb/s" not in source and "mb/s" not in source and "gb/s" not in source:
            number /= 1024
        return round(number, 1)