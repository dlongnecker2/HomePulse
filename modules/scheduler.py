import time
from datetime import datetime, timedelta


class Scheduler:
    def __init__(self, log):
        self.log = log
        self.jobs = []

    def every_minutes(self, name, minutes, function):
        job = {
            "type": "interval",
            "name": name,
            "interval": timedelta(minutes=minutes),
            "function": function,
            "last_run": None,
            "last_run_at": None,
        }
        self.jobs.append(job)
        return job

    def daily(self, name, hour, minute, function):
        job = {
            "type": "daily",
            "name": name,
            "hour": hour,
            "minute": minute,
            "function": function,
            "last_run_date": None,
            "last_run_at": None,
        }
        self.jobs.append(job)
        return job

    def remove_jobs_by_prefix(self, prefix):
        self.jobs = [job for job in self.jobs if not job["name"].startswith(prefix)]

    def run_pending(self):
        now = datetime.now()
        for job in self.jobs:
            if job["type"] == "interval":
                if job["last_run"] is None or now - job["last_run"] >= job["interval"]:
                    self._run_job(job)
                    job["last_run"] = now
            elif job["type"] == "daily":
                today = now.date()
                if now.hour == job["hour"] and now.minute >= job["minute"] and job["last_run_date"] != today:
                    self._run_job(job)
                    job["last_run_date"] = today

    def _run_job(self, job):
        self.log.info(f"Running scheduled job: {job['name']}")
        try:
            job["function"]()
            job["last_run_at"] = datetime.now()
            self.log.info(f"Finished scheduled job: {job['name']}")
        except Exception as e:
            self.log.exception(f"Scheduled job failed: {job['name']} - {e}")

    def run_forever(self, sleep_seconds=60):
        self.log.info("Scheduler started")
        while True:
            self.run_pending()
            time.sleep(sleep_seconds)
