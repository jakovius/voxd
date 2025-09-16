#!/usr/bin/env bash
# =============================================================================
#  VOXD – Desktop-launcher helper
#
#  Creates, edits, or removes .desktop entries for launching VOXD in GUI, Tray, or Flux mode.
#  • No sudo: everything lives in ~/.local/share
#  • Prompts the user which launcher(s) to install
#  • Use --edit to fix existing launchers with environment variables
#  • Use --remove to delete launchers and icon again
# =============================================================================
set -euo pipefail

YEL=$'\033[1;33m'; GRN=$'\033[1;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'
msg() { printf "${YEL}==>${NC} %s\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

# Paths
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
ICON_DIR_64="$HOME/.local/share/icons/hicolor/64x64/apps"
ICON_DEST="$ICON_DIR/voxd.png"
ICON_DEST_64="$ICON_DIR_64/voxd.png"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
  
  # Find the voxd executable - prefer virtual environment if available
  local voxd_path=""
  if command -v voxd >/dev/null 2>&1; then
    voxd_path=$(command -v voxd)
  else
    # Fallback: check common locations
    for candidate in "$HOME/.local/bin/voxd" "/usr/local/bin/voxd" "/usr/bin/voxd"; do
      if [[ -x "$candidate" ]]; then
        voxd_path="$candidate"
        break
      fi
    done
  fi
  
  if [[ -z "$voxd_path" ]]; then
    die "Cannot find voxd executable. Make sure voxd is installed and in PATH."
  fi
  
  msg "Using voxd executable: $voxd_path"
  
  # Create launcher with full environment setup
  local exec_cmd="bash -c 'export PATH=\"\$HOME/.local/bin:/usr/local/bin:\$PATH\"; export YDOTOOL_SOCKET=\"\$HOME/.ydotool_socket\"; \"$voxd_path\" --$mode'"
  
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
  command -v update-desktop-database >/dev/null && update-desktop-database "$APP_DIR" || true
  if command -v gtk-update-icon-cache >/dev/null; then
      gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor"
  else
      # Fallback: register via xdg-icon-resource
      command -v xdg-icon-resource >/dev/null && \
        xdg-icon-resource install --noupdate --size 64 "$ICON_DEST_64" voxd || true
  fi
}

remove_files() {
  rm -f "$DESKTOP_GUI" "$DESKTOP_TRAY" "$DESKTOP_FLUX" "$ICON_DEST"
  update_caches
  msg "Launchers removed."
}

edit_existing_launchers() {
  local found_any=false
  
  for file in "$DESKTOP_GUI" "$DESKTOP_TRAY" "$DESKTOP_FLUX"; do
    [[ -f "$file" ]] || continue
    found_any=true
    
    local basename_file=$(basename "$file")
    msg "Found existing launcher: $basename_file"
    
    # Show current Exec line
    local current_exec=$(grep "^Exec=" "$file" | cut -d= -f2-)
    printf "  Current: %s\n" "$current_exec"
    
    # Extract mode from filename
    local mode
    case "$basename_file" in
      *gui*) mode="gui" ;;
      *tray*) mode="tray" ;;
      *flux*) mode="flux" ;;
      *) mode="unknown" ;;
    esac
    
    if [[ $mode != "unknown" ]]; then
      printf "  ${YEL}Fix this launcher? [y/N]:${NC} "
      read -r answer
      if [[ $answer =~ ^[Yy]$ ]]; then
        msg "Updating $basename_file with environment variables..."
        create_desktop "$mode" "$file"
        msg "✓ Updated launcher"
      else
        msg "Skipped $basename_file"
      fi
    else
      msg "⚠ Cannot determine mode for $basename_file - skipping"
    fi
    echo
  done
  
  if [[ $found_any == false ]]; then
    msg "No existing VOXD launchers found in $APP_DIR"
    msg "Run without --edit to create new launchers."
  else
    update_caches
    msg "${GRN}Edit session complete.${NC}"
  fi
}

if [[ ${1:-} == "--remove" ]]; then
  remove_files
  exit 0
fi

if [[ ${1:-} == "--edit" ]]; then
  edit_existing_launchers
  exit 0
fi

printf "${YEL}Create desktop launchers?${NC}\n 1) GUI window\n 2) Tray icon\n 3) Flux mode (VAD)\n 4) All (default)\n 0) None / quit\nChoose [4]: "
read -r choice || true
choice=${choice:-4}

case "$choice" in
  1) modes=(gui) ;;
  2) modes=(tray) ;;
  3) modes=(flux) ;;
  4|"") modes=(gui tray flux) ;;
  0) msg "Nothing to do. Bye."; exit 0 ;;
  *) die "Invalid choice." ;;
esac

mkdir -p "$APP_DIR"
create_icon

for m in "${modes[@]}"; do
  case "$m" in
    gui)  create_desktop gui  "$DESKTOP_GUI" ;;
    tray) create_desktop tray "$DESKTOP_TRAY" ;;
    flux) create_desktop flux "$DESKTOP_FLUX" ;;
  esac
  msg "Installed launcher for $m mode → $APP_DIR"
done

update_caches
msg "${GRN}Done – launcher(s) installed. They may appear after re-login or menu reload.${NC}" 