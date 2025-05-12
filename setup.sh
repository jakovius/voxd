#!/bin/bash

set -e

if [ "$EUID" -eq 0 ]; then
  echo "❌ Do not run this script as root (with sudo)."
  echo "   It can cause permission issues with your local project files."
  echo "\n👉 To fix already broken permissions, run this from your project root:"
  echo "   sudo chown -R $SUDO_USER:$SUDO_USER ."
  echo "\nThen re-run this script as a normal user:"
  echo "   ./setup.sh"
  exit 1
fi

# check for python 3.8 or newer
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ Python 3 is not installed. Please install Python 3.8 or newer."
  exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.8"
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
  echo "❌ Python 3.8+ is required. Detected: $PYTHON_VERSION"
  exit 1
fi

# Identify the linux graphical backend (x11 or Wayland)
G_BACKEND=""
if [ -n "${XDG_SESSION_TYPE:-}" ]; then
  G_BACKEND="$XDG_SESSION_TYPE"
elif [ -n "${WAYLAND_DISPLAY:-}" ]; then
  G_BACKEND="wayland"
elif [ -n "${DISPLAY:-}" ]; then
  G_BACKEND="x11"
fi

# Common deps used in both Wayland and X11
sys_deps="ffmpeg gcc make xdg-open git cmake build-essential"

# X11 tools
sys_deps+=" xclip xdotool xbindkeys"

# Wayland-specific tools
sys_deps+=" wtype wl-copy"

# Preemptively ask for sudo if needed for apt installs
need_sudo=0
for pkg in $sys_deps; do
  if ! command -v "$pkg" >/dev/null 2>&1; then
    need_sudo=1
    break
  fi
done

if [ "$need_sudo" -eq 1 ]; then
  echo "🔒 Some dependencies require sudo to install system packages."
  sudo -v || { echo "❌ Sudo authentication failed. Exiting."; exit 1; }
fi

# Setup virtual environment if not exists
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Skip pip upgrade - just use whatever version came with venv
echo "==> Using pip version $(.venv/bin/pip --version)"


# Install Python dependencies
pip install -r requirements.txt

# Clone whisper.cpp if not already present
if [ ! -d "whisper.cpp" ]; then
  echo "==> Cloning whisper.cpp..."
  git clone https://github.com/ggerganov/whisper.cpp.git
fi

# Build whisper.cpp if needed
cd whisper.cpp
if [ ! -d "build" ]; then
  echo "==> Running cmake for whisper.cpp..."
  cmake -B build
fi

echo "==> Building whisper.cpp..."
cmake --build build --config Release

# --- Check for root-owned build files ---
BUILD_DIR="whisper.cpp/build"

if find "$BUILD_DIR" -user root | grep -q .; then
  echo "⚠️ Some files in $BUILD_DIR are owned by root."
  echo "This may cause permission errors during future builds."
  read -rp "Would you like to fix this now? [Y/n] " fix_perm
  fix_perm="${fix_perm,,}"  # to lowercase
  if [[ "$fix_perm" =~ ^(y|yes|)$ ]]; then
    echo "==> Fixing permissions..."
    sudo chown -R "$USER:$USER" "$BUILD_DIR"
  else
    echo "❗ You may encounter build errors if permissions remain incorrect."
  fi
fi

cd ..

# === Hotkey setup: prompt user and update config.yaml ===

update_config_hotkey() {
  local config_file="config.yaml"
  local key_combo="$1"
  if [ -z "$key_combo" ]; then
    echo "❌ No key combo entered. Skipping hotkey update."
    return 1
  fi
  # Always quote the value for YAML safety
  if grep -q '^hotkey_record:' "$config_file"; then
    sed -i "s|^hotkey_record:.*|hotkey_record: \"$key_combo\"|" "$config_file"
  else
    echo "hotkey_record: \"$key_combo\"" >> "$config_file"
  fi
  echo "✅ Updated hotkey_record in $config_file: $key_combo"
}

echo "==> Hotkey setup"
echo "To trigger Whisp recording, you need to set up a custom keyboard shortcut in your desktop environment."
echo "Recommended command for the shortcut:"
echo "bash -c '$PWD/.venv/bin/python -m whisp --trigger-record'"
echo

