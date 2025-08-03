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
    dnf5)  sudo dnf5 group install -y "Development Tools" ;;
    pacman)sudo pacman -Sy --noconfirm base-devel ;;
esac
}

# version compare  ver_ge <found> <needed-min>
ver_ge() { [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

# ─────────────────── detect distro / pkg-manager ──────────────────────────────
if   command -v apt   >/dev/null; then
     PM=apt   ; INSTALL="sudo apt install -y"
elif command -v dnf5  >/dev/null; then
     PM=dnf5  ; INSTALL="sudo dnf5 install -y"
elif command -v dnf   >/dev/null; then
     PM=dnf   ; INSTALL="sudo dnf install -y"
elif command -v pacman>/dev/null; then
     PM=pacman; INSTALL="sudo pacman -S --noconfirm"
else die "Unsupported distro – need apt, dnf/dnf5 or pacman."; fi
msg "Package manager: $PM"

# ────────────────── Pre-flight: ensure curl, git & internet ──────────────────────
for cmd in curl git; do
  if ! command -v "$cmd" >/dev/null; then
    msg "$cmd missing – installing…"
    case "$PM" in
      apt)   sudo apt update -qq && sudo apt install -y "$cmd" ;;
      dnf|dnf5) sudo $PM install -y "$cmd" ;;
      pacman) sudo pacman -Sy --noconfirm "$cmd" ;;
    esac
  fi
done

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
      SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard xdotool \
                 python3-venv libxcb-cursor0 libxcb-xinerama0 \
                 libportaudio2 portaudio19-dev )
      ;;
  dnf)
      SYS_DEPS=( git ffmpeg gcc gcc-c++ make cmake curl xclip xsel wl-clipboard xdotool \
                 python3-devel python3-virtualenv \
                 xcb-util-cursor-devel xcb-util-wm-devel \
                 portaudio portaudio-devel )
      ;;
  pacman)
      SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard xdotool \
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

  # Temporarily disable exit-on-error for installation attempts
  set +e

  # 1) distro repo
  install_ydotool_pkg
  # 2) upstream pre-built package
  if ! command -v ydotool >/dev/null; then
      install_ydotool_prebuilt
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
      $INSTALL "${SYS_DEPS[@]}"
      install_ydotool_src
  fi

  # Re-enable exit-on-error
  set -e

  # Post-install setup if binary exists
  if command -v ydotool >/dev/null; then
      sudo groupadd -f input || true
      sudo usermod -aG input "$USER" || true
      printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' \
          | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null || true
      sudo udevadm control --reload-rules || true
      sudo udevadm trigger || true
      systemctl --user daemon-reload || true
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
# src/setup.sh  (just after source .venv/bin/activate)
if ! command -v python >/dev/null && command -v python3 >/dev/null; then
  ln -s "$(command -v python3)" "$(dirname "$(command -v python3)")/python"
fi
PY=python3         # use python3 explicitly from here on
$PY -m pip install -U pip -q
msg "Installing Python dependencies…"
# Prefer binary wheels to avoid noisy C-builds; keep output minimal
PIP_DISABLE_PIP_VERSION_CHECK=1 \
pip install --prefer-binary -q -r requirements.txt
# Ensure recent hatch for editable install
$PY -m pip install -q --upgrade "hatchling>=1.24" hatch-vcs
msg "(If you noticed a lengthy C compile: that's 'sounddevice' building against PortAudio headers.)"
msg "Installing VOXT into venv (editable)…"
pip install -e .    > /dev/null

# Fix editable install .pth file if it's empty (hatchling bug workaround)
PTH_FILE=".venv/lib/python3.12/site-packages/_voxt.pth"
if [[ -f "$PTH_FILE" && ! -s "$PTH_FILE" ]]; then
  echo "$PWD/src" > "$PTH_FILE"
  msg "Fixed editable install .pth file"
fi

# ──────────────────  5. whisper.cpp (once)  ─────────────────────────────────––
WHISPER_BIN=""  # Initialize to prevent unbound variable errors

if command -v whisper-cli >/dev/null; then
  # A binary is already available system-wide – reuse it.
  WHISPER_BIN="$(command -v whisper-cli)"
  # Resolve to real location to avoid symlink loops later
  RESOLVED_BIN="$(readlink -f "$WHISPER_BIN" 2>/dev/null || true)"
  
  # Ensure we don't use the symlink itself as target
  if [[ -n "$RESOLVED_BIN" && "$RESOLVED_BIN" != "$HOME/.local/bin/whisper-cli" ]]; then
    WHISPER_BIN="$RESOLVED_BIN"
    msg "Found existing whisper-cli at $WHISPER_BIN – skipping source build."
  else
    # Symlink is broken or points to itself - rebuild from source
    msg "Found broken whisper-cli symlink – rebuilding from source."
    rm -f "$HOME/.local/bin/whisper-cli"  # Remove broken symlink
    WHISPER_BIN=""  # Force rebuild
  fi
fi

# Build from source if no valid binary found
if [[ -z "$WHISPER_BIN" ]]; then
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
      cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF
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
SYMLINK_PATH="$LOCAL_BIN/whisper-cli"

