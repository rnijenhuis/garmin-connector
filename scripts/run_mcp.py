"""Absolute-path STDIO launcher for tunnel-client; no working-directory assumptions."""
import os
from pathlib import Path
import sys

# Tunnel control-plane credentials belong to tunnel-client, never Garmin tools.
for name in ('CONTROL_PLANE_API_KEY', 'OPENAI_API_KEY'):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garmin_connector.mcp_server import main

if __name__ == '__main__':
    main()
