#!/usr/bin/env bash
# =============================================================================
#  VOXD – one-shot installer / updater
#
#  • Installs system packages        (apt | dnf | pacman – auto-detected)
#  • Creates / re-uses Python venv    (.venv)
#  • Installs Python dependencies & VOXD itself (editable)
#  • Clones + builds whisper.cpp      → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) ensures ydotool + daemon, validates completeness, forces source build if needed
#
#  Idempotent: re-running skips finished steps.
# =============================================================================
set -euo pipefail

# ────────────────── Setup logging ─────────────────────────────────────────────
LOG_FILE="$(date +%F)-setup-log.txt"
# Quiet console: keep original stdout on FD 3, send all output to log by default
exec 3>&1
exec >"$LOG_FILE" 2>&1

# ───────────────────────────── helpers ────────────────────────────────────────
YEL=$'\033[1;33m'; GRN=$'\033[1;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'
# Log-only message (console is quiet by default)
msg() { printf "==> %s\n" "$*"; }
# Console + log message
note() { printf "${YEL}==>${NC} %s\n" "$*" >&3; printf "==> %s\n" "$*"; }
# Fatal error: print to console and log, then exit
die() { printf "${RED}error:${NC} %s\n" "$*" >&3; printf "error: %s\n" "$*" >&2; exit 1; }

# ────────────────── Minimal CLI spinner/step helpers ──────────────────────────
SPINNER_PID=""; SPINNER_MSG="";
spinner_start() {
  SPINNER_MSG="$1"
  # Print initial line on console
  printf "%s " "$SPINNER_MSG" >&3
  # Hide cursor if possible
  tput civis 2>/dev/null || true
  (
    # spinner loop
    i=0
    frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    while true; do
      printf "\r%s %s" "$SPINNER_MSG" "${frames[$((i%10))]}" >&3
      i=$((i+1))
      sleep 0.1
    done
  ) &
  SPINNER_PID=$!
}
spinner_stop() {
  local rc=${1:-0}
  if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
    kill "$SPINNER_PID" 2>/dev/null || true
    wait "$SPINNER_PID" 2>/dev/null || true
  fi
  # Restore cursor
  tput cnorm 2>/dev/null || true
  if [[ $rc -eq 0 ]]; then
    printf "\r%s ${GRN}✓${NC}\n" "$SPINNER_MSG" >&3
  else
    printf "\r%s ${RED}✗${NC}\n" "$SPINNER_MSG" >&3
  fi
  SPINNER_PID=""; SPINNER_MSG="";
}

# Ensure spinner stops on unexpected errors
trap 'spinner_stop 1 2>/dev/null || true' ERR
# Always restore cursor / kill spinner on exit or signals
trap 'tput cnorm 2>/dev/null || true; [[ -n "$SPINNER_PID" ]] && kill "$SPINNER_PID" 2>/dev/null || true' EXIT INT TERM

# Current script directory (repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Tell user where logs will be written
note "VOXD setup started. Log: $(pwd)/$LOG_FILE"
note "Requesting sudo access (may prompt once)"
sudo -v || true

# ────────────────── Launcher helpers (auto-install) ───────────────────────────
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
ICON_DIR_64="$HOME/.local/share/icons/hicolor/64x64/apps"
ICON_DEST="$ICON_DIR/voxd.png"
ICON_DEST_64="$ICON_DIR_64/voxd.png"
ICON_SRC="$SCRIPT_DIR/src/voxd/assets/voxd-0.png"

DESKTOP_GUI="$APP_DIR/voxd-gui.desktop"
DESKTOP_TRAY="$APP_DIR/voxd-tray.desktop"
DESKTOP_FLUX="$APP_DIR/voxd-flux.desktop"

create_icon() {
  [[ -f "$ICON_SRC" ]] || { msg "Icon not found at $ICON_SRC – skipping icon copy."; return; }
  mkdir -p "$ICON_DIR" "$ICON_DIR_64"
  cp -f "$ICON_SRC" "$ICON_DEST"
  cp -f "$ICON_SRC" "$ICON_DEST_64"
}

create_desktop() {
  local mode="$1" dest="$2"

  # Try to locate voxd executable (prefer PATH); fall back to plain command
  local voxd_path="voxd"
  if command -v voxd >/dev/null 2>&1; then
    voxd_path=$(command -v voxd)
  else
    for candidate in "$HOME/.local/bin/voxd" \
                    "/usr/local/bin/voxd" \
                    "/usr/bin/voxd"; do
      if [[ -x "$candidate" ]]; then
        voxd_path="$candidate"
        break
      fi
    done
  fi

  local exec_cmd="bash -c 'export PATH=\"$HOME/.local/bin:/usr/local/bin:$PATH\"; export YDOTOOL_SOCKET=\"$HOME/.ydotool_socket\"; \"$voxd_path\" --$mode'"

  cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=VOXD ($mode)
Exec=$exec_cmd
Icon=voxd
Terminal=false
Categories=Utility;AudioVideo;
EOF
}

