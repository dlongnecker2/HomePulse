from modules.home import TimelineService
from modules.notifications import NotificationManager

# Test Timeline
timeline = TimelineService()
e1 = timeline.record_event('internet', 'Latency High', 'Detected 250ms latency', 'warning')
e2 = timeline.record_event('internet', 'Latency High', 'Detected 250ms latency', 'warning')
print(f'Events recorded: {timeline.event_count()}')
print(f'Event 1 ID: {e1.get("id") if e1 else None}')
print(f'Event 2 (deduped): {e2}')

# Test Notifications
notif = NotificationManager()
n1 = notif.add_notification('Internet Warning', 'High latency detected', severity='warning')
print(f'Notification created: {n1.id if n1 else None}')
n2 = notif.add_notification('Internet Warning', 'High latency detected', severity='warning')
print(f'Notification 2 (deduped): {n2}')
print(f'Unread count: {notif.get_unread_count()}')

print('Timeline and Notification services OK')
