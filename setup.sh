#!/usr/bin/env bash
# =============================================================================
#  VOXT – one-shot installer / updater
#
#  • Installs system packages        (apt | dnf | pacman – auto-detected)
#  • Creates / re-uses Python venv    (.venv)
#  • Installs Python dependencies & VOXT itself (editable)
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

# ────────────────── Pre-flight: ensure curl & internet ──────────────────────
if ! command -v curl >/dev/null; then
  msg "${RED}curl not found – required for downloads.${NC}"
  case "$PM" in
    apt)   echo "Install with: sudo apt install curl"   ;;
    dnf)   echo "Install with: sudo dnf install curl"   ;;
    pacman)echo "Install with: sudo pacman -S curl"     ;;
  esac
  die "Please install curl and re-run setup.sh."
fi

# Detect offline mode (no outbound HTTPS)
OFFLINE=""
if ! curl -s --head https://github.com >/dev/null 2>&1; then
  OFFLINE=1
  msg "${YEL}No internet connectivity – remote downloads will be skipped.${NC}"
fi

# ────────────────── SELinux detection (Fedora) ─────────────────────────────–
SELINUX_ACTIVE=""
if command -v getenforce >/dev/null && [[ $(getenforce) == Enforcing && $PM == dnf ]]; then
    SELINUX_ACTIVE=1
    msg "SELinux enforcing mode detected – will prepare local policy for whisper-cli."
fi

# ──────────────────  0. make sure compilers exist  ───────────────────────────–
need_compiler

# ──────────────────  1. distro-specific dependency list  ────────────────────
case "$PM" in
  apt)
      SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard \
                 python3-venv libxcb-cursor0 libxcb-xinerama0 \
                 libportaudio2 portaudio19-dev )
      ;;
  dnf)
      SYS_DEPS=( git ffmpeg gcc gcc-c++ make cmake curl xclip xsel wl-clipboard \
                 python3-devel python3-virtualenv \
                 xcb-util-cursor-devel xcb-util-wm-devel \
                 portaudio portaudio-devel )
      ;;
  pacman)
      SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard \
                 base-devel python-virtualenv \
                 xcb-util-cursor xcb-util-wm portaudio )
      ;;
esac

# Append SELinux dev package when needed (Fedora only)
if [[ $SELINUX_ACTIVE ]]; then
  SYS_DEPS+=(policycoreutils-devel)
fi

# Helper – install a package, trying an alternate name if provided
install_pkg() {
  local pkg="$1" alt="${2:-}"
  if $INSTALL "$pkg"; then
      return 0
  elif [[ -n "$alt" ]]; then
      $INSTALL "$alt"
  fi
}

# ──────────────────  2. Wayland?  figure out ydotool path  ────────────────────
# Helper to fetch latest release asset URLs from GitHub (no jq dependency)
get_latest_ydotool_asset() {
  [[ $OFFLINE ]] && return 1
  local ext="$1"
  curl -sL https://api.github.com/repos/ReimuNotMoe/ydotool/releases/latest \
    | grep -oE "https://[^\"]+ydotool[^\"]+\.${ext}" | head -n1
}

