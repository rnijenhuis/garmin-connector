"""Pure JSON-ready workout construction; no network or upload operations."""
from dataclasses import dataclass
from math import isfinite
from typing import Literal


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a finite positive number')


@dataclass(frozen=True)
class RunningStep:
    kind: Literal['warmup', 'interval', 'recovery', 'cooldown']
    distance_m: float
    pace_seconds_per_km: float | None = None

    def to_dict(self, order):
        kinds = {'warmup': 1, 'cooldown': 2, 'interval': 3, 'recovery': 4}
        if self.kind not in kinds:
            raise ValueError('unsupported running step kind')
        _positive(self.distance_m, 'distance_m')
        step = {
            'type': 'ExecutableStepDTO', 'stepOrder': order,
            'stepType': {'stepTypeId': kinds[self.kind], 'stepTypeKey': self.kind},
            'endCondition': {'conditionTypeId': 3, 'conditionTypeKey': 'distance',
                             'displayOrder': 3, 'displayable': True},
            'endConditionValue': float(self.distance_m),
            'targetType': {'workoutTargetTypeId': 1, 'workoutTargetTypeKey': 'no.target',
                           'displayOrder': 1},
        }
        if self.pace_seconds_per_km is not None:
            _positive(self.pace_seconds_per_km, 'pace_seconds_per_km')
            speed = 1000 / self.pace_seconds_per_km
            step.update(targetType={'workoutTargetTypeId': 6,
                                    'workoutTargetTypeKey': 'pace.zone', 'displayOrder': 1},
                        targetValueOne=speed, targetValueTwo=speed)
        return step


def build_running_workout(name, steps):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('workout name is required')
    serialized = [step.to_dict(i) for i, step in enumerate(steps, 1)]
    if not serialized:
        raise ValueError('at least one step is required')
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
