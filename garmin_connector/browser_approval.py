"""Private single-owner approval portal, independent of ChatGPT/model consent.

MCP may return review URLs, but cannot authenticate to this portal or approve.
Run behind private HTTPS (e.g. a tailnet reverse proxy), never public ingress.
"""
from .diagnostics import event
import argparse
import base64
from collections import deque
from getpass import getpass
from datetime import datetime, timezone
import hashlib
import hmac
from html import escape
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from .approvals import ApprovalStore, outside_project
from .scheduling import ScheduleApprovalStore
from .combined import CombinedApprovalStore

DEFAULT_STATE = '~/.local/state/garmin-connector/approvals'
DEFAULT_AUTH = '~/.config/garmin-connector/browser-auth.json'


def approval_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError('approval origin must be an HTTPS origin without path, credentials, query or fragment')
    # Accessing port also rejects malformed port values.
    parsed.port
    return value.rstrip('/')


def browser_stores(state_root=DEFAULT_STATE):
    root = outside_project(state_root)
    return {
        'upload': ApprovalStore(root / 'browser' / 'upload'),
        'upload-and-schedule': CombinedApprovalStore(root / 'browser' / 'combined'),
        # Use the legacy ledger too, so changing approval mode cannot bypass it.
        'schedule': ScheduleApprovalStore(root / 'browser' / 'schedule', attempt_directory=root / 'scheduling'),
    }


def password_record(password):
    if not isinstance(password, str) or len(password) < 20:
        raise ValueError('use a unique password of at least 20 characters')
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return {'salt': salt.hex(), 'digest': digest.hex()}


def load_auth(path):
    path = outside_project(path)
    if path.stat().st_mode & 0o077:
        raise ValueError('browser auth file must have mode 600')
    record = json.loads(path.read_text())
    if set(record) != {'salt', 'digest'} or len(bytes.fromhex(record['salt'])) != 32 or len(bytes.fromhex(record['digest'])) != 64:
        raise ValueError('invalid browser auth file')
    return record


def workout_summary(payload):
    """Plain text from validated payload, never interpolate unescaped HTML."""
    lines = [payload['workoutName']]

    def visit(steps, indent=''):
        for step in steps:
            if step['type'] == 'RepeatGroupDTO':
                lines.append(f"{indent}Repeat {step['numberOfIterations']} times (including final recovery):")
                visit(step['workoutSteps'], indent + '  ')
                continue
            value = step['endConditionValue']
            unit = 'seconds' if step['endCondition']['conditionTypeKey'] == 'time' else 'metres'
            target = step['targetType']['workoutTargetTypeKey']
            detail = 'no target'
            if target == 'pace.zone':
                pace = 1000 / step['targetValueOne']
                detail = f'{pace:g} seconds/km'
            elif target == 'heart.rate.zone':
                detail = f"HR zone {step['zoneNumber']}" if 'zoneNumber' in step else f"HR {step['targetValueOne']:g}–{step['targetValueTwo']:g} BPM"
            lines.append(f"{indent}{step['stepType']['stepTypeKey']}: {value:g} {unit}, {detail}")

    visit(payload['workoutSegments'][0]['workoutSteps'])
    def totals(steps):
        distance, duration, all_distance, all_time = 0, 0, True, True
        for step in steps:
            if step['type'] == 'RepeatGroupDTO':
                d, t, ad, at = totals(step['workoutSteps'])
                count = step['numberOfIterations']
                distance += d * count
                duration += t * count
                all_distance &= ad
                all_time &= at
            elif step['endCondition']['conditionTypeKey'] == 'distance':
                distance += step['endConditionValue']
                all_time = False
            else:
                duration += step['endConditionValue']
                all_distance = False
        return distance, duration, all_distance, all_time

    d, t, ad, at = totals(payload['workoutSegments'][0]['workoutSteps'])
    lines.append(f"{'Total distance' if ad else 'Known distance subtotal'}: {d:g} metres")
    lines.append(f"{'Total duration' if at else 'Known duration subtotal'}: {t:g} seconds")
    if not ad or not at:
        lines.append('Full distance/duration cannot both be calculated; pace targets are not measured duration.')
    return '\n'.join(lines)


