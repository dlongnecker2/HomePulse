def estimate_cost(session_energy_kwh, cost_per_kwh):
    return round(float(session_energy_kwh or 0) * float(cost_per_kwh or 0), 2)


def estimate_miles_added(session_energy_kwh, estimated_miles_per_kwh):
    return round(float(session_energy_kwh or 0) * float(estimated_miles_per_kwh or 0), 1)
