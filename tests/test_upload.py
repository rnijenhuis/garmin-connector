import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
from garmin_connector.upload import upload_interactively, validate_workout
from garmin_connector.workouts import example_workout


class UploadTests(unittest.TestCase):
    def run_upload(self, authenticate, answer='UPLOAD', terminal=True):
        with patch('sys.stdin.isatty', return_value=terminal), patch('builtins.input', return_value=answer), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            status = upload_interactively(example_workout(), authenticate)
        return status, out.getvalue() + err.getvalue()

    def test_valid_payload(self):
        validate_workout(example_workout())

    def test_invalid_payloads(self):
        for mutate in (lambda p: p.pop('workoutName'),
                       lambda p: p.update(workoutId=123),
                       lambda p: p['sportType'].update(sportTypeId=2),
                       lambda p: p['workoutSegments'][0]['workoutSteps'][0].update(stepOrder=9),
                       lambda p: p['workoutSegments'][0]['workoutSteps'][1].pop('targetValueTwo')):
            payload = example_workout()
            mutate(payload)
            with self.assertRaises(ValueError):
                validate_workout(payload)

    def test_cancel_without_authentication(self):
        for answer in ('', 'yes', 'upload', 'no'):
            auth = Mock()
            self.assertEqual(self.run_upload(auth, answer)[0], 0)
            auth.assert_not_called()

    def test_noninteractive_rejected(self):
        auth = Mock()
        self.assertEqual(self.run_upload(auth, terminal=False)[0], 1)
        auth.assert_not_called()

    def test_confirmation_creates_once_and_displays_response(self):
        client = Mock(spec=['upload_workout'])
        client.upload_workout.return_value = {'workoutId': 123, 'workoutName': 'Test'}
        auth = Mock(return_value=client)
        status, output = self.run_upload(auth)
        self.assertEqual(status, 0)
        self.assertIn('Garmin workout ID: 123', output)
        self.assertIn('"workoutName": "Test"', output)
        auth.assert_called_once_with()
        client.upload_workout.assert_called_once_with(example_workout())

    def test_authentication_failure(self):
        status, output = self.run_upload(Mock(side_effect=RuntimeError('secret')))
        self.assertEqual(status, 1)
        self.assertIn('No upload attempted', output)
        self.assertNotIn('secret', output)

    def test_upload_failure_not_retried(self):
        client = Mock()
        client.upload_workout.side_effect = RuntimeError('secret')
        status, output = self.run_upload(Mock(return_value=client))
        self.assertEqual(status, 1)
        client.upload_workout.assert_called_once()
        self.assertIn('before retrying', output)
        self.assertNotIn('secret', output)

    def test_missing_id_is_uncertain(self):
        client = Mock()
        client.upload_workout.return_value = {}
        self.assertEqual(self.run_upload(Mock(return_value=client))[0], 1)

    def test_interrupted_confirmation(self):
        auth = Mock()
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', side_effect=EOFError), redirect_stdout(io.StringIO()):
            self.assertEqual(upload_interactively(example_workout(), auth), 1)
        auth.assert_not_called()
