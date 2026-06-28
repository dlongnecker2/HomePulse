"""
RouterMonitorV2
Main entry point
"""

from modules.application import Application


if __name__ == "__main__":
    app = Application()
    app.start()
