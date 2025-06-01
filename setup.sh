#!/usr/bin/env bash
# 
# Whisp installer – phase-0 skeleton
# Runs diagnostics only; no packages are installed yet.
# Safe to run repeatedly.

set -e

PHASE() { echo -e "\n\033[1;36m==> $*\033[0m"; }
STEP () { echo "   • $*"; }

# --------------------------------------------------------------------
PHASE "0. Preconditions"

# 0a – Refuse sudo
if [ "$EUID" = 0 ]; then
  echo "❌  Do NOT run this script with sudo."
  exit 1
fi

# 0b – Python ≥3.9
PY_OK=$(python3 - <<'PY'
import sys, shutil
print(int(sys.version_info >= (3,9)))
PY
)
if [ "$PY_OK" -ne 1 ]; then
  echo "❌  Python ≥ 3.9 not found.  Install it first."
  exit 1
fi
STEP "Python $(python3 -V) ✅"

# 0c – Detect session type
SESSION=${XDG_SESSION_TYPE:-${WAYLAND_DISPLAY:+wayland}}
STEP "Desktop backend: ${SESSION:-unknown}"

# --------------------------------------------------------------------
PHASE "1. Create / activate .venv"

if [ ! -d ".venv" ]; then
  STEP "python -m venv .venv"
  STEP "source .venv/bin/activate"
  STEP "pip install --upgrade pip"
else
  STEP "source .venv/bin/activate (already exists)"
fi

STEP "pip install -e .   # (placeholder – no deps yet)"

# --------------------------------------------------------------------
PHASE "2. whisper.cpp build diagnostics"

if [ -x whisper.cpp/build/bin/whisper-cli ]; then
  STEP "Existing build found → skip"
else
  STEP "Would clone & build whisper.cpp here"
fi

# --------------------------------------------------------------------
PHASE "3. Wayland helper"

if [ "$SESSION" = "wayland" ]; then
  if command -v ydotool &>/dev/null; then
    STEP "ydotool present ✅"
  else
    STEP "Would offer to run setup_ydotool.sh"
  fi
fi

PHASE "DONE (dry-run)"
echo "🎉  Skeleton ran without errors."
