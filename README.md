# Garmin connector

Simple reusable reads and offline running workout construction, tested using Python
3.14.4 and the installed garminconnect 0.3.20. Workout creation requires explicit interactive confirmation.

## Commands

Use the existing virtual environment:

```bash
.venv/bin/python main.py                  # offline workout JSON preview
.venv/bin/python main.py activities       # interactive authenticated reads
.venv/bin/python test_garmin.py           # same read-only smoke test
.venv/bin/python -m unittest discover -s tests -v
```

Authentication uses GARMIN_EMAIL or prompts for an email, password and MFA code.
Existing tokens are loaded from ~/.garminconnect. Imports never authenticate.
Tests use unittest.mock and do not contact Garmin.

## Modules

- `client.py`: explicit authentication entry point.
- `activities.py`: injected-client reads and JSON-ready activity reports. Empty
  responses return empty summaries and null details/laps without indexing a list.
- `workouts.py`: immutable RunningStep inputs and pure JSON payload construction.
- `cli.py`: interactive input and presentation only.

The MCP layer calls these functions without interactive prompts; authentication
and write approval are handled at the MCP integration boundary.

## Prepared workout

`examples/running_workout.json` contains the generated Garmin-shaped payload:

| Step | Kind | Distance | Pace |
|---|---|---|---|
| 1 | Warmup | 2 km | Open |
| 2 | Interval | 1 km | 5:00/km |
| 3 | Recovery | 500 m | Open |
| 4 | Interval | 1 km | 5:00/km |
| 5 | Recovery | 500 m | Open |
| 6 | Interval | 1 km | 5:00/km |
| 7 | Cooldown | 1 km | Open |

Total: 7 km. Recovery occurs only between intervals. Steps are expanded rather
than nested repeat groups. Distances are metres; pace target bounds are both
1000 / 300 = 3.3333333333333335 m/s (exact 5:00/km, no added tolerance).
No duration estimate is invented for steps with unspecified pace.

## Installed library inspection

Inspected local source files in
`.venv/lib/python3.14/site-packages/garminconnect/`:

- `workout.py` defines RunningWorkout, WorkoutSegment, ExecutableStep,
  RepeatGroup, PaceTarget and distance interval helpers. Typed models need the
  optional Pydantic dependency; the builder uses plain dictionaries and the
  generic payload format instead.
- `api/workouts.py` exposes `upload_workout(payload)`, which POSTs JSON to
  `/workout-service/workout`, and `upload_running_workout(workout)`, which accepts
  a typed RunningWorkout and delegates to that generic upload method.
- The library also exposes workout reads, updates, deletion, scheduling and
  device push operations. These write methods are not called by this project.

The first generated workout was successfully created in Garmin Connect as
workout ID 1744104267; the server returned the expected seven steps and 7 km total. Real workout creation requires explicit confirmation of the reviewed payload.
Scheduling, updates and device pushes are not implemented. No live Garmin operations are performed by automated tests.


## Confirmed test upload

```bash
.venv/bin/python main.py upload
```

This command builds the same seven-step workout, named **ChatGPT Garmin Connector
Test**, validates it, and prints its JSON before asking you to type `UPLOAD`.
Any other answer cancels. Piped/noninteractive input is rejected. Authentication
runs only after confirmation; enter your credentials and MFA privately in your
terminal. On success, the returned workout ID and full API response are printed.
There is no scheduling, device push, update, deletion or automatic retry.

The saved `examples/running_workout.json` contains the named preview; the upload
command builds it from code rather than loading arbitrary JSON. Validation checks
our supported JSON schema: required name, running sport, one segment, nonempty
ordered executable steps, positive finite distances and pace targets, consistent
Garmin enum IDs/keys, and no server IDs or additional fields. The installed generic upload method does
not validate required fields locally; this project validates its supported schema
before calling it. The first seven-step payload has been accepted by Garmin.
The optional typed RunningWorkout model additionally requires a duration estimate;
we use the generic dict API without inventing one for open-pace steps.

Authentication errors stop before upload. Upload errors, interruptions and missing
response IDs may have an uncertain outcome: check Garmin Connect before retrying
to avoid duplicate workouts. Error messages omit exception details to avoid
printing credentials or tokens. Each confirmed invocation creates a new workout.

After success, open Garmin Connect > Training & Planning > Workouts and find
**ChatGPT Garmin Connector Test**. Verify the seven steps and 7 km total. In the
mobile app, open the workout, choose the send icon, select your Forerunner 645,
and sync. On the watch select START > Run, hold UP, then Training > My Workouts,
select the workout, and choose Do Workout.

Garmin instructions:
- https://support.garmin.com/en-SG/?faq=Oyqt6jUjOF8L1Rnuc9Sms8
- https://www8.garmin.com/manuals/webhelp/forerunner645/EN-US/GUID-3AA7B50B-EBE5-4A29-A15A-316849BA9BDB.html

