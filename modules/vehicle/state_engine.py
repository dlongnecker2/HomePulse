"""
Vehicle State Engine
====================
Merges Chevrolet / OnStar vehicle telemetry with ChargePoint / Energy Center
charger data into a single unified vehicle state dictionary.

Rules
-----
* Chevrolet / OnStar owns: battery_percent, range_mi, odometer_mi,
  lifetime_energy_kwh, lifetime_efficiency_mi_per_kwh.
* ChargePoint / Energy Center owns: charging_power_kw, session_energy_kwh,
  estimated_miles_added, estimated_cost, charger_status, charging_time,
  miles_per_hour_added.
* plugged_in and charging use OR-logic: true if *either* source reports it.
  ChargePoint is preferred for live charging state because it updates faster.
* estimated_miles_added falls back to session_energy_kwh × vehicle efficiency
  when ChargePoint does not supply it directly.

Both sources are optional.  The merge never raises; it always returns a
complete dict (with None for unavailable values).
"""

_CP_CHARGING = frozenset({"charging", "active", "in progress"})
_CP_CONNECTED = frozenset(
    {"charging", "active", "in progress", "connected", "plugged in", "plugged"}
)


def _safe_float(value, minimum=None):
    """Parse *value* as float; return None on failure or below minimum."""
    if value is None:
        return None
    try:
        f = float(str(value).strip().replace("$", "").replace(",", ""))
        if minimum is not None and f < minimum:
            return None
        return f
    except (TypeError, ValueError):
        return None


def merge_vehicle_state(vehicle_dict, energy_dict):
    """
    Return a dict of unified fields to overlay on a VehicleStatus dict.

    Parameters
    ----------
    vehicle_dict : dict | None
        The raw VehicleStatus.to_dict() result (Chevrolet / OnStar data).
    energy_dict : dict | None
        The raw EnergyStatus.to_dict() result (ChargePoint / Energy Center).

    Returns
    -------
    dict with keys:
        plugged_in, charging, charging_power_kw, session_energy_kwh,
        estimated_miles_added, estimated_cost, charger_name, charger_status,
        charging_time, miles_per_hour_added, sources
    """
    v = vehicle_dict or {}
    e = energy_dict or {}
    energy_live = bool(e.get("enabled") and e.get("configured"))

    sources = {}

    # ── Source labels for Chevrolet-owned fields ──────────────────────────────
    for field in (
        "battery_percent",
        "range_mi",
        "odometer_mi",
        "lifetime_energy_kwh",
        "lifetime_efficiency_mi_per_kwh",
    ):
        if v.get(field) is not None:
            sources[field] = "chevrolet"

    # ── Plugged In ────────────────────────────────────────────────────────────
    chevy_plugged = v.get("plug_state") == "Plugged In"
    cp_status_text = str(e.get("status") or "").strip().lower()
    cp_plugged = energy_live and (
        bool(e.get("is_charging"))
        or (_safe_float(e.get("power_kw"), minimum=0.10) is not None)
        or cp_status_text in _CP_CONNECTED
    )
    plugged_in = chevy_plugged or cp_plugged
    if chevy_plugged and cp_plugged:
        sources["plugged_in"] = "combined"
    elif cp_plugged:
        sources["plugged_in"] = "chargepoint"
    else:
        sources["plugged_in"] = "chevrolet"

    # ── Charging ──────────────────────────────────────────────────────────────
    cp_charging = energy_live and (
        bool(e.get("is_charging"))
        or (_safe_float(e.get("power_kw"), minimum=0.10) is not None)
        or cp_status_text in _CP_CHARGING
    )
    chevy_charging = v.get("charging_state") == "Charging"
    charging = cp_charging or chevy_charging
    sources["charging"] = "chargepoint" if cp_charging else "chevrolet"

    # ── Charging Power: prefer ChargePoint ───────────────────────────────────
    charging_power_kw = None
    if energy_live:
        raw = _safe_float(e.get("power_kw"), minimum=0)
        if raw is not None:
            charging_power_kw = round(raw, 2)
            sources["charging_power_kw"] = "chargepoint"

    # ── Session Energy: prefer ChargePoint ───────────────────────────────────
    session_energy_kwh = None
    if energy_live:
        raw = _safe_float(e.get("session_energy_kwh"), minimum=0)
        if raw is not None:
            session_energy_kwh = round(raw, 2)
            sources["session_energy_kwh"] = "chargepoint"

    # ── Estimated Miles Added: prefer ChargePoint; fallback = calculated ─────
    estimated_miles_added = None
    if energy_live:
        raw = _safe_float(e.get("estimated_miles_added"), minimum=0)
        if raw is not None:
            estimated_miles_added = round(raw, 1)
            sources["estimated_miles_added"] = "chargepoint"
    if estimated_miles_added is None and session_energy_kwh:
        eff = _safe_float(v.get("lifetime_efficiency_mi_per_kwh"), minimum=0.01)
        if eff:
            estimated_miles_added = round(session_energy_kwh * eff, 1)
            sources["estimated_miles_added"] = "calculated"

    # ── Estimated Cost: prefer ChargePoint ───────────────────────────────────
    estimated_cost = None
    if energy_live:
        raw = _safe_float(e.get("estimated_cost"), minimum=0)
        if raw is not None:
            estimated_cost = round(raw, 2)
            sources["estimated_cost"] = "chargepoint"

    # ── Charger metadata ─────────────────────────────────────────────────────
    charger_name = e.get("charger_name") if energy_live else None
    charger_status = e.get("status") if energy_live else None
    charging_time = e.get("charging_time") if energy_live else None
    mph_raw = _safe_float(e.get("miles_per_hour_added"), minimum=0) if energy_live else None
    miles_per_hour_added = round(mph_raw, 1) if mph_raw is not None else None

    return {
        "plugged_in": plugged_in,
        "charging": charging,
        "charging_power_kw": charging_power_kw,
        "session_energy_kwh": session_energy_kwh,
        "estimated_miles_added": estimated_miles_added,
        "estimated_cost": estimated_cost,
        "charger_name": charger_name,
        "charger_status": charger_status,
        "charging_time": charging_time,
        "miles_per_hour_added": miles_per_hour_added,
        "sources": sources,
    }
