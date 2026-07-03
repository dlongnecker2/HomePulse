from modules.application import Application

# Test that Application instantiates with new services
app = Application()
print(f'Application initialized: {app.timeline is not None}')
print(f'Notification Manager: {app.notification_manager is not None}')
print(f'Timeline event count: {app.timeline.event_count()}')

# Record a test event
ev = app.timeline.record_event(
    category='system',
    title='Test Event',
    description='Testing v3.6.1',
    severity='info',
    source='test'
)
print(f'Event recorded with ID: {ev["id"][:8]}... and source: {ev["source"]}')

# Add a test notification
notif = app.notification_manager.add_notification(
    'Test Notification',
    'This is a test',
    severity='info'
)
print(f'Notification created: {notif.id[:8] if notif else None}...')
print(f'Unread notifications: {app.notification_manager.get_unread_count()}')

print('✓ Application and services fully operational')
