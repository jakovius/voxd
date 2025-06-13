#!/usr/bin/env bash
# =============================================================================
#  Whisp – one-shot installer / updater
#
#  • Installs system packages        (apt | dnf | pacman – auto-detected)
#  • Creates / re-uses Python venv    (.venv)
#  • Installs Python dependencies & Whisp itself (editable)
#  • Clones + builds whisper.cpp      → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) ensures ydotool + daemon, with fallback source build
#
#  Idempotent: re-running skips finished steps.
# =============================================================================
set -euo pipefail

# ───────────────────────────── helpers ────────────────────────────────────────
YEL=$'\033[1;33m'; GRN=$'\033[1;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'
msg() { printf "${YEL}==>${NC} %s\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }
[[ $EUID == 0 ]] && die "Run as a normal user, not root."

# bail out on missing cmd, or install compiler tool-chain on the fly
need_compiler() {
  if command -v gcc >/dev/null 2>&1 && command -v g++ >/dev/null 2>&1; then
    return 0
  fi
  msg "Compilers not found – installing build tools …"
  case "$PM" in
    apt)   sudo apt update -qq && sudo apt install -y build-essential ;;
    dnf)   sudo dnf groupinstall -y "Development Tools" ;;
    pacman)sudo pacman -Sy --noconfirm base-devel ;;
  esac
}

# version compare  ver_ge <found> <needed-min>
ver_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

# ─────────────────── detect distro / pkg-manager ──────────────────────────────
if   command -v apt   >/dev/null; then
     PM=apt   ; INSTALL="sudo apt install -y"
elif command -v dnf   >/dev/null; then
     PM=dnf   ; INSTALL="sudo dnf install -y"
elif command -v pacman>/dev/null; then
     PM=pacman; INSTALL="sudo pacman -S --noconfirm"
else die "Unsupported distro – need apt, dnf or pacman."; fi
msg "Package manager: $PM"

# ──────────────────  0. make sure compilers exist  ───────────────────────────–
need_compiler

# ──────────────────  1. common system deps list  ─────────────────────────────–
SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard )

case "$PM" in
  apt)   SYS_DEPS+=(python3-venv libxcb-cursor0 libxcb-xinerama0
                    libportaudio2 portaudio19-dev) ;;
  dnf)   SYS_DEPS+=("@development-tools" gcc-c++
                    python3-devel python3-virtualenv
                    xcb-util-cursor xcb-util-wm
                    portaudio portaudio-devel) ;;
  pacman)SYS_DEPS+=(base-devel python-virtualenv
                    xcb-util-cursor xcb-util-wm portaudio) ;;
esac

# ──────────────────  2. Wayland?  figure out ydotool path  ────────────────────
install_ydotool_pkg() {
  case "$PM" in
    apt)   $INSTALL ydotool   && return 0 ;;
    dnf)   $INSTALL ydotool   && return 0 ;;
    pacman)$INSTALL ydotool   && return 0 || true ;;   # Arch users might use AUR
  esac
  return 1
}

install_ydotool_src() {
  msg "Building ydotool from source (docs disabled)…"
  tmpd=$(mktemp -d)
  git clone --depth 1 https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  cmake -DENABLE_DOCUMENTATION=OFF -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  sudo cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  rm -rf "$tmpd"
}

ensure_ydotool() {
  # only on Wayland and if not in $PATH
  [[ ${XDG_SESSION_TYPE:-} != wayland* ]] && return 0
  command -v ydotool >/dev/null && return 0

  msg "ydotool missing – trying distro package first…"
  if ! install_ydotool_pkg; then
     # add build deps that our distro doesn't already have
     case "$PM" in
       apt)   SYS_DEPS+=(libevdev-dev libudev-dev libconfig++-dev \
                         libboost-program-options-dev) ;;
       dnf)   SYS_DEPS+=(libevdev-devel libudev-devel libconfig++-devel \
                         boost-program-options-devel) ;;
       pacman)SYS_DEPS+=(libevdev libconfig++ boost) ;;
     esac
     $INSTALL "${SYS_DEPS[@]}"      # top-up missing headers, if any
     install_ydotool_src
  fi

  # groups / uinput
  sudo groupadd -f input
  sudo usermod -aG input "$USER"
  printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' \
      | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null
  sudo udevadm control --reload-rules && sudo udevadm trigger

  # enable & start the per-user daemon
  systemctl --user daemon-reload
  systemctl --user enable --now ydotoold.service || true

  msg "ydotool installed – log out/in once to refresh group membership."
}

# ──────────────────  3. install system packages  ─────────────────────────────–
msg "Installing system deps: ${SYS_DEPS[*]}"
$INSTALL "${SYS_DEPS[@]}"

# ──────────────────  4. python venv & deps  ─────────────────────────────────––
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -U pip > /dev/null
msg "Installing Python dependencies…"
pip install -r requirements.txt > /dev/null
msg "Installing Whisp into venv (editable)…"
pip install -e .    > /dev/null

# ──────────────────  5. whisper.cpp (once)  ─────────────────────────────────––
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

# ──────────────────  6. default model  ───────────────────────────────────────–
MODEL_DIR=whisper.cpp/models ; MODEL_FILE=$MODEL_DIR/ggml-base.en.bin
if [[ ! -f $MODEL_FILE ]]; then
  msg "Downloading default Whisper model (base.en)…"
  mkdir -p "$MODEL_DIR"
  curl -L -o "$MODEL_FILE" \
       https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
fi

# ──────────────────  7. ydotool (Wayland helper)  ─────────────────────────────
ensure_ydotool

# ──────────────────  8. symlink whisper-cli to ~/.local/bin  ─────────────────
WHISPER_BIN="$PWD/whisper.cpp/build/bin/whisper-cli"
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
if [[ ! -e "$LOCAL_BIN/whisper-cli" ]]; then
  ln -s "$WHISPER_BIN" "$LOCAL_BIN/whisper-cli"
  msg "Symlinked whisper-cli to $LOCAL_BIN/whisper-cli"
else
  msg "whisper-cli already present in $LOCAL_BIN"
fi

# ──────────────────  9. done  ───────────────────────────────────────────────––
msg "${GRN}Setup complete!${NC}"
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m whisp --mode gui"