## Local MCP server (Ubuntu, STDIO)

Uses the already installed **official `mcp` SDK 2.3.0**. In SDK v2 the former
FastMCP class is named `MCPServer`; this project uses that supported API, not the
separate third-party `fastmcp` package. No Django, Docker, HTTP listener or VPS.

From the project directory, start in read-only mode:

```bash
.venv/bin/python -m garmin_connector.mcp_server
```

Absolute interpreter command (run with the project as working directory):

```bash
/home/robert/Documents-Prive/Projects/garmin-connector/.venv/bin/python -m garmin_connector.mcp_server
```

For the absolute command, set the working directory to
`/home/robert/Documents-Prive/Projects/garmin-connector` so Python can locate the
package. A STDIO server waits quietly for MCP messages on stdin. This is normal;
use Inspector rather than typing JSON or Garmin credentials into that terminal.
Ctrl+C stops it. Startup/import performs no Garmin login or network calls.

Dependencies are recorded in `requirements.txt`; the SDK is already installed
in this environment. For a fresh environment only, use `python -m venv .venv`
and `.venv/bin/python -m pip install -r requirements.txt`.

### Credentials and saved sessions

MCP uses saved tokens from `~/.garminconnect` only, outside the repository. It
never prompts, accepts credentials as tool arguments, or reads a project `.env`.
If a read tool returns `authentication_required`, stop and refresh the session
in a separate terminal using the existing manual smoke test:

```bash
.venv/bin/python test_garmin.py
```

This is a user-run, interactive read operation, not part of server startup or
unit tests. Protect the token directory with `chmod 700 ~/.garminconnect`.
Never paste token files into chats or commit credentials. Approval state is kept
separately at `~/.local/state/garmin-connector/approvals` (directory mode 700;
new request files mode 600), not in the repository.

### MCP Inspector

Inspector requires Node.js/npm (`npx`). From the project directory:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m garmin_connector.mcp_server
```

To allow terminal-approved uploads, start Inspector with:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m garmin_connector.mcp_server --enable-uploads
```

**Inspector starts its own Python server process.** A server started separately
in another terminal is not the process Inspector connects to. Stop/relaunch the
Inspector connection with the flag to enable uploads in its child process.

Alternatively open Inspector with `npx @modelcontextprotocol/inspector`, choose
**STDIO**, set Command to the absolute project `.venv/bin/python`, Arguments to
`-m garmin_connector.mcp_server`, and launch it with the project as its working
directory. Use the local URL/token printed by Inspector, connect, and list tools.
Inspector may download its own npm package on first use; this is separate from
the already installed Python SDK.

Try these tool arguments:

- `get_recent_activities`: `{"limit": 5}`. Fetches running activities only;
  returns activity ID, distance in km and duration in seconds (maximum limit 50).
- `get_activity_details`: `{"activity_id": 123456}` using a real activity ID.
  Returns distance/duration summary plus lap index, distance (m), duration (s).
- `build_running_workout`: use the JSON below. Completely offline.
- `upload_running_workout`: `{"workout": <workout object from builder>}`.
  Default server returns `uploads_disabled` and does not contact Garmin.

```json
{
  "name": "MCP Test Workout",
  "steps": [
    {"kind": "warmup", "distance_m": 2000},
    {"kind": "interval", "distance_m": 1000, "pace_seconds_per_km": 300},
    {"kind": "recovery", "distance_m": 500},
    {"kind": "interval", "distance_m": 1000, "pace_seconds_per_km": 300},
    {"kind": "recovery", "distance_m": 500},
    {"kind": "interval", "distance_m": 1000, "pace_seconds_per_km": 300},
    {"kind": "cooldown", "distance_m": 1000}
  ]
}
```

Distances (`distance_m` and generated `endConditionValue`) are **metres**;
`pace_seconds_per_km` is **seconds per kilometre** (300 means 5:00/km).
The installed `garminconnect/workout.py` documents `PaceTarget` bounds in m/s
and implements `pace_to_mps` with the same conversion as this builder:
`1000 / pace_seconds_per_km`. Thus 300 becomes 3.3333333333333335 m/s in both
`targetValueOne` and `targetValueTwo`; only exact pace targets are supported.

Responses have `ok` and either structured results or a safe `error.code` and
`error.message`. SDK schema validation failures are MCP tool errors. Raw activity
objects, GPS, names, dates, profile fields and raw upload responses are excluded.
STDOUT is reserved for MCP protocol messages; no prompts or debug prints.

### Verified integration and upload example

