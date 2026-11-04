"""Pure JSON-ready workout construction; no network or upload operations."""
from dataclasses import dataclass
from math import isfinite
from typing import Literal
from garminconnect.workout import ConditionType, StepType, TargetType


def _positive(value, name):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'{name} must be a finite positive number')


@dataclass(frozen=True)
class RunningStep:
    kind: Literal['warmup', 'interval', 'recovery', 'cooldown']
    distance_m: float | None = None
    pace_seconds_per_km: float | None = None
    duration_seconds: float | None = None
    heart_rate_bpm: int | None = None
    heart_rate_min_bpm: int | None = None
    heart_rate_max_bpm: int | None = None
    heart_rate_zone: int | None = None

    def to_dict(self, order):
        kinds = {'warmup': StepType.WARMUP, 'cooldown': StepType.COOLDOWN,
                 'interval': StepType.INTERVAL, 'recovery': StepType.RECOVERY}
        if self.kind not in kinds:
            raise ValueError('unsupported running step kind')
        if (self.distance_m is None) == (self.duration_seconds is None):
            raise ValueError('provide exactly one of distance_m and duration_seconds')
        timed = self.duration_seconds is not None
        value = self.duration_seconds if timed else self.distance_m
        _positive(value, 'duration_seconds' if timed else 'distance_m')
        hr_range = self.heart_rate_min_bpm is not None or self.heart_rate_max_bpm is not None
        targets = (self.pace_seconds_per_km is not None, self.heart_rate_bpm is not None,
                   hr_range, self.heart_rate_zone is not None)
        if sum(targets) > 1:
            raise ValueError('pace, exact BPM, BPM range and HR zone are mutually exclusive')
        step = {
            'type': 'ExecutableStepDTO', 'stepOrder': order,
            'stepType': {'stepTypeId': kinds[self.kind], 'stepTypeKey': self.kind},
            'endCondition': {'conditionTypeId': ConditionType.TIME if timed else ConditionType.DISTANCE,
                             'conditionTypeKey': 'time' if timed else 'distance',
                             'displayOrder': 2 if timed else 3, 'displayable': True},
            'endConditionValue': float(value),
            'targetType': {'workoutTargetTypeId': TargetType.NO_TARGET, 'workoutTargetTypeKey': 'no.target',
                           'displayOrder': 1},
        }
        if self.pace_seconds_per_km is not None:
            _positive(self.pace_seconds_per_km, 'pace_seconds_per_km')
            speed = 1000 / self.pace_seconds_per_km
            _positive(speed, 'pace target speed')
            step.update(targetType={'workoutTargetTypeId': TargetType.PACE_ZONE,
                                    'workoutTargetTypeKey': 'pace.zone', 'displayOrder': 1},
                        targetValueOne=speed, targetValueTwo=speed)
        if self.heart_rate_bpm is not None or hr_range or self.heart_rate_zone is not None:
            step['targetType'] = {'workoutTargetTypeId': TargetType.HEART_RATE_ZONE,
                                  'workoutTargetTypeKey': 'heart.rate.zone', 'displayOrder': 1}
            if self.heart_rate_zone is not None:
                _integer(self.heart_rate_zone, 'heart_rate_zone', 5)
                step['zoneNumber'] = self.heart_rate_zone
            else:
                low = self.heart_rate_bpm if self.heart_rate_bpm is not None else self.heart_rate_min_bpm
                high = self.heart_rate_bpm if self.heart_rate_bpm is not None else self.heart_rate_max_bpm
                _integer(low, 'heart rate BPM', 300)
                _integer(high, 'heart rate BPM', 300)
                if low > high:
                    raise ValueError('heart rate minimum must not exceed maximum')
                step.update(targetValueOne=float(low), targetValueTwo=float(high))
        return step


def _integer(value, name, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 1 to {maximum}')


MAX_STEPS = 100  # Stored nodes, including repeat groups, not expanded repetitions.
MAX_REPEAT_DEPTH = 4


@dataclass(frozen=True)
class RunningRepeat:
    repeat_count: int
    steps: tuple['RunningStep | RunningRepeat', ...]


def parse_steps(steps, depth=0, budget=None):
    """Parse strict MCP dictionaries with bounded recursive size/depth."""
    budget = [MAX_STEPS] if budget is None else budget
    if not isinstance(steps, list) or not steps:
        raise ValueError('provide a nonempty list of steps')
    parsed = []
    for step in steps:
        budget[0] -= 1
        if budget[0] < 0 or not isinstance(step, dict):
            raise ValueError('invalid steps or too many step nodes')
        if step.get('kind') == 'repeat':
            if depth >= MAX_REPEAT_DEPTH or set(step) != {'kind', 'repeat_count', 'steps'}:
                raise ValueError('invalid repeat fields or nesting depth')
            _integer(step['repeat_count'], 'repeat_count', 100)
            parsed.append(RunningRepeat(step['repeat_count'], tuple(parse_steps(step['steps'], depth + 1, budget))))
        else:
            parsed.append(RunningStep(**step))
    return parsed


def serialize_steps(steps):
    """Number nodes in depth-first order, matching Garmin's repeat helpers."""
    order = 0

    def visit(nodes, depth):
        nonlocal order
        if not isinstance(nodes, (list, tuple)) or not nodes:
            raise ValueError('provide nonempty steps')
        result = []
        for node in nodes:
            order += 1
            if order > MAX_STEPS:
                raise ValueError('too many step nodes')
            current = order
            if isinstance(node, RunningRepeat):
                if depth >= MAX_REPEAT_DEPTH:
                    raise ValueError('repeat nesting too deep')
                _integer(node.repeat_count, 'repeat_count', 100)
                children = visit(node.steps, depth + 1)
                result.append({'type': 'RepeatGroupDTO', 'stepOrder': current,
                               'stepType': {'stepTypeId': StepType.REPEAT, 'stepTypeKey': 'repeat', 'displayOrder': 6},
                               'numberOfIterations': node.repeat_count, 'workoutSteps': children,
                               'endCondition': {'conditionTypeId': ConditionType.ITERATIONS,
                                                'conditionTypeKey': 'iterations', 'displayOrder': 7, 'displayable': False},
                               'endConditionValue': float(node.repeat_count), 'smartRepeat': False})
            elif isinstance(node, RunningStep):
                result.append(node.to_dict(current))
            else:
                raise ValueError('unsupported step')
        return result

    return visit(steps, 0)


def build_running_workout(name, steps):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('workout name is required')
    serialized = serialize_steps(list(steps))
    sport = {'sportTypeId': 1, 'sportTypeKey': 'running', 'displayOrder': 1}
    return {'workoutName': name, 'sportType': dict(sport),
            'workoutSegments': [{'segmentOrder': 1, 'sportType': dict(sport),
                                 'workoutSteps': serialized}]}


def example_workout():
    steps = [RunningStep('warmup', 2000)]
    for interval in range(3):
        steps.append(RunningStep('interval', 1000, 300))
        if interval < 2:
            steps.append(RunningStep('recovery', 500))
    steps.append(RunningStep('cooldown', 1000))
    return build_running_workout('3 x 1 km at 5:00/km', steps)