# Prompt until non-empty key combo is entered
while true; do
  read -rp "Enter the key combo you want to use for recording (type it LITERALLY, e.g. ctrl+alt+r): " key_combo
  if [ -n "$key_combo" ]; then
    update_config_hotkey "$key_combo"
    break
  else
    echo "Please enter a valid key combo."
  fi
done

echo "👉 Please add a custom shortcut in your system settings using the above command and key combo."

# === ydotool setup for Wayland (well, hopefully for X11 too) ===

# function for installing ydotool
install_ydotool() {
  echo "=== 🧰 Installing ydotool for Wayland ==="

  echo "🔧 Installing dependencies..."
  sudo apt update
  sudo apt install -y git cmake build-essential \
      libevdev-dev libudev-dev libconfig++-dev \
      libboost-program-options-dev

  echo "📦 Cloning and building ydotool from source..."
  git clone https://github.com/ReimuNotMoe/ydotool.git ~/ydotool-src
  cd ~/ydotool-src
  mkdir -p build && cd build
  cmake ..
  make -j$(nproc)
  sudo make install
  cd ~
  rm -rf ~/ydotool-src

  echo "🛡️ Setting udev rule..."
  echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger

  echo "👥 Adding user to input group..."
  sudo usermod -aG input "$USER"

  echo "📂 Creating user systemd service..."
  mkdir -p ~/.config/systemd/user

  cat <<EOF > ~/.config/systemd/user/ydotoold.service
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=/usr/local/bin/ydotoold --socket-path=%h/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
EOF

  echo "🔍 Checking if systemd user service is available..."
  if ! systemctl --user is-active --quiet default.target; then
    echo "❌ Systemd user services not available."
    echo "   ydotoold cannot be installed as a background user daemon in this session."
    echo "👉 Please ensure you're running a full desktop environment with systemd user session support."
    echo "ℹ️ On some systems, you may need to log in via a display manager (like GDM, SDDM, etc.) instead of startx."
    return 1
  fi

  echo "⚙️ Enabling ydotoold..."
  systemctl --user daemon-reexec
  systemctl --user enable ydotoold.service
  systemctl --user start ydotoold.service

  # Add to shell config if not present
  SOCKET_LINE='export YDOTOOL_SOCKET="$HOME/.ydotool_socket"'
  if ! grep -Fxq "$SOCKET_LINE" ~/.bashrc; then
    echo "$SOCKET_LINE" >> ~/.bashrc
    echo "✅ Added YDOTOOL_SOCKET to ~/.bashrc"
  fi
  export YDOTOOL_SOCKET="$HOME/.ydotool_socket"
}

# run the ydotool setup (if needed) and diagnostics
if [ "$G_BACKEND" = "wayland" ]; then
  echo "🪟 Wayland detected — input simulation needs special setup."

  # Check if ydotool is already installed
  if ! command -v ydotool >/dev/null 2>&1; then
    read -rp "Would you like to install and configure ydotool for simulated typing on Wayland? [y/N] " install_ydt
    install_ydt="${install_ydt,,}"  # lowercase

    if [[ "$install_ydt" =~ ^(y|yes)$ ]]; then
      install_ydotool
      echo -e "\n⚠️ You must now reboot your system to finalize the setup (input group membership)."
      echo "👉 After rebooting, re-run this script to verify ydotool is working."
      exit 0
    fi
  else
    # Post-reboot check if daemon is running and typing works
    echo "🧪 Verifying ydotoold daemon and functionality..."
    systemctl --user is-active --quiet ydotoold && echo "✅ ydotoold is running." || {
      echo "❌ ydotoold is not running."
      echo "Attempting to start ydotoold..."
      systemctl --user start ydotoold
    }

    export YDOTOOL_SOCKET="$HOME/.ydotool_socket"

    echo "Typing test in 2 seconds..."
    sleep 2
    ydotool type "✅ ydotool is working!"
    echo -e "\n🚀 If you saw the above message typed into your terminal or text field, ydotool is working."
  fi
fi

# Run setup diagnostics
echo "==> Running setup checks..."
python3 -m utils.setup_utils --check

echo "\n✅ Whisp setup completed. You can now run the app using:"
echo "  source .venv/bin/activate && python -m whisp --mode cli"