update_caches() {
  if command -v update-desktop-database >/dev/null; then
    timeout 15s update-desktop-database "$APP_DIR" || true
  fi
  if command -v gtk-update-icon-cache >/dev/null; then
      timeout 20s gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" || true
  else
      if command -v xdg-icon-resource >/dev/null; then
        timeout 10s xdg-icon-resource install --noupdate --size 64 "$ICON_DEST_64" voxd || true
      fi
  fi
}

install_voxd_launchers() {
  mkdir -p "$APP_DIR"
  create_icon
  create_desktop gui  "$DESKTOP_GUI"
  create_desktop tray "$DESKTOP_TRAY"
  create_desktop flux "$DESKTOP_FLUX"
  update_caches
}
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
    dnf5)  
      # Try group install first, fallback to individual packages
      if ! sudo dnf5 group install -y "Development Tools" 2>/dev/null; then
        if ! sudo dnf5 group install -y "C Development Tools and Libraries" 2>/dev/null; then
          # Fallback to essential individual packages
          sudo dnf5 install -y gcc gcc-c++ make
        fi
      fi ;;
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
spinner_start "Ensuring build tools"
need_compiler
spinner_stop $?

# ──────────────────  1. distro-specific dependency list  ────────────────────
case "$PM" in
  apt)
      SYS_DEPS=( git ffmpeg gcc make cmake curl xclip xsel wl-clipboard xdotool \
                 python3-venv libxcb-cursor0 libxcb-xinerama0 \
                 libportaudio2 portaudio19-dev )
      ;;
  dnf|dnf5)
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
    dnf|dnf5)
        local url tmp
        url=$(get_latest_ydotool_asset rpm) || return 1
        [[ -z "$url" ]] && return 1
        tmp=$(mktemp --suffix=.rpm)
        curl -L -o "$tmp" "$url" && sudo $PM install -y "$tmp"
        ;;
    *) return 1 ;;
  esac
}

install_ydotool_pkg() {
  case "$PM" in
    apt)   $INSTALL ydotool   && return 0 ;;
    dnf|dnf5) $INSTALL ydotool   && return 0 ;;
    pacman)$INSTALL ydotool   && return 0 || true ;;   # Arch users might use AUR
  esac
  return 1
}

install_ydotool_src() {
  msg "Building ydotool from source (docs disabled)…"
  tmpd=$(mktemp -d)
  git clone --depth 1 https://github.com/ReimuNotMoe/ydotool.git "$tmpd/ydotool"
  
  # Disable manpage build to avoid documentation dependencies
  sed -i 's/add_subdirectory(manpage)/#add_subdirectory(manpage)/' "$tmpd/ydotool/CMakeLists.txt"
  
  cmake -DCMAKE_INSTALL_PREFIX=/usr/local -S "$tmpd/ydotool" -B "$tmpd/ydotool/build"
  sudo cmake --build "$tmpd/ydotool/build" --target install -j"$(nproc)"
  rm -rf "$tmpd"
}

# Helper function to check if ydotool installation is complete (includes daemon)
ydotool_complete() {
  command -v ydotool >/dev/null && command -v ydotoold >/dev/null
}

