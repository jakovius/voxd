#!/usr/bin/env bash
# =============================================================================
#  Whisp – one-shot interactive installer for a fresh git-clone
#
#  • Installs system packages   (apt / dnf / pacman – auto-detected)
#  • Creates / re-uses Python venv (.venv) and installs requirements
#  • Clones + builds whisper.cpp  → whisper.cpp/build/bin/whisper-cli
#  • Builds & enables ydotool (Wayland) or ensures xdotool (X11)
#  • Downloads a default Whisper model if missing
#
#  Idempotent: re-running is always safe.
# -----------------------------------------------------------------------------
#  Usage:
#     ./setup.sh            # normal
#     DEBUG=1 ./setup.sh    # verbose trace  (set -x)
# =============================================================================

set -euo pipefail
[[ ${DEBUG:-0} == 1 ]] && set -x   # enable bash tracing when DEBUG=1

# ---- colourised pretty-printing ---------------------------------------------
YEL=$'\033[1;33m'; GRN=$'\033[1;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'
msg() { printf "${YEL}==>${NC} %s\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

[[ $EUID == 0 ]] && die "Run as a normal user, not root."

# ---- 1. Verify compilers & CMake --------------------------------------------
for tool in gcc g++; do
  command -v "$tool" >/dev/null 2>&1 || \
    die "Required compiler \"$tool\" missing – try: sudo dnf install gcc-c++"
done

command -v cmake >/dev/null 2>&1 || \
  die "CMake is required – install it via your package manager."

cmake_version=$(cmake --version | awk '/version/ {print $3}')
ver_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }
ver_ge "$cmake_version" "3.13" \
  || die "CMake ≥ 3.13 required, found $cmake_version"

# ---- 2. Detect package manager ----------------------------------------------
detect_pkg() {
  if   command -v apt   >/dev/null; then
       PM=apt;    INSTALL="sudo apt install -y"
  elif command -v dnf   >/dev/null; then
       PM=dnf;    INSTALL="sudo dnf install -y"
  elif command -v pacman>/dev/null; then
       PM=pacman; INSTALL="sudo pacman -S --noconfirm"
  else
       die "Unsupported distro – need apt, dnf or pacman."
  fi
}
detect_pkg; msg "Package manager: $PM"

# ---- 3. System-level dependencies -------------------------------------------
SYS_DEPS=(
  git ffmpeg gcc make cmake curl
  xclip xsel wl-clipboard               # clipboard helpers
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
      "@development-tools"
      gcc-c++ python3-devel python3-virtualenv
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

# X11 needs xdotool, Wayland may need ydotool
if [[ ${XDG_SESSION_TYPE:-x11} != wayland* ]]; then
  command -v xdotool >/dev/null 2>&1 || SYS_DEPS+=(xdotool)
fi

msg "Installing system deps: ${SYS_DEPS[*]}"
$INSTALL "${SYS_DEPS[@]}"

# ---- 4. Python virtual environment ------------------------------------------
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

pip install --upgrade pip
msg "Installing Python dependencies…"
pip install -r requirements.txt

msg "Installing Whisp package into venv (editable)…"
pip install -e .

# ---- 5. Clone + build whisper.cpp -------------------------------------------
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

# ---- 6. Ensure at least one model -------------------------------------------
MODEL_DIR="whisper.cpp/models"
MODEL_FILE="$MODEL_DIR/ggml-base.en.bin"
if [[ ! -f $MODEL_FILE ]]; then
  msg "Downloading default Whisper model (base.en)…"
  mkdir -p "$MODEL_DIR"
  curl -L -o "$MODEL_FILE" \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
fi

# ---- 7. Wayland only: build ydotool if needed -------------------------------
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && ! command -v ydotool >/dev/null; then
  msg "Wayland detected and ydotool missing – building from source…"
  tmpd=$(mktemp -d)
  git clone https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  cmake -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  sudo cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  sudo groupadd -f input
  sudo usermod -aG input "$USER"
  printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' | \
      sudo tee /etc/udev/rules.d/99-uinput.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger
  rm -rf "$tmpd"
  msg "ydotool installed – log out & back in for group changes."
fi

# ---- 8. Offer nicer model-manager download (if still missing) ---------------
if [[ ! -f $MODEL_FILE ]] && ! whisp-model list 2>/dev/null | grep -q "ggml-base.en.bin"; then
  echo
  read -r -p "Download default base.en model now via model-manager (~142 MB)? [Y/n] " ans
  [[ $ans =~ ^([nN])$ ]] || whisp-model install base.en
fi

# ---- 9. Done ----------------------------------------------------------------
msg "${GRN}Setup complete!${NC}"
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m whisp --mode gui"
