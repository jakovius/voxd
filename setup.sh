#!/usr/bin/env bash
# =============================================================================
#  VOXT – one-shot installer / updater
#
#  • Installs system packages        (apt | dnf | pacman – auto-detected)
#  • Creates / re-uses Python venv    (.venv)
#  • Installs Python dependencies & VOXT itself (editable)
#  • Clones + builds whisper.cpp      → whisper.cpp/build/bin/whisper-cli
#  • (Wayland) ensures ydotool + daemon, validates completeness, forces source build if needed
#
#  Idempotent: re-running skips finished steps.
# =============================================================================
set -euo pipefail

# ────────────────── Setup logging ─────────────────────────────────────────────
LOG_FILE="$(date +%F)-setup-log.txt"
# Append all stdout/stderr to log while keeping it on console
exec > >(tee -a "$LOG_FILE") 2>&1

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
need_compiler

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
      msg "${YEL}ydotool could not be installed completely – VOXT will fall back to clipboard-paste only.${NC}"
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
msg "Installing VOXT (editable, from pyproject.toml)…"
# Ensure recent build backend
$PY -m pip install -q --upgrade "hatchling>=1.24"
msg "(If you noticed a lengthy C compile: that's 'sounddevice' building against PortAudio headers.)"
msg "Installing VOXT into venv (editable)…"
# Ensure tags exist locally; ignore failures (offline etc.)
if git rev-parse --git-dir >/dev/null 2>&1; then
  git fetch --tags --force --prune 2>/dev/null || true
  # If no SemVer tag is found, force a pretend version so hatch-vcs doesn't error
  if ! git describe --tags --abbrev=0 --match 'v[0-9]*.[0-9]*.[0-9]*' >/dev/null 2>&1; then
    export SETUPTOOLS_SCM_PRETEND_VERSION="${VOXT_PRETEND_VERSION:-0.0.0}"
  fi
else
  export SETUPTOOLS_SCM_PRETEND_VERSION="${VOXT_PRETEND_VERSION:-0.0.0}"
fi

pip install -e .

# Fix editable install .pth file if it's empty (hatchling bug workaround)
PTH_FILE=".venv/lib/python3.12/site-packages/_voxt.pth"
if [[ -f "$PTH_FILE" && ! -s "$PTH_FILE" ]]; then
  echo "$PWD/src" > "$PTH_FILE"
  msg "Fixed editable install .pth file"
fi

# ──────────────────  Prebuilt binaries config  ─────────────────────────────
# Where prebuilts live (owner/repo with Releases containing tar.gz assets)
# You can change these without editing code via env vars.
VOXT_BIN_REPO="${VOXT_BIN_REPO:-Jacob8472/voxd-prebuilts}"   # e.g. voxt-app/voxt-prebuilts
VOXT_BIN_TAG="${VOXT_BIN_TAG:-}"                 # optional; if empty → latest
VOXT_BIN_DIR="$HOME/.local/share/voxt/bin"
mkdir -p "$VOXT_BIN_DIR"

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
  if [[ -n "$VOXT_BIN_TAG" ]]; then
    api="https://api.github.com/repos/$repo/releases/tags/$VOXT_BIN_TAG"
  else
    api="https://api.github.com/repos/$repo/releases/latest"
  fi
  url="$(curl -fsSL -H 'Accept: application/vnd.github+json' "$api" \
        | grep -oE "https://[^\"]+/${asset//./\\.}" | head -n1 || true)"
  printf "%s" "$url"
}

# Download tar.gz + verify via SHA256SUMS file if present, then extract to VOXT_BIN_DIR.
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
  url="$(gh_release_asset_url "$VOXT_BIN_REPO" "$asset")"
  if [[ -z "$url" ]]; then
    return 1
  fi

  # Try to locate a matching checksum list in the same release
  if [[ "$arch" == "amd64" ]]; then
    sums_url="$(gh_release_asset_url "$VOXT_BIN_REPO" "SHA256SUMS_${arch}_${variant}.txt")"
  else
    sums_url="$(gh_release_asset_url "$VOXT_BIN_REPO" "SHA256SUMS_${arch}.txt")"
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

  # Extract to VOXT_BIN_DIR (contains only the binary + LICENSE + BUILDINFO)
  tar -C "$VOXT_BIN_DIR" -xzf "$tarball"
  binpath="$VOXT_BIN_DIR/$kind"
  chmod +x "$binpath" 2>/dev/null || true
  echo "$binpath"
  rm -rf "$tmpdir"
  return 0
}

# ──────────────────  5. whisper.cpp (prefer prebuilt)  ─────────────────────
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
  msg "Attempting to fetch prebuilt whisper-cli from $VOXT_BIN_REPO ${VOXT_BIN_TAG:+(tag $VOXT_BIN_TAG)} …"
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

# ──────────────────  6. default model  ───────────────────────────────────────–
# Store in XDG data dir and symlink into repo (consistent with runtime downloader)
MODEL_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_MODEL_DIR="$MODEL_BASE/voxt/models"
XDG_MODEL_FILE="$XDG_MODEL_DIR/ggml-base.en.bin"
REPO_MODEL_DIR="whisper.cpp/models"
REPO_MODEL_FILE="$REPO_MODEL_DIR/ggml-base.en.bin"

# Ensure target directories exist
mkdir -p "$XDG_MODEL_DIR"
mkdir -p "$REPO_MODEL_DIR"

# Migrate: if an old repo-local regular file exists and XDG missing, move it
if [[ -f "$REPO_MODEL_FILE" && ! -L "$REPO_MODEL_FILE" && ! -f "$XDG_MODEL_FILE" ]]; then
  msg "Migrating base model to XDG data dir ($XDG_MODEL_FILE)"
  mv "$REPO_MODEL_FILE" "$XDG_MODEL_FILE"
