"""Validation and interactive approval for creating one new running workout."""
import json
import sys
from .workouts import (RunningStep, RunningRepeat, build_running_workout,
                       MAX_STEPS, MAX_REPEAT_DEPTH, _positive)

TEST_WORKOUT_NAME = 'ChatGPT Garmin Connector Test'


def validate_workout(payload):
    """Rebuild our allowlisted schema, including bounded native repeat trees."""
    try:
        if not isinstance(payload, dict):
            raise ValueError('workout must be an object')
        segments = payload['workoutSegments']
        if not isinstance(segments, list) or len(segments) != 1:
            raise ValueError('exactly one running segment is supported')
        # Python equality considers True == 1. Reject boolean numeric fields
        # before canonical comparison; only these schema flags may be bools.
        def check_types(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if isinstance(child, bool) and key not in ('displayable', 'smartRepeat'):
                        raise ValueError('boolean numeric field')
                    if key in ('displayable', 'smartRepeat') and not isinstance(child, bool):
                        raise ValueError('invalid boolean flag')
                    check_types(child)
            elif isinstance(value, list):
                for child in value:
                    check_types(child)

        # Bound the supported repeat tree before reconstructing it.
        def decode(nodes, depth=0, budget=None):
            budget = [MAX_STEPS] if budget is None else budget
            if not isinstance(nodes, list) or not nodes:
                raise ValueError('steps must be a nonempty list')
            result = []
            for step in nodes:
                budget[0] -= 1
                if budget[0] < 0 or not isinstance(step, dict):
                    raise ValueError('invalid steps or too many step nodes')
                order = step['stepOrder']
                if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                    raise ValueError('stepOrder must be a positive integer')
                if step['type'] == 'RepeatGroupDTO':
                    if depth >= MAX_REPEAT_DEPTH:
                        raise ValueError('repeat nesting too deep')
                    result.append(RunningRepeat(step['numberOfIterations'],
                                  tuple(decode(step['workoutSteps'], depth + 1, budget))))
                    continue
                condition = step['endCondition']['conditionTypeKey']
                if condition not in ('time', 'distance'):
                    raise ValueError('unsupported end condition')
                kwargs = {'duration_seconds' if condition == 'time' else 'distance_m': step['endConditionValue']}
                target = step['targetType']['workoutTargetTypeKey']
                if target == 'pace.zone':
                    speed = step['targetValueOne']
                    _positive(speed, 'pace target speed')
                    if speed != step['targetValueTwo']:
                        raise ValueError('only exact pace targets are supported')
                    kwargs['pace_seconds_per_km'] = 1000 / speed
                elif target == 'heart.rate.zone':
                    if 'zoneNumber' in step:
                        kwargs['heart_rate_zone'] = step['zoneNumber']
                    else:
                        for key, field in (('targetValueOne', 'heart_rate_min_bpm'),
                                           ('targetValueTwo', 'heart_rate_max_bpm')):
                            value = step[key]
                            _positive(value, 'heart rate BPM')
                            if value > 300 or int(value) != value:
                                raise ValueError('BPM must be an integer from 1 to 300')
                            kwargs[field] = int(value)
                elif target != 'no.target':
                    raise ValueError('unsupported target')
                result.append(RunningStep(step['stepType']['stepTypeKey'], **kwargs))
            return result

        expected = build_running_workout(payload['workoutName'],
                                         decode(segments[0]['workoutSteps']))

        def preserve_pace(originals, rebuilt):
            for original, new in zip(originals, rebuilt):
                if new['type'] == 'RepeatGroupDTO':
                    preserve_pace(original['workoutSteps'], new['workoutSteps'])
                elif new['targetType']['workoutTargetTypeKey'] == 'pace.zone':
                    # Preserve validated speeds across floating-point round trips.
                    new['targetValueOne'] = original['targetValueOne']
                    new['targetValueTwo'] = original['targetValueTwo']

        preserve_pace(segments[0]['workoutSteps'], expected['workoutSegments'][0]['workoutSteps'])
        check_types(payload)
        if payload != expected:
            raise ValueError('payload does not match the supported running workout schema')
        json.dumps(payload, allow_nan=False)
    except (KeyError, TypeError, OverflowError, ZeroDivisionError, RecursionError) as exc:
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