ensure_ydotool() {
  # only on Wayland and if not in $PATH
  [[ ${XDG_SESSION_TYPE:-} != wayland* ]] && return 0
  
  # Check if everything is already properly set up
  if ydotool_complete && [[ -f ~/.config/systemd/user/ydotoold.service ]] && (systemctl --user is-active --quiet ydotoold.service || pgrep -x ydotoold >/dev/null); then
    msg "ydotool already configured and running"
    return 0
  fi

  msg "Setting up ydotool for Wayland typing support…"

  # Install ydotool + daemon if missing or incomplete
  if ! ydotool_complete; then
    if command -v ydotool >/dev/null && ! command -v ydotoold >/dev/null; then
      msg "ydotool found but daemon missing – package installation incomplete"
      msg "Removing incomplete installation and building from source…"
      # Remove incomplete package installation
      case "$PM" in
        apt)   sudo apt remove -y ydotool 2>/dev/null || true ;;
        dnf|dnf5) sudo $PM remove -y ydotool 2>/dev/null || true ;;
        pacman)sudo pacman -R --noconfirm ydotool 2>/dev/null || true ;;
      esac
    fi
    
    msg "Installing ydotool with daemon support…"
    
    # Temporarily disable exit-on-error for installation attempts
    set +e
    
    # 1) distro repo - but validate it includes daemon
    install_ydotool_pkg
    if command -v ydotool >/dev/null && ! command -v ydotoold >/dev/null; then
      msg "Package manager version lacks daemon – removing and building from source"
      case "$PM" in
        apt)   sudo apt remove -y ydotool 2>/dev/null || true ;;
        dnf|dnf5) sudo $PM remove -y ydotool 2>/dev/null || true ;;
        pacman)sudo pacman -R --noconfirm ydotool 2>/dev/null || true ;;
      esac
    fi
    
    # 2) upstream pre-built package (if distro repo failed/incomplete)
    if ! ydotool_complete; then
        install_ydotool_prebuilt
        if command -v ydotool >/dev/null && ! command -v ydotoold >/dev/null; then
          msg "Pre-built package lacks daemon – removing and building from source"
          sudo rm -f /usr/bin/ydotool /usr/local/bin/ydotool 2>/dev/null || true
        fi
    fi
    
    # 3) build from source if still incomplete
    if ! ydotool_complete; then
        msg "Building ydotool from source with daemon support (this may take a few minutes)…"
        # Install build dependencies
        case "$PM" in
          apt)   build_deps=(libevdev-dev libudev-dev libconfig++-dev libboost-program-options-dev) ;;
          dnf|dnf5) build_deps=(libevdev-devel libudev-devel libconfig++-devel boost-program-options-devel) ;;
          pacman)build_deps=(libevdev libconfig++ boost) ;;
        esac
        $INSTALL "${build_deps[@]}"
        install_ydotool_src
    fi
    
    # Re-enable exit-on-error
    set -e
  fi

  # Setup daemon and permissions if both tools are available
  if ydotool_complete; then
      # 1. User groups and permissions
      sudo groupadd -f input || true
      sudo usermod -aG input "$USER" || true
      
      # 2. udev rule for /dev/uinput access
      printf 'KERNEL=="uinput", MODE="0660", GROUP="input"\n' \
          | sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null || true
      sudo udevadm control --reload-rules || true
      sudo udevadm trigger || true
      
      # 3. Create systemd user service
      mkdir -p ~/.config/systemd/user
      
      # Get actual ydotoold path
      YDOTOOLD_PATH=$(command -v ydotoold)
      if [[ -z "$YDOTOOLD_PATH" ]]; then
        msg "${RED}Error: ydotoold not found in PATH after installation${NC}"
        return 1
      fi
      
      cat > ~/.config/systemd/user/ydotoold.service <<EOF
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=${YDOTOOLD_PATH} --socket-path=%h/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
EOF
      
      # 4. Environment variable setup
      SOCKET_LINE='export YDOTOOL_SOCKET="$HOME/.ydotool_socket"'
      for rcfile in ~/.bashrc ~/.zshrc; do
        if [[ -f "$rcfile" ]] && ! grep -Fxq "$SOCKET_LINE" "$rcfile"; then
          echo "$SOCKET_LINE" >> "$rcfile"
        fi
      done
      export YDOTOOL_SOCKET="$HOME/.ydotool_socket"
      
      # 5. Start daemon
      systemctl --user daemon-reload
      systemctl --user enable ydotoold.service
      
      # Attempt to start the service with retry logic for Fedora
      service_started=0
      for attempt in {1..3}; do
        if systemctl --user start ydotoold.service 2>/dev/null; then
          # Check if daemon actually started (systemctl can return success but daemon fails)
          sleep 1
          if systemctl --user is-active --quiet ydotoold.service; then
            service_started=1
            break
          else
            msg "Attempt $attempt: systemctl succeeded but daemon not active, retrying..."
            sleep 1
          fi
        else
          msg "Attempt $attempt to start ydotoold service failed, retrying in 1 second..."
          sleep 1
        fi
      done
      

      
      # If systemctl failed, try with sg input for immediate group access (Fedora/RHEL fix)
      if [[ $service_started -eq 0 ]]; then
        msg "Trying to start ydotool daemon with temporary group privileges..."
        if command -v sg >/dev/null; then
          # Use sg to temporarily assume input group membership
          msg "Running: sg input -c \"ydotoold --socket-path='$HOME/.ydotool_socket' --socket-own=$(id -u):$(id -g) &\""
          sg input -c "ydotoold --socket-path='$HOME/.ydotool_socket' --socket-own=$(id -u):$(id -g) &" >/dev/null 2>&1
          sleep 3  # Give more time for daemon to start
          if pgrep -x ydotoold >/dev/null; then
            service_started=1
            msg "✅ ydotool daemon started manually with group privileges"
          else
            msg "❌ Failed to start ydotool daemon with sg input"
          fi
        else
          msg "❌ sg command not available for fallback"
        fi
      else
        msg "✅ Systemctl start succeeded, skipping fallback"
      fi
      
      # 6. Verify daemon is running (check both systemctl and manual start)
      daemon_running=0
      if systemctl --user is-active --quiet ydotoold.service; then
        daemon_running=1
        msg "✅ ydotool daemon started successfully via systemd"
      elif pgrep -x ydotoold >/dev/null; then
        daemon_running=1
        msg "✅ ydotool daemon running manually (temporary group privileges)"
      fi
      
      if [[ $daemon_running -eq 1 ]]; then
        msg "Testing ydotool functionality…"
        # Quick test to ensure everything works
        if ydotool key 1:0 2>/dev/null; then
          msg "✅ ydotool fully functional"
        else
          msg "${YEL}⚠️ ydotool daemon running but may need logout/login for full permissions${NC}"
        fi
      else
        msg "${YEL}❌ ydotool daemon failed to start automatically${NC}"
        msg "You can start it manually with: systemctl --user start ydotoold.service"
        msg "Or log out/in to refresh permissions and try again"
      fi
      
      msg "ydotool configured – log out/in once to finalize group membership."
  else
      msg "${YEL}ydotool could not be installed completely – VOXD will fall back to clipboard-paste only.${NC}"
  fi
}

