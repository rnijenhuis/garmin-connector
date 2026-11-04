"""Offline scheduling validation and operation-specific terminal approvals."""
from datetime import date as calendar_date
import json
import os
import re
from .approvals import ApprovalStore, fingerprint, outside_project


def scheduling_payload(workout_id, date):
    if isinstance(workout_id, bool) or not isinstance(workout_id, int) or workout_id < 1:
        raise ValueError('workout_id must be a positive integer')
    if not isinstance(date, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date):
        raise ValueError('date must be YYYY-MM-DD')
    calendar_date.fromisoformat(date)
    return {'action': 'schedule_running_workout', 'workout_id': workout_id, 'date': date}


def validate_schedule(payload):
    if not isinstance(payload, dict) or payload != scheduling_payload(payload['workout_id'], payload['date']):
        raise ValueError('invalid scheduling request')
    return payload


class ScheduleApprovalStore(ApprovalStore):
    validate_payload = staticmethod(validate_schedule)
    confirmation_word = 'SCHEDULE'
    confirmation_prompt = 'Schedule this exact workout ID on this date? Type SCHEDULE: '

    def __init__(self, directory=None, attempt_directory=None, **kwargs):
        super().__init__(directory or '~/.local/state/garmin-connector/approvals/scheduling', **kwargs)
        self.attempt_directory = outside_project(attempt_directory) if attempt_directory else self.directory

    def claim_attempt(self, payload):
        """Persist before POST; concurrent callers and later approvals cannot retry.

        Retain on success or uncertainty. A human must reconcile Garmin state
        before manually clearing an attempt record; no MCP reset is exposed.
        """
        validate_schedule(payload)
        self.attempt_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.attempt_directory / f'schedule-{fingerprint(payload)}.attempt.json'
        with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(payload, stream)


def already_scheduled(entries, payload):
    """Use the installed library's schedule shape (calendarDate, workout ID).

    Unknown shapes fail closed, rather than guessing that no duplicate exists.
    """
    if not isinstance(entries, list):
        raise ValueError('unrecognized schedule list')
    found = False
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('invalid schedule entry')
        workout = entry.get('workout')
        if not isinstance(workout, dict):
            raise ValueError('unrecognized schedule workout')
        item = scheduling_payload(workout.get('workoutId'), entry.get('calendarDate'))
        if item == payload:
            found = True
    return found
