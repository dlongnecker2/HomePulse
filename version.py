from pathlib import Path


def _read_version(default_version="3.5.1"):
	version_file = Path("VERSION")
	if not version_file.exists():
		return default_version
	try:
		value = version_file.read_text(encoding="utf-8").strip()
		return value or default_version
	except Exception:
		return default_version


APP_NAME = "HomePulse"
APP_VERSION = _read_version("3.5.1")
APP_AUTHOR = "Dennis Longnecker"
APP_COPYRIGHT = "© 2026 Dennis Longnecker"
