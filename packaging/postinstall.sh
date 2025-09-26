#!/bin/sh
set -e

# Create input group if missing
getent group input >/dev/null 2>&1 || groupadd input || true

# Install udev rule (should already be staged by contents, but ensure reload)
if [ -f "/etc/udev/rules.d/99-uinput.rules" ]; then
  udevadm control --reload-rules || true
  udevadm trigger || true
fi

# Ensure uinput kernel module is loaded now and on boot (Wayland typing requires it)
if ! lsmod 2>/dev/null | grep -q '^uinput\b'; then
  modprobe uinput || true
fi
# Persist across reboots
if [ ! -f "/etc/modules-load.d/uinput.conf" ]; then
  echo uinput > /etc/modules-load.d/uinput.conf 2>/dev/null || true
fi
# Retrigger udev so the new rule takes effect immediately
udevadm trigger /dev/uinput || true

# If installed via sudo, add that user to 'input' group for ydotool permissions
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  usermod -aG input "$SUDO_USER" 2>/dev/null || true
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

# Pick a Python >= 3.9 if available; attempt RPM install on openSUSE if too old
pick_python() {
  for c in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      ver="$("$c" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
      case "$ver" in
        3.9|3.10|3.11|3.12|3.13) echo "$c"; return 0 ;;
        *) ;;
      esac
    fi
  done
  echo ""
}

PY="$(pick_python)"

# If no suitable python found, on zypper try to install a newer one
if [ -z "$PY" ] && command -v zypper >/dev/null 2>&1; then
  for pkg in python311 python3.11 python310 python3.10 python39 python3.9; do
    if zypper --non-interactive --no-gpg-checks install -y "$pkg" >/dev/null 2>&1; then
      break
    fi
  done
  PY="$(pick_python)"
fi

if [ -n "$PY" ]; then
  if [ ! -x "$APPDIR/.venv/bin/python" ]; then
    "$PY" -m venv --system-site-packages "$APPDIR/.venv" >/dev/null 2>&1 || true
  fi
  if [ -x "$APPDIR/.venv/bin/python" ]; then
    VPY="$APPDIR/.venv/bin/python"
    # Upgrade pip quietly; then install minimal extras that may be missing from repos
    "$VPY" -m pip install --upgrade --disable-pip-version-check pip >/dev/null 2>&1 || true
    # Ensure core runtime dependencies inside app venv (covers Leap mismatches)
    "$VPY" -m pip install --disable-pip-version-check --no-input sounddevice>=0.5 psutil numpy requests pyyaml tqdm pyperclip >/dev/null 2>&1 || true
    # Ensure platformdirs (imported by voxd.core.config); install only if missing
    "$VPY" - <<'PY' 2>/dev/null || "$VPY" -m pip install --disable-pip-version-check --no-input platformdirs >/dev/null 2>&1 || true
try:
    import platformdirs  # type: ignore
except Exception:
    raise SystemExit(1)
PY
    # Ensure importlib_resources backport for older Python (e.g., openSUSE Leap)
    "$VPY" - <<'PY' 2>/dev/null || "$VPY" -m pip install --disable-pip-version-check --no-input importlib-resources >/dev/null 2>&1 || true
try:
    import importlib_resources  # type: ignore
except Exception:
    raise SystemExit(1)
PY
    # Ensure PyQt6 (RPM/openSUSE may not provide python3-qt6)
    "$VPY" - <<'PY' 2>/dev/null || "$VPY" -m pip install --disable-pip-version-check --no-input PyQt6 >/dev/null 2>&1 || true
try:
    import PyQt6  # type: ignore
except Exception:
    raise SystemExit(1)
PY
    # Ensure pyqtgraph (optional UI component used by Flux/Tuner)
    "$VPY" - <<'PY' 2>/dev/null || "$VPY" -m pip install --disable-pip-version-check --no-input pyqtgraph >/dev/null 2>&1 || true
try:
    import pyqtgraph  # type: ignore
except Exception:
    raise SystemExit(1)
PY
  fi
fi


