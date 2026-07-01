from dataclasses import dataclass


@dataclass
class RegisteredWidget:
    widget_id: str
    title: str
    icon: str = ""
    priority: int = 100
    render: object = None
    refresh_interval: int = 10
    plugin: str = ""

    def to_dict(self):
        return {
            "widget_id": self.widget_id,
            "title": self.title,
            "icon": self.icon,
            "priority": self.priority,
            "refresh_interval": self.refresh_interval,
            "plugin": self.plugin,
        }


class WidgetRegistry:
    def __init__(self):
        self._widgets = {}

    def register(self, widget_id, title, icon="", priority=100, render=None, refresh_interval=10, plugin=""):
        widget = RegisteredWidget(
            widget_id=widget_id,
            title=title,
            icon=icon,
            priority=priority,
            render=render,
            refresh_interval=refresh_interval,
            plugin=plugin,
        )
        self._widgets[widget_id] = widget
        return widget

    def get(self, widget_id):
        return self._widgets.get(widget_id)

    def all(self):
        return [
            widget.to_dict()
            for widget in sorted(self._widgets.values(), key=lambda item: (item.priority, item.title))
        ]