# ──────────────────  3. install system packages  ─────────────────────────────–
spinner_start "Installing system packages"
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
spinner_stop 0

# ──────────────────  4. python venv & deps  ─────────────────────────────────––
spinner_start "Setting up Python env and installing VOXD"
if [[ ! -d .venv ]]; then
  msg "Creating virtualenv (.venv)…"
  python3 -m venv .venv
else
  msg "Using existing virtualenv (.venv)"
fi
source .venv/bin/activate
# src/setup.sh  (just after source .venv/bin/activate)
if ! command -v python >/dev/null && command -v python3 >/dev/null; then
  ln -s "$(command -v python3)" "$(dirname "$(command -v python3)")/python"
fi
PY=python3         # use python3 explicitly from here on
$PY -m pip install -U pip -q
msg "Installing VOXD (editable, from pyproject.toml)…"
# Ensure recent build backend
$PY -m pip install -q --upgrade "hatchling>=1.24"
msg "(If you noticed a lengthy C compile: that's 'sounddevice' building against PortAudio headers.)"
msg "Installing VOXD into venv (editable)…"
# Ensure tags exist locally; ignore failures (offline etc.)
if git rev-parse --git-dir >/dev/null 2>&1; then
  git fetch --tags --force --prune 2>/dev/null || true
  # If no SemVer tag is found, force a pretend version so hatch-vcs doesn't error
  if ! git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' >/dev/null 2>&1; then
    export SETUPTOOLS_SCM_PRETEND_VERSION="${VOXD_PRETEND_VERSION:-0.0.0}"
  fi
else
  export SETUPTOOLS_SCM_PRETEND_VERSION="${VOXD_PRETEND_VERSION:-0.0.0}"
fi

pip install -e .

# Fix editable install .pth file if it's empty (hatchling bug workaround)
PTH_FILE=".venv/lib/python3.12/site-packages/_voxd.pth"
if [[ -f "$PTH_FILE" && ! -s "$PTH_FILE" ]]; then
  echo "$PWD/src" > "$PTH_FILE"
  msg "Fixed editable install .pth file"
fi
spinner_stop 0

# ──────────────────  Prebuilt binaries config  ─────────────────────────────
# Where prebuilts live (owner/repo with Releases containing tar.gz assets)
# You can change these without editing code via env vars.
VOXD_BIN_REPO="${VOXD_BIN_REPO:-Jacob8472/voxd-prebuilts}"
VOXD_BIN_TAG="${VOXD_BIN_TAG:-}"
VOXD_BIN_DIR="$HOME/.local/share/voxd/bin"
mkdir -p "$VOXD_BIN_DIR"

detect_cpu_variant() {
  # Echoes two values: arch variant
  # arch: amd64|arm64 ; variant (x86_64 only): avx2|sse42
  local m v flags
  m="$(uname -m | tr '[:upper:]' '[:lower:]')"
  if [[ "$m" == "x86_64" || "$m" == "amd64" ]]; then
    # Try lscpu first
    if command -v lscpu >/dev/null; then
      if lscpu | grep -q '\bavx2\b'; then v="avx2"
      elif lscpu | grep -q 'sse4_2'; then v="sse42"
      else v="none"; fi
    else
      flags="$(grep -m1 -i 'flags' /proc/cpuinfo 2>/dev/null || true)"
      if grep -qi '\bavx2\b' <<<"$flags"; then v="avx2"
      elif grep -qi 'sse4_2' <<<"$flags"; then v="sse42"
      else v="none"; fi
    fi
    echo "amd64" "$v"
    return
  fi
  if [[ "$m" == "aarch64" || "$m" == "arm64" ]]; then
    echo "arm64" "neon"
    return
  fi
  echo "$m" "none"
}

