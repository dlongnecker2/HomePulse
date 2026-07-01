import subprocess
import unittest
from unittest.mock import patch

from modules.application import Application


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


if __name__ == "__main__":
    unittest.main()
