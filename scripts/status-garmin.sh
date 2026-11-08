#!/bin/bash
# Disable tracing before touching any inherited secrets.
set +x
set -eu
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
ACTION=status
if [[ "${1:-}" == "--watch" && $# == 1 ]]; then
    ACTION=monitor
elif [[ $# != 0 ]]; then
    echo 'Usage: status-garmin.sh [--watch]' >&2
    exit 1
fi
exec python3 "$ROOT/scripts/garmin_runtime.py" "$ACTION" "$ROOT"