# Return a single asset download URL if it exists; empty if not.
# Arguments: <owner/repo> <asset_name>
gh_release_asset_url() {
  local repo="$1" asset="$2" api url
  if [[ -n "$VOXD_BIN_TAG" ]]; then
    api="https://api.github.com/repos/$repo/releases/tags/$VOXD_BIN_TAG"
  else
    api="https://api.github.com/repos/$repo/releases/latest"
  fi
  url="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api" \
        | grep -oE "https://[^\"]+/${asset//./\\.}" | head -n1 || true)"
  printf "%s" "$url"
}

# Download tar.gz + verify via SHA256SUMS file if present, then extract to VOXD_BIN_DIR.
# Echoes extracted binary full path on success; returns non-zero on failure.
fetch_prebuilt_binary() {
  # Arguments: kind (whisper-cli|llama-server)
  local kind="$1"
  local arch variant base asset url sums_url tarball sumfile binpath
  read -r arch variant < <(detect_cpu_variant)
  if [[ "$arch" == "amd64" ]]; then
    if [[ "$variant" == "avx2" || "$variant" == "sse42" ]]; then
      base="${kind}_linux_${arch}_${variant}"
    else
      # No compatible x86 feature → skip prebuilts
      return 1
    fi
  elif [[ "$arch" == "arm64" ]]; then
    # our release naming omits variant for arm64
    base="${kind}_linux_${arch}"
  else
    return 1
  fi

  asset="${base}.tar.gz"
  url="$(gh_release_asset_url "$VOXD_BIN_REPO" "$asset")"
  if [[ -z "$url" ]]; then
    return 1
  fi

  # Try to locate a matching checksum list in the same release
  if [[ "$arch" == "amd64" ]]; then
    sums_url="$(gh_release_asset_url "$VOXD_BIN_REPO" "SHA256SUMS_${arch}_${variant}.txt")"
  else
    sums_url="$(gh_release_asset_url "$VOXD_BIN_REPO" "SHA256SUMS_${arch}.txt")"
  fi

  local tmpdir
  tmpdir="$(mktemp -d)"
  tarball="$tmpdir/$asset"
  curl -fsSL -o "$tarball" "$url"

  if command -v sha256sum >/dev/null && [[ -n "$sums_url" ]]; then
    sumfile="$tmpdir/SHA256SUMS.txt"
    curl -fsSL -o "$sumfile" "$sums_url" || true
    if [[ -s "$sumfile" ]]; then
      # Verify: extract expected hash for our asset and compare
      local expected actual
      expected="$(grep " $asset\$" "$sumfile" | awk '{print $1}' || true)"
      if [[ -n "$expected" ]]; then
        actual="$(sha256sum "$tarball" | awk '{print $1}')"
        if [[ "$expected" != "$actual" ]]; then
          echo "checksum-mismatch" >&2
          rm -rf "$tmpdir"
          return 2
        fi
      fi
    fi
  fi

  # Extract to VOXD_BIN_DIR (contains only the binary + LICENSE + BUILDINFO)
  tar -C "$VOXD_BIN_DIR" -xzf "$tarball"
  binpath="$VOXD_BIN_DIR/$kind"
  chmod +x "$binpath" 2>/dev/null || true
  echo "$binpath"
  rm -rf "$tmpdir"
  return 0
}

# ──────────────────  5. whisper.cpp (prefer prebuilt)  ─────────────────────
spinner_start "Setting up Whisper engine (whisper-cli)"
WHISPER_BIN=""

# a) If whisper-cli already on PATH and valid, reuse (keeps your current behavior)
if command -v whisper-cli >/dev/null; then
  WHISPER_BIN="$(command -v whisper-cli)"
  RESOLVED_BIN="$(readlink -f "$WHISPER_BIN" 2>/dev/null || true)"
  if [[ -n "$RESOLVED_BIN" && "$RESOLVED_BIN" != "$HOME/.local/bin/whisper-cli" ]]; then
    WHISPER_BIN="$RESOLVED_BIN"
    msg "Found existing whisper-cli at $WHISPER_BIN – skipping download/build."
  else
    msg "Found broken whisper-cli symlink – will try prebuilt or rebuild."
    rm -f "$HOME/.local/bin/whisper-cli"
    WHISPER_BIN=""
  fi
fi

