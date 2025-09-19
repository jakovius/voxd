#!/bin/sh
set -e

# Create input group if missing
getent group input >/dev/null 2>&1 || groupadd input || true

# Install udev rule (should already be staged by contents, but ensure reload)
if [ -f "/etc/udev/rules.d/99-uinput.rules" ]; then
  udevadm control --reload-rules || true
  udevadm trigger || true
fi

# Optional: load SELinux policy if shipped (rpm-based systems)
if command -v getenforce >/dev/null 2>&1; then
  if [ "$(getenforce 2>/dev/null)" = "Enforcing" ]; then
    if command -v semodule >/dev/null 2>&1 && [ -f "/opt/voxd/packaging/whisper_execmem.pp" ]; then
      semodule -i /opt/voxd/packaging/whisper_execmem.pp || true
    fi
  fi
fi

echo "voxd installed. Each user should run: voxd --setup"

# Create a local virtualenv to ensure missing Python deps (e.g., sounddevice) are available
# We inherit system site-packages to avoid duplicating distro Python libs
APPDIR="/opt/voxd"
PY="$(command -v python3 || command -v python || true)"
if [ -n "$PY" ]; then
  if [ ! -x "$APPDIR/.venv/bin/python" ]; then
    "$PY" -m venv --system-site-packages "$APPDIR/.venv" >/dev/null 2>&1 || true
  fi
  if [ -x "$APPDIR/.venv/bin/python" ]; then
    VPY="$APPDIR/.venv/bin/python"
    # Upgrade pip quietly; then install minimal extras that may be missing from repos
    "$VPY" -m pip install --upgrade --disable-pip-version-check pip >/dev/null 2>&1 || true
    "$VPY" -m pip install --disable-pip-version-check --no-input \
      sounddevice>=0.5 >/dev/null 2>&1 || true
  fi
fi


