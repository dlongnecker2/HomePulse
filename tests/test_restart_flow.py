import subprocess
import unittest
from unittest.mock import MagicMock, patch

from modules.application import Application
from modules.scheduler import Scheduler


class ApplicationRestartTests(unittest.TestCase):
    def test_scheduled_task_status_reports_task_exists(self):
        app = Application.__new__(Application)
        completed = subprocess.CompletedProcess(
            args=["schtasks"],
            returncode=0,
            stdout="TaskName: HomePulse\nLast Result: 0x00000000",
            stderr="",
        )

        with patch("subprocess.run", return_value=completed):
            status = app.scheduled_task_status()

        self.assertTrue(status["exists"])
        self.assertEqual(status["preferred_restart_method"], "Task Scheduler")
        self.assertEqual(status["last_result"], "0x00000000")

    def test_scheduled_task_status_reports_missing_task(self):
        app = Application.__new__(Application)
        completed = subprocess.CompletedProcess(
            args=["schtasks"],
            returncode=1,
            stdout="ERROR: The system cannot find the file specified.",
            stderr="",
        )

        with patch("subprocess.run", return_value=completed):
            status = app.scheduled_task_status()

        self.assertFalse(status["exists"])
        self.assertEqual(status["preferred_restart_method"], "Batch launcher")
        self.assertIsNone(status["last_result"])

    def test_environment_job_triggers_initial_refresh_during_startup(self):
        app = Application.__new__(Application)
        app.log = type(
            "Log",
            (),
            {"info": lambda self, *args, **kwargs: None, "warning": lambda self, *args, **kwargs: None},
        )()
        app.scheduler = Scheduler(app.log)
        app.environment = type(
            "Environment",
            (),
            {
                "enabled": lambda self: True,
                "refresh_interval_minutes": lambda self: 5,
            },
        )()
        app.environment_refresh = MagicMock(return_value={"last_successful_refresh": "2026-07-12T10:00:00"})

        Application.register_environment_job(app)

        self.assertEqual(len(app.scheduler.jobs), 1)
        self.assertTrue(app.environment_refresh.called)
        self.assertIsNotNone(app.scheduler.jobs[0]["last_run"])
        self.assertIsNotNone(app.scheduler.jobs[0]["last_run_at"])


if __name__ == "__main__":
    unittest.main()
