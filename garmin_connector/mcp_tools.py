"""MCP application layer. All Garmin clients are injected and lazily obtained."""
from copy import deepcopy
from garminconnect import GarminConnectAuthenticationError
from .activities import activity_summary
from .approvals import ApprovalStore, outside_project
from .client import connect
from .upload import validate_workout
from .workouts import RunningStep, build_running_workout


def saved_session_client():
    """No prompts or credentials in MCP; refresh/login only on a tool call."""
    return connect(None, None, token_dir=outside_project('~/.garminconnect'))


def error(code, message):
    return {'ok': False, 'error': {'code': code, 'message': message}}


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('activity_id must be a positive integer')


def safe_summary(activity):
    # Names, timestamps and HR are unnecessary for this MCP interface.
    summary = activity_summary(activity)
    return {'activity_id': summary['id'], 'distance_km': summary['distance_km'],
            'duration_seconds': activity.get('duration')}


class GarminTools:
    def __init__(self, client_factory=saved_session_client, approvals=None, enable_uploads=False):
        self.client_factory = client_factory
        self.approvals = approvals if approvals is not None else ApprovalStore()
        self.enable_uploads = enable_uploads

    def get_recent_activities(self, limit=5):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            return error('invalid_input', 'limit must be an integer from 1 to 50')
        try:
            client = self.client_factory()
            activities = client.get_activities(0, limit, activitytype='running') or []
            return {'ok': True, 'activities': [safe_summary(a) for a in activities]}
        except GarminConnectAuthenticationError:
            return error('authentication_required', 'Refresh your saved Garmin session in a separate terminal.')
        except Exception:
            return error('garmin_api_error', 'Could not retrieve running activities.')

    def get_activity_details(self, activity_id):
        try:
            positive_id(activity_id)
        except ValueError as exc:
            return error('invalid_input', str(exc))
        try:
            client = self.client_factory()
            activity = client.get_activity(activity_id)
            splits = client.get_activity_splits(activity_id) or {}
            metrics = activity.get('summaryDTO') or activity
            # Explicit field allowlist: never return raw activity or lap objects.
            laps = [{key: lap[key] for key in ('lapIndex', 'distance', 'duration') if key in lap}
                    for lap in splits.get('lapDTOs', [])]
            return {'ok': True, 'activity': {'activity_id': activity_id,
                    'distance_m': metrics.get('distance'),
                    'duration_seconds': metrics.get('duration')}, 'laps': laps}
        except GarminConnectAuthenticationError:
            return error('authentication_required', 'Refresh your saved Garmin session in a separate terminal.')
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status == 403:
                return error('activity_access_denied', 'Garmin denied access to this activity. Check the activity ID and access in your Garmin Connect account.')
            if status == 404:
                return error('activity_not_found', 'Garmin could not find an accessible activity with this ID.')
            return error('garmin_api_error', 'Could not retrieve activity details.')

    def build_running_workout(self, name, steps):
        try:
            if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
                raise ValueError('provide between 1 and 100 steps')
            payload = build_running_workout(name, [RunningStep(**step) for step in steps])
            validate_workout(payload)
            return {'ok': True, 'workout': payload}
        except (ValueError, TypeError, KeyError):
            return error('invalid_input', 'Provide a name and valid distance steps with optional positive pace_seconds_per_km.')

    def upload_running_workout(self, workout, approval_id=None):
        try:
            payload = deepcopy(workout)
            validate_workout(payload)
        except (ValueError, TypeError, KeyError):
            return error('invalid_input', 'Invalid generated running workout.')
        if not self.enable_uploads:
            return error('uploads_disabled', 'Server is read-only. Restart with --enable-uploads to prepare approvals.')
        try:
            if approval_id is None:
                request_id = self.approvals.request(payload)
                return {'ok': True, 'status': 'approval_required', 'approval_id': request_id,
                        'expires_in_seconds': 600,
                        'instruction': 'Review this request in a separate terminal with python -m garmin_connector.approvals APPROVAL_ID, then call again with the same workout and approval_id.'}
            self.approvals.consume(approval_id, payload)
        except (ValueError, OSError):
            return error('approval_required', 'A matching, unexpired, unused terminal approval is required.')
        # Consume BEFORE authentication/upload: errors never enable replay.
        try:
            client = self.client_factory()
        except Exception:
            return error('authentication_required', 'No upload attempted. Refresh saved session; request a new approval.')
        try:
            response = client.upload_workout(payload)
            workout_id = response.get('workoutId') if isinstance(response, dict) else None
            if not isinstance(workout_id, int) or isinstance(workout_id, bool) or workout_id < 1:
                raise ValueError('missing workout ID')
            return {'ok': True, 'status': 'uploaded', 'workout_id': workout_id,
                    'workout_name': payload['workoutName']}
        except Exception:
            return error('upload_outcome_unknown', 'Check Garmin Connect before retrying. Approval consumed; no automatic retry.')
