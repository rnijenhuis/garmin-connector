"""MCP application layer. All Garmin clients are injected and lazily obtained."""
from copy import deepcopy
from .diagnostics import observed
from garminconnect import GarminConnectAuthenticationError
from .activities import activity_summary
from .approvals import ApprovalStore, outside_project, fingerprint
from .client import connect
from .upload import validate_workout
from .workouts import parse_steps, build_running_workout
from .scheduling import ScheduleApprovalStore, scheduling_payload, already_scheduled


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


def running_metrics(metrics):
    """Garmin detail/lap run cadence already counts both feet; never double it."""
    return {output: metrics.get(source) for output, source in (
        ('average_heart_rate_bpm', 'averageHR'),
        ('max_heart_rate_bpm', 'maxHR'),
        ('average_running_cadence_spm', 'averageRunCadence'),
        ('max_running_cadence_spm', 'maxRunCadence'))}


class GarminTools:
    def __init__(self, client_factory=saved_session_client, approvals=None, enable_uploads=False,
                 schedule_approvals=None, enable_scheduling=False, browser_approval_origin=None, combined_approvals=None):
        if browser_approval_origin is not None:
            from .browser_approval import approval_origin
            browser_approval_origin = approval_origin(browser_approval_origin)
        self.browser_approval_origin = browser_approval_origin
        self.client_factory = client_factory
        self.approvals = approvals if approvals is not None else ApprovalStore()
        self.enable_uploads = enable_uploads
        self.schedule_approvals = schedule_approvals if schedule_approvals is not None else ScheduleApprovalStore()
        self.enable_scheduling = enable_scheduling
        self.combined_approvals = combined_approvals

    def _browser_approval(self, operation, request_id, payload):
        result = {'ok': True, 'status': 'approval_required', 'approval_id': request_id,
                  'approval_url': f'{self.browser_approval_origin}/review/{operation}/{request_id}',
                  'sha256': fingerprint(payload), 'expires_in_seconds': 600,
                  'instruction': 'Present the workout/action summary and this review link to the human. Only their authenticated browser confirmation grants consent. After they approve, call the same tool with identical arguments and this approval_id. Never open/approve the page on their behalf, treat a chat yes/boolean as authorization, poll repeatedly, or automatically create a replacement approval.'}
        if operation == 'schedule':
            result.update(workout_id=payload['workout_id'], date=payload['date'])
        return result

    @observed
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

    @observed
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
            laps = [{**{key: lap[key] for key in ('lapIndex', 'distance', 'duration') if key in lap},
                     **running_metrics(lap)}
                    for lap in splits.get('lapDTOs', [])]
            return {'ok': True, 'activity': {'activity_id': activity_id,
                    'distance_m': metrics.get('distance'),
                    'duration_seconds': metrics.get('duration'),
                    **running_metrics(metrics)}, 'laps': laps}
        except GarminConnectAuthenticationError:
            return error('authentication_required', 'Refresh your saved Garmin session in a separate terminal.')
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status == 403:
                return error('activity_access_denied', 'Garmin denied access to this activity. Check the activity ID and access in your Garmin Connect account.')
            if status == 404:
                return error('activity_not_found', 'Garmin could not find an accessible activity with this ID.')
            return error('garmin_api_error', 'Could not retrieve activity details.')

    @observed
    def build_running_workout(self, name, steps, for_upload=False):
        try:
            if not isinstance(for_upload, bool):
                raise ValueError('for_upload must be a boolean')
            if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
                raise ValueError('provide between 1 and 100 steps')
            payload = build_running_workout(name, parse_steps(steps))
            validate_workout(payload)
            if for_upload:
                return {'workout': payload}
            return {'ok': True, 'workout': payload}
        except (ValueError, TypeError, KeyError):
            return error('invalid_input', 'Provide a name and valid distance/time steps or repeat blocks, with one optional pace or heart-rate target.')

    @observed
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
                if self.browser_approval_origin:
                    return self._browser_approval('upload', request_id, payload)
                return {'ok': True, 'status': 'approval_required', 'approval_id': request_id,
                        'expires_in_seconds': 600,
                        'instruction': 'Review this request in a separate terminal with python -m garmin_connector.approvals APPROVAL_ID, then call again with the same workout and approval_id.'}
            self.approvals.consume(approval_id, payload)
        except (ValueError, OSError):
            return error('approval_required', 'A matching, unexpired, unused approval is required. Never create a fresh request automatically after an uncertain outcome.')
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


    @observed
    def schedule_running_workout(self, workout_id, date, approval_id=None):
        try:
            payload = scheduling_payload(workout_id, date)
        except (ValueError, TypeError):
            return error('invalid_input', 'Provide a positive integer workout_id and a valid YYYY-MM-DD date.')
        if not self.enable_scheduling:
            return error('scheduling_disabled', 'Restart with --enable-scheduling to prepare terminal approvals.')
        try:
            if approval_id is None:
                request_id = self.schedule_approvals.request(payload)
                if self.browser_approval_origin:
                    return self._browser_approval('schedule', request_id, payload)
                return {'ok': True, 'status': 'approval_required', 'workout_id': workout_id,
                        'date': date, 'approval_id': request_id, 'expires_in_seconds': 600,
                        'instruction': 'In a separate human terminal run python -m garmin_connector.approvals --schedule APPROVAL_ID, then call again with the same workout_id, date and approval_id.'}
            self.schedule_approvals.consume(approval_id, payload)
        except (ValueError, OSError):
            return error('approval_required', 'A matching, unexpired, unused scheduling approval is required.')
        # Consume before authentication or any reads/writes, just like upload.
        try:
            client = self.client_factory()
        except Exception:
            return error('authentication_required', 'No scheduling attempted. Refresh saved session; request a new approval.')
        try:
            workout = client.get_workout_by_id(workout_id)
            sport = workout.get('sportType') if isinstance(workout, dict) else None
            if not isinstance(sport, dict) or sport.get('sportTypeId') != 1 or sport.get('sportTypeKey') != 'running':
                return error('invalid_workout', 'Could not verify an existing running workout. Approval consumed; no scheduling attempted.')
            entries = client.get_scheduled_workouts_by_period(date, date)
            if already_scheduled(entries, payload):
                return {'ok': True, 'status': 'already_scheduled', 'workout_id': workout_id, 'date': date}
        except Exception:
            return error('schedule_check_failed', 'Could not verify workout/calendar state. Approval consumed; no scheduling attempted.')
        try:
            self.schedule_approvals.claim_attempt(payload)
        except FileExistsError:
            return error('schedule_attempt_exists', 'An earlier attempt for this workout/date is recorded. Check Garmin Connect; no scheduling attempted.')
        except (OSError, ValueError):
            return error('schedule_check_failed', 'Could not record scheduling attempt safely. No scheduling attempted.')
        try:
            response = client.schedule_workout(workout_id, date)
            # Confirm only the known schedule shape; never return raw responses.
            if not already_scheduled([response], payload):
                raise ValueError('unconfirmed scheduling result')
            return {'ok': True, 'status': 'scheduled', 'workout_id': workout_id, 'date': date}
        except Exception:
            return error('schedule_outcome_unknown', 'Check Garmin Connect before any further attempt. Approval consumed and attempt recorded; no automatic retry.')

    @observed
    def upload_and_schedule_running_workout(self, workout, date, approval_id=None):
        from .combined import combined_payload, execute
        try:
            payload = combined_payload(deepcopy(workout), date)
        except (ValueError, TypeError, KeyError):
            return error('invalid_input', 'Provide a valid running workout and explicit YYYY-MM-DD date.')
        if not self.enable_uploads:
            return error('uploads_disabled', 'Restart with --enable-uploads.')
        if not self.enable_scheduling:
            return error('scheduling_disabled', 'Restart with --enable-scheduling.')
        if not self.browser_approval_origin or self.combined_approvals is None:
            return error('browser_approval_required', 'Combined operation requires configured browser approval mode.')
        try:
            if approval_id is None:
                request_id = self.combined_approvals.request(payload)
                result = self._browser_approval('upload-and-schedule', request_id, payload)
                result['date'] = date
                return result
            return execute(self, payload, approval_id)
        except (ValueError, OSError, KeyError, TypeError):
            return error('approval_or_state_unavailable', 'Matching unexpired browser consent and durable state are required. If a write may have started, reconcile Garmin manually; never retry blindly or delete progress/attempt records.')