# Ensure we have a valid binary path (not a symlink)
if [[ -L "$WHISPER_BIN" ]]; then
  REAL_BIN=$(readlink -f "$WHISPER_BIN" 2>/dev/null || echo "$WHISPER_BIN")
else
  REAL_BIN="$WHISPER_BIN"
fi

# Prevent circular symlinks
if [[ "$REAL_BIN" == "$SYMLINK_PATH" ]]; then
   msg "whisper-cli symlink would point to itself – skipping to avoid loop."
elif [[ ! -f "$REAL_BIN" ]]; then
   msg "Warning: whisper-cli binary not found at $REAL_BIN – skipping symlink creation."
else
   # Remove any existing symlink/file first
   if [[ -L "$SYMLINK_PATH" ]]; then
      rm -f "$SYMLINK_PATH"
   elif [[ -e "$SYMLINK_PATH" ]]; then
      msg "File named whisper-cli already exists at $SYMLINK_PATH – leaving untouched."
      REAL_BIN=""  # Skip symlink creation
   fi
   
   # Create new symlink if safe to do so
   if [[ -n "$REAL_BIN" ]]; then
      ln -s "$REAL_BIN" "$SYMLINK_PATH"
      msg "Symlinked whisper-cli to $SYMLINK_PATH"
   fi
fi

# ──────────────────  8b. persist absolute paths in config.yaml  ──────────────
if [[ -n "$WHISPER_BIN" ]]; then
  $PY - <<PY
import sys, os
from pathlib import Path

# Add repo src to import path
repo_src = Path(os.getcwd()) / "src"
if repo_src.exists():
    sys.path.insert(0, str(repo_src))

try:
    from voxt.core.config import AppConfig  # type: ignore
except ModuleNotFoundError as e:
    print("[setup] Warning: could not import voxt (", e, ") – skipping config update.")
    sys.exit(0)

_p = Path("$WHISPER_BIN")
try:
    whisper_bin = _p.resolve()
except RuntimeError:
    whisper_bin = _p.absolute()
model_path = Path(os.getcwd()) / "whisper.cpp" / "models" / "ggml-base.en.bin"

cfg = AppConfig()
cfg.set("whisper_binary", str(whisper_bin))
cfg.set("model_path", str(model_path))
cfg.save()
print("[setup] Absolute paths written to ~/.config/voxt/config.yaml")
PY
else
  msg "Warning: No whisper-cli binary found – skipping config update."
fi

# ──────────────────  9. done  ───────────────────────────────────────────────––
msg "${GRN}Setup complete!${NC}"
# Wayland reminder for ydotool permissions
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]] && command -v ydotool >/dev/null; then
  echo -e "${GRN}➡  IMPORTANT:${NC} Log out or reboot once so 'ydotool' gains access to /dev/uinput."; read -n1 -r -p "Press any key to acknowledge…"
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
      dnf|dnf5)   sudo $PM install -y pipx ;;
      pacman)
        if ! sudo pacman -S --noconfirm pipx; then
          sudo pacman -S --noconfirm python-pipx || true
        fi ;;
    esac
    pipx ensurepath
    export PATH="$HOME/.local/bin:$PATH"
    # Refresh current shell PATH for the remainder of this script
    if [[ $SHELL =~ /bash$ ]] && [[ -f "$HOME/.bashrc" ]]; then source "$HOME/.bashrc"; fi
    if [[ $SHELL =~ /zsh$ ]]  && [[ -f "$HOME/.zshrc"  ]]; then source "$HOME/.zshrc" ; fi
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

# ────────────────── 11. Hotkey Setup Assistant  ─────────────────────────────
# Delegate hotkey setup to the specialized hotkey_setup.sh tool

setup_voxt_hotkey() {
  if [[ -x "./hotkey_setup.sh" ]]; then
    echo ""
    msg "Setting up VOXT hotkey..."
    echo "Using specialized hotkey setup tool for better reliability and safety."
    echo ""
    
    read -r -p "Open the Hotkey Guide & diagnostics? (instructions only – nothing will be changed) [Y/n]: " setup_hotkey
    setup_hotkey=${setup_hotkey:-Y}
    
    if [[ $setup_hotkey =~ ^[Yy]$ ]]; then
      ./hotkey_setup.sh guide
    else
      echo ""
      echo "🔧 Hotkey setup skipped. You can set it up later with:"
      echo "  ./hotkey_setup.sh guide    - GUI setup instructions"
      echo "  ./hotkey_setup.sh diagnose - Troubleshoot issues"
      echo "  ./hotkey_setup.sh list     - Check current status"
    fi
  else
    echo ""
    msg "⚠️  hotkey_setup.sh not found or not executable"
    echo "Manual hotkey setup required:"
    echo "  Command: bash -c 'voxt --trigger-record'"
    echo "  Key: your choice (e.g., Super+R)"
    echo "  Path: System Settings → Keyboard → Custom Shortcuts"
  fi
}

# Main hotkey setup prompt
if command -v voxt >/dev/null 2>&1; then
  setup_voxt_hotkey
fi
