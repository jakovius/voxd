#!/usr/bin/env bash
set -euo pipefail

msg() { printf "==> %s\n" "$*"; }
die() { printf "error: %s\n" "$*" >&2; exit 1; }

if [[ $EUID -ne 0 ]]; then
  # re-exec via sudo if not root
  if command -v sudo >/dev/null; then
    exec sudo "$0" "$@"
  else
    die "This script must run as root (sudo not available)."
  fi
fi

# Detect package manager
PM=""
if command -v apt >/dev/null; then PM=apt;
elif command -v dnf5 >/dev/null; then PM=dnf5;
elif command -v dnf >/dev/null; then PM=dnf;
elif command -v pacman >/dev/null; then PM=pacman;
else PM=""; fi

install() {
  case "$PM" in
    apt)   apt update -qq || true; apt install -y "$@" ;;
    dnf|dnf5) $PM install -y "$@" ;;
    pacman) pacman -Sy --noconfirm "$@" ;;
    *) return 1 ;;
  esac
}

command -v gcc >/dev/null || install gcc make cmake || true
command -v git >/dev/null || install git || true

ydotool_complete() { command -v ydotool >/dev/null && command -v ydotoold >/dev/null; }

msg "Installing ydotool (with daemon)…"
set +e
install ydotool
set -e

if ! ydotool_complete; then
  # Try upstream prebuilt (apt/dnf only)
  if [[ "$PM" == apt || "$PM" == dnf || "$PM" == dnf5 ]]; then
    tmpd=$(mktemp -d)
    get_latest() {
      ext="$1"
      curl -sL https://api.github.com/repos/ReimuNotMoe/ydotool/releases/latest | grep -oE "https://[^"]+ydotool[^"]+\.${ext}" | head -n1
    }
    if [[ "$PM" == apt ]]; then
      url=$(get_latest deb || true)
      if [[ -n "$url" ]]; then curl -L -o "$tmpd/yd.deb" "$url" && dpkg -i "$tmpd/yd.deb" || true; fi
    else
      url=$(get_latest rpm || true)
      if [[ -n "$url" ]]; then curl -L -o "$tmpd/yd.rpm" "$url" && $PM install -y "$tmpd/yd.rpm" || true; fi
    fi
    rm -rf "$tmpd"
  fi
fi

if ! ydotool_complete; then
  msg "Building ydotool from source…"
  case "$PM" in
    apt)   install libevdev-dev libudev-dev libconfig++-dev libboost-program-options-dev ;;
    dnf|dnf5) install libevdev-devel libudev-devel libconfig++-devel boost-program-options-devel ;;
    pacman) install libevdev libconfig++ boost ;;
  esac
  tmpd=$(mktemp -d)
  git clone --depth 1 https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  sed -i 's/add_subdirectory(manpage)/#add_subdirectory(manpage)/' "$tmpd/ydotool/CMakeLists.txt"
  cmake -DCMAKE_INSTALL_PREFIX=/usr -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  rm -rf "$tmpd"
fi

if ! ydotool_complete; then
  die "ydotool installation failed"
fi

msg "Configuring permissions and user service…"
groupadd -f input || true

# Add invoking user (if set by sudo) to input group
TARGET_USER=${SUDO_USER:-${PKEXEC_UID:-}}
if [[ -n "$TARGET_USER" ]]; then
  usermod -aG input "$TARGET_USER" || true
fi

printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' > /etc/udev/rules.d/99-uinput.rules
udevadm control --reload-rules || true
udevadm trigger || true

# Create systemd user service in the user's config dir
if [[ -n "$TARGET_USER" ]]; then
  USER_HOME=$(eval echo ~"$TARGET_USER")
  su - "$TARGET_USER" -c "mkdir -p \"$USER_HOME/.config/systemd/user\""
  YD=$(command -v ydotoold)
  su - "$TARGET_USER" -c "cat > \"$USER_HOME/.config/systemd/user/ydotoold.service\" <<EOF
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=$YD --socket-path=%h/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
EOF"
  # Export env var
  if [[ -f "$USER_HOME/.bashrc" ]]; then
    su - "$TARGET_USER" -c "grep -q 'YDOTOOL_SOCKET' \"$USER_HOME/.bashrc\" || echo 'export YDOTOOL_SOCKET=\"$HOME/.ydotool_socket\"' >> \"$USER_HOME/.bashrc\""
  fi
  if [[ -f "$USER_HOME/.zshrc" ]]; then
    su - "$TARGET_USER" -c "grep -q 'YDOTOOL_SOCKET' \"$USER_HOME/.zshrc\" || echo 'export YDOTOOL_SOCKET=\"$HOME/.ydotool_socket\"' >> \"$USER_HOME/.zshrc\""
  fi
  # Enable and start
  su - "$TARGET_USER" -c "systemctl --user daemon-reload"
  su - "$TARGET_USER" -c "systemctl --user enable ydotoold.service"
  su - "$TARGET_USER" -c "systemctl --user start ydotoold.service || true"
fi

msg "ydotool setup completed. A logout/login or reboot may be required for group membership to take effect."


