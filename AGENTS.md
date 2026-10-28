# Garmin Connector contributor instructions

## Architecture

- `mcp_server.py` exposes four tools through the official Python MCP SDK over
  STDIO. Inspector launches its own Python child process. Keep stdout reserved
  for protocol messages; startup/import must not authenticate or contact Garmin.
- `mcp_tools.py` implements `get_recent_activities` (running summaries),
  `get_activity_details` (summary and laps), `build_running_workout` (offline
  JSON), and `upload_running_workout` (prepare approval, then create once).
  Garmin clients are injected/lazily obtained; MCP uses saved sessions only.
- `workouts.py` builds plain dictionaries; `upload.py` validates the supported
  schema; `approvals.py` owns separate human terminal approval state.
  Builder results wrap the payload in `{"ok": true, "workout": ...}`; upload
  takes the inner object. Keep every successful builder output compatible with
  upload validation, including floating-point pace conversions.
- Distances are metres; pace inputs are seconds/km, converted to Garmin m/s
  targets with `1000 / seconds_per_km`. Current support is explicit distance
  steps (including recovery) with open/exact pace. Do not claim support for
  heart-rate targets, repeat blocks, time-based steps/recovery or automatic
  recovery insertion without implementation and verification.

## Approval and privacy

- Uploads are disabled by default; preserve `--enable-uploads` as an opt-in.
  It permits preparing approval requests, not bypassing human approval.
- Preserve exact-payload SHA256 binding, expiry ten minutes from request creation,
  separate interactive terminal review with literal `UPLOAD`, and atomic
  single-use consumption before authentication/upload. Failures consume approval;
  do not add automatic upload retries or a tool/model approval shortcut.
- Agents must never approve requests for users, modify approval files to grant
  consent, or execute live uploads as an automated verification step.
- Preserve response allowlists and sanitized errors. Never expose GPS coordinates,
  credentials, session tokens, raw activity/profile data or raw Garmin responses
  through MCP, logs, fixtures or committed files. Keep credentials and approval
  state outside the repository; MCP must not prompt for credentials on STDIO.

## Required checks

- Add/update meaningful tests for changes to workout generation, validation or
  upload. Cover builder/validator compatibility, invalid input and applicable
  approval, expiry, payload binding, replay and failure behavior.
- Run the existing suite with the existing environment:
  `timeout 45s .venv/bin/python -m unittest discover -s tests -v`.
- Never perform live Garmin uploads during automated tests. Inject mocked Garmin
  clients and temporary approval directories. STDIO integration checks must use
  offline operations; never use live authentication/API calls as a test fixture.
