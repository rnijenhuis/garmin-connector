# Technische referentie

Bestaande CLI-, Inspector-, payload- en testdocumentatie, behouden uit de README.
Voor dagelijks ChatGPT-gebruik: [opstarten](STARTUP.md). Historische testresultaten hieronder blijven als zodanig behouden; de actuele verificatie staat onderaan.

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
- `workouts.py`: immutable RunningStep/RunningRepeat inputs and pure JSON construction.
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
- `api/workouts.py` also provides `schedule_workout(workout_id, date_str)` and
  `get_scheduled_workouts_by_period(start, end)`. Scheduling is a separate
  terminal-approved MCP operation. Updates, deletion and device push are not exposed.

The first generated workout was successfully created in Garmin Connect as
workout ID 1744104267; the server returned the expected seven steps and 7 km total. Real workout creation requires explicit confirmation of the reviewed payload.
Updates and device pushes are not implemented; calendar scheduling is a separate MCP tool. No live Garmin operations are performed by automated tests.


## Confirmed test upload

```bash
.venv/bin/python main.py upload
```

This command builds the same seven-step workout, named **ChatGPT Garmin Connector
Test**, validates it, and prints its JSON before asking you to type `UPLOAD`.
Any other answer cancels. Piped/noninteractive input is rejected. Authentication
runs only after confirmation; enter your credentials and MFA privately in your
terminal. On success, the returned workout ID and full API response are printed.
This CLI command does not schedule, push, update, delete or automatically retry.

The saved `examples/running_workout.json` contains the named preview; the upload
command builds it from code rather than loading arbitrary JSON. Validation checks
our supported JSON schema: required name, running sport, one segment, nonempty
ordered executable steps/repeat blocks, positive finite distances/durations and
valid pace/heart-rate targets, consistent
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

Distance inputs (`distance_m`) are **metres** and time inputs
(`duration_seconds`) are **seconds**. Supply exactly one per executable step;
the generated `endConditionValue` uses the corresponding unit.

`pace_seconds_per_km` is **seconds per kilometre** (300 means 5:00/km).
The installed `garminconnect/workout.py` documents `PaceTarget` bounds in m/s
and implements `pace_to_mps` with the same conversion as this builder:
`1000 / pace_seconds_per_km`. Thus 300 becomes 3.3333333333333335 m/s in both
`targetValueOne` and `targetValueTwo`; only exact pace targets are supported.

Responses have `ok` and either structured results or a safe `error.code` and
`error.message`. SDK schema validation failures are MCP tool errors. Raw activity
objects, GPS, names, dates, profile fields and raw upload responses are excluded.
STDOUT is reserved for MCP protocol messages; no prompts or debug prints.

To copy the entire builder result directly into Inspector's upload tool JSON
editor, add `"for_upload": true` alongside `name` and `steps` in the builder
arguments. Successful output is then exactly `{"workout": {...}}`, ready to
paste into `upload_running_workout` without removing fields. Building remains
offline and does not prepare approval or upload. Leave `for_upload` omitted or
false for the existing `{"ok": true, "workout": {...}}` response. Errors retain
`{"ok": false, "error": ...}` in both modes; do not paste an error into upload.
In Inspector's individual `workout` field, paste only the inner workout object.

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
an HTTP 401 internally). Modification, deletion and device push are not exposed.
Calendar scheduling requires its own tool call and human approval (terminal
by default; authenticated browser review in the private ChatGPT mode).

After upload, open Garmin Connect > Training & Planning > Workouts and locate
**MCP Test Workout** (or your chosen name). Open it and check the returned workout
ID, step order, distances and pace targets; the example above totals 7 km.
Check Garmin Connect before retrying any upload with an uncertain outcome.

### Common errors

- `uploads_disabled`: the payload is valid but Inspector's Python child is
  read-only. Restart that connection with `--enable-uploads`.
- `invalid_input`: check the name, step kinds, positive finite distances/durations,
  mutually exclusive targets, HR bounds, repeat limits and the inner workout object. Passing the whole builder response,
  adding server IDs/extra fields or changing the generated schema is rejected.
  SDK argument-schema failures appear as MCP tool errors instead.
