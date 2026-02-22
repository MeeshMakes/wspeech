#!/usr/bin/env bash
# wSpeech launcher — re-generates desktop icon then starts the app
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Make sure icon is up to date
python3 "$SCRIPT_DIR/make_icon.py" 2>/dev/null || true

# Launch the app
exec python3 "$SCRIPT_DIR/wspeech.py" "$@"
