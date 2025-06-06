#!/usr/bin/env bash
# =============================================================================
#  Whisp – one-shot, self-healing installer
#
#  • Detects apt / dnf / pacman and installs missing tool-chains automatically
#  • Creates / re-uses a Python venv (.venv) and installs requirements
#  • Fetches + builds whisper.cpp → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) auto-builds ydotool if absent
#
#  Re-running after success prints a friendly “all done” message and exits.
# =============================================================================
set -Eeuo pipefail

###############################################################################
# Colours & helpers -----------------------------------------------------------
YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[0;31m'; NC='\033[0m'
msg()  { printf "${YEL}==>${NC} %b\n" "$*"; }
die()  { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }
ok()   { printf "${GRN}%b${NC}\n" "$*"; }

[[ $EUID == 0 ]] && die "Run as a normal user, not root."

###############################################################################
# Detect package manager & housekeeping ---------------------------------------
detect_pkg() {
  if   command -v apt-get >/dev/null; then
       PM=apt;    INSTALL="sudo apt-get install -y"; UPDATE="sudo apt-get update -y"
       BUILD_GROUP="build-essential"
  elif command -v dnf >/dev/null; then
       PM=dnf;    INSTALL="sudo dnf install -y";      UPDATE="sudo dnf makecache"
       BUILD_GROUP="@development-tools"
  elif command -v pacman >/dev/null; then
       PM=pacman; INSTALL="sudo pacman -S --noconfirm"; UPDATE="sudo pacman -Sy"
       BUILD_GROUP="base-devel"
  else
       die "Unsupported distro – need apt, dnf or pacman."
  fi
}
detect_pkg

###############################################################################
# 0. Make sure gcc / g++ exist -------------------------------------------------
need_compilers=0
for t in gcc g++; do command -v "$t" >/dev/null || { need_compilers=1; break; }; done
if (( need_compilers )); then
  msg "Compilers missing – installing $BUILD_GROUP …"
  $UPDATE; $INSTALL "$BUILD_GROUP"
fi

###############################################################################
# 1. Make sure cmake ≥ 3.13 exists -------------------------------------------
cmake_ok=0
if command -v cmake >/dev/null; then
  cmake_ver=$(cmake --version | awk '/version/ {print $3}')
  # version_compare: returns 0 (true) if $1 >= $2
  version_compare() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
  version_compare "$cmake_ver" "3.13" && cmake_ok=1
fi

if (( ! cmake_ok )); then
  msg "CMake < 3.13 (or not installed) – installing …"
  $UPDATE; $INSTALL cmake
fi

###############################################################################
# 2. System-wide dependencies --------------------------------------------------
SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard )

case "$PM" in
  apt)
    SYS_DEPS+=( python3-venv libxcb-cursor0 libxcb-xinerama0
                libportaudio2 portaudio19-dev )
    ;;
  dnf)
    SYS_DEPS+=( python3-devel python3-virtualenv
                xcb-util-cursor xcb-util-wm
                portaudio portaudio-devel )
    ;;
  pacman)
    SYS_DEPS+=( python-virtualenv xcb-util-cursor xcb-util-wm portaudio )
    ;;
esac

# Extra headers if we need to build ydotool under Wayland
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && ! command -v ydotool >/dev/null; then
  NEED_YDOTOOL=1
  case "$PM" in
    apt)   SYS_DEPS+=(libevdev-dev libudev-dev libconfig++-dev libboost-program-options-dev) ;;
    dnf)   SYS_DEPS+=(libevdev-devel libudev-devel libconfig++-devel boost-program-options-devel) ;;
    pacman)SYS_DEPS+=(libevdev libconfig++ boost) ;;
  esac
fi

msg "Package manager: $PM"
msg "Installing system deps: ${SYS_DEPS[*]}"
$UPDATE; $INSTALL "${SYS_DEPS[@]}"

###############################################################################
# 3. Python virtualenv ---------------------------------------------------------
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
source .venv/bin/activate

python -m pip install --upgrade pip
msg "Installing Python dependencies…"
pip install -r requirements.txt
msg "Installing Whisp package into venv (editable)…"
pip install -e .

###############################################################################
# 4. whisper.cpp ---------------------------------------------------------------
if [[ ! -d whisper.cpp ]]; then
  msg "Cloning whisper.cpp…"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
fi

if [[ ! -x whisper.cpp/build/bin/whisper-cli ]]; then
  msg "Building whisper.cpp…"
  cmake -S whisper.cpp -B whisper.cpp/build
  cmake --build whisper.cpp/build -j"$(nproc)"
else
  ok "whisper.cpp already built."
fi

###############################################################################
# 5. Ensure at least one model -------------------------------------------------
MODEL_DIR="whisper.cpp/models"
MODEL_FILE="$MODEL_DIR/ggml-base.en.bin"

if [[ ! -f $MODEL_FILE ]]; then
  msg "Downloading default Whisper model (base.en)…"
  mkdir -p "$MODEL_DIR"
  curl -L -o "$MODEL_FILE" \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
fi

###############################################################################
# 6. Optional: ydotool under Wayland ------------------------------------------
if [[ ${NEED_YDOTOOL:-0} == 1 ]]; then
  msg "Wayland detected & ydotool missing – building from source…"
  tmpd=$(mktemp -d)
  git clone https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  cmake -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  sudo cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  sudo groupadd -f input
  sudo usermod -aG input "$USER"
  printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' \
    | sudo tee /etc/udev/rules.d/99-uinput.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  rm -rf "$tmpd"
  ok "ydotool installed – log out & back in for group changes."
fi

###############################################################################
# 7. Final message -------------------------------------------------------------
ok "Setup complete!"
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m whisp --mode gui"

# Friendly prompt to fetch the model via the model manager
if ! whisp-model list 2>/dev/null | grep -q "ggml-base.en.bin"; then
  echo
  read -r -p "Download default base.en model now (~142 MB)? [Y/n] " ans
  if [[ $ans =~ ^([yY]|$) ]]; then
    whisp-model install base.en
  else
    echo "You can do it later with:  whisp-model install base.en"
  fi
fi

###############################################################################
# 8. Fast-exit if everything already ready ------------------------------------
# (second / third runs land here almost immediately)
exit 0
