import asyncio
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from garminconnect import GarminConnectAuthenticationError
from mcp import Client, StdioServerParameters
from garmin_connector.approvals import ApprovalStore, outside_project
from garmin_connector.mcp_tools import GarminTools, saved_session_client
from garmin_connector.mcp_server import create_server
from garmin_connector.workouts import example_workout


class MCPToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.store = ApprovalStore(self.temp.name, clock=lambda: self.now)
        self.api = Mock(spec=['get_activities', 'get_activity', 'get_activity_splits', 'upload_workout'])
        self.factory = Mock(return_value=self.api)
        self.tools = GarminTools(self.factory, self.store, enable_uploads=True)
        self.payload = example_workout()

    def approve(self, request_id, answer='UPLOAD'):
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=answer), redirect_stdout(io.StringIO()):
            return self.store.approve_interactively(request_id)

    def request(self):
        result = self.tools.upload_running_workout(self.payload)
        self.assertEqual(result['status'], 'approval_required')
        self.factory.assert_not_called()
        return result['approval_id']

    def test_filtered_running_summaries_strip_personal_fields(self):
        self.api.get_activities.return_value = [{'activityId': 12, 'distance': 2000,
            'duration': 600, 'activityName': 'Home', 'startLatitude': 52, 'startLongitude': 4,
            'ownerFullName': 'Private', 'startTimeLocal': 'private'}]
        result = self.tools.get_recent_activities()
        self.assertEqual(result, {'ok': True, 'activities': [
            {'activity_id': 12, 'distance_km': 2, 'duration_seconds': 600}]})
        self.api.get_activities.assert_called_once_with(0, 5, activitytype='running')

    def test_empty_activity_list(self):
        for value in ([], None):
            self.api.get_activities.return_value = value
            self.assertEqual(self.tools.get_recent_activities()['activities'], [])

    def test_details_and_laps_strip_sensitive_fields(self):
        self.api.get_activity.return_value = {'activityId': 12, 'activityName': 'Home',
            'summaryDTO': {'distance': 7000, 'duration': 2400, 'startLatitude': 52}}
        self.api.get_activity_splits.return_value = {'lapDTOs': [
            {'lapIndex': 1, 'distance': 1000, 'duration': 300, 'startLongitude': 4}], 'ownerId': 99}
        result = self.tools.get_activity_details(12)
        self.assertEqual(result['activity'], {'activity_id': 12, 'distance_m': 7000, 'duration_seconds': 2400})
        self.assertEqual(result['laps'], [{'lapIndex': 1, 'distance': 1000, 'duration': 300}])
        self.api.get_activity.assert_called_once_with(12)
        self.api.get_activity_splits.assert_called_once_with(12)

    def test_activity_http_errors_are_specific_and_sanitized(self):
        for status, code in ((403, 'activity_access_denied'), (404, 'activity_not_found'),
                             (500, 'garmin_api_error')):
            for endpoint in ('get_activity', 'get_activity_splits'):
                with self.subTest(status=status, endpoint=endpoint):
                    self.api.reset_mock(side_effect=True)
                    self.api.get_activity.return_value = {'summaryDTO': {'distance': 1000}}
                    failure = RuntimeError('private server response')
                    failure.response = Mock(status_code=status)
                    getattr(self.api, endpoint).side_effect = failure
                    result = self.tools.get_activity_details(24849396557)
                    self.assertEqual(result['error']['code'], code)
                    self.assertNotIn('private server response', json.dumps(result))
                    if endpoint == 'get_activity':
                        self.api.get_activity_splits.assert_not_called()

    def test_invalid_input_never_authenticates(self):
        for limit in (0, 51, True, '5', 1.5):
            self.assertEqual(self.tools.get_recent_activities(limit)['error']['code'], 'invalid_input')
        for activity_id in (-1, 0, True, '12'):
            self.assertFalse(self.tools.get_activity_details(activity_id)['ok'])
        self.assertFalse(self.tools.build_running_workout('Test', [])['ok'])
        self.assertFalse(self.tools.build_running_workout('Test', [{'kind': 'interval', 'distance_m': -1}])['ok'])
        self.assertFalse(self.tools.upload_running_workout({'workoutId': 1})['ok'])
        self.factory.assert_not_called()

    def test_offline_build(self):
        result = self.tools.build_running_workout('Test', [
            {'kind': 'interval', 'distance_m': 1000, 'pace_seconds_per_km': 300}])
        self.assertTrue(result['ok'])
        self.factory.assert_not_called()

    def test_read_only_default(self):
        tools = GarminTools(self.factory, self.store)
        self.assertEqual(tools.upload_running_workout(self.payload)['error']['code'], 'uploads_disabled')
        self.factory.assert_not_called()
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_authentication_and_api_errors_are_sanitized(self):
        for failure, code in [(GarminConnectAuthenticationError('private token'), 'authentication_required'),
                              (RuntimeError('private token'), 'garmin_api_error')]:
            self.factory.side_effect = failure
            for result in (self.tools.get_recent_activities(), self.tools.get_activity_details(12)):
                self.assertEqual(result['error']['code'], code)
                self.assertNotIn('private token', json.dumps(result))

    def test_pending_cannot_upload_and_model_boolean_is_not_approval(self):
        request_id = self.request()
        for approval_id in (request_id, True, '../bad'):
            self.assertEqual(self.tools.upload_running_workout(self.payload, approval_id)['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_approved_upload_once_returns_only_id_and_name(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.upload_workout.return_value = {'workoutId': 123, 'ownerId': 999}
        result = self.tools.upload_running_workout(self.payload, request_id)
        self.assertEqual(result, {'ok': True, 'status': 'uploaded', 'workout_id': 123,
                                 'workout_name': self.payload['workoutName']})
        self.api.upload_workout.assert_called_once_with(self.payload)
        self.assertFalse(self.tools.upload_running_workout(self.payload, request_id)['ok'])
        self.api.upload_workout.assert_called_once()

    def test_wrong_payload_rejected(self):
        request_id = self.request()
        self.approve(request_id)
        changed = example_workout()
        changed['workoutName'] = 'Different'
        self.assertFalse(self.tools.upload_running_workout(changed, request_id)['ok'])
        self.factory.assert_not_called()

    def test_expired_approval_rejected(self):
        request_id = self.request()
        self.approve(request_id)
        self.now += 601
        self.assertFalse(self.tools.upload_running_workout(self.payload, request_id)['ok'])
        self.factory.assert_not_called()

    def test_failed_attempt_consumes_approval(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.upload_workout.side_effect = RuntimeError('secret')
        result = self.tools.upload_running_workout(self.payload, request_id)
        self.assertEqual(result['error']['code'], 'upload_outcome_unknown')
        self.assertNotIn('secret', json.dumps(result))
        self.assertFalse(self.tools.upload_running_workout(self.payload, request_id)['ok'])
        self.api.upload_workout.assert_called_once()

    def test_upload_authentication_failure_does_not_write(self):
        request_id = self.request()
        self.approve(request_id)
        self.factory.side_effect = GarminConnectAuthenticationError('private')
        self.assertEqual(self.tools.upload_running_workout(self.payload, request_id)['error']['code'], 'authentication_required')
        self.api.upload_workout.assert_not_called()
        self.assertFalse(self.tools.upload_running_workout(self.payload, request_id)['ok'])

    def test_missing_id_is_uncertain(self):
        request_id = self.request()
        self.approve(request_id)
        self.api.upload_workout.return_value = {}
        self.assertEqual(self.tools.upload_running_workout(self.payload, request_id)['error']['code'], 'upload_outcome_unknown')

    def test_terminal_required_and_denial(self):
        request_id = self.request()
        with patch('sys.stdin.isatty', return_value=False), redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                self.store.approve_interactively(request_id)
        self.assertFalse(self.approve(request_id, answer='yes'))
        self.assertFalse(self.tools.upload_running_workout(self.payload, request_id)['ok'])

    def test_state_cannot_be_inside_repository(self):
        with self.assertRaises(ValueError):
            outside_project(Path(__file__).resolve().parents[1] / 'tokens')

    def test_startup_has_no_auth_or_filesystem_side_effects(self):
        with patch('garmin_connector.mcp_tools.connect') as connect, patch.object(Path, 'mkdir') as mkdir, patch('builtins.input', side_effect=AssertionError('must not prompt')):
            import garmin_connector.mcp_server as module
            importlib.reload(module)
            module.create_server()
            connect.assert_not_called()
            mkdir.assert_not_called()

    @patch('garmin_connector.mcp_tools.connect')
    def test_session_auth_uses_no_credentials(self, connect):
        saved_session_client()
        connect.assert_called_once_with(None, None, token_dir=Path('~/.garminconnect').expanduser().resolve())


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_tools_through_sdk(self):
        api = Mock()
        api.get_activities.return_value = []
        api.get_activity.return_value = {'summaryDTO': {'distance': 1000}}
        api.get_activity_splits.return_value = {'lapDTOs': []}
        tools = GarminTools(Mock(return_value=api))
        async with Client(create_server(tools), read_timeout_seconds=5) as client:
            listed = await client.list_tools()
            self.assertEqual({tool.name for tool in listed.tools}, {
                'get_recent_activities', 'get_activity_details', 'build_running_workout', 'upload_running_workout'})
            for name, args in [('get_recent_activities', {}), ('get_activity_details', {'activity_id': 12}),
                               ('build_running_workout', {'name': 'Test', 'steps': [{'kind': 'warmup', 'distance_m': 2000}]})]:
                result = await client.call_tool(name, args)
                self.assertFalse(result.is_error)
                self.assertTrue(result.structured_content['ok'])
            result = await client.call_tool('upload_running_workout', {'workout': example_workout()})
            self.assertEqual(result.structured_content['error']['code'], 'uploads_disabled')
            invalid = await client.call_tool('get_recent_activities', {'limit': True})
            self.assertTrue(invalid.is_error)

    async def test_real_stdio_offline(self):
        # Bounded subprocess test: real SDK framing with no Garmin tools invoked.
        async with asyncio.timeout(15):
            params = StdioServerParameters(command=sys.executable,
                args=['-m', 'garmin_connector.mcp_server'], cwd=str(Path(__file__).resolve().parents[1]))
            async with Client(params, read_timeout_seconds=5) as client:
                listed = await client.list_tools()
                self.assertEqual(len(listed.tools), 4)
                result = await client.call_tool('build_running_workout', {
                    'name': 'Offline STDIO test', 'steps': [{'kind': 'warmup', 'distance_m': 2000}]})
                self.assertFalse(result.is_error)
                self.assertTrue(result.structured_content['ok'])
