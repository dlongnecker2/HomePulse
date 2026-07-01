from modules.core.device_registry import DeviceRegistry
from modules.core.plugin import Plugin
from modules.core.widget_registry import WidgetRegistry


class CompatibilityPlugin(Plugin):
    def __init__(
        self,
        application,
        plugin_id,
        display_name,
        icon,
        device_type,
        widget_id,
        capabilities=None,
        priority=100,
    ):
        super().__init__(application)
        self.plugin_id = plugin_id
        self.display_name = display_name
        self.icon = icon
        self.device_type = device_type
        self.widget_id = widget_id
        self.capabilities = capabilities or []
        self.priority = priority

    def get_dashboard_widget(self):
        return {
            "widget_id": self.widget_id,
            "title": self.display_name,
            "icon": self.icon,
            "priority": self.priority,
            "refresh_interval": 10,
            "plugin": self.plugin_id,
        }


class PluginManager:
    def __init__(self, application, log):
        self.application = application
        self.log = log
        self.device_registry = DeviceRegistry()
        self.widget_registry = WidgetRegistry()
        self._plugins = {}

    def register(self, plugin):
        self._plugins[plugin.plugin_id] = plugin
        return plugin

    def discover_registered_plugins(self):
        return list(self._plugins.values())

    def register_compatibility_plugins(self):
        plugins = (
            CompatibilityPlugin(
                self.application,
                "home",
                "Home Center",
                "home",
                "sensor",
                "home_center",
                ["summary", "overall_status", "alerts"],
                5,
            ),
            CompatibilityPlugin(
                self.application,
                "internet",
                "Internet",
                "wifi",
                "internet",
                "internet_status",
                ["health_check", "latency", "packet_loss", "speed_test"],
                10,
            ),
            CompatibilityPlugin(
                self.application,
                "energy",
                "Energy",
                "zap",
                "charger",
                "energy_center",
                ["charging_status", "power_kw", "session_energy", "cost"],
                20,
            ),
            CompatibilityPlugin(
                self.application,
                "solar",
                "Solar",
                "sun",
                "solar",
                "solar_center",
                ["production_kw", "production_history", "enphase_health"],
                30,
            ),
            CompatibilityPlugin(
                self.application,
                "vehicle",
                "Vehicle",
                "car",
                "vehicle",
                "vehicle_center",
                ["battery", "range", "odometer", "efficiency"],
                40,
            ),
            CompatibilityPlugin(
                self.application,
                "weather",
                "Weather",
                "cloud-sun",
                "weather",
                "weather_summary",
                ["temperature", "cloud_cover", "forecast"],
                50,
            ),
            CompatibilityPlugin(
                self.application,
                "lighting",
                "Lighting",
                "lightbulb",
                "lighting",
                "exterior_lights",
                ["placeholder", "home_assistant_ready"],
                60,
            ),
        )
        for plugin in plugins:
            self.register(plugin)

    def initialize_plugins(self):
        for plugin in self.discover_registered_plugins():
            if not plugin.enabled:
                continue
            plugin.initialize()
            self.device_registry.register(
                device_id=f"{plugin.plugin_id}_device",
                name=plugin.display_name,
                type=plugin.device_type,
                plugin=plugin.plugin_id,
                status="registered",
                health="unknown",
                capabilities=plugin.capabilities,
            )
            widget = plugin.get_dashboard_widget()
            if widget:
                self.widget_registry.register(**widget)
        self.log_registration_summary()

    def enabled_plugins(self):
        return [plugin for plugin in self.discover_registered_plugins() if plugin.enabled]

    def metadata(self):
        return [plugin.get_status() for plugin in self.discover_registered_plugins()]

    def log_registration_summary(self):
        plugins = ", ".join(plugin.display_name for plugin in self.enabled_plugins()) or "None"
        widgets = ", ".join(widget["title"] for widget in self.widget_registry.all()) or "None"
        device_types = ", ".join(self.device_registry.types()) or "None"
        self.log.info(f"Loaded plugins: {plugins}")
        self.log.info(f"Registered dashboard widgets: {widgets}")
        self.log.info(f"Registered device types: {device_types}")
