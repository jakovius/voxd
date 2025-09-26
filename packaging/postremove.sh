#!/bin/sh
set -e

# No user-home cleanup (multi-user). Leave models/config intact.

# Clean up application-managed virtualenv to avoid stale interpreters lingering
APPDIR="/opt/voxd"
if [ -d "$APPDIR/.venv" ]; then
  rm -rf "$APPDIR/.venv" 2>/dev/null || true
fi


