import json
from pathlib import Path


CONFIG_FILE = Path("config.json")


class Config:
    def __init__(self):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def get(self, *keys):
        value = self.data
        for key in keys:
            value = value[key]
        return value