# b) Try downloading a prebuilt from GitHub Releases
if [[ -z "$WHISPER_BIN" ]]; then
  msg "Attempting to fetch prebuilt whisper-cli from $VOXD_BIN_REPO ${VOXD_BIN_TAG:+(tag $VOXD_BIN_TAG)} …"
  if prebuilt="$(fetch_prebuilt_binary "whisper-cli")"; then
    WHISPER_BIN="$prebuilt"
    msg "Using prebuilt whisper-cli: $WHISPER_BIN"
  fi
fi

# c) Fall back to source build if still missing
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
spinner_stop 0

# Whisper CLI symlink
spinner_start "Linking whisper-cli to ~/.local/bin"
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
spinner_stop 0

# ──────────────────  6. default model  ───────────────────────────────────────–
# Store in XDG data dir
MODEL_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_MODEL_DIR="$MODEL_BASE/voxd/models"
XDG_MODEL_FILE="$XDG_MODEL_DIR/ggml-base.en.bin"

# Ensure XDG target directory exists
mkdir -p "$XDG_MODEL_DIR"

# Download to XDG location if missing (non-interactive)
spinner_start "Ensuring Whisper model (base.en)"
if [[ ! -f "$XDG_MODEL_FILE" ]]; then
  if [[ $OFFLINE ]]; then
    msg "Offline – model file not found. Please place ggml-base.en.bin into $XDG_MODEL_DIR manually."
  else
    msg "Downloading default Whisper model (base.en) to XDG data dir…"
    curl -L -o "$XDG_MODEL_FILE" \
         https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
  fi
fi
spinner_stop 0


# ──────────────────  7. ydotool (Wayland helper)  ─────────────────────────────
spinner_start "Configuring Wayland typing (ydotool)"
ensure_ydotool
spinner_stop $?

# ──────────────────  8. llama.cpp (prefer prebuilt)  ─────────────

# Model download helper with verification
download_qwen_model() {
    local model_dir="$1"
    local model_file="$model_dir/qwen2.5-3b-instruct-q4_k_m.gguf"
    local download_url="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true"
    
    if [[ -f "$model_file" ]]; then
        msg "qwen2.5-3b-instruct model already exists at $model_file"
        return 0
    fi
    
    mkdir -p "$model_dir"
    msg "Downloading qwen2.5-3b-instruct model (approx. 1.9GB)..."
    
    if curl -L -f --progress-bar -o "$model_file.tmp" "$download_url"; then
        mv "$model_file.tmp" "$model_file"
        msg "✅ Downloaded qwen2.5-3b-instruct model successfully"
        return 0
    else
        rm -f "$model_file.tmp"
        msg "${RED}❌ Failed to download qwen2.5-3b-instruct model${NC}"
        echo ""
        echo "Please download manually from:"
        echo "  $download_url"
        echo ""
        echo "Or choose an alternative Qwen model from:"
        echo "  https://huggingface.co/models?search=qwen+gguf"
        echo ""
        echo "Place the .gguf file in: $model_dir/"
        echo "Supported formats: Q4_K_M, Q4_0, Q5_0, Q5_1, Q8_0"
        return 1
    fi
}

spinner_start "Setting up llama.cpp server"
LLAMA_SERVER_BIN=""

# a) Reuse existing llama-server if present
if command -v llama-server >/dev/null; then
  LLAMA_SERVER_BIN="$(command -v llama-server)"
  RESOLVED_LLAMA_BIN="$(readlink -f "$LLAMA_SERVER_BIN" 2>/dev/null || true)"
  if [[ -n "$RESOLVED_LLAMA_BIN" && "$RESOLVED_LLAMA_BIN" != "$HOME/.local/bin/llama-server" ]]; then
    LLAMA_SERVER_BIN="$RESOLVED_LLAMA_BIN"
    msg "Found existing llama-server at $LLAMA_SERVER_BIN – skipping download/build."
  else
    msg "Found broken llama-server symlink – will try prebuilt or rebuild."
    rm -f "$HOME/.local/bin/llama-server"
    LLAMA_SERVER_BIN=""
  fi
fi

# b) Try downloading a prebuilt from GitHub Releases
if [[ -z "$LLAMA_SERVER_BIN" ]]; then
  msg "Attempting to fetch prebuilt llama-server from $VOXD_BIN_REPO ${VOXD_BIN_TAG:+(tag $VOXD_BIN_TAG)} …"
  if prebuilt_llama="$(fetch_prebuilt_binary "llama-server")"; then
    LLAMA_SERVER_BIN="$prebuilt_llama"
    msg "Using prebuilt llama-server: $LLAMA_SERVER_BIN"
  fi
fi

