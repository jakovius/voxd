#!/usr/bin/env bash
# =============================================================================
#  Whisp – interactive installer for a fresh git-clone
#
#  • Installs system packages via apt/dnf/pacman (auto-detect)
#  • Creates / re-uses a local Python venv  (.venv)
#  • Installs Python deps from requirements.txt
#  • Clones + builds whisper.cpp   → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) builds & enables ydotool if it isn’t on the system
#
#  Idempotent: re-running does nothing if everything is already in place.
# =============================================================================
set -euo pipefail

# ANSI colours
YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[0;31m'; NC='\033[0m'
# print utility – %b lets escape-sequences inside $* take effect
msg() { printf "${YEL}==>${NC} %b\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

[[ $EUID == 0 ]] && die "Run this as a normal user, not root."

# -----------------------------------------------------------------------------#
# 0. Detect package manager
detect_pkg() {
  if   command -v apt   >/dev/null; then
       PM=apt
       INSTALL="sudo apt install -y"
  elif command -v dnf   >/dev/null; then
       PM=dnf
       INSTALL="sudo dnf install -y"
       # ── add Fedora-specific runtime libs for Qt ──
       SYS_DEPS+=(portaudio portaudio-devel xcb-util-cursor xcb-util-wm)
  elif command -v pacman>/dev/null; then
       PM=pacman
       INSTALL="sudo pacman -S --noconfirm"
  else
       die "Unsupported distro – need apt, dnf or pacman."
  fi
}
detect_pkg;  msg "Package manager: $PM"

# -----------------------------------------------------------------------------#
# 1. System packages
SYS_DEPS=(git ffmpeg gcc make cmake curl build-essential python3-venv \
          libxcb-cursor0 libxcb-xinerama0 libportaudio2)
# in case the dev headers for future PyAudio are desired:
SYS_DEPS+=(portaudio19-dev)

# Fedora branch (dnf) – optional but nice
if [[ $PM == dnf ]]; then
  SYS_DEPS+=(python3-virtualenv)
fi

if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && ! command -v ydotool >/dev/null; then
  NEED_YDOTOOL=1
  SYS_DEPS+=(libevdev-dev libudev-dev libconfig++-dev libboost-program-options-dev)
fi

msg "Installing system deps: ${SYS_DEPS[*]}"
$INSTALL "${SYS_DEPS[@]}"

# -----------------------------------------------------------------------------#
# 2. Python virtual environment
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
source .venv/bin/activate

pip install --upgrade pip
msg "Installing Python dependencies…"
pip install -r requirements.txt

msg "Installing Whisp package into venv (editable)…"
pip install -e .

# -----------------------------------------------------------------------------#
# 3. Clone + build whisper.cpp  (local to repo)
if [[ ! -d whisper.cpp ]]; then
  msg "Cloning whisper.cpp…"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
fi

if [[ ! -x whisper.cpp/build/bin/whisper-cli ]]; then
  msg "Building whisper.cpp (first time only)…"
  cmake -S whisper.cpp -B whisper.cpp/build
  cmake --build whisper.cpp/build -j"$(nproc)"
else
  msg "whisper.cpp already built."
fi

# -----------------------------------------------------------------------------#
# 4. Optional: ydotool on Wayland
if [[ ${NEED_YDOTOOL:-0} == 1 ]]; then
  msg "Wayland detected and ydotool missing – building from source…"
  tmpd=$(mktemp -d)
  git clone https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  cmake -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  sudo cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  sudo groupadd -f input
  sudo usermod -aG input "$USER"
  printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' |
      sudo tee /etc/udev/rules.d/99-uinput.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  rm -rf "$tmpd"
  msg "ydotool installed – log out & back in for group changes."
fi

# -----------------------------------------------------------------------------#
# 5. Done
msg "${GRN}Setup complete!${NC}"
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m whisp --mode gui"
