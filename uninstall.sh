#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# VOXT Uninstaller - Comprehensive removal script
# ──────────────────────────────────────────────────────────────────────────────

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script metadata
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOXT_REPO_DIR="$SCRIPT_DIR"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                    VOXT Uninstaller                           ║${NC}"
echo -e "${BLUE}║               Complete removal of VOXT components             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ──────────────────────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────────────────────

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

ask_user() {
    local prompt="$1"
    local default="${2:-y}"
    local response
    
    if [[ "$default" == "y" ]]; then
        read -p "$prompt [Y/n]: " response
        response=${response:-y}
    else
        read -p "$prompt [y/N]: " response
        response=${response:-n}
    fi
    
    case "$response" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# ──────────────────────────────────────────────────────────────────────────────
# Linux distribution detection
# ──────────────────────────────────────────────────────────────────────────────

detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        DISTRO_ID="$ID"
        DISTRO_NAME="$NAME"
    else
        DISTRO_ID="unknown"
        DISTRO_NAME="Unknown Linux"
    fi
    
    log_info "Detected distribution: $DISTRO_NAME"
}

detect_package_manager() {
    if command -v apt >/dev/null 2>&1; then
        PKG_MANAGER="apt"
        PKG_REMOVE="sudo apt remove -y"
        PKG_AUTOREMOVE="sudo apt autoremove -y"
    elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
        PKG_REMOVE="sudo dnf remove -y"
        PKG_AUTOREMOVE="sudo dnf autoremove -y"
    elif command -v yum >/dev/null 2>&1; then
        PKG_MANAGER="yum"
        PKG_REMOVE="sudo yum remove -y"
        PKG_AUTOREMOVE="sudo yum autoremove -y"
    elif command -v pacman >/dev/null 2>&1; then
        PKG_MANAGER="pacman"
        PKG_REMOVE="sudo pacman -Rs"
        PKG_AUTOREMOVE="sudo pacman -Rns \$(pacman -Qtdq)"
    elif command -v zypper >/dev/null 2>&1; then
        PKG_MANAGER="zypper"
        PKG_REMOVE="sudo zypper remove -y"
        PKG_AUTOREMOVE="sudo zypper packages --unneeded | awk -F'|' 'NR==0 || NR==1 || NR==2 || NR==3 || NR==4 {next} {print \$3}' | grep -v Name | sudo xargs zypper remove -y"
    else
        PKG_MANAGER="unknown"
        PKG_REMOVE=""
        PKG_AUTOREMOVE=""
        log_warning "Could not detect package manager. Manual package removal may be required."
    fi
    
    if [[ "$PKG_MANAGER" != "unknown" ]]; then
        log_info "Detected package manager: $PKG_MANAGER"
    fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Component detection and removal functions
# ──────────────────────────────────────────────────────────────────────────────

stop_running_processes() {
    echo ""
    log_info "Checking for running VOXT processes..."
    
    local processes_found=false
    
    if pgrep -f "voxt" >/dev/null 2>&1; then
        log_warning "Found running VOXT processes"
        processes_found=true
    fi
    
    if pgrep -f "llama-server" >/dev/null 2>&1; then
        log_warning "Found running llama-server processes"
        processes_found=true
    fi
    
    if pgrep -f "ydotoold" >/dev/null 2>&1; then
        log_warning "Found running ydotoold processes"
        processes_found=true
    fi
    
    if [[ "$processes_found" == "true" ]]; then
        if ask_user "Stop all running VOXT-related processes?"; then
            log_info "Stopping processes..."
            pkill -f voxt 2>/dev/null || true
            pkill -f llama-server 2>/dev/null || true
            pkill -f ydotoold 2>/dev/null || true
            sleep 2
            log_success "Processes stopped"
        else
            log_warning "Processes left running - some files may not be removable"
        fi
    else
        log_info "No running VOXT processes found"
    fi
}

remove_pipx_installation() {
    echo ""
    log_info "Checking for pipx installation..."
    
    if command -v pipx >/dev/null 2>&1; then
        if pipx list | grep -q "voxt"; then
            log_warning "Found VOXT installed via pipx"
            if ask_user "Remove VOXT from pipx?"; then
                log_info "Uninstalling VOXT from pipx..."
                pipx uninstall voxt
                log_success "VOXT removed from pipx"
            fi
        else
            log_info "VOXT not found in pipx installations"
        fi
    else
        log_info "pipx not found - skipping pipx check"
    fi
}

remove_repository_files() {
    echo ""
    log_info "Checking repository installation..."
    
    local repo_components=()
    
    # Check for virtual environment
    if [[ -d "$VOXT_REPO_DIR/.venv" ]]; then
        repo_components+=(".venv (Python virtual environment)")
    fi
    
    # Check for whisper.cpp
    if [[ -d "$VOXT_REPO_DIR/whisper.cpp" ]]; then
        repo_components+=("whisper.cpp (speech recognition)")
    fi
    
    # Check for llama.cpp
    if [[ -d "$VOXT_REPO_DIR/llama.cpp" ]]; then
        repo_components+=("llama.cpp (local AI)")
    fi
    
    # Check for symlinks
    local symlinks_found=()
    if [[ -L ~/.local/bin/whisper-cli ]]; then
        symlinks_found+=("~/.local/bin/whisper-cli")
    fi
    if [[ -L ~/.local/bin/llama-server ]]; then
        symlinks_found+=("~/.local/bin/llama-server")
    fi
    if [[ -L ~/.local/bin/llama-cli ]]; then
        symlinks_found+=("~/.local/bin/llama-cli")
    fi
    
    if [[ ${#repo_components[@]} -gt 0 ]]; then
        log_warning "Found repository components:"
        for component in "${repo_components[@]}"; do
            echo "  - $component"
        done
        
        if ask_user "Remove all repository build artifacts?"; then
            # Deactivate venv if active
            if [[ -n "$VIRTUAL_ENV" ]]; then
                log_info "Deactivating virtual environment..."
                deactivate 2>/dev/null || true
            fi
            
            log_info "Removing repository components..."
            rm -rf "$VOXT_REPO_DIR/.venv" 2>/dev/null || true
            rm -rf "$VOXT_REPO_DIR/whisper.cpp" 2>/dev/null || true
            rm -rf "$VOXT_REPO_DIR/llama.cpp" 2>/dev/null || true
            log_success "Repository components removed"
        fi
    else
        log_info "No repository build artifacts found"
    fi
    
    if [[ ${#symlinks_found[@]} -gt 0 ]]; then
        log_warning "Found binary symlinks:"
        for symlink in "${symlinks_found[@]}"; do
            echo "  - $symlink"
        done
        
        if ask_user "Remove binary symlinks?"; then
            log_info "Removing symlinks..."
            rm -f ~/.local/bin/whisper-cli 2>/dev/null || true
            rm -f ~/.local/bin/llama-server 2>/dev/null || true
            rm -f ~/.local/bin/llama-cli 2>/dev/null || true
            log_success "Symlinks removed"
        fi
    else
        log_info "No binary symlinks found"
    fi
}

remove_user_data() {
    echo ""
    log_info "Checking user data and configuration..."
    
    local user_data_found=()
    
    # Check configuration
    if [[ -d ~/.config/voxt ]]; then
        user_data_found+=("~/.config/voxt (configuration files)")
    fi
    
    # Check data directory
    if [[ -d ~/.local/share/voxt ]]; then
        local data_size=$(du -sh ~/.local/share/voxt 2>/dev/null | cut -f1)
        user_data_found+=("~/.local/share/voxt (models, logs, data - $data_size)")
    fi
    
    # Check desktop launchers
    local launchers=()
    if [[ -f ~/.local/share/applications/voxt.desktop ]]; then
        launchers+=("~/.local/share/applications/voxt.desktop")
    fi
    if ls ~/.local/share/applications/voxt-*.desktop >/dev/null 2>&1; then
        launchers+=(~/.local/share/applications/voxt-*.desktop)
    fi
    
    if [[ ${#user_data_found[@]} -gt 0 ]]; then
        log_warning "Found user data:"
        for data in "${user_data_found[@]}"; do
            echo "  - $data"
        done
        
        echo ""
        log_warning "⚠️  This includes all downloaded models, configuration, and logs!"
        if ask_user "Remove all user data and configuration?" "n"; then
            log_info "Removing user data..."
            rm -rf ~/.config/voxt 2>/dev/null || true
            rm -rf ~/.local/share/voxt 2>/dev/null || true
            log_success "User data removed"
        fi
    else
        log_info "No user data found"
    fi
    
    if [[ ${#launchers[@]} -gt 0 ]]; then
        log_warning "Found desktop launchers:"
        for launcher in "${launchers[@]}"; do
            echo "  - $launcher"
        done
        
        if ask_user "Remove desktop launchers?"; then
            log_info "Removing launchers..."
            rm -f ~/.local/share/applications/voxt.desktop 2>/dev/null || true
            rm -f ~/.local/share/applications/voxt-*.desktop 2>/dev/null || true
            log_success "Desktop launchers removed"
        fi
    else
        log_info "No desktop launchers found"
    fi
}

remove_systemd_services() {
    echo ""
    log_info "Checking systemd services..."
    
    if [[ -f ~/.config/systemd/user/ydotoold.service ]]; then
        log_warning "Found ydotoold systemd service"
        if ask_user "Stop and remove ydotoold service?"; then
            log_info "Stopping and disabling ydotoold service..."
            systemctl --user stop ydotoold.service 2>/dev/null || true
            systemctl --user disable ydotoold.service 2>/dev/null || true
            rm -f ~/.config/systemd/user/ydotoold.service
            systemctl --user daemon-reload 2>/dev/null || true
            log_success "ydotoold service removed"
        fi
    else
        log_info "No ydotoold systemd service found"
    fi
}

remove_udev_rules() {
    echo ""
    log_info "Checking udev rules..."
    
    if [[ -f /etc/udev/rules.d/99-uinput.rules ]]; then
        log_warning "Found udev rule for ydotool: /etc/udev/rules.d/99-uinput.rules"
        if ask_user "Remove udev rule? (requires sudo)"; then
            log_info "Removing udev rule..."
            sudo rm -f /etc/udev/rules.d/99-uinput.rules
            sudo udevadm control --reload-rules 2>/dev/null || true
            log_success "udev rule removed"
        fi
    else
        log_info "No ydotool udev rules found"
    fi
}

remove_user_from_groups() {
    echo ""
    log_info "Checking user group memberships..."
    
    if groups | grep -q "input"; then
        log_warning "User is in 'input' group (added for ydotool)"
        echo "  This may have been added specifically for VOXT/ydotool functionality"
        if ask_user "Remove user from 'input' group? (requires sudo)" "n"; then
            log_info "Removing user from input group..."
            sudo gpasswd -d "$USER" input 2>/dev/null || true
            log_success "User removed from input group"
            log_warning "⚠️  You may need to log out and back in for group changes to take effect"
        fi
    else
        log_info "User not in 'input' group"
    fi
}

remove_system_packages() {
    echo ""
    log_info "Checking system packages..."
    
    if [[ "$PKG_MANAGER" == "unknown" ]]; then
        log_warning "Package manager not detected - skipping package removal"
        log_info "You may want to manually remove these packages if they were installed for VOXT:"
        echo "  - ffmpeg, portaudio19-dev, cmake, build-essential, git, curl, etc."
        return
    fi
    
    log_warning "VOXT setup may have installed system packages like:"
    echo "  - ffmpeg (audio/video processing)"
    echo "  - portaudio19-dev (audio interface)"
    echo "  - cmake, build-essential (build tools)"
    echo "  - git, curl (download tools)"
    echo "  - xclip, wl-clipboard (clipboard tools)"
    echo ""
    echo "⚠️  These packages may be used by other applications!"
    
    if ask_user "Remove VOXT-related system packages? (CAUTION: may break other apps)" "n"; then
        log_info "Removing packages..."
        
        case "$PKG_MANAGER" in
            "apt")
                $PKG_REMOVE ffmpeg portaudio19-dev cmake build-essential git curl xclip wl-clipboard 2>/dev/null || true
                ;;
            "dnf"|"yum")
                $PKG_REMOVE ffmpeg portaudio-devel cmake gcc-c++ git curl xclip wl-clipboard 2>/dev/null || true
                ;;
            "pacman")
                $PKG_REMOVE ffmpeg portaudio cmake base-devel git curl xclip wl-clipboard 2>/dev/null || true
                ;;
            "zypper")
                $PKG_REMOVE ffmpeg portaudio-devel cmake gcc-c++ git curl xclip wl-clipboard 2>/dev/null || true
                ;;
        esac
        
        log_info "Running autoremove to clean up orphaned packages..."
        eval "$PKG_AUTOREMOVE" 2>/dev/null || true
        
        log_success "Packages removed"
    fi
}

remove_repository_directory() {
    echo ""
    log_info "Checking repository directory..."
    
    if [[ -d "$VOXT_REPO_DIR" && "$PWD" == "$VOXT_REPO_DIR" ]]; then
        log_warning "You are currently in the VOXT repository directory"
        log_warning "Repository location: $VOXT_REPO_DIR"
        
        if ask_user "Remove the entire VOXT repository directory?"; then
            log_info "Moving out of repository directory..."
            cd ~
            log_info "Removing repository directory..."
            rm -rf "$VOXT_REPO_DIR"
            log_success "Repository directory removed"
            log_warning "⚠️  This uninstall script has been deleted along with the repository"
        fi
    else
        log_info "Not in repository directory or directory not found"
    fi
}

# ──────────────────────────────────────────────────────────────────────────────
# Main execution
# ──────────────────────────────────────────────────────────────────────────────

main() {
    echo "This script will help you completely remove VOXT from your system."
    echo "You will be prompted before each removal step."
    echo ""
    
    # Detect system
    detect_distro
    detect_package_manager
    
    # Execute removal steps
    stop_running_processes
    remove_pipx_installation
    remove_repository_files
    remove_user_data
    remove_systemd_services
    remove_udev_rules
    remove_user_from_groups
    remove_system_packages
    remove_repository_directory
    
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    Uninstall Complete!                        ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    log_success "VOXT uninstall process completed"
    echo ""
    echo "Notes:"
    echo "• If you removed yourself from the 'input' group, log out and back in"
    echo "• Some system packages were left to avoid breaking other applications"
    echo "• Thank you for trying VOXT! 🗣️⌨️"
}

# Run with proper error handling
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
