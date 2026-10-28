#!/usr/bin/env bash
# Usage: bash run.sh [--source /dev/video0|file.mp4] [--vcam] [--preset CCD] ...
cd "$(dirname "$0")"
exec "${BADCAMERA_VENV:-$HOME/.local/share/badcamera/venv}/bin/python" -m badcamera "$@"
