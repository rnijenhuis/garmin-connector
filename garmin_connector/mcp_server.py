"""Local STDIO entry point; startup has no Garmin or filesystem side effects."""
import argparse
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool
from typing import Any, Literal
from .mcp_tools import GarminTools


class StepInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['warmup', 'interval', 'recovery', 'cooldown']
    distance_m: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    duration_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    heart_rate_bpm: StrictInt | None = Field(default=None, ge=1, le=300)
    heart_rate_min_bpm: StrictInt | None = Field(default=None, ge=1, le=300)
    heart_rate_max_bpm: StrictInt | None = Field(default=None, ge=1, le=300)
    heart_rate_zone: StrictInt | None = Field(default=None, ge=1, le=5)
    pace_seconds_per_km: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)


class RepeatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['repeat']
    repeat_count: StrictInt = Field(ge=1, le=100)
    steps: list['StepInput | RepeatInput'] = Field(min_length=1, max_length=100)


RepeatInput.model_rebuild()


def create_server(service=None):
    service = service if service is not None else GarminTools()
    instructions = ('Use the offline builder before upload; summarize steps, targets and concrete calendar date for the user. '
                    'For preparing a workout for a day, prefer upload_and_schedule_running_workout after offline building. ONE browser approval covers BOTH actions. Completion requires scheduled with the correct date. Standalone tools retain separate approvals. Never approve for the user or automatically retry writes. '
                    'Resolve relative dates with the user timezone. Pass the inner workout and the returned workout ID between tools; do not ask users to copy JSON. '
                    'Scheduling does not send to a device: instruct the user to sync/send via Garmin Connect for their Forerunner 645. ')
    if service.browser_approval_origin:
        instructions += ('Present approval_url as a link for the user to open and authenticate privately, then wait. A chat yes or client tool confirmation is not server approval. '
                         'After browser approval, repeat the same tool arguments with the original approval_id. Never browse/approve for the user. '
                         'Check Garmin Connect after unknown write outcomes; do not request fresh approval automatically.')
    else:
        instructions += 'Use separate human terminal approval. Never approve on behalf of the user.'
    server = MCPServer('Garmin Connector', instructions=instructions)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

    @server.tool(structured_output=True, annotations=read)
    def get_recent_activities(limit: StrictInt = 5) -> dict[str, Any]:
        """Return distance/duration summaries of recent running activities; limit 1..50."""
        return service.get_recent_activities(limit)

    @server.tool(structured_output=True, annotations=read)
    def get_activity_details(activity_id: StrictInt) -> dict[str, Any]:
        """Return activity summary and laps with average/max heart rate (bpm) and running cadence (total steps/min, both feet). Missing metrics are null. No GPS, names or profile data."""
        return service.get_activity_details(activity_id)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def build_running_workout(name: str, steps: list[StepInput | RepeatInput], for_upload: StrictBool = False) -> dict[str, Any]:
        """Build offline. Set for_upload=true for JSON arguments ready to paste into upload_running_workout. Pace: seconds/km; HR: BPM or zone."""
        return service.build_running_workout(name, [step.model_dump(exclude_none=True) for step in steps], for_upload=for_upload)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def upload_running_workout(workout: dict, approval_id: str | None = None) -> dict[str, Any]:
        """Prepare approval without an ID; upload once after separate human approval of this exact payload. In browser mode, show approval_url and wait for the user."""
        return service.upload_running_workout(workout, approval_id)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def schedule_running_workout(workout_id: StrictInt, date: str, approval_id: str | None = None) -> dict[str, Any]:
        """Schedule an existing running workout on YYYY-MM-DD after separate human approval; in browser mode show approval_url and wait. Never upload implicitly."""
        return service.schedule_running_workout(workout_id, date, approval_id)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def upload_and_schedule_running_workout(workout: dict, date: str, approval_id: str | None = None) -> dict[str, Any]:
        """Prepare ONE browser approval for BOTH upload and scheduling on YYYY-MM-DD. Show link and wait. Repeat identical workout/date with original approval_id after human consent. Only scheduled means complete; then remind user to sync Garmin Connect. Explicit resume reuses progress within original expiry; after expiry obtain fresh browser consent for identical workout/date. Unknown uploads never retry; uncertain scheduling only rechecks calendar. No automatic retry or replacement approval."""
        return service.upload_and_schedule_running_workout(workout, date, approval_id)

    return server


mcp = create_server()


def main():
    parser = argparse.ArgumentParser(description='Local Garmin MCP server over STDIO')
    parser.add_argument('--enable-uploads', action='store_true', help='Allow human-approved creation of NEW workouts')
    parser.add_argument('--enable-scheduling', action='store_true', help='Allow human-approved calendar scheduling')
    parser.add_argument('--approval-mode', choices=['terminal', 'browser'], default='terminal',
                        help='Human consent channel; browser mode is for a private single-owner tunnel')
    parser.add_argument('--approval-origin', help='Private HTTPS origin of the independently authenticated approval portal')
    args = parser.parse_args()
    options = {}
    if args.approval_mode == 'browser':
        from .browser_approval import approval_origin, browser_stores
        try:
            origin = approval_origin(args.approval_origin or '')
        except ValueError:
            parser.error('browser mode requires --approval-origin with a private HTTPS origin')
        stores = browser_stores()
        options = dict(combined_approvals=stores['upload-and-schedule'], approvals=stores['upload'], schedule_approvals=stores['schedule'], browser_approval_origin=origin)
    elif args.approval_origin:
        parser.error('--approval-origin requires --approval-mode browser')
    create_server(GarminTools(enable_uploads=args.enable_uploads, enable_scheduling=args.enable_scheduling, **options)).run(transport='stdio')


if __name__ == '__main__':
    main()
