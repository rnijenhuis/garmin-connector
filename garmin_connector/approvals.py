"""Local human approval, separate from MCP. Files contain workouts, never tokens."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
from .upload import validate_workout

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def outside_project(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents:
        raise ValueError('state and token directories must be outside the project')
    return resolved


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class ApprovalStore:
    """One-use, exact-payload approvals; trusted local user owns this directory."""
    def __init__(self, directory=None, clock=time.time):
        self.directory = outside_project(directory or '~/.local/state/garmin-connector/approvals')
        self.clock = clock

    validate_payload = staticmethod(validate_workout)
    confirmation_word = "UPLOAD"
    confirmation_prompt = "Approve creation of this exact workout? Type UPLOAD: "

    def path(self, request_id, suffix):
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{32}', request_id):
            raise ValueError('invalid approval ID')
        return self.directory / f'{request_id}.{suffix}.json'

    def request(self, payload):
        self.validate_payload(payload)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        request_id = secrets.token_hex(16)
        record = {'payload': payload, 'sha256': fingerprint(payload),
                  'expires_at': self.clock() + 600}
        path = self.path(request_id, 'pending')
        with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(record, stream, allow_nan=False)
        return request_id

    def read(self, request_id, suffix):
        try:
            record = json.loads(self.path(request_id, suffix).read_text())
            self.validate_payload(record['payload'])
            if self.clock() >= record['expires_at'] or fingerprint(record['payload']) != record['sha256']:
                raise ValueError('approval expired or payload changed')
            return record
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('approval unavailable or invalid') from exc

    def approve_interactively(self, request_id):
        record = self.read(request_id, 'pending')
        print(json.dumps(record['payload'], indent=2))
        print('SHA256:', record['sha256'])
        if not sys.stdin.isatty():
            raise ValueError('approval requires an interactive terminal')
        if input(self.confirmation_prompt) != self.confirmation_word:
            print('Approval cancelled.')
            return False
        # Re-read after user input to detect expiry or changes during review.
        if self.read(request_id, 'pending') != record:
            raise ValueError('request changed during review')
        self.path(request_id, 'pending').rename(self.path(request_id, 'approved'))
        print('Approved for one attempt before the original ten-minute expiry.')
        return True

    def _review_decision(self, request_id, reviewed_sha256, *, approve):
        """Trusted terminal/browser callers only; never expose as an MCP tool.

        Recheck the original expiry and reviewed digest immediately before the
        atomic transition. Knowing an ID/hash is not authorization to call this.
        """
        record = self.read(request_id, 'pending')
        if not isinstance(reviewed_sha256, str) or not secrets.compare_digest(record['sha256'], reviewed_sha256):
            raise ValueError('review does not match pending payload')
        self.path(request_id, 'pending').rename(self.path(request_id, 'approved' if approve else 'denied'))

    def consume(self, request_id, payload):
        record = self.read(request_id, 'approved')
        if fingerprint(payload) != record['sha256']:
            raise ValueError('approval does not match this workout')
        try:
            # Atomic rename: only one caller/process can claim an approval.
            self.path(request_id, 'approved').rename(self.path(request_id, 'consumed'))
        except OSError as exc:
            raise ValueError('approval already consumed or unavailable') from exc


def main():
    parser = argparse.ArgumentParser(description='Review and approve one MCP workout request')
    parser.add_argument('request_id')
    parser.add_argument('--schedule', action='store_true', help='Review a scheduling request; requires SCHEDULE')
    args = parser.parse_args()
    try:
        if args.schedule:
            from .scheduling import ScheduleApprovalStore
            store = ScheduleApprovalStore()
        else:
            store = ApprovalStore()
        store.approve_interactively(args.request_id)
    except (ValueError, OSError, EOFError, KeyboardInterrupt):
        print('Approval failed or cancelled; no Garmin operation was performed.', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