The manual end-to-end test verified Python/STDIO startup, Inspector connection,
activity summaries, activity details/laps, offline workout construction and a
terminal-approved Garmin Connect upload. The verified workout is **MCP Test
Workout**, Garmin workout ID **1744319670**. This is a recorded manual result;
automated tests do not make live Garmin calls.

Use the builder arguments above, then follow this complete upload sequence with
Inspector's upload-enabled server. Each successful upload creates a new workout.

Only when you intend to create a new workout, restart Inspector's server with
`--enable-uploads` appended to its arguments. Then:

1. Call `build_running_workout` with the JSON above and review its result:
   `{"ok": true, "workout": {...}}`.
   Copy only the inner `workout` object into the upload tool's `workout` argument,
   not the outer `ok` wrapper. In the following examples, `WORKOUT_OBJECT` means
   that complete copied object (replace the placeholder before submitting).
2. Call `upload_running_workout` with `workout` and no approval ID. This creates
   local pending state only and returns an `approval_id`; it does not authenticate
   or upload. Tool arguments:
   `{"workout": WORKOUT_OBJECT}`.
3. In a separate, human-operated terminal from the project directory run:
   `.venv/bin/python -m garmin_connector.approvals APPROVAL_ID`.
   Review the full JSON and SHA256, then type exactly `UPLOAD` to approve.
4. Call `upload_running_workout` again with the identical `workout` and returned
   `approval_id`. It consumes approval before authentication and makes one call
   to the library's creation method, returning only workout ID and name.
   Tool arguments: `{"workout": WORKOUT_OBJECT, "approval_id": "RETURNED_APPROVAL_ID"}`.
   Success has the shape:
   `{"ok": true, "status": "uploaded", "workout_id": 1744319670, "workout_name": "MCP Test Workout"}`
   (a new upload receives its own ID).

Approvals expire ten minutes after request creation and cannot be replayed or
used for changed payloads. Cancellation/noninteractive input grants nothing.
No MCP tool approves requests, and a model boolean cannot authorize uploads.
Approval files are a local trust boundary: an agent with arbitrary shell/file
access as your OS user could approve or alter them. Keep approval CLI/files out
of automated agent permissions; MCP alone cannot grant approval.

Authentication or upload failure consumes approval. An upload failure or absent
ID can have an unknown outcome: check Garmin Connect before a fresh attempt.
The application does not retry uploads (the Garmin library can refresh and retry
an HTTP 401 internally). Scheduling, modification, deletion and device push are
not exposed.

After upload, open Garmin Connect > Training & Planning > Workouts and locate
**MCP Test Workout** (or your chosen name). Open it and check the returned workout
ID, step order, distances and pace targets; the example above totals 7 km.
Check Garmin Connect before retrying any upload with an uncertain outcome.

### Common errors

- `uploads_disabled`: the payload is valid but Inspector's Python child is
  read-only. Restart that connection with `--enable-uploads`.
- `invalid_input`: check the name, step kinds, positive finite numeric distances
  and pace, and the inner workout object. Passing the whole builder response,
  adding server IDs/extra fields or changing the generated schema is rejected.
  SDK argument-schema failures appear as MCP tool errors instead.
- STDIO OAuth errors: this local server uses STDIO, not an HTTP OAuth endpoint.
  Select STDIO and the Python command/arguments above; an Inspector OAuth flow
  is not Garmin login. Garmin `authentication_required` is separate: refresh
  saved tokens in a human terminal with `test_garmin.py`, then retry. Never enter
  credentials into the MCP protocol stream; keep stdout protocol-only.
- `approval_required`: request/review a fresh approval if absent, expired, used
  or mismatched. Approval is consumed before authentication, even if that fails.

### Current limitations

The MCP builder accepts 1–100 explicit distance steps in one running segment:
`warmup`, `interval`, `recovery`, `cooldown`, with open or exact pace targets.
Distance-based recovery intervals are supported when supplied explicitly; there
is no automatic recovery insertion or time-based recovery. Heart-rate targets,
nested repeat blocks, time-based steps and pace ranges are unsupported by this
builder/validator, even where the installed Garmin library offers them.
Scheduling, updating, deleting and device push are not exposed by MCP. These
features are not implemented as part of this documentation update.

### Automated checks

```bash
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

Tests inject mocked Garmin responses and use temporary approval directories.
They cover all tools, privacy filtering, invalid inputs, safe error handling,
read-only defaults, human approval, expiry, changed payloads, one-use behavior,
and a real bounded STDIO SDK client test that only calls the offline builder.
No interactive Garmin authentication or live Garmin API calls are used.

Documentation-update verification (2026-10-28): 38 of 39 automated tests passed;
`test_real_stdio_offline` timed out during MCP discovery/initialization. This
local automated result is separate from the successful manual Inspector test
recorded above. No live Garmin calls were made for this documentation update.
