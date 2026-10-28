"""Offline preview, read-only activity reports and confirmed workout creation."""
import argparse
import json
import os
from getpass import getpass
from .activities import latest_activity_report
from .client import connect
from .workouts import example_workout
from .upload import TEST_WORKOUT_NAME, upload_interactively


def authenticate():
    email = os.getenv('GARMIN_EMAIL') or input('Garmin e-mail: ')
    password = getpass('Garmin password (empty for existing session): ')
    return connect(email, password, prompt_mfa=lambda: input('Garmin MFA code: '))


def show_activities():
    client = authenticate()
    print(json.dumps(latest_activity_report(client), indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='Garmin reads and offline workout preview')
    parser.add_argument('command', nargs='?', choices=['preview', 'activities', 'upload'], default='preview')
    args = parser.parse_args()
    if args.command == 'activities':
        show_activities()
    elif args.command == 'upload':
        payload = example_workout()
        payload['workoutName'] = TEST_WORKOUT_NAME
        raise SystemExit(upload_interactively(payload, authenticate))
    else:
        print(json.dumps(example_workout(), indent=2))
