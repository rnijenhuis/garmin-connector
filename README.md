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

These functions can be called from future MCP tools without interactive prompts;
keep authentication and write approval at that future integration boundary.

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

The generated structure is checked offline. Garmin server acceptance has not
been tested. Real workout creation requires explicit confirmation of the reviewed payload.
Scheduling, updates and device pushes are not implemented. No real Garmin writes or
live authentication were performed during this implementation.


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
Garmin enum IDs/keys, and no server IDs or additional fields. Generic upload does
not validate required fields locally. Garmin server acceptance is still pending.
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

Absolute command (works from any directory):

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
  "name": "MCP Running Preview",
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

Responses have `ok` and either structured results or a safe `error.code` and
`error.message`. SDK schema validation failures are MCP tool errors. Raw activity
objects, GPS, names, dates, profile fields and raw upload responses are excluded.
STDOUT is reserved for MCP protocol messages; no prompts or debug prints.

### Optional upload approval workflow (not run during development)

Only when you intend to create a new workout, restart Inspector's server with
`--enable-uploads` appended to its arguments. Then:

1. Build and review a workout.
2. Call `upload_running_workout` with `workout` and no approval ID. This creates
   local pending state only and returns an `approval_id`; it does not authenticate
   or upload.
3. In a separate, human-operated terminal from the project directory run:
   `.venv/bin/python -m garmin_connector.approvals APPROVAL_ID`.
   Review the full JSON and SHA256, then type exactly `UPLOAD` to approve.
4. Call `upload_running_workout` again with the identical `workout` and returned
   `approval_id`. It consumes approval before authentication and makes one call
   to the library's creation method, returning only workout ID and name.

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

### Automated checks

```bash
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

Tests inject mocked Garmin responses and use temporary approval directories.
They cover all tools, privacy filtering, invalid inputs, safe error handling,
read-only defaults, human approval, expiry, changed payloads, one-use behavior,
and a real bounded STDIO SDK client test that only calls the offline builder.
No interactive Garmin authentication or live Garmin API calls are used.
