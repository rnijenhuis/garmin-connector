"""Offline lifecycle tests: no OpenAI, Tailscale or Garmin calls."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).resolve().parents[1] / 'scripts/garmin_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.python = self.root / '.venv/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.write_text('')
        self.python.chmod(0o700)
        self.state = self.root / 'state'
        self.state.mkdir()

    def child(self, ignore=False):
        code = ('import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready",flush=True); time.sleep(60)' if ignore else 'import time; print("ready",flush=True); time.sleep(60)')
        p = subprocess.Popen(['python3', '-c', code], stdout=subprocess.PIPE)
        p.stdout.readline()
        def cleanup():
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()
        self.addCleanup(cleanup)
        return p

    def save(self, p, name='tunnel'):
        path = self.state / (name + '.pid')
        path.write_text(json.dumps(runtime.identity(p.pid)))
        return path

    def test_stop_and_pid_reuse(self):
        p = self.child()
        path = self.save(p)
        value = json.loads(path.read_text())
        value['start'] = 'wrong'
        path.write_text(json.dumps(value))
        runtime.stop(path, .1)
        self.assertIsNone(p.poll())
        self.save(p)
        runtime.stop(path, .1)
        self.assertIsNotNone(p.wait(timeout=2))
        self.assertFalse(path.exists())

    def test_hung_process_killed(self):
        p = self.child(True)
        runtime.stop(self.save(p), .05)
        self.assertEqual(p.wait(timeout=2), -signal.SIGKILL)

    def test_unexpected_exit(self):
        p = self.child()
        path = self.save(p)
        p.kill()
        p.wait()
        self.assertIsNone(runtime.record(path))
        runtime.stop(path)
        self.assertFalse(path.exists())

    def start_context(self):
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.object(runtime.shutil, 'which', return_value='/mock/tunnel-client'))
        stack.enter_context(patch.object(runtime, 'tailscale', return_value=(True, True)))
        stack.enter_context(patch.object(runtime, 'free_port'))
        stack.enter_context(patch.object(runtime, 'unmanaged_process', return_value=False))
        stack.enter_context(patch.dict(os.environ, {'CONTROL_PLANE_API_KEY': 'fake-test-only'}))
        return stack

    def test_normal_start_and_duplicate(self):
        launched = []
        def launch(command, env, path, root):
            p = self.child()
            path.write_text(json.dumps(runtime.identity(p.pid)))
            launched.append((command, env))
            return p
        def http(url):
            return 200 if 'readyz' in url else 404
        with self.start_context(), patch.object(runtime, 'launch', side_effect=launch), patch.object(runtime, 'http', side_effect=http), patch.object(runtime.time, 'monotonic', side_effect=[0, 1, 2, 5, 6]):
            runtime.start(self.root, self.state)
        self.assertEqual(len(launched), 2)
        self.assertNotIn('CONTROL_PLANE_API_KEY', launched[0][1])
        self.assertEqual(launched[1][1]['CONTROL_PLANE_ORGANIZATION_ID'], runtime.ORGANIZATION)
        with self.start_context(), patch.object(runtime, 'http', side_effect=http), patch.object(runtime, 'launch') as launch_mock:
            runtime.start(self.root, self.state)
            launch_mock.assert_not_called()
        for name in ('tunnel', 'approval'):
            runtime.stop(self.state / (name + '.pid'), .1)

    def test_missing_key(self):
        with self.start_context(), patch.dict(os.environ, {}, clear=True), patch.object(runtime.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'API-key ontbreekt'):
                runtime.start(self.root, self.state)

    def test_missing_dependencies_and_python(self):
        with patch.object(runtime.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'afhankelijkheid'):
                runtime.start(self.root, self.state)
        self.python.unlink()
        with self.start_context():
            with self.assertRaisesRegex(RuntimeError, 'Python-omgeving'):
                runtime.start(self.root, self.state)

    def test_busy_port(self):
        with patch.object(runtime.socket, 'socket') as socket_mock:
            socket_mock.return_value.__enter__.return_value.bind.side_effect = OSError('busy')
            with self.assertRaisesRegex(RuntimeError, 'bezet'):
                runtime.free_port(8788)

    def test_partial_failure_preserves_existing(self):
        existing = self.child()
        path = self.save(existing, 'approval')
        with self.start_context(), patch.object(runtime, 'launch', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                runtime.start(self.root, self.state)
        self.assertIsNotNone(runtime.record(path))
        self.assertIsNone(existing.poll())

    def test_partial_failure_rolls_back_created(self):
        created = []
        def launch(command, env, path, root):
            if created:
                raise RuntimeError('crash')
            p = self.child()
            path.write_text(json.dumps(runtime.identity(p.pid)))
            created.append(p)
            return p
        with self.start_context(), patch.object(runtime, 'launch', side_effect=launch):
            with self.assertRaises(RuntimeError):
                runtime.start(self.root, self.state)
        self.assertIsNotNone(created[0].wait(timeout=2))
        self.assertFalse((self.state / 'approval.pid').exists())

    def test_crash_after_spawn_rolls_back(self):
        created = []
        def launch(command, env, path, root):
            p = self.child()
            path.write_text(json.dumps(runtime.identity(p.pid)))
            created.append(p)
            if len(created) == 2:
                p.kill()
                p.wait()
            return p
        with self.start_context(), patch.object(runtime, 'launch', side_effect=launch):
            with self.assertRaisesRegex(RuntimeError, 'direct gestopt'):
                runtime.start(self.root, self.state)
        self.assertIsNotNone(created[0].wait(timeout=2))
        self.assertFalse(list(self.state.glob('*.pid')))

    def test_readiness_timeout_rolls_back(self):
        created = []
        def launch(command, env, path, root):
            p = self.child()
            path.write_text(json.dumps(runtime.identity(p.pid)))
            created.append(p)
            return p
        with self.start_context(), patch.object(runtime, 'launch', side_effect=launch), patch.object(runtime.time, 'monotonic', side_effect=[0, 20]):
            with self.assertRaisesRegex(RuntimeError, 'Starttimeout'):
                runtime.start(self.root, self.state)
        self.assertFalse(list(self.state.glob('*.pid')))
        for p in created:
            self.assertIsNotNone(p.wait(timeout=2))

    def test_tailscale_validation(self):
        config = {'Web': {'robert-pc.tail8c36bd.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8788'}}}}, 'TCP': {'443': {'HTTPS': True}}}
        def result(data):
            return subprocess.CompletedProcess([], 0, json.dumps(data).encode())
        for funnel in (False, True):
            config['AllowFunnel'] = {'robert-pc.tail8c36bd.ts.net:443': funnel}
            with patch.object(runtime.subprocess, 'run', side_effect=[result({'BackendState': 'Running'}), result(config)]):
                self.assertEqual(runtime.tailscale(), (True, not funnel))

    def test_concurrent_start_attempts(self):
        driver = self.root / 'driver.py'
        driver.write_text(f"""import importlib.util, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('runtime', {str(Path('scripts/garmin_runtime.py').resolve())!r})
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
root = Path({str(self.root)!r})
r.state_directory = lambda: root / 'state'
r.shutil.which = lambda name: '/mock/' + name
r.tailscale = lambda: (True, True)
r.free_port = lambda port: None
r.unmanaged_process = lambda name: False
r.http = lambda url: 200 if 'readyz' in url else 404
original = r.launch
def launch(command, env, path, root):
 with (root / 'launches').open('a') as out:
  out.write(path.name + chr(10))
 return original([sys.executable, '-c', 'import time; time.sleep(60)'], env, path, root)
