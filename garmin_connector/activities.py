"""Read-only operations accepting an injected Garmin client."""


def recent_activities(client, limit=5):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError('limit must be a positive integer')
    return client.get_activities(0, limit) or []


def activity_summary(activity):
    return {
        'id': activity.get('activityId'),
        'name': activity.get('activityName'),
        'date': activity.get('startTimeLocal'),
        'distance_km': round((activity.get('distance') or 0) / 1000, 2),
        'avg_hr': activity.get('averageHR'),
    }


def latest_activity_report(client, limit=5):
    activities = recent_activities(client, limit)
    report = {'activities': [activity_summary(a) for a in activities],
              'details': None, 'laps': None}
    if activities and activities[0].get('activityId') is not None:
        activity_id = activities[0]['activityId']
        report['details'] = client.get_activity(activity_id)
        report['laps'] = client.get_activity_splits(activity_id)
    return report
