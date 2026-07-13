# Environment Foundation

This phase adds a cache-backed environmental monitoring layer for Home Assistant entities.

## Architecture

- `modules/environment/manager.py` performs one controlled Home Assistant refresh at a time.
- A refresh reads:
  - `/api/states`
  - `/api/config/entity_registry/list`
  - `/api/config/device_registry/list`
  - `/api/config/area_registry/list`
- The manager normalizes supported environmental entities into a stable internal model and persists them through `EnvironmentStore`.
- Web routes never call Home Assistant directly. They only read the last completed cached snapshot.
- If Home Assistant is temporarily unavailable, the last successful snapshot remains available and is marked stale.

## Entity Normalization Rules

- Support is intentionally narrow.
- Discovery prefers, in order:
  - `device_class`
  - registry metadata
  - domain/state-class/unit hints
  - friendly-name fallback only as a low-confidence display label
- Area grouping comes first.
- Device grouping comes second.
- Entities with missing registry metadata stay in explicit fallback groups instead of being dropped.
- Raw values and units are preserved.
- Parsed numeric and boolean values are stored separately.

## Storage

- `environment_entities` stores the stable entity registry.
- `environment_readings` stores reading history.
- Duplicate readings are skipped when raw value, unit, parsed value, and availability have not meaningfully changed.
- New entities with no readings return an empty history series.

## Read-Only API

- `GET /api/environment/status`
  - Returns the cached snapshot with freshness and stale metadata.
- `GET /api/environment/entities`
  - Returns the cached area/device/entity grouping.
- `GET /api/environment/history/<entity_id>`
  - Returns the stored history series for a single entity.
  - Returns an empty series when no samples exist.

## UI

- `GET /environment`
  - Renders the basic Home Monitoring Center page from the cached snapshot.
  - It does not make Home Assistant requests during template rendering.

## Operational Notes

- Background refresh is scheduled by the existing application scheduler.
- History capture keeps going if one entity row is malformed.
- Unsupported sensor entities remain excluded.
