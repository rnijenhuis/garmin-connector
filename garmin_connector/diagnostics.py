"""Fixed-vocabulary diagnostics. Never serialize arguments, exceptions or responses."""
from functools import wraps
import json
import os
from pathlib import Path
import stat
import time

OPERATIONS = {'get_recent_activities', 'get_activity_details', 'build_running_workout',
              'upload_running_workout', 'schedule_running_workout', 'portal', 'runtime'}
OUTCOMES = {'success', 'approval_required', 'authentication_required', 'garmin_api_error',
            'invalid_input', 'uploads_disabled', 'scheduling_disabled', 'upload_outcome_unknown',
            'schedule_outcome_unknown', 'schedule_check_failed', 'schedule_attempt_exists',
            'invalid_workout', 'activity_access_denied', 'activity_not_found',
            'uploaded', 'scheduled', 'already_scheduled', 'authentication_failed',
            'approval_error', 'tunnel_recent', 'tunnel_stale', 'tunnel_disconnected', 'tunnel_unknown'}


def directory():
    path = Path.home() / '.local/state/garmin-connector-runtime'
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('unsafe diagnostics directory')
    return path


def event(operation, outcome):
    if os.environ.get('GARMIN_DIAGNOSTICS') != '1':
        return
    if operation not in OPERATIONS or outcome not in OUTCOMES:
        return
    try:
        path = directory() / 'diagnostics.jsonl'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'a') as stream:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
                return
            # Bound storage under the same lock; retain no raw third-party logs.
            if info.st_size > 1024 * 1024:
                stream.truncate(0)
            stream.write(json.dumps({'time': time.time(), 'pid': os.getpid(),
                                     'operation': operation, 'outcome': outcome}) + '\n')
    except OSError:
        pass  # Diagnostics must never change approval or write semantics.


def observed(method):
    @wraps(method)
    def call(*args, **kwargs):
        result = method(*args, **kwargs)
        code = result.get('error', {}).get('code') or result.get('status', 'success')
        if result.get('error', {}).get('code') == 'approval_required':
            code = 'approval_error'
        event(method.__name__, code)
        return result
    return call
