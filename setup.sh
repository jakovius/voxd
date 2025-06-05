#!/usr/bin/env bash
# =============================================================================
#  Whisp – interactive installer for a fresh git-clone
#
#  • Installs system packages      (apt / dnf / pacman – auto-detected)
#  • Creates / re-uses a Python venv   (.venv)
#  • Installs Python deps from requirements.txt
#  • Clones + builds whisper.cpp   → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) builds & enables ydotool if it isn’t on the system
#
#  Idempotent: re-running does nothing if everything is already in place.
# =============================================================================
+set -euo pipefail   # fail fast, undefined vars are errors, pipelines propagate rc

# -----------------------------------------------------------------------------#
# Colours + helpers (define once – we delete the duplicate further down)
YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[0;31m'; NC='\033[0m'
msg() { printf "${YEL}==>${NC} %b\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

# DEBUG=1 ./setup.sh  → prints every command
[[ ${DEBUG:-0} == 1 ]] && set -x

# -----------------------------------------------------------------------------#
# 1) Verify compilers exist ----------------------------------------------------
for tool in gcc g++; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    die "Required compiler \"$tool\" is missing – try: sudo dnf install gcc-c++"
  fi
done

# 2) Check CMake version -------------------------------------------------------
cmake_version=$(cmake --version | awk '/version/ {print $3}')
ver_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
if ! ver_ge "$cmake_version" "3.13"; then
  die "CMake ≥ 3.13 required, found $cmake_version"
fi

# --- pretty printing ---------------------------------------------------------
YEL='\033[1;33m'; GRN='\033[1;32m'; RED='\033[0;31m'; NC='\033[0m'
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
  elif command -v pacman>/dev/null; then
       PM=pacman
       INSTALL="sudo pacman -S --noconfirm"
  else
       die "Unsupported distro – need apt, dnf or pacman."
  fi
}
detect_pkg; msg "Package manager: $PM"

# -----------------------------------------------------------------------------#
# 1. System packages
#    – first the *common* bits, then a case-block adds / overrides distro names
SYS_DEPS=(
  git ffmpeg gcc make cmake curl
  xclip xsel wl-clipboard                # clipboard helpers
)

case "$PM" in
  apt)
    SYS_DEPS+=(
      build-essential python3-venv
      libxcb-cursor0 libxcb-xinerama0
      libportaudio2 portaudio19-dev
    )
    ;;

  dnf)
    SYS_DEPS+=(
      "@development-tools"     # group: gcc make … (no longer pulls gcc-c++)
      gcc-c++                  # C++ front-end needed by whisper.cpp
      python3-devel python3-virtualenv
      xcb-util-cursor xcb-util-wm
      portaudio portaudio-devel
    )
    ;;

  pacman)
    SYS_DEPS+=(
      base-devel python-virtualenv
      xcb-util-cursor xcb-util-wm
      portaudio
    )
    ;;
esac

# Extra headers only needed when we have to build ydotool (Wayland)
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && ! command -v ydotool >/dev/null; then
  NEED_YDOTOOL=1
  case "$PM" in
    apt)   SYS_DEPS+=(libevdev-dev  libudev-dev  libconfig++-dev  libboost-program-options-dev) ;;
    dnf)   SYS_DEPS+=(libevdev-devel libudev-devel libconfig++-devel boost-program-options-devel) ;;
    pacman)SYS_DEPS+=(libevdev  libconfig++  boost) ;;   # Arch’s libudev is in systemd-libs
  esac
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
# 3. Clone + build whisper.cpp  (local to repo) -------------------------------
if [[ ! -d whisper.cpp ]]; then
  msg "Cloning whisper.cpp…"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
fi

if [[ ! -x whisper.cpp/build/bin/whisper-cli ]]; then
  msg "Building whisper.cpp (first time only)…"
  cmake -S whisper.cpp -B whisper.cpp/build
  # We temporarily drop '-e' so we can inspect the result and print a nicer error.
  set +e
  cmake --build whisper.cpp/build -j"$(nproc)"
  build_rc=$?
  set -e
  if (( build_rc != 0 )); then
    cat <<EOF >&2

${RED}🚨 whisper.cpp build failed (exit $build_rc)${NC}
See: whisper.cpp/build/CMakeFiles/CMakeError.log  (and CMakeOutput.log)

EOF
    exit $build_rc
  fi
else
  msg "whisper.cpp already built."
fi

# -----------------------------------------------------------------------------#
# 4. Ensure there is at least one model in place
MODEL_DIR="whisper.cpp/models"
MODEL_FILE="$MODEL_DIR/ggml-base.en.bin"
if [[ ! -f $MODEL_FILE ]]; then
  echo "→ Downloading default Whisper model (base.en)…"
  mkdir -p "$MODEL_DIR"
  curl -L -o "$MODEL_FILE" \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
fi

# -----------------------------------------------------------------------------#
# 5. Optional: ydotool on Wayland
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
# 6. Done
msg "${GRN}Setup complete!${NC}"
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m whisp --mode gui"

# -----------------------------------------------------------------------------#
# 7. Offer to install the model via model manager (optional, nicer UX)
if ! whisp-model list | grep -q "ggml-base.en.bin" 2>/dev/null; then
  echo
  read -r -p "Download default base.en model now (~142 MB)? [Y/n] " ans
  if [[ $ans =~ ^([yY]|$) ]]; then
      whisp-model install base.en
  else
      echo "You can do it later with:  whisp-model install base.en"
  fi
fi