def create_approval_app(origin, auth_record, stores=None, *, clock=time.monotonic):
    """Only a successful authenticated, same-origin, CSRF-bound POST grants consent."""
    origin = approval_origin(origin)
    stores = stores if stores is not None else browser_stores()
    csrf_key = secrets.token_bytes(32)  # Restart invalidates rendered forms, not approvals.
    failed_logins = deque()
    headers = {
        'Cache-Control': 'no-store', 'Pragma': 'no-cache',
        'Content-Security-Policy': "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        'Strict-Transport-Security': 'max-age=31536000',
    }

    def csrf(operation, request_id, record):
        data = f"{operation}:{request_id}:{record['sha256']}:{record['expires_at']}".encode()
        return hmac.new(csrf_key, data, hashlib.sha256).hexdigest()

    def authorized(request):
        now = clock()
        while failed_logins and now - failed_logins[0] >= 60:
            failed_logins.popleft()
        if len(failed_logins) >= 10:
            return False
        try:
            scheme, encoded = request.headers.get('authorization', '').split(' ', 1)
            if scheme.lower() != 'basic' or len(encoded) > 2048:
                raise ValueError('invalid authorization')
            username, password = base64.b64decode(encoded, validate=True).decode().split(':', 1)
            digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(auth_record['salt']), n=16384, r=8, p=1).hex()
            if hmac.compare_digest(username, 'owner') and hmac.compare_digest(digest, auth_record['digest']):
                return True
        except (ValueError, UnicodeError, TypeError):
            pass
        # A normal unauthenticated browser challenge should not spend the limit.
        if request.headers.get('authorization'):
            failed_logins.append(now)
            event("portal", "authentication_failed")
        return False

    async def review(request: Request):
        if not authorized(request):
            return Response('Authentication required.', status_code=401,
                            headers={**headers, 'WWW-Authenticate': 'Basic realm="Garmin workout approval", charset="UTF-8"'})
        # Do not trust forwarded headers or a caller-supplied Host for links/CSRF.
        if request.headers.get('host') != urlsplit(origin).netloc:
            event('portal', 'approval_error')
            return Response('Invalid host.', status_code=400, headers=headers)
        operation = request.path_params['operation']
        request_id = request.path_params['request_id']
        store = stores.get(operation)
        if store is None:
            return Response('Not found.', status_code=404, headers=headers)
        try:
            record = store.read(request_id, 'pending')
            if request.method == 'POST':
                if request.headers.get('origin') != origin:
                    event('portal', 'approval_error')
                    return Response('Invalid origin.', status_code=403, headers=headers)
                if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                    event('portal', 'approval_error')
                    return Response('Invalid form.', status_code=400, headers=headers)
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 2048:
                        event('portal', 'approval_error')
                        return Response('Form too large.', status_code=413, headers=headers)
                form = parse_qs(body.decode(), strict_parsing=True)
                if (set(form) != {'csrf', 'sha256', 'decision'} or any(len(values) != 1 for values in form.values())
                        or form['decision'][0] not in ('approve', 'deny')
                        or not hmac.compare_digest(form['csrf'][0], csrf(operation, request_id, record))):
                    event('portal', 'approval_error')
                    return Response('Invalid confirmation.', status_code=403, headers=headers)
                store._review_decision(request_id, form['sha256'][0], approve=form['decision'][0] == 'approve')
                message = 'Approved for one attempt before the original expiry.' if form['decision'][0] == 'approve' else 'Denied. No Garmin change authorized.'
                return HTMLResponse(f'<h1>{message}</h1><p>Return to ChatGPT and ask it to continue. Do not create a new request.</p>', headers=headers)
            payload = record['payload']
            if operation == 'upload-and-schedule':
                summary = ('Approve BOTH upload of a NEW workout AND calendar scheduling on '
                           + payload['date'] + ':\n' + workout_summary(payload['workout'])
                           + '\nResumption reuses durable progress; it never uploads twice. '
                           'After expiry fresh browser consent is required. Unknown writes require reconciliation.')
            elif operation == 'upload':
                summary = 'Create a NEW Garmin workout:\n' + workout_summary(payload)
            else:
                summary = f"Schedule existing workout {payload['workout_id']} on {payload['date']} (calendar date)."
            expiry = datetime.fromtimestamp(record['expires_at'], timezone.utc).isoformat()
            content = (f'<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
                       f'<title>Review Garmin change</title></head><body><h1>Review Garmin change</h1>'
                       f'<pre>{escape(summary)}</pre><p>Expires {expiry} (UTC). '
                       f'Approval expires ten minutes after request creation. Review all details below.</p>'
                       f'<details><summary>Exact payload and SHA256</summary><pre>{escape(json.dumps(payload, indent=2))}</pre>'
                       f'<code>{record["sha256"]}</code></details><form method="post">'
                       f'<input type="hidden" name="csrf" value="{csrf(operation, request_id, record)}">'
                       f'<input type="hidden" name="sha256" value="{record["sha256"]}">'
                       f'<button type="submit" name="decision" value="approve">Approve this {operation}</button> '
                       f'<button type="submit" name="decision" value="deny">Deny</button></form>'
                       f'<p>This page grants consent only. ChatGPT must continue the operation; no Garmin API is called here.</p></body></html>')
            return HTMLResponse(content, headers=headers)
        except (ValueError, OSError, KeyError, TypeError, UnicodeError):
            event('portal', 'approval_error')
            return Response('Request unavailable, expired, changed or already reviewed.', status_code=409, headers=headers)

    return Starlette(routes=[Route('/review/{operation}/{request_id}', review, methods=['GET', 'POST'])])


def main():
    parser = argparse.ArgumentParser(description='Private HTTPS-backed browser approval for Garmin Connector')
    parser.add_argument('--setup', action='store_true', help='Create local password hash interactively; no network')
    parser.add_argument('--auth-file', default=DEFAULT_AUTH)
    parser.add_argument('--origin', help='Private HTTPS origin used by your browser, e.g. https://garmin.example.ts.net')
    parser.add_argument('--port', type=int, default=8788)
    args = parser.parse_args()
    try:
        if args.setup:
            if not __import__('sys').stdin.isatty():
                raise ValueError('setup requires a human terminal')
            password = getpass('New approval password (20+ characters; never your Garmin password): ')
            if getpass('Repeat approval password: ') != password:
                raise ValueError('passwords do not match')
            record = password_record(password)
            path = outside_project(args.auth_file)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                json.dump(record, stream)
            print('Approval password hash created. Browser username: owner. Password was not saved.')
            return
        if not args.origin:
            raise ValueError('--origin is required')
        app = create_approval_app(args.origin, load_auth(args.auth_file))
    except (ValueError, OSError, KeyError, TypeError):
        parser.error('Invalid or unavailable approval configuration. Use --setup once; require a private HTTPS origin and mode-600 auth file.')
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=args.port, proxy_headers=False, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