- STDIO OAuth errors: this local server uses STDIO, not an HTTP OAuth endpoint.
  Select STDIO and the Python command/arguments above; an Inspector OAuth flow
  is not Garmin login. Garmin `authentication_required` is separate: refresh
  saved tokens in a human terminal with `test_garmin.py`, then retry. Never enter
  credentials into the MCP protocol stream; keep stdout protocol-only.
- `approval_required`: request/review a fresh approval if absent, expired, used
  or mismatched. Approval is consumed before authentication, even if that fails.

### Advanced running workouts

The builder supports `warmup`, `interval`, `recovery` and `cooldown` steps,
ending after either `distance_m` or `duration_seconds`. Existing flat distance
inputs and their payloads remain supported. Recovery must be supplied explicitly.
Choose at most one target per step:

| Input fields | Meaning |
|---|---|
| None | Open target |
| `pace_seconds_per_km` | Exact pace; converted to m/s as above |
| `heart_rate_bpm` | Exact integer BPM (equal lower/upper bounds) |
| `heart_rate_min_bpm`, `heart_rate_max_bpm` | Inclusive integer BPM range; both required, minimum ≤ maximum |
| `heart_rate_zone` | Configured Garmin running HR zone, integer 1–5 |

BPM inputs must be integers from 1–300, a connector validation limit, not a
personal training recommendation or a limit enforced by the library. Zone
bounds come from your Garmin profile; the offline builder does not fetch or
verify your configured zones. Pace and HR targets cannot be combined.

Installed `garminconnect.workout.CustomHeartRateTarget` and
`HeartRateZoneTarget` both use `TargetType.HEART_RATE_ZONE` (4), key
`heart.rate.zone`. Custom BPM uses `targetValueOne`/`targetValueTwo`; configured
zones use `zoneNumber` without BPM values. Time uses `ConditionType.TIME` (2).
Native repeats match `create_repeat_group` / `RepeatGroup`: `RepeatGroupDTO`,
repeat step type 6, iterations condition 7, `numberOfIterations`, and nested
`workoutSteps`. Step orders are unique consecutive integers in depth-first
order, including group nodes. The installed generic upload API forwards this
JSON without flattening it.

Example builder arguments (2 km warm-up, three 1 km efforts with 2-minute
recoveries, then a 1 km cool-down):

```json
{
  "name": "HR and timed recovery intervals",
  "steps": [
    {"kind": "warmup", "distance_m": 2000, "heart_rate_min_bpm": 130, "heart_rate_max_bpm": 145},
    {"kind": "repeat", "repeat_count": 3, "steps": [
      {"kind": "interval", "distance_m": 1000, "pace_seconds_per_km": 300},
      {"kind": "recovery", "duration_seconds": 120}
    ]},
    {"kind": "cooldown", "distance_m": 1000, "heart_rate_min_bpm": 130, "heart_rate_max_bpm": 140}
  ]
}
```

For a 5 km zone-2 run use
`{"kind": "interval", "distance_m": 5000, "heart_rate_zone": 2}`.
For 20 minutes at exactly 140 BPM use
`{"kind": "interval", "duration_seconds": 1200, "heart_rate_bpm": 140}`.
The upload process is unchanged: pass the inner `workout`, obtain separate human
human approval, and resubmit that exact payload with its approval ID.

Repeat counts are integers 1–100; each block needs at least one child. The
connector permits at most 100 stored nodes including groups and four nested
repeat levels. These are local validation limits, not claimed Garmin/device
limits. Every child, including recovery, runs on every repetition (including
the last). Both distance and time recovery are supported; no automatic recovery
insertion or skip-last-recovery option is exposed.

Advanced structures are verified offline against installed library models and
mocked uploads, **not yet by a live Garmin upload**. The recorded manual upload
above used the original flat distance format. Device-specific support remains
unverified. Pace ranges, secondary/combined targets, updating, deleting and
device push remain unsupported by this MCP interface.

### Schedule an existing running workout

`schedule_running_workout` is a fifth MCP tool, separate from upload. Uploading
creates a workout template; it does **not** put it on the calendar.

The installed library's `schedule_workout(workout_id, date_str)` POSTs
`{"date": "YYYY-MM-DD"}` to its configured workout scheduling URL, with the
workout ID appended. This connector uses that method; it does not invent an
endpoint. `get_scheduled_workouts_by_period(date, date)` checks for duplicates.
The installed rescheduling code documents records with `calendarDate` and a
nested `workout.workoutId`; these are the fields used for confirmation/checks.

