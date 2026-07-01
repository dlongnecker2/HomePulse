from datetime import datetime, timedelta


def retention_cutoff(retention_days, now=None):
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        days = 365
    if days < 1:
        days = 365
    return (now or datetime.now()) - timedelta(days=days)