# Attempt to install pre-built .deb / .rpm released upstream
install_ydotool_prebuilt() {
  case "$PM" in
    apt)
        local url tmp
        url=$(get_latest_ydotool_asset deb) || return 1
        [[ -z "$url" ]] && return 1
        tmp=$(mktemp --suffix=.deb)
        curl -L -o "$tmp" "$url" && sudo dpkg -i "$tmp"
        ;;
    dnf)
        local url tmp
        url=$(get_latest_ydotool_asset rpm) || return 1
        [[ -z "$url" ]] && return 1
        tmp=$(mktemp --suffix=.rpm)
        curl -L -o "$tmp" "$url" && sudo dnf install -y "$tmp"
        ;;
    *) return 1 ;;
  esac
}

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

  msg "ydotool missing – attempting installation…"
  # 1) distro repo
  install_ydotool_pkg || true
  # 2) upstream pre-built package
  if ! command -v ydotool >/dev/null; then
      install_ydotool_prebuilt || true
  fi
  # 3) build from source as last resort
  if ! command -v ydotool >/dev/null; then
      msg "Building ydotool from source (this may take a few minutes)…"
      case "$PM" in
        apt)   SYS_DEPS+=(libevdev-dev libudev-dev libconfig++-dev \
                          libboost-program-options-dev) ;;
        dnf)   SYS_DEPS+=(libevdev-devel libudev-devel libconfig++-devel \
                          boost-program-options-devel) ;;
        pacman)SYS_DEPS+=(libevdev libconfig++ boost) ;;
      esac
      $INSTALL "${SYS_DEPS[@]}" || true
      install_ydotool_src || true
  fi

  # Post-install setup if binary exists
  if command -v ydotool >/dev/null; then
      sudo groupadd -f input
      sudo usermod -aG input "$USER"
      printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' \
          | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null
      sudo udevadm control --reload-rules && sudo udevadm trigger
      systemctl --user daemon-reload
      systemctl --user enable --now ydotoold.service || true
      msg "ydotool installed – log out/in once to refresh group membership."
  else
      msg "${YEL}ydotool could not be installed – VOXT will fall back to clipboard-paste only.${NC}"
  fi
}

# ──────────────────  3. install system packages  ─────────────────────────────–
msg "Installing system deps: ${SYS_DEPS[*]}"

# ---------- 1) try one big transaction ----------
if $INSTALL "${SYS_DEPS[@]}"; then
    msg "System deps installed / already present."
else
    msg "Some packages failed – resolving individually…"
    failed_pkgs=()

    # ---------- 2) fallback: try each package alone ----------
    for pkg in "${SYS_DEPS[@]}"; do
        if ! $INSTALL "$pkg" 2>/dev/null; then
            failed_pkgs+=("$pkg")
        fi
    done

    # ---------- 3) final aliases ----------
    for pkg in "${failed_pkgs[@]}"; do
        case "$pkg" in
          xcb-util-cursor-devel) install_pkg "$pkg" xcb-util-cursor ;;  # Fedora alias
          xcb-util-wm-devel)     install_pkg "$pkg" xcb-util-wm     ;;
          *)                     msg "⚠️  Could not install $pkg (may be obsolete on this distro)" ;;
        esac
    done
fi

# ──────────────────  4. python venv & deps  ─────────────────────────────────––
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
source .venv/bin/activate
# Upgrade pip quietly
python -m pip install -U pip -q
msg "Installing Python dependencies…"
# Prefer binary wheels to avoid noisy C-builds; keep output minimal
PIP_DISABLE_PIP_VERSION_CHECK=1 \
pip install --prefer-binary -q -r requirements.txt
msg "(If you noticed a lengthy C compile: that's 'sounddevice' building against PortAudio headers.)"
msg "Installing VOXT into venv (editable)…"
pip install -e .    > /dev/null

# ──────────────────  5. whisper.cpp (once)  ─────────────────────────────────––
if command -v whisper-cli >/dev/null; then
  # A binary is already available system-wide – reuse it.
  WHISPER_BIN="$(command -v whisper-cli)"
  msg "Found existing whisper-cli at $WHISPER_BIN – skipping source build."
else
  # Build from source inside repo_root/whisper.cpp  (old behaviour)
  if [[ $OFFLINE ]]; then
    msg "Offline mode – skipping whisper.cpp git clone. Assuming sources are present."
  else
    if [[ ! -d whisper.cpp ]]; then
        msg "Cloning whisper.cpp…"
        git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
    fi
  fi
  if [[ ! -x whisper.cpp/build/bin/whisper-cli ]]; then
      msg "Building whisper.cpp (this may take a while)…"
      cmake -S whisper.cpp -B whisper.cpp/build
      cmake --build whisper.cpp/build -j"$(nproc)"
  else
      msg "whisper.cpp already built."
  fi
  WHISPER_BIN="$PWD/whisper.cpp/build/bin/whisper-cli"
fi