Restart Inspector and refresh List Tools. Enable scheduling explicitly:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m garmin_connector.mcp_server --enable-scheduling
```

Add `--enable-uploads` too if you also need uploads. Neither flag grants consent.
First call `schedule_running_workout` with an existing workout ID and a real
calendar date (this example is not a live scheduling result):

```json
{"workout_id": 1744319670, "date": "2026-11-01"}
```

Without `approval_id`, the tool only creates local pending approval and returns
`status: "approval_required"`, the requested ID/date, an `approval_id` and a
600-second expiry. No login or Garmin reads/writes occur. In a separate human
terminal, review the exact action, ID, date and SHA256:

```bash
.venv/bin/python -m garmin_connector.approvals --schedule YOUR_APPROVAL_ID
```

Type exactly `SCHEDULE` (not `UPLOAD`), then call the tool again:

```json
{"workout_id": 1744319670, "date": "2026-11-01", "approval_id": "YOUR_APPROVAL_ID"}
```

Approval is bound to this operation, workout ID and date, expires ten minutes
from request creation, and is consumed once before authentication or API calls.
Upload approval cannot authorize scheduling, or vice versa. MCP never approves
on your behalf. Scheduling uses the existing saved Garmin session lazily.
After approval, the tool verifies the template is running, checks schedules,
then makes at most one application-level scheduling call. A confirmed response:

```json
{"ok": true, "status": "scheduled", "workout_id": 1744319670, "date": "2026-11-01"}
```

A matching calendar entry returns `already_scheduled` without a POST. Open
Garmin Connect's Calendar on the chosen date and verify the workout. No device
push, rescheduling or unscheduling is performed.

Security, errors and limits:

- IDs must be positive integers (not booleans/strings). Dates must be exactly
  `YYYY-MM-DD` and valid calendar dates. No time or timezone is accepted; past
  dates are not locally prohibited, and Garmin may impose additional limits.
- Default mode returns `scheduling_disabled`. Invalid arguments return
  `invalid_input` before any authentication or API calls. Expired, reused or
  mismatched approvals return `approval_required`.
- Missing/unverifiable running sport returns `invalid_workout`. Read errors or
  unexpected calendar shapes return `schedule_check_failed` without a POST.
  Only schedule lists with `calendarDate` and nested `workout.workoutId` are
  currently recognized. A successful POST with an unrecognized response is
  reported as `schedule_outcome_unknown`, not assumed to have failed.
- Scheduling approval state lives at
  `~/.local/state/garmin-connector/approvals/scheduling` (outside the repo;
  new directories 700 and records 600). Atomic per-workout/date `.attempt.json`
  records are written **before** POST and retained on success or uncertainty.
  These block later/concurrent attempts across approvals and server restarts
  with `schedule_attempt_exists`, even if Garmin's calendar read is stale.
- Never blindly retry an unknown outcome. Inspect the Garmin calendar first.
  If an earlier entry was removed or an attempt definitively failed, a human
  administrator must reconcile it and remove only the matching local attempt
  record before requesting fresh approval. No MCP reset is exposed. Agents
  must not delete these records to bypass duplicate protection.
- Duplicate protection covers this local state directory and recognizable
  remote entries; external/manual clients can still race the check. It is not
  global exactly-once delivery. The application never retries writes; the
  installed Garmin library can refresh authentication and retry HTTP 401
  internally. Only requested ID/date/status are returned, never raw calendar,
  workout, profile, credential or session data.
- Scheduling is tested with mocked clients and the installed method's HTTP
  payload offline. Live scheduling and Garmin response/device behavior have
  not been verified. No dependencies were reinstalled or live API calls made.

### Automated checks

```bash
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

Tests inject mocked Garmin responses and use temporary approval directories.
They cover all tools, privacy filtering, invalid inputs, safe error handling,
read-only defaults, human approval, expiry, changed payloads, one-use behavior,
and bounded real STDIO SDK client tests using offline construction and the
read-only upload rejection. Advanced tests cover installed-library payload
compatibility, nested ordering, invalid HR/time/repeat inputs, legacy payload
compatibility, and approval binding/expiry/replay/failure for advanced workouts.
No interactive Garmin authentication or live Garmin API calls are used.

