"""Validation and interactive approval for creating one new running workout."""
import json
import sys
from .workouts import RunningStep, build_running_workout

TEST_WORKOUT_NAME = 'ChatGPT Garmin Connector Test'


def validate_workout(payload):
    """Validate our supported distance-step schema, excluding server IDs/updates."""
    try:
        if not isinstance(payload, dict):
            raise ValueError('workout must be an object')
        segments = payload['workoutSegments']
        if not isinstance(segments, list) or len(segments) != 1:
            raise ValueError('exactly one running segment is supported')
        steps = []
        for step in segments[0]['workoutSteps']:
            pace = None
            if step['targetType']['workoutTargetTypeKey'] == 'pace.zone':
                speed = step['targetValueOne']
                if isinstance(speed, bool) or not isinstance(speed, (float, int)) or speed <= 0:
                    raise ValueError('pace target speed must be positive')
                if speed != step['targetValueTwo']:
                    raise ValueError('this builder supports exact pace targets only')
                pace = 1000 / speed
            steps.append(RunningStep(step['stepType']['stepTypeKey'],
                                     step['endConditionValue'], pace))
        expected = build_running_workout(payload['workoutName'], steps)
        # Preserve validated speeds: pace -> speed round trips can differ by
        # one floating-point bit for otherwise valid custom pace values.
        for original, rebuilt in zip(segments[0]['workoutSteps'],
                                     expected['workoutSegments'][0]['workoutSteps']):
            if original['targetType']['workoutTargetTypeKey'] == 'pace.zone':
                rebuilt['targetValueOne'] = original['targetValueOne']
                rebuilt['targetValueTwo'] = original['targetValueTwo']
        # Strict comparison also rejects IDs, unknown fields, wrong sport/condition
        # identifiers, missing target values and nonconsecutive step ordering.
        if payload != expected:
            raise ValueError('payload does not match the supported running workout schema')
        json.dumps(payload, allow_nan=False)
    except (KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('missing or invalid workout fields') from exc
    return payload


def upload_interactively(payload, authenticate):
    """Preview, approve, authenticate, then make exactly one creation request."""
    validate_workout(payload)
    print(json.dumps(payload, indent=2))
    if not sys.stdin.isatty():
        print('Upload cancelled: an interactive terminal is required.')
        return 1
    try:
        confirmation = input('Create this NEW workout in Garmin Connect? Type UPLOAD to confirm: ')
        if confirmation != 'UPLOAD':
            print('Upload cancelled.')
            return 0
        try:
            client = authenticate()
        except Exception:
            print('Authentication failed. No upload attempted. Check your credentials/session and MFA.', file=sys.stderr)
            return 1
        try:
            response = client.upload_workout(payload)
        except Exception:
            print('Upload failed or its outcome is unknown. Check Garmin Connect before retrying to avoid duplicates.', file=sys.stderr)
            return 1
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled. If interrupted during upload, check Garmin Connect before retrying.')
        return 1
    print('Garmin API response:')
    print(json.dumps(response, indent=2, ensure_ascii=False, default=str))
    workout_id = response.get('workoutId') if isinstance(response, dict) else None
    if workout_id is None:
        print('No workoutId returned. Check Garmin Connect before retrying.', file=sys.stderr)
        return 1
    print(f'Garmin workout ID: {workout_id}')
    return 0
