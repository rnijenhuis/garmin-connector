"""Offline schema and approval regression tests for advanced running steps."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from garminconnect.workout import (
    CustomHeartRateTarget, HeartRateZoneTarget, PaceTarget, RepeatGroup,
    create_repeat_group, create_recovery_step, create_targeted_interval_step,
    create_targeted_distance_interval_step,
)
from mcp import Client, StdioServerParameters
import sys
import asyncio

from garmin_connector.approvals import ApprovalStore
from garmin_connector.mcp_server import create_server
from garmin_connector.mcp_tools import GarminTools
from garmin_connector.upload import validate_workout
from garmin_connector.workouts import (
    RunningStep, RunningRepeat, build_running_workout, example_workout,
    parse_steps,
)


def advanced_steps():
    return [
        {'kind': 'warmup', 'distance_m': 2000, 'heart_rate_min_bpm': 130, 'heart_rate_max_bpm': 145},
        {'kind': 'repeat', 'repeat_count': 3, 'steps': [
            {'kind': 'interval', 'distance_m': 1000, 'pace_seconds_per_km': 300},
            {'kind': 'recovery', 'duration_seconds': 120}]},
        {'kind': 'cooldown', 'duration_seconds': 300, 'heart_rate_bpm': 135},
    ]


def workout_nodes(payload):
    return payload['workoutSegments'][0]['workoutSteps']


class AdvancedWorkoutTests(unittest.TestCase):
    def build(self, steps=None):
        return build_running_workout('Advanced offline', parse_steps(advanced_steps() if steps is None else steps))

    def test_builder_can_return_exact_upload_arguments_without_preparing_approval(self):
        factory = Mock()
        approvals = Mock()
        tools = GarminTools(factory, approvals, enable_uploads=True)
        result = tools.build_running_workout('Advanced offline', advanced_steps(), for_upload=True)
        self.assertEqual(result, {'workout': self.build()})
        validate_workout(result['workout'])
        approvals.request.assert_not_called()
        factory.assert_not_called()
        tools.enable_uploads = False
        self.assertEqual(tools.upload_running_workout(**result)['error']['code'], 'uploads_disabled')
        self.assertEqual(tools.build_running_workout('Invalid', [], for_upload=True)['ok'], False)
        self.assertEqual(tools.build_running_workout('Invalid', advanced_steps(), for_upload='true')['error']['code'], 'invalid_input')

    def test_old_flat_payload_is_unchanged(self):
        # Existing checked-in preview is the seven-step legacy format.
        expected = json.loads((Path(__file__).resolve().parents[1] / 'examples/running_workout.json').read_text())
        actual = example_workout()
        actual['workoutName'] = expected['workoutName']
        self.assertEqual(actual, expected)
        validate_workout(actual)
        from_iterator = build_running_workout('Advanced offline', iter(parse_steps(advanced_steps())))
        self.assertEqual(from_iterator, self.build())

    def test_native_repeat_matches_installed_library(self):
        payload = self.build()
        steps = workout_nodes(payload)
        group = steps[1]
        expected = create_repeat_group(3, [
            create_targeted_distance_interval_step(1000, 3, PaceTarget(lower_limit=1000/300, upper_limit=1000/300)),
            create_recovery_step(120, 4)], 2).model_dump(exclude_none=True)
        # Legacy executable step shape deliberately omits optional displayOrder.
        for child in expected['workoutSteps']:
            child['stepType'].pop('displayOrder')
        self.assertEqual(group, expected)
        self.assertEqual([steps[0]['stepOrder'], group['stepOrder'],
                          *[s['stepOrder'] for s in group['workoutSteps']], steps[2]['stepOrder']], [1, 2, 3, 4, 5])
        self.assertIs(validate_workout(payload), payload)
        RepeatGroup.model_validate(group)  # Offline installed model compatibility.

    def test_hr_payloads_match_installed_library(self):
        for fields, target in [
            ({'heart_rate_bpm': 140}, CustomHeartRateTarget(lower_limit=140, upper_limit=140)),
            ({'heart_rate_min_bpm': 130, 'heart_rate_max_bpm': 145}, CustomHeartRateTarget(lower_limit=130, upper_limit=145)),
            ({'heart_rate_zone': 2}, HeartRateZoneTarget(zone_number=2)),
        ]:
            for timed in (False, True):
                with self.subTest(fields=fields, timed=timed):
                    duration = {'duration_seconds': 120} if timed else {'distance_m': 5000}
                    payload = self.build([{'kind': 'interval', **duration, **fields}])
                    expected = (create_targeted_interval_step(120, 1, target) if timed else
                                create_targeted_distance_interval_step(5000, 1, target)).model_dump(exclude_none=True)
                    expected['stepType'].pop('displayOrder')
                    self.assertEqual(workout_nodes(payload)[0], expected)
                    validate_workout(payload)

    def test_all_kinds_allow_time_or_distance(self):
        for kind in ('warmup', 'interval', 'recovery', 'cooldown'):
            for condition, value in (('duration_seconds', 120), ('distance_m', 500)):
                with self.subTest(kind=kind, condition=condition):
                    payload = self.build([{'kind': kind, condition: value}])
                    step = workout_nodes(payload)[0]
                    self.assertEqual(step['endCondition']['conditionTypeKey'], 'time' if condition == 'duration_seconds' else 'distance')
                    self.assertEqual(step['endConditionValue'], value)
                    validate_workout(payload)

    def test_nested_repeat_order_and_mixed_recoveries(self):
        steps = advanced_steps()
        steps[1]['steps'].append({'kind': 'repeat', 'repeat_count': 2, 'steps': [
            {'kind': 'interval', 'duration_seconds': 60, 'heart_rate_zone': 2},
            {'kind': 'recovery', 'distance_m': 200}]})
        payload = self.build(steps)
        group = workout_nodes(payload)[1]
        self.assertEqual(group['workoutSteps'][2]['stepOrder'], 5)
        self.assertEqual([s['stepOrder'] for s in group['workoutSteps'][2]['workoutSteps']], [6, 7])
        self.assertEqual(workout_nodes(payload)[2]['stepOrder'], 8)
        validate_workout(payload)
        RepeatGroup.model_validate(group)

    def test_invalid_steps_never_authenticate(self):
        invalid = [
            {'kind': 'interval'},
            {'kind': 'interval', 'distance_m': 1000, 'duration_seconds': 60},
        ]
        base = {'kind': 'interval', 'duration_seconds': 120}
        for field in ('duration_seconds', 'pace_seconds_per_km', 'heart_rate_bpm', 'heart_rate_zone'):
            for value in (0, -1, True, '2', float('nan'), float('inf')):
                invalid.append({**base, field: value})
        for fields in (
            {'heart_rate_bpm': 301}, {'heart_rate_bpm': 140.5},
            {'heart_rate_zone': 6}, {'heart_rate_zone': 2.0},
            {'heart_rate_min_bpm': 145}, {'heart_rate_max_bpm': 145},
            {'heart_rate_min_bpm': 145, 'heart_rate_max_bpm': 130},
            {'heart_rate_bpm': 140, 'heart_rate_zone': 2},
            {'heart_rate_bpm': 140, 'pace_seconds_per_km': 300},
            {'heart_rate_zone': 2, 'pace_seconds_per_km': 300},
            {'heart_rate_min_bpm': 130, 'heart_rate_max_bpm': 145, 'pace_seconds_per_km': 300},
            {'unknown': 1},
        ):
            invalid.append({**base, **fields})
        factory = Mock(side_effect=AssertionError('must remain offline'))
        tools = GarminTools(client_factory=factory)
        for step in invalid:
            with self.subTest(step=step):
                self.assertEqual(tools.build_running_workout('Invalid', [step])['error']['code'], 'invalid_input')
        factory.assert_not_called()

    def test_repeat_limits(self):
        child = {'kind': 'recovery', 'duration_seconds': 60}
        for count in (0, -1, True, 1.5, '3', 101):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.build([{'kind': 'repeat', 'repeat_count': count, 'steps': [child]}])
        for children in ([], None, {}):
            with self.assertRaises(ValueError):
                self.build([{'kind': 'repeat', 'repeat_count': 3, 'steps': children}])
        nested = child
        for _ in range(5):
            nested = {'kind': 'repeat', 'repeat_count': 2, 'steps': [nested]}
        with self.assertRaises(ValueError):
            self.build([nested])
        with self.assertRaises(ValueError):
            self.build([{'kind': 'repeat', 'repeat_count': 2, 'steps': [child] * 100}])
        with self.assertRaises(ValueError):
            build_running_workout('Invalid', [RunningRepeat(True, (RunningStep('recovery', duration_seconds=60),))])

    def test_upload_rejects_tampered_advanced_payloads(self):
        mutations = [
            lambda p: workout_nodes(p)[1].update(numberOfIterations=True),
            lambda p: workout_nodes(p)[1].update(numberOfIterations=0),
            lambda p: workout_nodes(p)[1].update(numberOfIterations=101),
            lambda p: workout_nodes(p)[1].update(stepOrder=2.0),
            lambda p: workout_nodes(p)[1].update(endConditionValue=4),
            lambda p: workout_nodes(p)[1].update(smartRepeat=True),
            lambda p: workout_nodes(p)[1]['stepType'].update(stepTypeId=99),
            lambda p: workout_nodes(p)[1]['workoutSteps'][0].update(stepOrder=1),
            lambda p: workout_nodes(p)[1]['workoutSteps'][0]['endCondition'].update(conditionTypeId=2),
            lambda p: workout_nodes(p)[1]['workoutSteps'][1].update(endConditionValue=-120),
            lambda p: workout_nodes(p)[0].update(targetValueTwo=120),
            lambda p: workout_nodes(p)[0].update(targetValueOne=float('nan')),
            lambda p: workout_nodes(p)[0].update(zoneNumber=2),
            lambda p: workout_nodes(p)[0]['targetType'].update(workoutTargetTypeId=6),
            lambda p: workout_nodes(p)[2].update(targetValueOne=True),
            lambda p: workout_nodes(p)[1].update(workoutSteps=[]),
            lambda p: workout_nodes(p)[1].update(childStepId=123),
            lambda p: workout_nodes(p)[0].update(secondaryTargetType={'workoutTargetTypeId': 6}),
        ]
        factory = Mock()
        tools = GarminTools(client_factory=factory, enable_uploads=True)
        for mutate in mutations:
            payload = self.build()
            mutate(payload)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_workout(payload)
            self.assertEqual(tools.upload_running_workout(payload)['error']['code'], 'invalid_input')
        factory.assert_not_called()

    def test_upload_rejects_invalid_zones_and_oversized_repeat_trees(self):
        for zone in (0, 6, True, 2.0, '2'):
            payload = self.build([{'kind': 'interval', 'distance_m': 1000, 'heart_rate_zone': 2}])
            workout_nodes(payload)[0]['zoneNumber'] = zone
            with self.subTest(zone=zone), self.assertRaises(ValueError):
                validate_workout(payload)
        payload = self.build()
        group = workout_nodes(payload)[1]
        leaf = group['workoutSteps'][0]
        group['workoutSteps'] = [deepcopy(leaf) for _ in range(100)]
        with self.assertRaises(ValueError):
            validate_workout(payload)
        payload = self.build()
        group = workout_nodes(payload)[1]
        for _ in range(5):
            parent = deepcopy(group)
            parent['workoutSteps'] = [group]
            group = parent
        workout_nodes(payload)[1] = group
        with self.assertRaises(ValueError):
            validate_workout(payload)

    def test_advanced_upload_failures_consume_approval(self):
        for authentication_fails in (False, True):
            with self.subTest(authentication_fails=authentication_fails), tempfile.TemporaryDirectory() as directory:
                store = ApprovalStore(directory)
                api = Mock(spec=['upload_workout'])
                api.upload_workout.side_effect = RuntimeError('private token')
                factory = Mock(side_effect=RuntimeError('private token')) if authentication_fails else Mock(return_value=api)
                tools = GarminTools(factory, store, enable_uploads=True)
                payload = self.build()
                approval_id = tools.upload_running_workout(payload)['approval_id']
                with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='UPLOAD'), redirect_stdout(io.StringIO()):
                    store.approve_interactively(approval_id)
                result = tools.upload_running_workout(payload, approval_id)
                self.assertEqual(result['error']['code'], 'authentication_required' if authentication_fails else 'upload_outcome_unknown')
                self.assertNotIn('private token', json.dumps(result))
                self.assertEqual(tools.upload_running_workout(payload, approval_id)['error']['code'], 'approval_required')
                if authentication_fails:
                    api.upload_workout.assert_not_called()
                else:
                    api.upload_workout.assert_called_once_with(payload)

    def test_custom_pace_round_trip_inside_repeat(self):
        payload = self.build([{'kind': 'repeat', 'repeat_count': 2, 'steps': [
            {'kind': 'interval', 'duration_seconds': 45, 'pace_seconds_per_km': 317.123}]}])
        validate_workout(payload)

    def test_advanced_payload_approval_is_exact_expiring_and_single_use(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            store = ApprovalStore(directory, clock=lambda: now[0])
            api = Mock(spec=['upload_workout'])
            api.upload_workout.return_value = {'workoutId': 123, 'private': 'hidden'}
            factory = Mock(return_value=api)
            tools = GarminTools(factory, store, enable_uploads=True)
            payload = self.build()
            request = tools.upload_running_workout(payload)
            approval_id = request['approval_id']
            factory.assert_not_called()
            self.assertEqual(tools.upload_running_workout(payload, approval_id)['error']['code'], 'approval_required')
            with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='UPLOAD'), redirect_stdout(io.StringIO()):
                self.assertTrue(store.approve_interactively(approval_id))
            for change in ('repeat', 'time', 'hr'):
                changed = deepcopy(payload)
                if change == 'repeat':
                    workout_nodes(changed)[1].update(numberOfIterations=4, endConditionValue=4.0)
                elif change == 'time':
                    workout_nodes(changed)[1]['workoutSteps'][1]['endConditionValue'] = 121
                else:
                    workout_nodes(changed)[0]['targetValueOne'] = 131
                self.assertEqual(tools.upload_running_workout(changed, approval_id)['error']['code'], 'approval_required')
            factory.assert_not_called()
            result = tools.upload_running_workout(payload, approval_id)
            self.assertEqual(result, {'ok': True, 'status': 'uploaded', 'workout_id': 123, 'workout_name': 'Advanced offline'})
            api.upload_workout.assert_called_once_with(payload)
            self.assertEqual(tools.upload_running_workout(payload, approval_id)['error']['code'], 'approval_required')
            second = tools.upload_running_workout(payload)['approval_id']
            with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='UPLOAD'), redirect_stdout(io.StringIO()):
                store.approve_interactively(second)
            now[0] += 600
            self.assertEqual(tools.upload_running_workout(payload, second)['error']['code'], 'approval_required')
            api.upload_workout.assert_called_once()


class AdvancedProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def check_builder(self, client):
        result = await client.call_tool('build_running_workout', {'name': 'Advanced offline', 'steps': advanced_steps()})
        self.assertFalse(result.is_error)
        self.assertTrue(result.structured_content['ok'])
        payload = result.structured_content['workout']
        validate_workout(payload)
        self.assertEqual(workout_nodes(payload)[1]['numberOfIterations'], 3)
        disabled = await client.call_tool('upload_running_workout', {'workout': payload})
        self.assertEqual(disabled.structured_content['error']['code'], 'uploads_disabled')

    async def test_builder_output_pastes_directly_into_upload_tool(self):
        factory = Mock()
        async with Client(create_server(GarminTools(factory)), read_timeout_seconds=5) as client:
            result = await client.call_tool('build_running_workout', {
                'name': 'Advanced offline', 'steps': advanced_steps(), 'for_upload': True})
            self.assertFalse(result.is_error)
            arguments = result.structured_content
            self.assertEqual(set(arguments), {'workout'})
            validate_workout(arguments['workout'])
            uploaded = await client.call_tool('upload_running_workout', arguments)
            self.assertFalse(uploaded.is_error)
            self.assertEqual(uploaded.structured_content['error']['code'], 'uploads_disabled')
            invalid = await client.call_tool('build_running_workout', {
                'name': 'Advanced offline', 'steps': advanced_steps(), 'for_upload': 'true'})
            self.assertTrue(invalid.is_error)
        factory.assert_not_called()

    async def test_mcp_advanced_schema_and_errors(self):
        factory = Mock(side_effect=AssertionError('no Garmin calls'))
        async with Client(create_server(GarminTools(factory)), read_timeout_seconds=5) as client:
            await self.check_builder(client)
            for steps in ([{'kind': 'interval', 'duration_seconds': True}],
                          [{'kind': 'repeat', 'repeat_count': True, 'steps': advanced_steps()}],
                          [{'kind': 'interval', 'distance_m': 10, 'heart_rate_zone': 6}],
                          [{'kind': 'repeat', 'repeat_count': 2, 'steps': [{'kind': 'recovery', 'duration_seconds': 30, 'private': 1}]}]):
                result = await client.call_tool('build_running_workout', {'name': 'Invalid', 'steps': steps})
                self.assertTrue(result.is_error)
        factory.assert_not_called()

    async def test_real_stdio_advanced_offline(self):
        async with asyncio.timeout(15):
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'garmin_connector.mcp_server'], cwd=str(Path(__file__).resolve().parents[1]))
            async with Client(params, read_timeout_seconds=5) as client:
                await self.check_builder(client)
