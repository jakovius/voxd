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


