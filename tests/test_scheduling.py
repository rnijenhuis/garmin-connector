"""Scheduling tests: all Garmin calls mocked, all approval state temporary."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from garminconnect.api.workouts import WorkoutsMixin
from mcp import Client
from garmin_connector.approvals import ApprovalStore
from garmin_connector.mcp_server import create_server
from garmin_connector.mcp_tools import GarminTools
from garmin_connector.scheduling import ScheduleApprovalStore, scheduling_payload
from garmin_connector.workouts import example_workout


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.store = ScheduleApprovalStore(self.temp.name, clock=lambda: self.now)
        self.api = Mock(spec=['get_workout_by_id', 'get_scheduled_workouts_by_period', 'schedule_workout'])
        self.api.get_workout_by_id.return_value = {'sportType': {'sportTypeId': 1, 'sportTypeKey': 'running'}, 'ownerId': 'private'}
        self.api.get_scheduled_workouts_by_period.return_value = []
        self.response = {'calendarDate': '2026-11-01', 'workout': {'workoutId': 1744319670}, 'owner': 'private'}
        self.api.schedule_workout.return_value = self.response
        self.factory = Mock(return_value=self.api)
        self.tools = GarminTools(self.factory, schedule_approvals=self.store, enable_scheduling=True)

    def call(self, approval_id=None, **kwargs):
        return self.tools.schedule_running_workout(kwargs.get('workout_id', 1744319670), kwargs.get('date', '2026-11-01'), approval_id)

    def request(self):
        result = self.call()
        self.assertEqual(result['status'], 'approval_required')
        self.factory.assert_not_called()
        return result['approval_id']

    def approve(self, request_id, answer='SCHEDULE'):
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=answer), redirect_stdout(io.StringIO()):
            return self.store.approve_interactively(request_id)

    def test_installed_library_method_posts_documented_payload(self):
        # Invoke the actual installed method with only its HTTP client mocked.
        client = Mock()
        client.garmin_workouts_schedule_url = '/installed-library-schedule-base'
        result = WorkoutsMixin.schedule_workout(client, 123, '2026-11-01')
        client.client.post.assert_called_once_with('connectapi', '/installed-library-schedule-base/123', json={'date': '2026-11-01'}, api=True)
        self.assertIs(result, client.client.post.return_value)

    def test_validation_before_any_api_or_approval_state(self):
        for value in (0, -1, True, '123', 1.5):
            self.assertEqual(self.call(workout_id=value)['error']['code'], 'invalid_input')
        for value in ('2026-02-29', '2026-11-31', '20261101', '2026-1-01', '2026-11-01T12:00:00', '2026-11-01 ', '', None, True, '0000-01-01'):
            self.assertEqual(self.call(date=value)['error']['code'], 'invalid_input')
        self.factory.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
        self.assertEqual(scheduling_payload(1, '2028-02-29')['date'], '2028-02-29')

    def test_scheduling_is_separate_opt_in(self):
        tools = GarminTools(self.factory, enable_uploads=True, schedule_approvals=self.store)
        self.assertEqual(tools.schedule_running_workout(1, '2026-11-01')['error']['code'], 'scheduling_disabled')
        self.factory.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_terminal_required_and_upload_word_is_not_consent(self):
        request_id = self.request()
        with patch('sys.stdin.isatty', return_value=False), redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            self.store.approve_interactively(request_id)
        self.assertFalse(self.approve(request_id, 'UPLOAD'))
        self.assertEqual(self.call(request_id)['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_pending_and_model_boolean_cannot_schedule(self):
        request_id = self.request()
        for value in (request_id, True, '../invalid'):
            self.assertEqual(self.call(value)['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_approval_binds_operation_workout_and_date(self):
        request_id = self.request()
        self.approve(request_id)
        for kwargs in ({'date': '2026-11-02'}, {'workout_id': 123}):
            self.assertEqual(self.call(request_id, **kwargs)['error']['code'], 'approval_required')
        self.factory.assert_not_called()
        # Even sharing a directory cannot repurpose an upload approval.
        upload = ApprovalStore(self.temp.name, clock=lambda: self.now)
        upload_id = upload.request(example_workout())
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='UPLOAD'), redirect_stdout(io.StringIO()):
            upload.approve_interactively(upload_id)
        self.assertEqual(self.call(upload_id)['error']['code'], 'approval_required')
        with self.assertRaises(ValueError):
            upload.consume(request_id, example_workout())
        self.factory.assert_not_called()

    def test_expiry_at_ten_minutes(self):
        request_id = self.request()
        self.approve(request_id)
        self.now += 600
        self.assertEqual(self.call(request_id)['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_success_is_sanitized_single_use_and_persistent(self):
        request_id = self.request()
        self.approve(request_id)
        self.assertEqual(self.call(request_id), {'ok': True, 'status': 'scheduled', 'workout_id': 1744319670, 'date': '2026-11-01'})
        self.api.get_workout_by_id.assert_called_once_with(1744319670)
        self.api.get_scheduled_workouts_by_period.assert_called_once_with('2026-11-01', '2026-11-01')
        self.api.schedule_workout.assert_called_once_with(1744319670, '2026-11-01')
        self.assertEqual(self.call(request_id)['error']['code'], 'approval_required')
        self.tools.schedule_approvals = ScheduleApprovalStore(self.temp.name, clock=lambda: self.now)
        fresh = self.call()['approval_id']
        self.approve(fresh)
        self.assertEqual(self.call(fresh)['error']['code'], 'schedule_attempt_exists')
        self.api.schedule_workout.assert_called_once()
        for file in Path(self.temp.name).glob('*.json'):
            self.assertEqual(os.stat(file).st_mode & 0o777, 0o600)

    def test_existing_remote_schedule_does_not_post(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.get_scheduled_workouts_by_period.return_value = [self.response]
        self.assertEqual(self.call(request_id)['status'], 'already_scheduled')
        self.api.schedule_workout.assert_not_called()

    def test_other_workouts_and_dates_are_not_duplicates(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.get_scheduled_workouts_by_period.return_value = [
            {'calendarDate': '2026-11-02', 'workout': {'workoutId': 1744319670}},
            {'calendarDate': '2026-11-01', 'workout': {'workoutId': 99}}]
        self.assertEqual(self.call(request_id)['status'], 'scheduled')

    def test_non_running_or_unverifiable_workout_rejected(self):
        for response in ({'sportType': {'sportTypeId': 2, 'sportTypeKey': 'cycling'}}, {}, None):
            request_id = self.call()['approval_id']
            self.approve(request_id)
            self.api.get_workout_by_id.return_value = response
            self.assertEqual(self.call(request_id)['error']['code'], 'invalid_workout')
            self.api.schedule_workout.assert_not_called()
            self.api.get_scheduled_workouts_by_period.assert_not_called()

    def test_preflight_failures_never_post(self):
        for value in (None, {}, [{'unexpected': 'private token'}]):
            request_id = self.call()['approval_id']
            self.approve(request_id)
            self.api.get_scheduled_workouts_by_period.return_value = value
            self.assertEqual(self.call(request_id)['error']['code'], 'schedule_check_failed')
            self.api.schedule_workout.assert_not_called()
        self.api.get_workout_by_id.side_effect = RuntimeError('private token')
        request_id = self.call()['approval_id']
        self.approve(request_id)
        result = self.call(request_id)
        self.assertEqual(result['error']['code'], 'schedule_check_failed')
        self.assertNotIn('private token', json.dumps(result))

    def test_authentication_failure_consumes_approval(self):
        request_id = self.request()
        self.approve(request_id)
        self.factory.side_effect = RuntimeError('private token')
        self.assertEqual(self.call(request_id)['error']['code'], 'authentication_required')
        self.assertEqual(self.call(request_id)['error']['code'], 'approval_required')
        self.api.schedule_workout.assert_not_called()

    def test_uncertain_write_is_not_retried_even_with_fresh_approval(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.schedule_workout.side_effect = RuntimeError('private token')
        result = self.call(request_id)
        self.assertEqual(result['error']['code'], 'schedule_outcome_unknown')
        self.assertNotIn('private token', json.dumps(result))
        fresh = self.call()['approval_id']
        self.approve(fresh)
        self.assertEqual(self.call(fresh)['error']['code'], 'schedule_attempt_exists')
        self.api.schedule_workout.assert_called_once()

    def test_unknown_post_response_is_uncertain(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.schedule_workout.return_value = {'private': 'hidden'}
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        self.api.schedule_workout.assert_called_once()

    def test_local_attempt_claim_is_atomic(self):
        request_id = self.request()
        payload = scheduling_payload(1744319670, '2026-11-01')
        self.store.claim_attempt(payload)
        with self.assertRaises(FileExistsError):
            ScheduleApprovalStore(self.temp.name).claim_attempt(payload)
        self.api.schedule_workout.assert_not_called()


class SchedulingProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_schema_and_offline_approval_request(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = Mock()
            service = GarminTools(factory, schedule_approvals=ScheduleApprovalStore(directory), enable_scheduling=True)
            async with Client(create_server(service), read_timeout_seconds=5) as client:
                tools = (await client.list_tools()).tools
                tool = next(tool for tool in tools if tool.name == 'schedule_running_workout')
                self.assertFalse(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.idempotent_hint)
                invalid = await client.call_tool('schedule_running_workout', {'workout_id': True, 'date': '2026-11-01'})
                self.assertTrue(invalid.is_error)
                result = await client.call_tool('schedule_running_workout', {'workout_id': 123, 'date': '2026-11-01'})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content['status'], 'approval_required')
            factory.assert_not_called()
