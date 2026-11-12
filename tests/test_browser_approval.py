"""Independent browser consent and private ChatGPT transport, entirely offline."""
import asyncio
from copy import deepcopy
from html import unescape
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock

from mcp import Client, StdioServerParameters
from starlette.testclient import TestClient

from garmin_connector.approvals import ApprovalStore, fingerprint
from garmin_connector.browser_approval import (
    approval_origin, browser_stores, create_approval_app, load_auth, password_record,
)
from garmin_connector.mcp_server import create_server
from garmin_connector.mcp_tools import GarminTools
from garmin_connector.workouts import example_workout

ORIGIN = 'https://garmin.private.test'
PASSWORD = 'unit-test-only-approval-password'


class BrowserApprovalTests(unittest.TestCase):
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
        self.app = create_approval_app(ORIGIN, self.auth, self.stores)
        self.browser = TestClient(self.app, base_url=ORIGIN)
        self.browser.auth = ('owner', PASSWORD)
        self.addCleanup(self.browser.close)
        self.api = Mock(spec=['upload_workout', 'get_workout_by_id', 'get_scheduled_workouts_by_period', 'schedule_workout', 'get_activities'])
        self.api.upload_workout.return_value = {'workoutId': 123, 'private': 'hidden'}
        self.api.get_workout_by_id.return_value = {'sportType': {'sportTypeId': 1, 'sportTypeKey': 'running'}}
        self.api.get_scheduled_workouts_by_period.return_value = []
        self.api.schedule_workout.return_value = {'calendarDate': '2026-11-01', 'workout': {'workoutId': 123}}
        self.factory = Mock(return_value=self.api)
        self.tools = GarminTools(self.factory, approvals=self.stores['upload'], enable_uploads=True,
                                 schedule_approvals=self.stores['schedule'], enable_scheduling=True,
                                 browser_approval_origin=ORIGIN)
        self.payload = example_workout()

    def prepare(self, operation='upload'):
        return (self.tools.upload_running_workout(self.payload) if operation == 'upload' else
                self.tools.schedule_running_workout(123, '2026-11-01'))

    def form(self, prepared):
        response = self.browser.get(prepared['approval_url'])
        self.assertEqual(response.status_code, 200)
        fields = {name: unescape(value) for name, value in re.findall(r'name="(csrf|sha256)" value="([^"]+)"', response.text)}
        return {**fields, 'decision': 'approve'}

    def approve(self, prepared):
        return self.browser.post(prepared['approval_url'], data=self.form(prepared), headers={'Origin': ORIGIN})

    def test_preparing_is_offline_with_safe_review_link(self):
        for operation in ('upload', 'schedule'):
            result = self.prepare(operation)
            self.assertEqual(result['status'], 'approval_required')
            self.assertTrue(result['approval_url'].startswith(ORIGIN + '/review/' + operation + '/'))
            self.assertEqual(result['expires_in_seconds'], 600)
            self.assertNotIn('terminal', result['instruction'])
            self.assertNotIn(PASSWORD, json.dumps(result))
        self.factory.assert_not_called()

    def test_independent_auth_is_required_for_get_and_post(self):
        request = self.prepare()
        form = self.form(request)
        anonymous = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(anonymous.close)
        for method in ('get', 'post'):
            response = (anonymous.get(request['approval_url']) if method == 'get' else
                        anonymous.post(request['approval_url'], data=form, headers={'Origin': ORIGIN}))
            self.assertEqual(response.status_code, 401)
            self.assertNotIn(self.payload['workoutName'], response.text)
        result = self.tools.upload_running_workout(self.payload, request['approval_id'])
        self.assertEqual(result['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_get_and_model_yes_cannot_approve(self):
        request = self.prepare()
        self.browser.get(request['approval_url'] + '?approve=true')
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'approval_required')
        self.factory.assert_not_called()
        self.assertTrue(self.stores['upload'].path(request['approval_id'], 'pending').exists())

    def test_origin_csrf_and_review_digest_are_all_required(self):
        request = self.prepare()
        valid = self.form(request)
        for origin, data in ((None, valid), ('null', valid), ('https://evil.test', valid), (ORIGIN, {**valid, 'csrf': 'fake'}),
                             (ORIGIN, {**valid, 'sha256': 'fake'}), (ORIGIN, {**valid, 'approved': 'true'})):
            headers = {'Origin': origin} if origin else {}
            result = self.browser.post(request['approval_url'], data=data, headers=headers)
            self.assertIn(result.status_code, (403, 409))
            self.assertTrue(self.stores['upload'].path(request['approval_id'], 'pending').exists())
        self.factory.assert_not_called()

    def test_null_origin_is_rejected_and_same_origin_form_still_works(self):
        request = self.prepare()
        page = self.browser.get(request['approval_url'])
        self.assertEqual(page.headers['referrer-policy'], 'strict-origin-when-cross-origin')
        form = self.form(request)
        rejected = self.browser.post(request['approval_url'], data=form, headers={'Origin': 'null'})
        self.assertEqual(rejected.status_code, 403)
        self.assertTrue(self.stores['upload'].path(request['approval_id'], 'pending').exists())
        self.factory.assert_not_called()
        accepted = self.browser.post(request['approval_url'], data=form, headers={'Origin': ORIGIN})
        self.assertEqual(accepted.status_code, 200)
        self.factory.assert_not_called()  # Consent alone must not call Garmin.

    def test_only_reviewed_payload_can_be_approved(self):
        request = self.prepare()
        old_form = self.form(request)
        path = self.stores['upload'].path(request['approval_id'], 'pending')
        record = json.loads(path.read_text())
        record['payload']['workoutName'] = 'Changed after review'
        record['sha256'] = fingerprint(record['payload'])
        path.write_text(json.dumps(record))
        response = self.browser.post(request['approval_url'], data=old_form, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 403)
        self.factory.assert_not_called()

    def test_expiry_is_original_ten_minutes_not_review_time(self):
        request = self.prepare()
        form = self.form(request)
        self.now += 600
        response = self.browser.post(request['approval_url'], data=form, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_end_to_end_upload_then_separate_schedule_consent(self):
        upload = self.prepare()
        form = self.form(upload)
        self.assertEqual(self.browser.post(upload['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 200)
        self.factory.assert_not_called()  # Portal itself never invokes Garmin.
        result = self.tools.upload_running_workout(self.payload, upload['approval_id'])
        self.assertEqual(result['workout_id'], 123)
        self.api.upload_workout.assert_called_once_with(self.payload)
        self.assertEqual(self.tools.upload_running_workout(self.payload, upload['approval_id'])['error']['code'], 'approval_required')
        self.assertEqual(self.browser.post(upload['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 409)
        schedule = self.prepare('schedule')
        self.assertEqual(self.tools.schedule_running_workout(123, '2026-11-01', schedule['approval_id'])['error']['code'], 'approval_required')
        self.api.schedule_workout.assert_not_called()
        self.assertEqual(self.approve(schedule).status_code, 200)
        changed = self.tools.schedule_running_workout(123, '2026-11-02', schedule['approval_id'])
        self.assertEqual(changed['error']['code'], 'approval_required')
        result = self.tools.schedule_running_workout(123, '2026-11-01', schedule['approval_id'])
        self.assertEqual(result, {'ok': True, 'status': 'scheduled', 'workout_id': 123, 'date': '2026-11-01'})
        self.api.schedule_workout.assert_called_once_with(123, '2026-11-01')

    def test_approval_survives_portal_restart_but_old_forms_do_not(self):
        request = self.prepare()
        form = self.form(request)
        other = TestClient(create_approval_app(ORIGIN, self.auth, self.stores), base_url=ORIGIN)
        other.auth = ('owner', PASSWORD)
        self.addCleanup(other.close)
        self.assertEqual(other.post(request['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 403)
        self.assertEqual(self.approve(request).status_code, 200)
        self.assertEqual(other.get(request['approval_url']).status_code, 409)
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['status'], 'uploaded')

    def test_browser_cannot_grant_legacy_or_wrong_operation_approval(self):
        legacy = ApprovalStore(self.root)
        request_id = legacy.request(self.payload)
        self.assertEqual(self.browser.get(f'{ORIGIN}/review/upload/{request_id}').status_code, 409)
        request = self.prepare()
        self.assertEqual(self.browser.get(request['approval_url'].replace('/upload/', '/schedule/')).status_code, 409)
        self.assertTrue(legacy.path(request_id, 'pending').exists())
        self.assertEqual(self.browser.get(request['approval_url'].replace('/upload/', '/anything/')).status_code, 404)
        self.factory.assert_not_called()

    def test_deny_does_not_authorize_and_expiry_never_extends(self):
        request = self.prepare()
        form = {**self.form(request), 'decision': 'deny'}
        self.assertEqual(self.browser.post(request['approval_url'], data=form, headers={'Origin': ORIGIN}).status_code, 200)
        self.assertTrue(self.stores['upload'].path(request['approval_id'], 'denied').exists())
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'approval_required')
        self.factory.assert_not_called()

    def test_changed_workout_and_failures_do_not_allow_replay(self):
        request = self.prepare()
        self.approve(request)
        changed = deepcopy(self.payload)
        changed['workoutName'] = 'Other'
        self.assertEqual(self.tools.upload_running_workout(changed, request['approval_id'])['error']['code'], 'approval_required')
        self.factory.assert_not_called()
        self.api.upload_workout.side_effect = RuntimeError('private session token')
        result = self.tools.upload_running_workout(self.payload, request['approval_id'])
        self.assertEqual(result['error']['code'], 'upload_outcome_unknown')
        self.assertNotIn('private session token', json.dumps(result))
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'approval_required')
        self.api.upload_workout.assert_called_once()

    def test_authentication_failure_consumes_browser_approval(self):
        request = self.prepare()
        self.approve(request)
        self.factory.side_effect = RuntimeError('private password')
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'authentication_required')
        self.assertEqual(self.tools.upload_running_workout(self.payload, request['approval_id'])['error']['code'], 'approval_required')
        self.api.upload_workout.assert_not_called()

    def test_shared_schedule_attempt_ledger_preserves_duplicate_protection(self):
        from garmin_connector.scheduling import ScheduleApprovalStore, scheduling_payload
        legacy = ScheduleApprovalStore(self.root / 'scheduling')
        legacy.claim_attempt(scheduling_payload(123, '2026-11-01'))
        request = self.prepare('schedule')
        self.approve(request)
        result = self.tools.schedule_running_workout(123, '2026-11-01', request['approval_id'])
        self.assertEqual(result['error']['code'], 'schedule_attempt_exists')
        self.api.schedule_workout.assert_not_called()

    def test_html_escaping_no_cache_and_no_sensitive_auth_material(self):
        self.payload['workoutName'] = '<script>alert("untrusted")</script>'
        request = self.prepare()
        response = self.browser.get(request['approval_url'])
        self.assertNotIn('<script>', response.text)
        self.assertIn('&lt;script&gt;', response.text)
        self.assertNotIn(PASSWORD, response.text)
        self.assertNotIn(self.auth['digest'], response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertEqual(response.headers['referrer-policy'], 'strict-origin-when-cross-origin')

    def test_login_rate_limit_and_bad_host(self):
        request = self.prepare()
        other = TestClient(self.app, base_url=ORIGIN)
        self.addCleanup(other.close)
        for _ in range(10):
            self.assertEqual(other.get(request['approval_url'], auth=('owner', 'wrong')).status_code, 401)
        self.assertEqual(self.browser.get(request['approval_url']).status_code, 401)
        self.factory.assert_not_called()
        clean = TestClient(create_approval_app(ORIGIN, self.auth, self.stores), base_url=ORIGIN)
        self.addCleanup(clean.close)
        self.assertEqual(clean.get(request['approval_url'], auth=('owner', PASSWORD), headers={'Host': 'evil.test'}).status_code, 400)

    def test_review_shows_hr_repeat_and_time_targets(self):
        result = self.tools.build_running_workout('Advanced review', [
            {'kind': 'warmup', 'distance_m': 2000, 'heart_rate_min_bpm': 130, 'heart_rate_max_bpm': 145},
            {'kind': 'repeat', 'repeat_count': 3, 'steps': [
                {'kind': 'interval', 'distance_m': 1000, 'pace_seconds_per_km': 300},
                {'kind': 'recovery', 'duration_seconds': 120}]},
            {'kind': 'cooldown', 'duration_seconds': 300, 'heart_rate_zone': 2}])
        self.payload = result['workout']
        response = self.browser.get(self.prepare()['approval_url'])
        for expected in ('Repeat 3 times', 'including final recovery', '120 seconds, no target',
                         '130–145 BPM', '300 seconds/km', '300 seconds, HR zone 2'):
            self.assertIn(expected, response.text)
        self.factory.assert_not_called()

    def test_wrong_content_type_duplicate_fields_and_oversized_posts_fail_closed(self):
        request = self.prepare()
        form = self.form(request)
        response = self.browser.post(request['approval_url'], json=form, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 400)
        response = self.browser.post(request['approval_url'], content='x=' + 'a' * 2048,
                                     headers={'Origin': ORIGIN, 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 413)
        from urllib.parse import urlencode
        response = self.browser.post(request['approval_url'], content=urlencode(form) + '&decision=deny',
                                     headers={'Origin': ORIGIN, 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.stores['upload'].path(request['approval_id'], 'pending').exists())
        self.factory.assert_not_called()

    def test_origin_and_auth_configuration_fail_closed(self):
        for value in ('http://garmin.private.test', 'https://user:password@host', 'https://host/path',
                      'https://host?token=secret', 'https://host#fragment', 'https://host\n', 'https://host:bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                approval_origin(value)
        self.assertEqual(approval_origin(ORIGIN + '/'), ORIGIN)
        with self.assertRaises(ValueError):
            password_record('short')
        file = self.root / 'auth.json'
        file.write_text(json.dumps(self.auth))
        file.chmod(0o600)
        self.assertEqual(load_auth(file), self.auth)
        file.chmod(0o644)
        with self.assertRaises(ValueError):
            load_auth(file)
        with self.assertRaises(ValueError):
            browser_stores(Path(__file__).resolve().parents[1] / 'private-state')


class BrowserProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_cannot_approve_its_own_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            stores = browser_stores(directory)
            factory = Mock()
            tools = GarminTools(factory, approvals=stores['upload'], schedule_approvals=stores['schedule'],
                                enable_uploads=True, enable_scheduling=True, browser_approval_origin=ORIGIN)
            async with Client(create_server(tools), read_timeout_seconds=5) as client:
                names = {t.name for t in (await client.list_tools()).tools}
                self.assertEqual(len(names), 6)
                self.assertFalse(any('approve' in name for name in names))
                result = await client.call_tool('upload_running_workout', {'workout': example_workout(), 'approval_id': None})
                self.assertEqual(result.structured_content['status'], 'approval_required')
                request_id = result.structured_content['approval_id']
                pending = await client.call_tool('upload_running_workout', {'workout': example_workout(), 'approval_id': request_id})
                self.assertEqual(pending.structured_content['error']['code'], 'approval_required')
                self.assertFalse(stores['upload'].path(request_id, 'approved').exists())
                forged = await client.call_tool('upload_running_workout', {'workout': example_workout(), 'approval_id': request_id, 'approved': True})
                self.assertTrue(forged.is_error or forged.structured_content['error']['code'] == 'approval_required')
            factory.assert_not_called()

    async def test_real_stdio_browser_launcher_from_another_directory(self):
        # A real offline process: no reads, writes or real approval state creation.
        root = Path(__file__).resolve().parents[1]
        async with asyncio.timeout(15):
            params = StdioServerParameters(command=sys.executable,
                args=[str(root / 'scripts/run_mcp.py'), '--approval-mode', 'browser', '--approval-origin', ORIGIN], cwd='/tmp')
            async with Client(params, read_timeout_seconds=5) as client:
                self.assertEqual(len((await client.list_tools()).tools), 6)
                result = await client.call_tool('build_running_workout', {'name': 'Offline browser integration', 'steps': [{'kind': 'interval', 'duration_seconds': 60}]})
                self.assertTrue(result.structured_content['ok'])
                disabled = await client.call_tool('upload_running_workout', {'workout': result.structured_content['workout']})
                self.assertEqual(disabled.structured_content['error']['code'], 'uploads_disabled')