Verification (2026-10-28): all 92 tests passed in 4.765 seconds with the command
above in a normal host process. Restricted execution sandboxes can cause STDIO
discovery to time out; request permission to run the suite outside the sandbox
if this occurs. Keep the existing timeouts and real STDIO tests; do not skip them
or change server security settings. No live Garmin calls or dependency reinstalls
are needed.


## Documentatiecontrole — 4 november 2026

De verplichte suite `timeout 45s .venv/bin/python -m unittest discover -s tests -v` slaagde buiten de sandbox: **93 tests, 5.094 seconden, OK**. De sandboxuitvoering bleef bij een echte STDIO-test hangen; de hostuitvoering gebruikte dezelfde suite en timeouts, zonder live Garmin-calls. De browserregressie controleert `strict-origin-when-cross-origin`, weigering van `Origin: null` en daaropvolgende geldige same-origin-toestemming zonder Garmin-aanroep vanuit de portal. De oude `no-referrer`-assertie is bijgewerkt; productiecode is in deze documentatieronde niet gewijzigd.

CLI-help gecontroleerd voor `main.py`, MCP-server, approval-CLI, browserportal en tunnel-client init/run/doctor; clientversie 0.0.19 en Python 3.14.4 lokaal bevestigd. Tailscale Serve-status alleen gelezen: private HTTPS-root proxy naar 127.0.0.1:8788. Lokale Markdown-bestandslinks en `git diff --check` gecontroleerd. Geen profielbestanden/geheimen uitgelezen en geen echte reviewpagina, Garmin-authenticatie, upload of planning als verificatie uitgevoerd.

Open: huidig tunnelprofiel en account-/tailnetrechten zijn niet volledig geaudit; nieuwe Ubuntu-installatie, mobiele ChatGPT, live kalenderplanning en geavanceerde Garmin-/horlogeondersteuning zijn niet opnieuw of nog niet geverifieerd. De template voor de tunnel-userdienst gebruikt profiel `garmin`, terwijl de werkende handmatige opzet `garmin-plus` gebruikt; de installatiehandleiding vermeldt de lokale aanpassing.


### Hartslag en loopcadans in `get_activity_details`

Zowel `activity` als ieder object in `laps` bevat deze aanvullende velden.
Bestaande afstand-, duur-, ID- en rondevelden blijven behouden.

| Uitvoerveld | Garmin-bronveld in `summaryDTO` / `lapDTOs` | Eenheid |
| --- | --- | --- |
| `average_heart_rate_bpm` | `averageHR` | bpm |
| `max_heart_rate_bpm` | `maxHR` | bpm |
| `average_running_cadence_spm` | `averageRunCadence` | totale stappen/min |
| `max_running_cadence_spm` | `maxRunCadence` | totale stappen/min |

Ontbrekende of expliciet null bronwaarden worden JSON `null`, nooit een
verzonnen 0. Expliciete bronwaarde 0 blijft 0. Decimalen blijven behouden.
Bij een vlakke activiteitrespons worden dezelfde bronvelden gebruikt.
De Garmin detail- en lapvelden bevatten al de totale loopcadans van beide
voeten: er wordt **niet verdubbeld**, ook niet bij lage waarden. Deze mapping
gebruikt geen FIT-cadans, generieke fietscadans of op waarde gebaseerde heuristiek.
Garmin definieert loopcadans als stappen per minuut met beide voeten:
[Garmin Support](https://support.garmin.com/en-HK/?faq=S6QyNSOVQv5AqnwgocFpz5).

Op 4 november 2026 alleen-lezen gecontroleerd met activiteit 24968477985:
de detailrespons en alle 13 rondes bevatten `averageHR`, `maxHR`,
`averageRunCadence` en `maxRunCadence`. De activiteit geeft 141/163 bpm en
164,4375/188 stappen/min; dit bevestigt dat verdubbelen hier onjuist is.
De lokale bijgewerkte mapping is op deze activiteit gecontroleerd; een reeds
lopende MCP-server moet de gewijzigde code opnieuw laden voordat de gekoppelde
tool deze velden teruggeeft.
Alleen expliciet toegestane velden komen in de toolrespons; geen ruwe respons,
GPS, namen, profielgegevens of credentials.
