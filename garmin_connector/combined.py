"""Browser-only composite consent and crash-safe, payload-keyed progress.

A consumed approval authorizes resumption of this operation until its ORIGINAL
expiry only. Fresh browser consent after expiry attaches to the same journal.
Unknown writes are never repeated, even with fresh consent.
"""
from contextlib import contextmanager
import fcntl
import json
import os
import tempfile
from .approvals import ApprovalStore, fingerprint
from .upload import validate_workout
from .scheduling import scheduling_payload, already_scheduled


def combined_payload(workout, date):
    validate_workout(workout)
    scheduling_payload(1, date)
    return {'action': 'upload_and_schedule_running_workout', 'workout': workout, 'date': date}


def validate_combined(payload):
    if not isinstance(payload, dict) or payload != combined_payload(payload['workout'], payload['date']):
        raise ValueError('invalid combined operation')


class CombinedApprovalStore(ApprovalStore):
    validate_payload = staticmethod(validate_combined)

    def approve_interactively(self, request_id):
        raise ValueError('combined operation requires authenticated browser consent')

    @contextmanager
    def locked(self, payload):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = fingerprint(payload)
        with open(self.directory / (key + '.lock'), 'a',
                  opener=lambda p, flags: os.open(p, flags, 0o600)) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self.directory / (key + '.progress.json')

    def authorize(self, request_id, payload):
        # Caller holds the operation lock. Consumption grants ONLY this durable
        # operation, not permission to repeat its already-attempted writes.
        try:
            record = self.read(request_id, 'consumed')
            if record['sha256'] != fingerprint(payload):
                raise ValueError('changed operation')
        except ValueError:
            self.consume(request_id, payload)

    @staticmethod
    def save(path, state):
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.progress-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def execute(service, payload, request_id):
    store = service.combined_approvals
    date = payload['date']

    def failure(code, message, state):
        result = {'ok': False, 'status': 'uploaded_not_scheduled' if state.get('workout_id') else 'incomplete',
                  'date': date, 'error': {'code': code, 'message': message}}
        if state.get('workout_id'):
            result['workout_id'] = state['workout_id']
        return result

    with store.locked(payload) as path:
        store.authorize(request_id, payload)  # Always before authentication/reads/writes.
        state = json.loads(path.read_text()) if path.exists() else {'phase': 'ready'}
        if not isinstance(state, dict) or state.get('phase') not in ('ready', 'upload_started', 'uploaded', 'schedule_started', 'scheduled'):
            raise ValueError('invalid progress')
        if state['phase'] in ('uploaded', 'schedule_started', 'scheduled'):
            scheduling_payload(state['workout_id'], date)
        if state['phase'] == 'scheduled':
            return {'ok': True, 'status': 'scheduled', 'workout_id': state['workout_id'], 'date': date}
        if state['phase'] == 'upload_started':
            return failure('upload_outcome_unknown', 'Upload may have succeeded. Reconcile manually in Garmin Connect; never upload this operation again.', state)
        try:
            client = service.client_factory()
        except Exception:
            return failure('authentication_required', 'No write attempted this call. Refresh saved session; explicitly resume with the same arguments and approval ID before expiry, or obtain fresh browser consent after expiry.', state)
        if state['phase'] == 'ready':
            store.authorize(request_id, payload)  # Authentication may have taken past expiry.
            state['phase'] = 'upload_started'
            store.save(path, state)  # Must be durable BEFORE the first HTTP write.
            try:
                response = client.upload_workout(payload['workout'])
                workout_id = response.get('workoutId') if isinstance(response, dict) else None
                scheduling_payload(workout_id, date)
            except Exception:
                return failure('upload_outcome_unknown', 'Upload may have succeeded; manual Garmin reconciliation required. No upload retry, including with fresh approval.', state)
            state.update(phase='uploaded', workout_id=workout_id)
            try:
                store.save(path, state)  # Persist ID before ANY scheduling call.
            except OSError:
                return failure('progress_unavailable', 'Upload succeeded but durable ID storage failed. No scheduling attempted; reconcile manually using this workout ID. Never upload again.', state)
        workout_id = state['workout_id']
        schedule = scheduling_payload(workout_id, date)
        try:
            workout = client.get_workout_by_id(workout_id)
            sport = workout.get('sportType') if isinstance(workout, dict) else None
            if not isinstance(sport, dict) or sport.get('sportTypeId') != 1 or sport.get('sportTypeKey') != 'running':
                raise ValueError('unverified running workout')
            entries = client.get_scheduled_workouts_by_period(date, date)
            found = already_scheduled(entries, schedule)
        except Exception:
            return failure('schedule_check_failed', 'Upload succeeded; calendar/workout could not be verified. Explicit resumption may recheck, without uploading again.', state)
        if not found:
            if state['phase'] == 'schedule_started':
                return failure('schedule_outcome_unknown', 'Upload succeeded; prior scheduling is unconfirmed. Manual reconciliation required; no POST retry.', state)
            try:
                store.authorize(request_id, payload)
            except ValueError:
                return failure('approval_required', 'Upload succeeded; original consent expired before scheduling. Obtain fresh browser consent for the identical workout/date to resume without reupload.', state)
            try:
                service.schedule_approvals.claim_attempt(schedule)
            except FileExistsError:
                return failure('schedule_outcome_unknown', 'Upload succeeded; an earlier scheduling attempt exists but calendar has not confirmed it. Manual reconciliation required; no scheduling retry.', state)
            except OSError:
                return failure('progress_unavailable', 'Upload succeeded; scheduling attempt could not be recorded. No scheduling POST attempted this call. Explicitly resume with valid consent.', state)
            try:
                # fsync the shared claim as well, without deleting or resetting it.
                claim = service.schedule_approvals.attempt_directory / f'schedule-{fingerprint(schedule)}.attempt.json'
                with open(claim, 'rb') as stream:
                    os.fsync(stream.fileno())
                directory_fd = os.open(claim.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                state['phase'] = 'schedule_started'
                store.save(path, state)
            except OSError:
                return failure('progress_unavailable', 'Upload succeeded; scheduling progress could not be committed. No scheduling POST attempted this call. Manual reconciliation may be required.', state)
            try:
                response = client.schedule_workout(workout_id, date)
                if not already_scheduled([response], schedule):
                    raise ValueError('unconfirmed response')
            except Exception:
                return failure('schedule_outcome_unknown', 'Upload succeeded; scheduling outcome is uncertain. Explicit resumption only checks the calendar; it never repeats the POST. Reconcile manually if absent.', state)
        state['phase'] = 'scheduled'
        try:
            store.save(path, state)
        except OSError:
            return failure('progress_unavailable', 'Calendar confirmed scheduling but final progress could not be committed. Explicitly resume to recheck without repeating writes.', state)
        return {'ok': True, 'status': 'scheduled', 'workout_id': workout_id, 'date': date}