r.launch = launch
os.environ['CONTROL_PLANE_API_KEY'] = 'fake-test-only'
sys.argv = ['runtime', 'start', str(root)]
r.main()
""")
        processes = [subprocess.Popen(['python3', str(driver)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(3)]
        try:
            for p in processes:
                _, error = p.communicate(timeout=10)
                self.assertEqual(p.returncode, 0, error.decode())
            self.assertEqual((self.root / 'launches').read_text().splitlines(), ['approval.pid', 'tunnel.pid'])
        finally:
            for p in processes:
                if p.poll() is None:
                    p.kill()
                p.communicate()
            for name in ('tunnel', 'approval'):
                runtime.stop(self.state / (name + '.pid'), .1)

class MonitoringTests(unittest.TestCase):
    def snapshot(self, **overrides):
        data = {'schema_version': 1, 'snapshot_at': '2026-11-08T14:00:00Z', 'components': {
            'control-plane': {'status': 'ok', 'state': 'polling', 'details': {
                'last_success': '2026-11-08T13:59:55Z', 'consecutive_failures': 0}}}}
        data['components']['control-plane']['details'].update(overrides)
        return data

    def test_poll_success_is_not_end_to_end(self):
        now = runtime.datetime.fromisoformat('2026-11-08T14:00:00+00:00').timestamp()
        self.assertEqual(runtime.tunnel_evidence(self.snapshot(), now), ('RECENT_POLL_SUCCESS', 'UNVERIFIED'))

    def test_disconnected_stale_unknown_and_auth(self):
        now = runtime.datetime.fromisoformat('2026-11-08T14:00:00+00:00').timestamp()
        for detail, expected in (({'consecutive_failures': 1}, 'DISCONNECTED'),
                                 ({'last_success': '2026-11-08T13:00:00Z'}, 'STALE'),
                                 ({'last_success': None}, 'UNKNOWN'),
                                 ({'last_success': '2026-11-09T14:00:00Z'}, 'UNKNOWN'),
                                 ({'http_status': 401}, 'AUTH_FAILED')):
            self.assertEqual(runtime.tunnel_evidence(self.snapshot(**detail), now)[0], expected)
        for value in (None, {}, [], {'schema_version': 2}, {'schema_version': 1, 'snapshot_at': None}):
            self.assertEqual(runtime.tunnel_evidence(value, now), ('UNKNOWN', 'UNKNOWN'))
        self.assertEqual(runtime.tunnel_evidence(self.snapshot(), now + 100)[0], 'STALE')

    def test_http_200_with_stale_poll_fails_status(self):
        import io
        from contextlib import redirect_stdout
        with patch.object(runtime, 'record', return_value={'pid': 123}), patch.object(runtime, 'owns_listener', return_value=True), patch.object(runtime, 'tailscale', return_value=(True, True)), patch.object(runtime, 'http', side_effect=lambda url: 200 if 'readyz' in url else 404), patch.object(runtime, 'health_details', return_value=self.snapshot()), patch.object(runtime.time, 'time', return_value=9999999999), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runtime.status(Path('/tmp')), 1)
        self.assertIn('STALE', output.getvalue())
        self.assertIn('End-to-end MCP:          UNVERIFIED', output.getvalue())

    def test_unrelated_http_server_cannot_pass(self):
        import io
        from contextlib import redirect_stdout
        with patch.object(runtime, 'record', return_value={'pid': 123}), patch.object(runtime, 'owns_listener', return_value=False), patch.object(runtime, 'tailscale', return_value=(True, True)), patch.object(runtime, 'http', return_value=200) as http, patch.object(runtime, 'health_details') as details, redirect_stdout(io.StringIO()):
            self.assertEqual(runtime.status(Path('/tmp')), 1)
            details.assert_not_called()
            http.assert_not_called()

    def test_discovery_partial_and_unknown_do_not_pass(self):
        now = runtime.datetime.fromisoformat('2026-11-08T14:00:00+00:00').timestamp()
        data = self.snapshot()
        mcp = {'status': 'ok', 'observed_at': data['snapshot_at'], 'limited': False,
               'details': {'initialize': {'ok': True}, 'tools_list': {'ok': True, 'complete': True}}}
        data['components']['mcp'] = mcp
        self.assertEqual(runtime.tunnel_evidence(data, now)[1], 'RECENT_DISCOVERY_OBSERVED')
        mcp['details']['tools_list']['complete'] = False
        self.assertEqual(runtime.tunnel_evidence(data, now)[1], 'UNVERIFIED')
        mcp['details']['tools_list']['complete'] = True
        mcp['observed_at'] = '2026-11-08T13:00:00Z'
        self.assertEqual(runtime.tunnel_evidence(data, now)[1], 'UNVERIFIED')
