import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path


class ConfigBackupService:
    def __init__(self, config_path, backup_dir=None, retention_limit=20):
        self.config_path = Path(config_path)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else self.config_path.parent / "data" / "config_backups"
        self.retention_limit = int(retention_limit or 20)

    def list_backups(self):
        if not self.backup_dir.exists():
            return []
        backups = [path for path in self.backup_dir.glob("config-*.json") if path.is_file()]
        return sorted(backups, key=lambda path: path.stat().st_mtime, reverse=True)

    def validate_backup(self, backup_path):
        path = Path(backup_path)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.validate_config_payload(payload)
        return payload

    def restore_backup(self, backup_path):
        payload = self.validate_backup(backup_path)
        self.write_config(payload)
        return payload

    def create_backup(self):
        if not self.config_path.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = self._next_backup_path()
        backup_path.write_bytes(self.config_path.read_bytes())
        self._prune_backups()
        return backup_path

    def write_config(self, payload):
        self.validate_config_payload(payload)
        target_dir = self.config_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target_dir,
                prefix=f"{self.config_path.stem}-",
                suffix=".tmp",
                delete=False,
                newline="\n",
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            with temp_path.open("r", encoding="utf-8") as handle:
                validated = json.load(handle)
            self.validate_config_payload(validated)

            backup_path = self.create_backup()
            os.replace(temp_path, self.config_path)
            temp_path = None
            self._prune_backups()
            return backup_path
        except Exception:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    def _next_backup_path(self):
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        candidate = self.backup_dir / f"config-{timestamp}.json"
        suffix = 1
        while candidate.exists():
            candidate = self.backup_dir / f"config-{timestamp}-{suffix}.json"
            suffix += 1
        return candidate

    def _prune_backups(self):
        backups = self.list_backups()
        for path in backups[self.retention_limit :]:
            try:
                path.unlink()
            except Exception:
                pass

    @staticmethod
    def validate_config_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("Configuration root must be a JSON object.")

        for key in ("router_reboot", "email", "history", "weather", "lighting", "garden", "solar", "vehicle", "energy"):
            value = payload.get(key)
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"Configuration section '{key}' must be an object.")

        return True

    @staticmethod
    def merge_config(base, updates):
        if not isinstance(base, dict):
            base = {}
        if not isinstance(updates, dict):
            raise ValueError("Configuration updates must be a JSON object.")

        merged = deepcopy(base)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = ConfigBackupService.merge_config(merged.get(key, {}), value)
            else:
                merged[key] = deepcopy(value)
        return merged
