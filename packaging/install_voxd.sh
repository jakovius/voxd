#!/usr/bin/env bash
# install_voxd.sh - Cross-distro installer for local VOXD packages
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/packaging/install_voxd.sh -o install_voxd.sh
#   bash install_voxd.sh ./voxd_1.4.1-1_amd64.deb
# or, after downloading package into current dir, just:
#   bash install_voxd.sh
set -euo pipefail

info() { printf "\033[1;34m[voxd-install]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[voxd-install]\033[0m %s\n" "$*"; }
err()  { printf "\033[0;31m[voxd-install]\033[0m %s\n" "$*" 1>&2; }

PKG_PATH="${1:-}"

# Try to auto-detect the package file if not provided
if [[ -z "$PKG_PATH" ]]; then
  if compgen -G "voxd_*_*.deb" > /dev/null; then
    PKG_PATH="$(ls -1 voxd_*_*.deb | head -n1)"
  elif compgen -G "voxd-*-*.rpm" > /dev/null; then
    PKG_PATH="$(ls -1 voxd-*-*.rpm | head -n1)"
  elif compgen -G "voxd-*-*.pkg.tar.zst" > /dev/null; then
    PKG_PATH="$(ls -1 voxd-*-*.pkg.tar.zst | head -n1)"
  fi
fi

if [[ -z "$PKG_PATH" ]]; then
  err "No package file given and none found in current directory."
  err "Usage: $0 /path/to/voxd_<ver>-<rel>_<arch>.deb"
  exit 1
fi

if [[ ! -f "$PKG_PATH" ]]; then
  err "Package not found: $PKG_PATH"
  exit 1
fi

# Detect distro
if command -v apt >/dev/null 2>&1; then
  DISTRO=debian
elif command -v dnf >/dev/null 2>&1 || command -v dnf5 >/dev/null 2>&1 || command -v zypper >/dev/null 2>&1; then
  DISTRO=rpm
elif command -v pacman >/dev/null 2>&1; then
  DISTRO=arch
else
  err "Unsupported distro. Need apt, dnf/dnf5/zypper, or pacman."
  exit 1
fi

case "$DISTRO" in
  debian)
    info "Installing on Debian/Ubuntu using apt (resolves dependencies)"
    # Enable Ubuntu universe if needed (for packages like ydotool)
    if command -v lsb_release >/dev/null 2>&1 && [[ $(lsb_release -is 2>/dev/null || echo "") == "Ubuntu" ]]; then
      if ! apt-cache policy ydotool 2>/dev/null | grep -q Candidate:; then
        warn "Enabling Ubuntu 'universe' repository (needed for ydotool)…"
        sudo add-apt-repository -y universe || true
      fi
    fi
    sudo apt update
    # Use apt to install the local .deb so it pulls dependencies
    if ! sudo apt install -y "./$PKG_PATH"; then
      warn "Attempting to fix broken deps and retry…"
      sudo apt -f install -y || true
      sudo apt install -y "./$PKG_PATH"
    fi
    ;;
  rpm)
    info "Installing on RPM-based system"
    if command -v dnf5 >/dev/null 2>&1; then
      sudo dnf5 install -y "$PKG_PATH"
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y "$PKG_PATH"
    elif command -v zypper >/dev/null 2>&1; then
      sudo zypper --non-interactive install --force-resolution "$PKG_PATH"
    else
      err "No supported RPM package manager found."
      exit 1
    fi
    ;;
  arch)
    info "Installing on Arch Linux"
    sudo pacman -U --noconfirm "$PKG_PATH"
    ;;
esac

info "Install complete. Run 'voxd' to start; first run performs per-user setup."


