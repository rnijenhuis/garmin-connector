"""Diagnostic output is an enum-only record, never exception/input serialization."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from garmin_connector import diagnostics
from garmin_connector.mcp_tools import GarminTools
from garmin_connector.workouts import example_workout


class DiagnosticTests(unittest.TestCase):
    def test_failure_logging_cannot_leak_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GARMIN_DIAGNOSTICS': '1'}), patch.object(diagnostics, 'directory', return_value=Path(tmp)):
            def fail():
                raise RuntimeError('API_KEY SESSION_TOKEN PASSWORD APPROVAL_SECRET')
            tool = GarminTools(client_factory=fail)
            self.assertFalse(tool.get_recent_activities()['ok'])
            diagnostics.event('API_KEY', 'success')
            diagnostics.event('runtime', 'SESSION_TOKEN')
            text = (Path(tmp) / 'diagnostics.jsonl').read_text()
            for secret in ('API_KEY', 'SESSION_TOKEN', 'PASSWORD', 'APPROVAL_SECRET'):
                self.assertNotIn(secret, text)
            value = json.loads(text)
            self.assertEqual(set(value), {'pid', 'time', 'operation', 'outcome'})
            self.assertEqual(value['outcome'], 'garmin_api_error')

    def test_diagnostics_failure_does_not_change_tool_result(self):
        with patch.dict(os.environ, {'GARMIN_DIAGNOSTICS': '1'}), patch.object(diagnostics, 'directory', side_effect=OSError('secret')):
            self.assertTrue(GarminTools().build_running_workout('offline', [{'kind': 'interval', 'distance_m': 1000}])['ok'])

    def test_symlink_and_permissive_logs_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GARMIN_DIAGNOSTICS': '1'}), patch.object(diagnostics, 'directory', return_value=Path(tmp)):
            target = Path(tmp) / 'private'
            target.write_text('unchanged')
            log = Path(tmp) / 'diagnostics.jsonl'
            log.symlink_to(target)
            diagnostics.event('runtime', 'tunnel_disconnected')
            self.assertEqual(target.read_text(), 'unchanged')
            log.unlink()
            log.write_text('unchanged')
            log.chmod(0o644)
            diagnostics.event('runtime', 'tunnel_disconnected')
            self.assertEqual(log.read_text(), 'unchanged')

    def test_upload_auth_approval_and_unknown_outcome_are_logged_without_retry(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'GARMIN_DIAGNOSTICS': '1'}), patch.object(diagnostics, 'directory', return_value=Path(tmp)):
            approvals = Mock()
            api = Mock()
            factory = Mock(return_value=api)
            tool = GarminTools(client_factory=factory, approvals=approvals, enable_uploads=True)
            payload = example_workout()
            approvals.consume.side_effect = ValueError('approval-secret')
            self.assertFalse(tool.upload_running_workout(payload, 'private-id')['ok'])
            factory.assert_not_called()
            approvals.consume.side_effect = None
            factory.side_effect = RuntimeError('credential-secret')
            self.assertFalse(tool.upload_running_workout(payload, 'private-id')['ok'])
            api.upload_workout.assert_not_called()
            factory.side_effect = None
            api.upload_workout.side_effect = RuntimeError('token-secret')
            result = tool.upload_running_workout(payload, 'private-id')
            self.assertEqual(result['error']['code'], 'upload_outcome_unknown')
            api.upload_workout.assert_called_once()
            text = (Path(tmp) / 'diagnostics.jsonl').read_text()
            self.assertEqual([json.loads(line)['outcome'] for line in text.splitlines()],
                             ['approval_error', 'authentication_required', 'upload_outcome_unknown'])
            for secret in ('approval-secret', 'credential-secret', 'token-secret', 'private-id', payload['workoutName']):
                self.assertNotIn(secret, text)