# c) Fallback: build from source (CPU-only)
if [[ -z "$LLAMA_SERVER_BIN" ]]; then
  if [[ $OFFLINE ]]; then
    msg "Offline mode – skipping llama.cpp clone. Assuming sources are present."
  else
    if [[ ! -d llama.cpp ]]; then
      msg "Cloning llama.cpp…"
      git clone --depth 1 https://github.com/ggerganov/llama.cpp.git
    fi
  fi
  if [[ ! -x llama.cpp/build/bin/llama-server ]]; then
    msg "Building llama.cpp (CPU-only)…"
    cmake -S llama.cpp -B llama.cpp/build -DBUILD_SHARED_LIBS=OFF -DLLAMA_SERVER=ON -DLLAMA_CURL=ON
    cmake --build llama.cpp/build -j"$(nproc)" --target llama-server
  else
    msg "llama.cpp already built."
  fi
  LLAMA_SERVER_BIN="$PWD/llama.cpp/build/bin/llama-server"
fi

# d) Symlink llama-server to ~/.local/bin
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"
LLAMA_SYMLINK_PATH="$LOCAL_BIN/llama-server"

if [[ -L "$LLAMA_SERVER_BIN" ]]; then
  REAL_LLAMA_BIN=$(readlink -f "$LLAMA_SERVER_BIN" 2>/dev/null || echo "$LLAMA_SERVER_BIN")
else
  REAL_LLAMA_BIN="$LLAMA_SERVER_BIN"
fi

if [[ "$REAL_LLAMA_BIN" == "$LLAMA_SYMLINK_PATH" ]]; then
  msg "llama-server symlink would point to itself – skipping."
elif [[ ! -f "$REAL_LLAMA_BIN" ]]; then
  msg "Warning: llama-server binary not found at $REAL_LLAMA_BIN – skipping symlink creation."
else
  if [[ -L "$LLAMA_SYMLINK_PATH" ]]; then
    rm -f "$LLAMA_SYMLINK_PATH"
  elif [[ -e "$LLAMA_SYMLINK_PATH" ]]; then
    msg "File named llama-server already exists at $LLAMA_SYMLINK_PATH – leaving untouched."
    REAL_LLAMA_BIN=""
  fi
  if [[ -n "$REAL_LLAMA_BIN" ]]; then
    ln -s "$REAL_LLAMA_BIN" "$LLAMA_SYMLINK_PATH"
    msg "Symlinked llama-server to $LLAMA_SYMLINK_PATH"
  fi
fi
spinner_stop 0

# e) Ensure Qwen model is available (non-interactive)
spinner_start "Ensuring Qwen 2.5 3B-Instruct model"
LLAMACPP_MODELS_DIR="$HOME/.local/share/voxd/llamacpp_models"
if [[ ! -f "$LLAMACPP_MODELS_DIR/qwen2.5-3b-instruct-q4_k_m.gguf" ]]; then
  download_qwen_model "$LLAMACPP_MODELS_DIR" || true
fi
spinner_stop 0

# (whisper-cli symlink step moved earlier)

# ──────────────────  9b. persist absolute paths in config.yaml  ──────────────
spinner_start "Writing configuration"
export LLAMA_SERVER_BIN
if [[ -n "$WHISPER_BIN" ]]; then
  $PY - <<PY
import sys, os
from pathlib import Path

# Add repo src to import path
repo_src = Path(os.getcwd()) / "src"
if repo_src.exists():
    sys.path.insert(0, str(repo_src))

try:
    from voxd.core.config import AppConfig  # type: ignore
    from voxd.paths import LLAMACPP_MODELS_DIR, DATA_DIR  # type: ignore
except ModuleNotFoundError as e:
    print("[setup] Warning: could not import voxd (", e, ") – skipping config update.")
    sys.exit(0)

_p = Path("$WHISPER_BIN")
try:
    whisper_bin = _p.resolve()
except RuntimeError:
    whisper_bin = _p.absolute()
model_path = DATA_DIR / "models" / "ggml-base.en.bin"

cfg = AppConfig()
cfg.set("whisper_binary", str(whisper_bin))
cfg.set("whisper_model_path", str(model_path))

# Update llama.cpp server path: prefer prebuilt path from env, fallback to repo build
env_llama = os.environ.get("LLAMA_SERVER_BIN")
if env_llama and Path(env_llama).exists():
    cfg.set("llamacpp_server_path", str(Path(env_llama).resolve()))
else:
    llama_server_path = Path(os.getcwd()) / "llama.cpp" / "build" / "bin" / "llama-server"
    if llama_server_path.exists():
        cfg.set("llamacpp_server_path", str(llama_server_path))

llamacpp_model_path = LLAMACPP_MODELS_DIR / "qwen2.5-3b-instruct-q4_k_m.gguf"
if llamacpp_model_path.exists():
    cfg.set("llamacpp_default_model", str(llamacpp_model_path))

