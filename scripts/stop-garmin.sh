#!/bin/bash
# Disable tracing before touching any inherited secrets.
set +x
set -eu
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
exec python3 "$ROOT/scripts/garmin_runtime.py" stop "$ROOT"
