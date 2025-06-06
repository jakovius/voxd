#!/usr/bin/env bash
# =============================================================================
#  Whisp – interactive installer for a fresh git-clone
#
#  ↳ 100 % hands-free: if compilers or other base tools are missing,
#    they are installed automatically via the detected package manager.
#
#  • Installs system packages      (apt / dnf / pacman – auto-detected)
#  • Creates / re-uses a Python venv   (.venv)
#  • Installs Python deps from requirements.txt
#  • Clones + builds whisper.cpp   → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) builds & enables ydotool if it isn’t on the system
#
#  Idempotent: re-running does nothing if everything is already in place.
# =============================================================================
set -euo pipefail

# -----------------------------------------------------------------------------
# 0. Detect package manager early (needed to self-install gcc/g++)
detect_pkg() {
  if   command -v apt   >/dev/null; then
       PM=apt
       INSTALL="sudo apt-get install -y"
       UPDATE="sudo apt-get update -y"
       BUILD_GROUP="build-essential"
  elif command -v dnf   >/dev/null; then
       PM=dnf
       INSTALL="sudo dnf install -y"
       UPDATE="sudo dnf makecache"
       BUILD_GROUP="@development-tools"
  elif command -v pacman>/dev/null; then
       PM=pacman
       INSTALL="sudo pacman -S --noconfirm"
       UPDATE="sudo pacman -Sy"
       BUILD_GROUP="base-devel"
  else
       echo "setup.sh: unsupported distro – need apt, dnf or pacman." >&2
       exit 1
  fi
}
detect_pkg

# -----------------------------------------------------------------------------
# Colour helpers
YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[0;31m'; NC='\033[0m'
msg() { printf "${YEL}==>${NC} %b\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

[[ $EUID == 0 ]] && die "Run this as a normal user, not root."

# -----------------------------------------------------------------------------
# 1. Ensure C / C++ tool-chain exists – install it on the fly if absent
need_build_tools=""
for tool in gcc g++; do
  if ! command -v "$tool" >/dev/null 2>&1; then
     need_build_tools=1; break
  fi
done

if [[ -n $need_build_tools ]]; then
  msg "Compilers not found – installing ${BUILD_GROUP} …"
  $UPDATE
  $INSTALL "$BUILD_GROUP"
fi

# 2. Check CMake ≥ 3.13 --------------------------------------------------------
cmake_version=$(cmake --version 2>/dev/null | awk '/version/ {print $3}')
ver_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
if [[ -z $cmake_version || ! ver_ge "$cmake_version" "3.13" ]]; then
  msg "CMake < 3.13 detected – installing an up-to-date CMake …"
  case "$PM" in
    apt)   $UPDATE && $INSTALL cmake ;;
    dnf)   $INSTALL cmake ;;
    pacman)$INSTALL cmake ;;
  esac
fi

# -----------------------------------------------------------------------------
# 3. Common + distro-specific system deps
SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard )

case "$PM" in
  apt)
    SYS_DEPS+=( build-essential python3-venv
                libxcb-cursor0 libxcb-xinerama0
                libportaudio2 portaudio19-dev )
    ;;
  dnf)
    SYS_DEPS+=( $BUILD_GROUP          # group already ensures gcc/g++
                python3-devel python3-virtualenv
                xcb-util-cursor xcb-util-wm
                portaudio portaudio-devel )
    ;;
  pacman)
    SYS_DEPS+=( base-devel python-virtualenv
                xcb-util-cursor xcb-util-wm
                portaudio )
    ;;
esac

# Extra headers for ydotool on Wayland
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && ! command -v ydotool >/dev/null; then
  NEED_YDOTOOL=1
  case "$PM" in
    apt)   SYS_DEPS+=(libevdev-dev libudev-dev libconfig++-dev \
                      libboost-program-options-dev) ;;
    dnf)   SYS_DEPS+=(libevdev-devel libudev-devel libconfig++-devel \
                      boost-program-options-devel) ;;
    pacman)SYS_DEPS+=(libevdev libconfig++ boost) ;;
  esac
fi

msg "Package manager: $PM"
msg "Installing system deps: ${SYS_DEPS[*]}"
$UPDATE
$INSTALL "${SYS_DEPS[@]}"

# -----------------------------------------------------------------------------
# 4. Python virtual environment ------------------------------------------------
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

# -----------------------------------------------------------------------------
# 5. Clone + build whisper.cpp -------------------------------------------------
if [[ ! -d whisper.cpp ]]; then
  msg "Cloning whisper.cpp…"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
fi

if [[ ! -x whisper.cpp/build/bin/whisper-cli ]]; then
  msg "Building whisper.cpp (first run only)…"
  cmake -S whisper.cpp -B whisper.cpp/build
  cmake --build whisper.cpp/build -j"$(nproc)"
else
  msg "whisper.cpp already built."
fi

# -----------------------------------------------------------------------------
# 6. Ensure at least one model is present -------------------------------------
MODEL_DIR="whisper.cpp/models"
MODEL_FILE="$MODEL_DIR/ggml-base.en.bin"
if [[ ! -f $MODEL_FILE ]]; then
  msg "Downloading default Whisper model (base.en)…"
  mkdir -p "$MODEL_DIR"
  curl -L -o "$MODEL_FILE" \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
fi

# -----------------------------------------------------------------------------
# 7. Optional: ydotool on Wayland ---------------------------------------------
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

# -----------------------------------------------------------------------------
# 8. Finished -----------------------------------------------------------------
msg "${GRN}Setup complete!${NC}"
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