fi

# Download to XDG location if missing
if [[ ! -f "$XDG_MODEL_FILE" ]]; then
  if [[ $OFFLINE ]]; then
    msg "Offline mode – model file not found. Please place ggml-base.en.bin into $XDG_MODEL_DIR manually."
  else
    msg "Downloading default Whisper model (base.en) to XDG data dir…"
    curl -L -o "$XDG_MODEL_FILE" \
         https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
  fi
fi

# Ensure repo symlink points to XDG file
if [[ -f "$XDG_MODEL_FILE" ]]; then
  XDG_MODEL_REAL=$(readlink -f "$XDG_MODEL_FILE" 2>/dev/null || echo "$XDG_MODEL_FILE")
  if [[ -L "$REPO_MODEL_FILE" ]]; then
    CUR_TARGET=$(readlink -f "$REPO_MODEL_FILE" 2>/dev/null || readlink "$REPO_MODEL_FILE")
    if [[ "$CUR_TARGET" != "$XDG_MODEL_REAL" ]]; then
      rm -f "$REPO_MODEL_FILE"
      ln -s "$XDG_MODEL_REAL" "$REPO_MODEL_FILE"
      msg "Updated repo symlink: $REPO_MODEL_FILE → $XDG_MODEL_REAL"
    else
      msg "Repo symlink already up to date"
    fi
  elif [[ -e "$REPO_MODEL_FILE" ]]; then
    msg "Repo model path exists as a regular file; leaving it (no symlink created)."
  else
    ln -s "$XDG_MODEL_REAL" "$REPO_MODEL_FILE"
    msg "Symlinked repo model: $REPO_MODEL_FILE → $XDG_MODEL_REAL"
  fi
fi

# ──────────────────  7. ydotool (Wayland helper)  ─────────────────────────────
ensure_ydotool

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
  msg "Attempting to fetch prebuilt llama-server from $VOXT_BIN_REPO ${VOXT_BIN_TAG:+(tag $VOXT_BIN_TAG)} …"
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

# e) Offer model download
LLAMACPP_MODELS_DIR="$HOME/.local/share/voxt/llamacpp_models"
if [[ ! -f "$LLAMACPP_MODELS_DIR/qwen2.5-3b-instruct-q4_k_m.gguf" ]]; then
  read -r -p "Download default qwen2.5-3b-instruct model for AIPP? [Y/n]: " download_model
  download_model=${download_model:-Y}
  if [[ $download_model =~ ^[Yy]$ ]]; then
    download_qwen_model "$LLAMACPP_MODELS_DIR" || true
  fi
fi

# ──────────────────  9. symlink whisper-cli to ~/.local/bin  ─────────────────
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

# ──────────────────  9b. persist absolute paths in config.yaml  ──────────────
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
    from voxt.core.config import AppConfig  # type: ignore
    from voxt.paths import LLAMACPP_MODELS_DIR, DATA_DIR  # type: ignore
except ModuleNotFoundError as e:
    print("[setup] Warning: could not import voxt (", e, ") – skipping config update.")
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

# ──────────────────  10. done  ───────────────────────────────────────────────––

# ──────────────────  Report: what is already available  ─────────────────────
echo ""
msg "Idempotency report:"
if [[ -d .venv ]]; then echo "  • venv: present (.venv)"; else echo "  • venv: will be created"; fi
if command -v whisper-cli >/dev/null 2>&1; then echo "  • whisper-cli: present ($(command -v whisper-cli))"; else echo "  • whisper-cli: not found"; fi
MODEL_BASE_REPORT="${XDG_DATA_HOME:-$HOME/.local/share}"
MODEL_FILE_REPORT="$MODEL_BASE_REPORT/voxt/models/ggml-base.en.bin"
if [[ -f "$MODEL_FILE_REPORT" ]]; then echo "  • whisper model: present ($MODEL_FILE_REPORT)"; else echo "  • whisper model: missing"; fi
if [[ ${XDG_SESSION_TYPE:-} == wayland* ]]; then
  if command -v ydotool >/dev/null 2>&1 && command -v ydotoold >/dev/null 2>&1; then
    echo "  • ydotool: present (Wayland typing enabled)"
  else
    echo "  • ydotool: not fully configured (Wayland)"
  fi
else
  echo "  • ydotool: not required (X11)"
fi
if command -v llama-server >/dev/null 2>&1; then echo "  • llama.cpp: present (llama-server)"; else echo "  • llama.cpp: not installed"; fi
if command -v pipx >/dev/null 2>&1 && pipx list 2>/dev/null | grep -q "voxt "; then echo "  • pipx 'voxt': installed"; else echo "  • pipx 'voxt': not installed"; fi

msg "${GRN}Setup complete!${NC}"
echo "Setup log (appended per run): $(pwd)/$LOG_FILE"
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
  msg "pipx not detected – installing pipx for global 'voxt' command"
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
  if pipx list 2>/dev/null | grep -q "voxt "; then
    msg "'voxt' already installed via pipx – forcing update"
    pipx install --force "$PWD" || true
  else
    msg "Installing 'voxt' globally via pipx"
    pipx install --force "$PWD" || true
  fi
else
  msg "pipx still not available – skipping global install"
fi

# ────────────────── 11. Hotkey Guidance (manual)  ───────────────────────────
echo ""
msg "Hotkey setup (manual):"
echo "  Configure a custom keyboard shortcut in your system to run:"
echo "    bash -c 'voxt --trigger-record'"
echo "  Example binding: Super+Z (or any key you prefer)."
echo "  Location: System Settings → Keyboard → Custom Shortcuts."
echo "  Test the command directly with: voxt --trigger-record"