cfg.save()
print("[setup] Configuration updated with resolved paths")
PY
else
  msg "Warning: No whisper-cli binary found – skipping config update."
fi
spinner_stop $?

# ──────────────────  10. done  ───────────────────────────────────────────────––

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

spinner_start "Setting up global 'voxd' command (pipx)"
# Offer to install pipx (if missing) and register voxd command globally.
if ! command -v pipx >/dev/null; then
  msg "pipx not detected – installing pipx for global 'voxd' command"
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
  # Handle Fedora bashrc unbound variable issue
  if [[ $SHELL =~ /bash$ ]] && [[ -f "$HOME/.bashrc" ]]; then 
    set +u  # Temporarily disable unbound variable checking
    source "$HOME/.bashrc" 2>/dev/null || true
    set -u  # Re-enable unbound variable checking
  fi
  if [[ $SHELL =~ /zsh$ ]]  && [[ -f "$HOME/.zshrc"  ]]; then
    source "$HOME/.zshrc" 2>/dev/null || true
  fi
fi

if command -v pipx >/dev/null; then
  if pipx list 2>/dev/null | grep -q "voxd "; then
    msg "'voxd' already installed via pipx – forcing update"
    pipx install --force "$PWD" || true
  else
    msg "Installing 'voxd' globally via pipx"
    pipx install --force "$PWD" || true
  fi
else
  msg "pipx still not available – skipping global install"
fi
spinner_stop 0

# ──────────────────  10b. install desktop launchers (auto, all modes) ────────
spinner_start "Installing desktop launchers (gui, tray, flux)"
_launch_rc=0
timeout 60s install_voxd_launchers || _launch_rc=$?
spinner_stop $_launch_rc

# ──────────────────  Final Idempotency Report (console + log) ────────────────
note "Idempotency report:"
if [[ -d .venv ]]; then line="  • venv: present (.venv)"; else line="  • venv: will be created"; fi; printf "%s\n" "$line" >&3; printf "%s\n" "$line"
if command -v whisper-cli >/dev/null 2>&1; then line="  • whisper-cli: present ($(command -v whisper-cli))"; else line="  • whisper-cli: not found"; fi; printf "%s\n" "$line" >&3; printf "%s\n" "$line"
MODEL_BASE_REPORT="${XDG_DATA_HOME:-$HOME/.local/share}"; MODEL_FILE_REPORT="$MODEL_BASE_REPORT/voxd/models/ggml-base.en.bin"
if [[ -f "$MODEL_FILE_REPORT" ]]; then line="  • whisper model: present ($MODEL_FILE_REPORT)"; else line="  • whisper model: missing"; fi; printf "%s\n" "$line" >&3; printf "%s\n" "$line"
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]]; then
  if command -v ydotool >/dev/null 2>&1 && command -v ydotoold >/dev/null 2>&1; then line="  • ydotool: present (Wayland typing enabled)"; else line="  • ydotool: not fully configured (Wayland)"; fi
else
  line="  • ydotool: not required (X11)"
fi
printf "%s\n" "$line" >&3; printf "%s\n" "$line"
if command -v llama-server >/dev/null 2>&1; then line="  • llama.cpp: present (llama-server)"; else line="  • llama.cpp: not installed"; fi; printf "%s\n" "$line" >&3; printf "%s\n" "$line"
if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "voxd "; then line="  • pipx 'voxd': installed"; else line="  • pipx 'voxd': not installed"; fi; printf "%s\n" "$line" >&3; printf "%s\n" "$line"

if [[ -f "$DESKTOP_GUI" && -f "$DESKTOP_TRAY" && -f "$DESKTOP_FLUX" ]]; then
  note "Desktop launchers installed: VOXD (gui, tray, flux)"
else
  note "Desktop launchers installation was partial or skipped – see setup log"
fi
note "Setup complete. Log: $(pwd)/$LOG_FILE"
note "Reboot required to finalize ydotool permissions."
printf "\n${GRN}IMPORTANT:${NC} Please reboot your system to finalize ydotool permissions.\n" >&3
printf "${YEL}Tip:${NC} Add a system hotkey to trigger recording:\n" >&3
printf "  Command: voxd --trigger-record\n" >&3
printf "  Where:   System Settings → Keyboard → Custom Shortcuts\n" >&3
printf "  Example: Bind to Super+Z\n\n" >&3
# ────────────────── 11. Hotkey Guidance (manual)  ───────────────────────────
echo ""
msg "Hotkey setup (manual):"
echo "  Configure a custom keyboard shortcut in your system to run:"
echo "    bash -c 'voxd --trigger-record'"
echo "  Example binding: Super+Z (or any key you prefer)."
echo "  Location: System Settings → Keyboard → Custom Shortcuts."
echo "  Test the command directly with: voxd --trigger-record"
