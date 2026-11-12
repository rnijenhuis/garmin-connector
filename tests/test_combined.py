"""Composite operations: temporary consent/progress and mocked Garmin only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from html import unescape
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient
from mcp import Client
from garmin_connector.browser_approval import browser_stores, create_approval_app, password_record, workout_summary
from garmin_connector.combined import combined_payload, CombinedApprovalStore
from garmin_connector.mcp_tools import GarminTools
from garmin_connector.mcp_server import create_server
from garmin_connector.scheduling import ScheduleApprovalStore, scheduling_payload
from garmin_connector.workouts import example_workout

ORIGIN = 'https://garmin.private.test'
PASSWORD = 'temporary-tests-only-password'
DATE = '2026-11-12'


class CombinedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = password_record(PASSWORD)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1000
        self.stores = browser_stores(self.root)
        for store in self.stores.values():
            store.clock = lambda: self.now
        self.browser = TestClient(create_approval_app(ORIGIN, self.auth, self.stores), base_url=ORIGIN)
        self.browser.auth = ('owner', PASSWORD)
        self.addCleanup(self.browser.close)
        self.api = Mock()
        self.api.upload_workout.return_value = {'workoutId': 123, 'private': 'secret'}
        self.api.get_workout_by_id.return_value = {'sportType': {'sportTypeId': 1, 'sportTypeKey': 'running'}}
        self.api.get_scheduled_workouts_by_period.return_value = []
        self.response = {'calendarDate': DATE, 'workout': {'workoutId': 123}}
        self.api.schedule_workout.return_value = self.response
        self.factory = Mock(return_value=self.api)
        self.tools = self.new_tools()
        self.workout = example_workout()

    def new_tools(self):
        return GarminTools(self.factory, approvals=self.stores['upload'], enable_uploads=True,
                           schedule_approvals=self.stores['schedule'], enable_scheduling=True,
                           browser_approval_origin=ORIGIN, combined_approvals=self.stores['upload-and-schedule'])

    def call(self, request_id=None, workout=None, date=DATE):
        return self.tools.upload_and_schedule_running_workout(self.workout if workout is None else workout, date, request_id)

    def prepare(self):
        result = self.call()
        self.assertEqual(result['status'], 'approval_required')
        return result

    def form(self, prepared):
        page = self.browser.get(prepared['approval_url'])
        self.assertEqual(page.status_code, 200)
        return {**{name: unescape(value) for name, value in re.findall(r'name="(csrf|sha256)" value="([^"]+)"', page.text)}, 'decision': 'approve'}

    def approve(self, prepared):
        self.assertEqual(self.browser.post(prepared['approval_url'], data=self.form(prepared), headers={'Origin': ORIGIN}).status_code, 200)
        return prepared['approval_id']

    def consent(self):
        return self.approve(self.prepare())

    def test_prepare_and_browser_approval_never_contact_garmin(self):
        prepared = self.prepare()
        page = self.browser.get(prepared['approval_url'])
        for expected in ('BOTH upload', 'calendar scheduling', DATE, self.workout['workoutName'], 'Total distance'):
            self.assertIn(expected, page.text)
        self.approve(prepared)
        self.factory.assert_not_called()

    def test_auth_origin_csrf_operation_binding_and_no_model_approval(self):
        prepared = self.prepare()
        valid = self.form(prepared)
        for origin, form in [('null', valid), (ORIGIN, {**valid, 'csrf': 'yes'}), (ORIGIN, {**valid, 'sha256': 'yes'})]:
            self.assertIn(self.browser.post(prepared['approval_url'], data=form, headers={'Origin': origin}).status_code, (403, 409))
        self.assertEqual(self.browser.get(prepared['approval_url'], auth=('owner', 'wrong')).status_code, 401)
        self.assertEqual(self.browser.post(prepared['approval_url'], data=valid, headers={'Origin': ORIGIN}, auth=('owner', 'wrong')).status_code, 401)
        self.assertEqual(self.browser.get(prepared['approval_url'], headers={'Host': 'garmin.private.test:444'}).status_code, 400)
        for request_id in (prepared['approval_id'], True, 'ja', '../bad'):
            self.assertFalse(self.call(request_id)['ok'])
        wrong = prepared['approval_url'].replace('/upload-and-schedule/', '/upload/')
        self.assertEqual(self.browser.post(wrong, data=valid, headers={'Origin': ORIGIN}).status_code, 409)
        with self.assertRaises(ValueError):
            self.stores['upload-and-schedule'].approve_interactively(prepared['approval_id'])
        self.factory.assert_not_called()

    def test_payload_date_operation_and_expiry_binding(self):
        request_id = self.consent()
        changed = deepcopy(self.workout)
        changed['workoutName'] = 'Changed'
        self.assertFalse(self.call(request_id, workout=changed)['ok'])
        self.assertFalse(self.call(request_id, date='2026-11-13')['ok'])
        self.assertFalse(self.tools.upload_running_workout(self.workout, request_id)['ok'])
        self.assertFalse(self.tools.schedule_running_workout(123, DATE, request_id)['ok'])
        self.now += 600
        self.assertFalse(self.call(request_id)['ok'])
        self.factory.assert_not_called()

    def test_success_is_durable_sanitized_and_replay_does_not_write(self):
        request_id = self.consent()
        expected = {'ok': True, 'status': 'scheduled', 'workout_id': 123, 'date': DATE}
        self.assertEqual(self.call(request_id), expected)
        self.tools = self.new_tools()
        self.assertEqual(self.call(request_id), expected)
        fresh = self.consent()
        self.assertEqual(self.call(fresh), expected)
        self.api.upload_workout.assert_called_once_with(self.workout)
        self.api.schedule_workout.assert_called_once_with(123, DATE)
        for path in self.root.rglob('*'):
            if path.is_file():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_preflight_failure_resume_and_expiry_requires_fresh_consent(self):
        request_id = self.consent()
        self.api.get_scheduled_workouts_by_period.side_effect = RuntimeError('private')
        result = self.call(request_id)
        self.assertEqual(result['status'], 'uploaded_not_scheduled')
        self.assertEqual(result['workout_id'], 123)
        self.assertNotIn('private', json.dumps(result))
        self.api.schedule_workout.assert_not_called()
        self.now += 600
        self.assertFalse(self.call(request_id)['ok'])
        self.api.get_scheduled_workouts_by_period.side_effect = None
        fresh = self.consent()
        self.tools = self.new_tools()
        self.assertEqual(self.call(fresh)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()
        self.api.schedule_workout.assert_called_once()

    def test_resume_before_expiry_only_runs_missing_step(self):
        request_id = self.consent()
        self.api.get_workout_by_id.side_effect = RuntimeError('read failure')
        self.assertEqual(self.call(request_id)['status'], 'uploaded_not_scheduled')
        self.api.get_workout_by_id.side_effect = None
        self.assertEqual(self.call(request_id)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()

    def test_expiry_during_upload_stops_schedule(self):
        request_id = self.consent()
        def upload(payload):
            self.now += 600
            return {'workoutId': 123}
        self.api.upload_workout.side_effect = upload
        result = self.call(request_id)
        self.assertEqual(result['error']['code'], 'approval_required')
        self.assertEqual(result['workout_id'], 123)
        self.api.schedule_workout.assert_not_called()
        fresh = self.consent()
        self.assertEqual(self.call(fresh)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()

    def test_unknown_upload_never_repeated_even_with_new_consent(self):
        for response in (None, {}, {'workoutId': True}):
            with self.subTest(response=response):
                self.workout['workoutName'] = str(response)
                self.api.upload_workout.return_value = response
                request_id = self.consent()
                self.assertEqual(self.call(request_id)['error']['code'], 'upload_outcome_unknown')
                self.assertEqual(self.call(request_id)['error']['code'], 'upload_outcome_unknown')
                fresh = self.consent()
                self.assertEqual(self.call(fresh)['error']['code'], 'upload_outcome_unknown')
        self.assertEqual(self.api.upload_workout.call_count, 3)
        self.api.schedule_workout.assert_not_called()

    def test_upload_exception_and_crash_marker_are_not_retried(self):
        request_id = self.consent()
        self.api.upload_workout.side_effect = RuntimeError('secret')
        self.assertEqual(self.call(request_id)['error']['code'], 'upload_outcome_unknown')
        self.tools = self.new_tools()
        self.assertEqual(self.call(request_id)['error']['code'], 'upload_outcome_unknown')
        self.api.upload_workout.assert_called_once()

    def test_unknown_scheduling_only_reconciles_calendar(self):
        request_id = self.consent()
        self.api.schedule_workout.side_effect = RuntimeError('secret')
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        fresh = self.consent()
        self.assertEqual(self.call(fresh)['error']['code'], 'schedule_outcome_unknown')
        self.api.get_scheduled_workouts_by_period.return_value = [self.response]
        self.assertEqual(self.call(fresh)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()
        self.api.schedule_workout.assert_called_once()

    def test_unknown_schedule_response_and_calendar_fail_closed(self):
        request_id = self.consent()
        self.api.get_scheduled_workouts_by_period.return_value = {'unknown': 'secret'}
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_check_failed')
        self.api.schedule_workout.assert_not_called()
        self.api.get_scheduled_workouts_by_period.return_value = []
        self.api.schedule_workout.return_value = {}
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        self.api.schedule_workout.assert_called_once()

    def test_shared_ledger_blocks_terminal_browser_and_combined_duplicates(self):
        legacy = ScheduleApprovalStore(self.root / 'scheduling')
        legacy.claim_attempt(scheduling_payload(123, DATE))
        request_id = self.consent()
        self.assertEqual(self.call(request_id)['error']['code'], 'schedule_outcome_unknown')
        self.api.schedule_workout.assert_not_called()
        # Conversely the combined claim blocks the legacy store.
        self.workout['workoutName'] = 'other'
        self.api.upload_workout.return_value = {'workoutId': 456}
        self.api.schedule_workout.return_value = {'calendarDate': DATE, 'workout': {'workoutId': 456}}
        self.assertEqual(self.call(self.consent())['status'], 'scheduled')
        with self.assertRaises(FileExistsError):
            legacy.claim_attempt(scheduling_payload(456, DATE))

    def test_concurrent_calls_and_distinct_approvals_have_one_upload(self):
        first, second = self.consent(), self.consent()
        barrier = threading.Barrier(3)
        def run(request_id):
            barrier.wait(timeout=5)
            return self.new_tools().upload_and_schedule_running_workout(self.workout, DATE, request_id)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(run, first), pool.submit(run, second)
            barrier.wait(timeout=5)
            self.assertEqual(a.result(timeout=5)['status'], 'scheduled')
            self.assertEqual(b.result(timeout=5)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()
        self.api.schedule_workout.assert_called_once()

    def test_state_persisted_before_writes_and_upload_id_before_reads(self):
        store = self.stores['upload-and-schedule']
        def state():
            return json.loads(next(store.directory.glob('*.progress.json')).read_text())
        def upload(payload):
            self.assertEqual(state()['phase'], 'upload_started')
            return {'workoutId': 123}
        def read(workout_id):
            self.assertEqual(state(), {'phase': 'uploaded', 'workout_id': 123})
            return {'sportType': {'sportTypeId': 1, 'sportTypeKey': 'running'}}
        self.api.upload_workout.side_effect = upload
        self.api.get_workout_by_id.side_effect = read
        self.assertEqual(self.call(self.consent())['status'], 'scheduled')

    def test_no_write_if_journal_cannot_be_committed(self):
        request_id = self.consent()
        with patch.object(CombinedApprovalStore, 'save', side_effect=OSError('disk full')):
            self.assertFalse(self.call(request_id)['ok'])
        self.api.upload_workout.assert_not_called()
        self.api.schedule_workout.assert_not_called()

    def test_invalid_input_opt_ins_and_terminal_preserved(self):
        for date in ('2026-02-29', '2026-1-01', True, None):
            self.assertEqual(self.call(date=date)['error']['code'], 'invalid_input')
        self.assertEqual(self.call(workout={})['error']['code'], 'invalid_input')
        self.tools.enable_uploads = False
        self.assertEqual(self.call()['error']['code'], 'uploads_disabled')
        self.tools.enable_uploads = True
        self.tools.enable_scheduling = False
        self.assertEqual(self.call()['error']['code'], 'scheduling_disabled')
        self.tools.enable_scheduling = True
        self.tools.browser_approval_origin = None
        self.assertEqual(self.call()['error']['code'], 'browser_approval_required')
        self.factory.assert_not_called()

    def test_denied_and_expired_pending_requests_never_authorize(self):
        prepared = self.prepare()
        form = {**self.form(prepared), 'decision': 'deny'}
        self.assertEqual(self.browser.post(prepared['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 200)
        self.assertFalse(self.call(prepared['approval_id'])['ok'])
        prepared = self.prepare()
        form = self.form(prepared)
        self.now += 600
        self.assertEqual(self.browser.post(prepared['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 409)
        self.assertFalse(self.call(prepared['approval_id'])['ok'])
        self.factory.assert_not_called()

    def test_authentication_failure_can_resume_without_write_replay(self):
        request_id = self.consent()
        self.factory.side_effect = RuntimeError('private credentials')
        result = self.call(request_id)
        self.assertEqual(result['error']['code'], 'authentication_required')
        self.assertNotIn('private credentials', json.dumps(result))
        self.api.upload_workout.assert_not_called()
        self.factory.side_effect = None
        self.assertEqual(self.call(request_id)['status'], 'scheduled')
        self.api.upload_workout.assert_called_once()

    def test_id_storage_failure_reports_partial_success_and_blocks_upload(self):
        request_id = self.consent()
        save = CombinedApprovalStore.save
        def fail_id(path, state):
            if state.get('workout_id'):
                raise OSError('disk full')
            return save(path, state)
        with patch.object(CombinedApprovalStore, 'save', side_effect=fail_id):
            result = self.call(request_id)
        self.assertEqual(result['status'], 'uploaded_not_scheduled')
        self.assertEqual(result['workout_id'], 123)
        self.assertEqual(self.call(request_id)['error']['code'], 'upload_outcome_unknown')
        self.api.upload_workout.assert_called_once()
        self.api.schedule_workout.assert_not_called()

    def test_concurrent_same_approval_does_not_duplicate_writes(self):
        request_id = self.consent()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.call, request_id) for _ in range(2)]
            self.assertTrue(all(f.result(timeout=5)['status'] == 'scheduled' for f in futures))
        self.api.upload_workout.assert_called_once()
        self.api.schedule_workout.assert_called_once()

    def test_summary_nested_totals_and_targets(self):
        result = self.tools.build_running_workout('<script>review</script>', [
            {'kind': 'repeat', 'repeat_count': 2, 'steps': [
                {'kind': 'interval', 'distance_m': 1000, 'pace_seconds_per_km': 300},
                {'kind': 'repeat', 'repeat_count': 3, 'steps': [
                    {'kind': 'recovery', 'duration_seconds': 60, 'heart_rate_zone': 2}]}]}])
        self.workout = result['workout']
        page = self.browser.get(self.prepare()['approval_url']).text
        for expected in ('2000 metres', '360 seconds', '300 seconds/km', 'HR zone 2', '&lt;script&gt;'):
            self.assertIn(expected, page)
        self.assertNotIn('<script>', page)


class CombinedProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_tool_schema_and_offline_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            stores = browser_stores(directory)
            factory = Mock()
            tools = GarminTools(factory, enable_uploads=True, enable_scheduling=True,
                                browser_approval_origin=ORIGIN, combined_approvals=stores['upload-and-schedule'])
            async with Client(create_server(tools), read_timeout_seconds=5) as client:
                tool = next(t for t in (await client.list_tools()).tools if t.name == 'upload_and_schedule_running_workout')
                self.assertEqual(set(tool.input_schema['required']), {'workout', 'date'})
                result = await client.call_tool(tool.name, {'workout': example_workout(), 'date': DATE})
                self.assertEqual(result.structured_content['status'], 'approval_required')
            factory.assert_not_called()