# ──────────────────  6. default model  ───────────────────────────────────────–
MODEL_DIR=whisper.cpp/models ; MODEL_FILE=$MODEL_DIR/ggml-base.en.bin
if [[ ! -f $MODEL_FILE ]]; then
  if [[ $OFFLINE ]]; then
    msg "Offline mode – model file not found. Please place ggml-base.en.bin into $MODEL_DIR manually."
  else
    msg "Downloading default Whisper model (base.en)…"
    mkdir -p "$MODEL_DIR"
    curl -L -o "$MODEL_FILE" \
         https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
  fi
fi

# ──────────────────  7. ydotool (Wayland helper)  ─────────────────────────────
ensure_ydotool

# ──────────────────  8. symlink whisper-cli to ~/.local/bin  ─────────────────
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
if [[ ! -e "$LOCAL_BIN/whisper-cli" ]]; then
  ln -s "$WHISPER_BIN" "$LOCAL_BIN/whisper-cli"
  msg "Symlinked whisper-cli to $LOCAL_BIN/whisper-cli"
else
  msg "whisper-cli already present in $LOCAL_BIN"
fi

# ──────────────────  8b. persist absolute paths in config.yaml  ──────────────
python - <<PY
from pathlib import Path
from voxt.core.config import AppConfig
cfg = AppConfig()
cfg.set("whisper_binary", str(Path("$WHISPER_BIN").resolve()))
cfg.set("model_path", str(Path("$PWD/whisper.cpp/models/ggml-base.en.bin").resolve()))
cfg.save()
print("[setup] Absolute paths written to ~/.config/voxt/config.yaml")
PY

# ──────────────────  9. done  ───────────────────────────────────────────────––
msg "${GRN}Setup complete!${NC}"
# Wayland reminder for ydotool permissions
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && command -v ydotool >/dev/null; then
  echo "ℹ️  Wayland detected – please log out and back in so 'ydotool' gains access to /dev/uinput."
fi
echo "Activate venv:   source .venv/bin/activate"
echo "Run GUI mode:    python -m voxt --mode gui"
echo "---> see in README.md on easy use setup."

# ──────────────────  5b. SELinux policy for whisper-cli  ────────────────────
if [[ $SELINUX_ACTIVE ]]; then
  msg "Configuring SELinux policy for whisper-cli (execmem)…"
  cat > whisper_execmem.te <<'EOF'
module whisper_execmem 1.0;
require {
    type user_home_t;
    class process execmem;
}
allow user_home_t self:process execmem;
EOF
  checkmodule -M -m -o whisper_execmem.mod whisper_execmem.te
  semodule_package -o whisper_execmem.pp -m whisper_execmem.mod
  sudo semodule -i whisper_execmem.pp
  rm -f whisper_execmem.te whisper_execmem.mod whisper_execmem.pp
fi

# SELinux reminder
if [[ $SELINUX_ACTIVE ]]; then
  echo "ℹ️  SELinux policy 'whisper_execmem' installed. If whisper-cli still throws execmem denials, consult README or run 'sudo setenforce 0' for a temporary test."
fi

# ────────────────── 10. optional pipx global install  ───────────────────────
# Offer to install pipx (if missing) and register voxt command globally.

if ! command -v pipx >/dev/null; then
  read -r -p "pipx not detected – install pipx for a global 'voxt' command? [Y/n]: " reply
  reply=${reply:-Y}
  if [[ $reply =~ ^[Yy]$ ]]; then
    case "$PM" in
      apt)   sudo apt install -y pipx ;;
      dnf)   sudo dnf install -y pipx ;;
      pacman)sudo pacman -S --noconfirm pipx ;;
    esac
    pipx ensurepath
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

if command -v pipx >/dev/null; then
  read -r -p "Install voxt into pipx (global command) now? [Y/n]: " ans
  ans=${ans:-Y}
  if [[ $ans =~ ^[Yy]$ ]]; then
    pipx install --force "$PWD"
    echo "✔  'voxt' command installed globally via pipx. Open a new shell if not yet on PATH."
  else
    echo "You can later run: pipx install $PWD"
  fi
else
  echo "pipx not available – skip global command install. You can install pipx later."
fi
