import importlib
import json
import unittest
from unittest.mock import Mock, patch
from garmin_connector.activities import latest_activity_report, recent_activities
from garmin_connector.client import connect
from garmin_connector.workouts import RunningStep, build_running_workout, example_workout


class ActivityTests(unittest.TestCase):
    def test_empty_responses_never_fetch_details(self):
        for response in ([], None):
            with self.subTest(response=response):
                api = Mock()
                api.get_activities.return_value = response
                self.assertEqual(latest_activity_report(api),
                                 {'activities': [], 'details': None, 'laps': None})
                api.get_activity.assert_not_called()
                api.get_activity_splits.assert_not_called()

    def test_details_and_laps_fetched_once(self):
        api = Mock()
        api.get_activities.return_value = [{'activityId': 42, 'activityName': 'Run',
                                           'distance': 1234, 'averageHR': 140}]
        api.get_activity.return_value = {'activityName': 'Run'}
        api.get_activity_splits.return_value = {'lapDTOs': [{'distance': 1000}]}
        report = latest_activity_report(api)
        self.assertEqual(report['activities'][0]['distance_km'], 1.23)
        self.assertEqual(report['details'], {'activityName': 'Run'})
        self.assertEqual(report['laps'], api.get_activity_splits.return_value)
        api.get_activities.assert_called_once_with(0, 5)
        api.get_activity.assert_called_once_with(42)
        api.get_activity_splits.assert_called_once_with(42)

    def test_missing_fields(self):
        api = Mock()
        api.get_activities.return_value = [{'distance': None}]
        report = latest_activity_report(api)
        self.assertEqual(report['activities'][0]['distance_km'], 0)
        api.get_activity.assert_not_called()
        api.get_activity_splits.assert_not_called()

    def test_bad_limit(self):
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                recent_activities(Mock(), limit)

    @patch('garminconnect.Garmin')
    def test_authentication_is_injected_and_mocked(self, factory):
        callback = Mock()
        self.assertIs(connect('user', 'password', token_dir='/tmp/tokens',
                              prompt_mfa=callback), factory.return_value)
        factory.assert_called_once_with('user', 'password', prompt_mfa=callback)
        factory.return_value.login.assert_called_once_with('/tmp/tokens')

    @patch('garminconnect.Garmin')
    def test_smoke_module_import_has_no_api_side_effects(self, factory):
        importlib.import_module('test_garmin')
        factory.assert_not_called()


class WorkoutTests(unittest.TestCase):
    def test_requested_workout(self):
        workout = json.loads(json.dumps(example_workout(), allow_nan=False))
        steps = workout['workoutSegments'][0]['workoutSteps']
        self.assertEqual(workout['sportType']['sportTypeKey'], 'running')
        self.assertEqual([s['stepOrder'] for s in steps], list(range(1, 8)))
        self.assertEqual([s['stepType']['stepTypeKey'] for s in steps],
                         ['warmup', 'interval', 'recovery', 'interval', 'recovery', 'interval', 'cooldown'])
        self.assertEqual([s['endConditionValue'] for s in steps],
                         [2000, 1000, 500, 1000, 500, 1000, 1000])
        self.assertEqual(sum(s['endConditionValue'] for s in steps), 7000)
        for step in steps:
            self.assertEqual(step['endCondition']['conditionTypeKey'], 'distance')
            if step['stepType']['stepTypeKey'] == 'interval':
                self.assertEqual(step['targetType']['workoutTargetTypeId'], 6)
                self.assertAlmostEqual(step['targetValueOne'], 1000 / 300)
                self.assertEqual(step['targetValueOne'], step['targetValueTwo'])
            else:
                self.assertEqual(step['targetType']['workoutTargetTypeKey'], 'no.target')

    def test_invalid_inputs(self):
        for value in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_running_workout('test', [RunningStep('interval', value)])
                with self.assertRaises(ValueError):
                    build_running_workout('test', [RunningStep('interval', 1000, value)])
        for name, steps in [('', [RunningStep('warmup', 100)]), ('test', []),
                            ('test', [RunningStep('bad', 100)])]:
            with self.assertRaises(ValueError):
                build_running_workout(name, steps)

    def test_builds_are_independent(self):
        first = example_workout()
        first['workoutSegments'][0]['workoutSteps'].clear()
        self.assertEqual(len(example_workout()['workoutSegments'][0]['workoutSteps']), 7)


if __name__ == '__main__':
    unittest.main()
