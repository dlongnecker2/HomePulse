class Plugin:
    plugin_id = ""
    display_name = ""
    icon = ""
    version = "1.0.0"
    enabled = True

    def __init__(self, application=None):
        self.application = application

    def initialize(self):
        return None

    def shutdown(self):
        return None

    def get_status(self):
        return {
            "plugin_id": self.plugin_id,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "version": self.version,
        }

    def get_dashboard_widget(self):
        return None

    def get_settings_section(self):
        return None

    def get_history_metrics(self):
        return []

    def get_api_routes(self):
        return []
