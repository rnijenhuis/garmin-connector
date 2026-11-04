# Garmin Connector contributor instructions

## Architecture

- `mcp_server.py` exposes five tools through the official Python MCP SDK over
  STDIO. Inspector launches its own Python child process. Keep stdout reserved
  for protocol messages; startup/import must not authenticate or contact Garmin.
- `mcp_tools.py` implements `get_recent_activities` (running summaries),
  `get_activity_details` (summary and laps), `build_running_workout` (offline
  JSON), `upload_running_workout` (prepare approval, then create once), and
  `schedule_running_workout` (approve an existing workout ID/date, then schedule).
  Garmin clients are injected/lazily obtained; MCP uses saved sessions only.
- `workouts.py` builds plain dictionaries; `upload.py` validates the supported
  schema; `approvals.py` owns payload-bound human approval state (terminal by default).
  Builder results wrap the payload in `{"ok": true, "workout": ...}`; upload
  takes the inner object. Optional `for_upload: true` returns exactly
  `{"workout": ...}` for pasting as complete upload arguments; it must stay
  offline and never request approval or authenticate. Keep builder payloads compatible with
  upload validation, including floating-point pace conversions.
- Distances are metres; pace inputs are seconds/km, converted to Garmin m/s
  targets with `1000 / seconds_per_km`. Executable steps end on exactly one of
  distance or duration (seconds) and use at most one target: open, exact pace,
  exact/ranged integer BPM (1–300), or configured HR zone (1–5).
- `RunningRepeat` / MCP `kind: repeat` encodes native `RepeatGroupDTO` blocks.
  Preserve unique consecutive depth-first ordering, repeat counts 1–100,
  nonempty children, at most 100 stored nodes and four repeat levels. These
  are connector limits, not Garmin limits. Every child runs each repetition.
  Follow the installed library's enum constants and payload structures.
  Do not expand native repeats or add automatic recovery insertion.
- Advanced payloads are checked offline against the installed library; live
  acceptance/device support has not been verified. Keep that distinction in
  documentation until a human performs an approved manual verification.

## Scheduling

- Use the installed library's `schedule_workout(workout_id, date_str)` with its
  `{"date": date_str}` payload. Upload never implicitly schedules a workout.
  Validate positive integer ID and strict valid YYYY-MM-DD before API calls.
- Keep `--enable-scheduling` separate from `--enable-uploads`, disabled by
  default. `ScheduleApprovalStore` uses separate state and operation-bound
  payloads. Terminal approval uses literal `SCHEDULE`, ten-minute original
  expiry and single-use consumption before authentication/reads/writes.
  Preserve upload's `UPLOAD` word and existing approval compatibility.
- Lazy saved-session authentication only after scheduling approval. Verify an
  existing running template and check `get_scheduled_workouts_by_period` before
  posting. Unknown calendar shapes fail closed. Filter all responses.
- Preserve atomic persistent per-workout/date attempt claims before POST,
  including on uncertain outcomes. No automatic scheduling retry or MCP reset.
  Agents must never delete attempt records to bypass duplicate protection.
  Explain remote/manual race limitations and human reconciliation requirements.
- Scheduling is offline/mock verified only; never claim live acceptance until
  a human verifies it. Do not expose raw schedules, profile data or credentials.

## Private ChatGPT integration

- The user's direct-ChatGPT requirement adds opt-in browser consent; do not remove
  terminal mode. Read `docs/chatgpt-integration.md` for setup and trust boundaries.
  Both modes use STDIO. `scripts/run_mcp.py` provides an absolute-path launcher
  for a dedicated single-owner Secure MCP Tunnel, without a public MCP listener.
  Never inherit OpenAI tunnel/runtime keys into Garmin application code.
- `--approval-mode browser` requires a configured private HTTPS approval origin.
  The portal in `browser_approval.py` binds only to loopback behind private TLS.
  It independently authenticates the owner using a salted scrypt password hash,
  outside the repo. Preserve authentication, exact Origin/Host checks, CSRF
  binding to operation/ID/hash/expiry, escaped summaries, POST-only consent,
  no-cache/no-referrer, anti-framing headers and disabled access logging.
- `_review_decision` is a trusted local helper, never an MCP tool. Never expose
  any MCP approve/reset endpoint, accept model booleans/headers as consent,
  treat elicitation responses as proof of human action, or assume ChatGPT native
  confirmation/remembered tool permissions grant server approval. Agents must
  never authenticate to or approve a user's real review page on their behalf.
- Browser state is namespaced separately from terminal state. The scheduling
  attempt ledger remains shared across modes. Preserve original ten-minute
  expiry, SHA256 payload binding and atomic single use before authentication.
  No change may silently approve later upload/schedule steps. The portal itself
  never calls Garmin. Tests may simulate human actions only in temporary state.
- ChatGPT instructions must route summary → user review link → wait → same
  arguments + original approval ID. No manual JSON copying, automatic retry or
  self-approval. Upload and calendar scheduling are separate changes; watch
  synchronization remains a user action. Never claim a workout is on the watch.
- This is single-owner/private only: no public OAuth service or multi-user Garmin
  mapping exists. Never publish/expose it or share its tunnel in a multi-user
  workspace. Account-side setup and safe ChatGPT tool calls must be observed
  before reporting connection success; do not invent tunnel IDs or credentials.
  Mobile availability, public deployment and real Garmin writes are unverified.

## Approval and privacy

- Uploads are disabled by default; preserve `--enable-uploads` as an opt-in.
  It permits preparing approval requests, not bypassing human approval.
- Preserve exact-payload SHA256 binding, expiry ten minutes from request creation,
  separate human review (literal `UPLOAD` in terminal mode, authenticated
  action-specific browser POST in browser mode), and atomic
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
  upload, scheduling or browser approval. Cover authentication/CSRF/expiry/
  payload/operation binding, refusal of model self-approval, cross-mode duplicate
  protection, and installed-library HR/time/repeat payload compatibility, legacy
  flat workouts, nested ordering/limits, invalid input and applicable
  approval, expiry, payload binding, replay and failure behavior.
- Run the existing suite with the existing environment:
  `timeout 45s .venv/bin/python -m unittest discover -s tests -v`.
- Never perform live Garmin uploads or scheduling during automated tests. Inject mocked Garmin
  clients and temporary approval directories. STDIO integration checks must use
  offline operations; never use live authentication/API calls as a test fixture.
