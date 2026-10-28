"""Local STDIO entry point; startup has no Garmin or filesystem side effects."""
import argparse
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from typing import Any, Literal
from .mcp_tools import GarminTools


class StepInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['warmup', 'interval', 'recovery', 'cooldown']
    distance_m: float = Field(gt=0, allow_inf_nan=False)
    pace_seconds_per_km: float | None = Field(default=None, gt=0, allow_inf_nan=False)


def create_server(service=None):
    service = service if service is not None else GarminTools()
    server = MCPServer('Garmin Connector', instructions='Reads are the default. Upload requires a separate human terminal approval. Never approve on behalf of the user.')
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)

    @server.tool(structured_output=True, annotations=read)
    def get_recent_activities(limit: StrictInt = 5) -> dict[str, Any]:
        """Return distance/duration summaries of recent running activities; limit 1..50."""
        return service.get_recent_activities(limit)

    @server.tool(structured_output=True, annotations=read)
    def get_activity_details(activity_id: StrictInt) -> dict[str, Any]:
        """Return activity summary and laps without GPS, names or profile data."""
        return service.get_activity_details(activity_id)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def build_running_workout(name: str, steps: list[StepInput]) -> dict[str, Any]:
        """Build distance-based running workout JSON offline. Pace is seconds per km."""
        return service.build_running_workout(name, [step.model_dump() for step in steps])

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                            idempotentHint=False, openWorldHint=True))
    def upload_running_workout(workout: dict, approval_id: str | None = None) -> dict[str, Any]:
        """Prepare approval without an ID; upload once only after separate terminal approval of this exact payload."""
        return service.upload_running_workout(workout, approval_id)

    return server


mcp = create_server()


def main():
    parser = argparse.ArgumentParser(description='Local Garmin MCP server over STDIO')
    parser.add_argument('--enable-uploads', action='store_true', help='Allow terminal-approved creation of NEW workouts')
    args = parser.parse_args()
    create_server(GarminTools(enable_uploads=args.enable_uploads)).run(transport='stdio')


if __name__ == '__main__':
    main()
