"""Linux lifecycle helper for the Bash entry points; never handles approval state."""
from datetime import datetime, timezone
import math
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

ORIGIN = 'https://robert-pc.tail8c36bd.ts.net'
ORGANIZATION = 'org-9ENwHB5TGd84UsFzcKujMFas'
BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def identity(pid):
    try:
        p = Path('/proc') / str(pid)
        fields = (p / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z' or p.stat().st_uid != os.getuid():
            return None
        return {'pid': pid, 'start': fields[19], 'boot': BOOT,
                'command': hashlib.sha256((p / 'cmdline').read_bytes()).hexdigest()}
    except (OSError, ValueError):
        return None


def record(path):
    try:
        value = json.loads(path.read_text())
        pid = value['pid']
        if type(pid) is not int or pid <= 1:
            return None
        return value if identity(pid) == value else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def stop(path, timeout=5):
    value = record(path)
    if value:
        try:
            fd = os.pidfd_open(value['pid'])
        except ProcessLookupError:
            fd = None
        if fd is not None:
            try:
                # Recheck after opening: the descriptor pins the process, never a reused PID.
                if identity(value['pid']) == value:
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                    if not select.select([fd], [], [], timeout)[0]:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                        if not select.select([fd], [], [], 2)[0]:
                            raise RuntimeError('Proces stopt niet; PID-record behouden.')
            except ProcessLookupError:
                pass
            finally:
                os.close(fd)
    path.unlink(missing_ok=True)


def http(url):
    # No proxy, credentials, redirects, response bodies, or disabled TLS verification.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(url, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, urllib.error.URLError):
        return None


def tailscale():
    def query(*args):
        result = subprocess.run(['tailscale', *args], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=5, check=True)
        return json.loads(result.stdout)
    try:
        connected = query('status', '--json').get('BackendState') == 'Running'
        config = query('serve', 'status', '--json')
        endpoint = ORIGIN.removeprefix('https://') + ':443'
        route = config.get('Web', {}).get(endpoint, {}).get('Handlers', {}).get('/', {})
        valid = (route.get('Proxy') == 'http://127.0.0.1:8788'
                 and config.get('TCP', {}).get('443', {}).get('HTTPS') is True
                 and not any(config.get('AllowFunnel', {}).values()))
        return connected, valid
    except (OSError, ValueError, AttributeError, TypeError, subprocess.SubprocessError):
        return False, False


def unmanaged_process(name):
    """Refuse identifiable pre-existing instances, including ones still binding."""
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            if name == 'tunnel':
                match = (b'run' in args and b'garmin-plus' in args
                         and any(Path(os.fsdecode(arg)).name == 'tunnel-client' for arg in args if arg))
            else:
                match = b'garmin_connector.browser_approval' in args
            if match and identity(int(entry.name)):
                return True
        except OSError:
            continue
    return False


def free_port(port):
    try:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    except OSError:
        raise RuntimeError(f'Poort {port} is bezet; bestaande dienst wordt niet overgenomen.') from None


def state_directory():
    # Fixed private per-user location; reject symlinks and permissive existing directories.
    parent = Path.home() / '.local' / 'state'
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = parent / 'garmin-connector-runtime'
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('Onveilige runtime-directory; verwacht eigen directory met mode 700.')
    return path


def launch(command, env, path, root):
    child = subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
    # Popen returns after exec; /proc identity therefore describes the actual command.
    value = identity(child.pid)
    if value is None:
        raise RuntimeError('Proces is direct gestopt; controleer configuratie.')
    try:
        with path.open('x') as stream:
            json.dump(value, stream)
    except BaseException:
        child.terminate()
        child.wait(timeout=5)
        raise
    return child


def start(root, state):
    for dependency in ('tunnel-client', 'tailscale'):
        if not shutil.which(dependency):
            raise RuntimeError(f'Ontbrekende afhankelijkheid: {dependency}.')
    python = root / '.venv/bin/python'
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError('Python-omgeving ontbreekt: .venv/bin/python.')
    connected, route = tailscale()
    if not connected or not route:
        raise RuntimeError('Tailscale niet verbonden of private HTTPS Serve-route onjuist; niets gewijzigd.')
    specs = [('approval', [str(python), '-m', 'garmin_connector.browser_approval',
                           '--origin', ORIGIN, '--port', '8788'], 8788),
             ('tunnel', [shutil.which('tunnel-client'), 'run', '--profile', 'garmin-plus'], 8080)]
    missing = [spec for spec in specs if not record(state / (spec[0] + '.pid'))]
    if not missing:
        if http('http://127.0.0.1:8080/readyz') != 200 or http('http://127.0.0.1:8788/') != 404:
            raise RuntimeError('Bestaande processen reageren niet; gebruik status en stop voor herstel.')
        print('Beide beheerde processen draaien al.')
        return
    for name, command, port in missing:
        if unmanaged_process(name):
            raise RuntimeError(f'Onbeheerd {name}-proces gevonden; stop dat via zijn eigen beheer.')
        free_port(port)
    env = dict(os.environ)
    env['GARMIN_DIAGNOSTICS'] = '1'
    key = env.pop('CONTROL_PLANE_API_KEY', '') or env.pop('OPENAI_API_KEY', '')
    env.pop('OPENAI_API_KEY', None)
    if any(spec[0] == 'tunnel' for spec in missing) and not key:
        if not sys.stdin.isatty():
            raise RuntimeError('OpenAI API-key ontbreekt; start interactief of exporteer de runtime-key veilig.')
        key = getpass.getpass('OpenAI API-key (verborgen): ')
        if not key:
            raise RuntimeError('OpenAI API-key ontbreekt.')
    created, children = [], []
    try:
        for name, command, port in missing:
            path = state / (name + '.pid')
            path.unlink(missing_ok=True)
            child_env = dict(env)
            if name == 'tunnel':
                child_env['CONTROL_PLANE_API_KEY'] = key
                child_env['CONTROL_PLANE_ORGANIZATION_ID'] = ORGANIZATION
                child_env['LOG_FILE'] = '/dev/null'
                child_env['LOG_HTTP_RAW_UNSAFE'] = 'false'
            children.append(launch(command, child_env, path, root))
            created.append(path)
        deadline = time.monotonic() + 15
        stable = None
        while time.monotonic() < deadline:
            if any(c.poll() is not None for c in children):
                raise RuntimeError('Onderdeel direct gestopt; controleer profiel of browserwachtwoordconfiguratie.')
            if not all(record(state / (name + '.pid')) for name, _, _ in specs):
                raise RuntimeError('Onderdeel onverwacht gestopt.')
            ready = http('http://127.0.0.1:8080/readyz') == 200 and http('http://127.0.0.1:8788/') == 404
            if ready:
                stable = stable or time.monotonic()
                if time.monotonic() - stable >= 2:
                    if http(ORIGIN + '/') != 404:
                        raise RuntimeError('HTTPS-route niet bereikbaar met de verwachte portalrespons.')
                    print('Garmin Connector lokaal gestart. OpenAI/ChatGPT-verbinding nog niet bevestigd.')
                    return
            else:
                stable = None
            time.sleep(0.2)
        raise RuntimeError('Starttimeout: lokale diensten worden niet gereed.')
    except BaseException:
        for path in reversed(created):
            stop(path)
        raise


def health_details():
    """Bounded, no-proxy/no-redirect local read; never print/store raw health JSON."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open('http://127.0.0.1:8080/health?details=true', timeout=2) as response:
            if response.status != 200:
                return None
            body = response.read(65537)
            return json.loads(body) if len(body) <= 65536 else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def age(value, now):
    try:
        timestamp = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        result = now - timestamp
        return result if math.isfinite(result) and result >= -5 else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def tunnel_evidence(data, now=None):
    """v0.0.19 schema 1, observed with an isolated mock control plane.

    A successful poll proves only recent control-plane access, not response delivery
    or ChatGPT functionality. Unknown/partial schemas never pass.
    """
    now = time.time() if now is None else now
    try:
        if data['schema_version'] != 1:
            return 'UNKNOWN', 'UNKNOWN'
        snapshot = age(data['snapshot_at'], now)
        if snapshot is None:
            return 'UNKNOWN', 'UNKNOWN'
        if snapshot > 15:
            return 'STALE', 'UNKNOWN'
        component = data['components']['control-plane']
        details = component['details']
        if details.get('http_status') in (401, 403):
            return 'AUTH_FAILED', 'UNKNOWN'
        failures = details['consecutive_failures']
        if type(failures) is not int or failures < 0:
            return 'UNKNOWN', 'UNKNOWN'
        if failures > 0 or component['state'] == 'backoff':
            return 'DISCONNECTED', 'UNKNOWN'
        success_age = age(details.get('last_success'), now)
        # Fixed upper bound avoids trusting an arbitrary server-provided deadline.
        if success_age is None:
            transport = 'UNKNOWN'
        elif success_age > 90:
            transport = 'STALE'
        elif component['status'] == 'ok' and component['state'] == 'polling':
            transport = 'RECENT_POLL_SUCCESS'
        else:
            transport = 'UNKNOWN'
        mcp = data['components'].get('mcp', {})
        md = mcp.get('details', {})
        observed_age = age(mcp.get('observed_at'), now)
        discovery = ('RECENT_DISCOVERY_OBSERVED' if mcp.get('status') == 'ok'
                     and observed_age is not None and observed_age <= 90
                     and md.get('initialize', {}).get('ok') is True
                     and md.get('tools_list', {}).get('ok') is True
                     and md.get('tools_list', {}).get('complete') is True
                     and not mcp.get('limited', True) else 'UNVERIFIED')
        return transport, discovery
    except (KeyError, TypeError, AttributeError):
        return 'UNKNOWN', 'UNKNOWN'


def owns_listener(value, port):
    """Correlate the health listener with the pinned managed process, not any HTTP server."""
    if value is None:
        return False
    try:
        inodes = set()
        for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == f'0100007F:{port:04X}' and fields[3] == '0A':
                inodes.add('socket:[' + fields[9] + ']')
        descriptors = Path('/proc') / str(value['pid']) / 'fd'
        return (any(os.readlink(fd) in inodes for fd in descriptors.iterdir())
                and identity(value['pid']) == value)
    except OSError:
        return False


def status(state):
    connected, route = tailscale()
    tunnel = record(state / 'tunnel.pid')
    approval = record(state / 'approval.pid')
    tunnel_owned = owns_listener(tunnel, 8080)
    approval_owned = owns_listener(approval, 8788)
    local = tunnel_owned and http('http://127.0.0.1:8080/readyz') == 200
    portal = approval_owned and http('http://127.0.0.1:8788/') == 404
    https = portal and connected and route and http(ORIGIN + '/') == 404
    transport, discovery = tunnel_evidence(health_details()) if tunnel_owned else ('UNKNOWN', 'UNKNOWN')
    print('Garmin Connector Status\n-----------------------')
    for label, value in (
        ('Tunnel process', 'RUNNING' if tunnel else 'STOPPED/UNMANAGED'),
        ('Approval process', 'RUNNING' if approval else 'STOPPED/UNMANAGED'),
        ('Tailscale daemon', 'RUNNING' if connected else 'UNAVAILABLE'),
        ('Tunnel local HTTP', 'STARTUP_READY' if local else 'FAILED/UNATTRIBUTED'),
        ('Approval local HTTP', 'EXPECTED_ROOT_404' if portal else 'FAILED/UNATTRIBUTED'),
        ('Private HTTPS route', 'EXPECTED_ROOT_404' if https else 'FAILED'),
        ('Tunnel control plane', transport),
        ('MCP discovery', discovery),
        ('Garmin authentication', 'UNVERIFIED (use get_recent_activities from ChatGPT; no login probe)'),
        ('End-to-end MCP', 'UNVERIFIED (call offline build_running_workout from ChatGPT)')):
        print(f'{label + ":":24} {value}')
    from garmin_connector.diagnostics import event
    outcome = {'RECENT_POLL_SUCCESS': 'tunnel_recent', 'STALE': 'tunnel_stale',
               'DISCONNECTED': 'tunnel_disconnected', 'AUTH_FAILED': 'authentication_failed'}.get(transport, 'tunnel_unknown')
    event('runtime', outcome)
    print('Diagnostics: fixed event codes only; diagnostics.jsonl in private runtime state.')
    # Never present incomplete verification as a green overall health result.
    if not (tunnel and approval and local and portal and https) or transport in ('STALE', 'DISCONNECTED', 'AUTH_FAILED'):
        return 1
    return 2  # End-to-end/remote Garmin verification requires a user-side call.


def main():
    os.umask(0o077)
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Linux en Python 3.9+ met pidfd-ondersteuning vereist.')
    probe = os.pidfd_open(os.getpid())
    os.close(probe)
    def interrupted(signum, frame):
        raise RuntimeError('Opdracht onderbroken; nieuwe processen worden opgeruimd.')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    action, root = sys.argv[1:]
    sys.path.insert(0, str(Path(root)))
    state = state_directory()
    os.environ['GARMIN_DIAGNOSTICS'] = '1'
    fd = os.open(state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        if action == 'monitor':
            while True:
                status(state)
                time.sleep(30)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == 'start':
            start(Path(root), state)
        elif action == 'stop':
            stop(state / 'tunnel.pid')
            stop(state / 'approval.pid')
            print('Alle door het startscript beheerde processen zijn gestopt.')
        else:
            return status(state)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.SubprocessError):
        # No raw exception: third-party messages may contain secrets.
        exc = sys.exception()
        print(f'Fout: {exc}' if isinstance(exc, RuntimeError) else 'Fout: lokale proces- of bestandsoperatie mislukt.', file=sys.stderr)
        sys.exit(1)
