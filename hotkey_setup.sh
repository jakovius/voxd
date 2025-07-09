#!/usr/bin/env bash
# =============================================================================
#  VOXT Hotkey Setup & Management Tool
#
#  Automates global hotkey setup, validation, troubleshooting, and cleanup
#  for VOXT voice-to-text application across different desktop environments.
#
#  Usage:
#    ./hotkey_setup.sh setup      - Interactive hotkey setup
#    ./hotkey_setup.sh diagnose   - Troubleshoot hotkey issues
#    ./hotkey_setup.sh cleanup    - Clean orphaned keybinding entries
#    ./hotkey_setup.sh remove     - Remove VOXT hotkeys
# =============================================================================
set -euo pipefail

# ───────────────────────────── helpers ────────────────────────────────────────
YEL=$'\033[1;33m'; GRN=$'\033[1;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'
msg() { printf "${YEL}==>${NC} %s\n" "$*"; }
die() { printf "${RED}error:${NC} %s\n" "$*" >&2; exit 1; }

detect_desktop() {
  # Check for GNOME-based environments first (most reliable)
  if command -v gnome-shell >/dev/null 2>&1 && pgrep -x gnome-shell >/dev/null 2>&1; then
    echo "gnome"
  elif [[ -n "${XDG_CURRENT_DESKTOP:-}" ]]; then
    local desktop="${XDG_CURRENT_DESKTOP,,}"
    # Map known GNOME variants
    case "$desktop" in
      *gnome*|ubuntu:gnome|unity)
        echo "gnome"
        ;;
      *kde*|*plasma*)
        echo "kde"
        ;;
      *)
        echo "$desktop"
        ;;
    esac
  elif [[ -n "${DESKTOP_SESSION:-}" ]]; then
    local session="${DESKTOP_SESSION,,}"
    case "$session" in
      *gnome*|ubuntu)
        echo "gnome"
        ;;
      *kde*|*plasma*)
        echo "kde"
        ;;
      *)
        echo "$session"
        ;;
    esac
  else
    echo "unknown"
  fi
}

get_voxt_hotkey() {
  # Try multiple methods to detect VOXT hotkeys
  
  # Method 1: Direct dconf search (most reliable)
  if command -v dconf >/dev/null; then
    local dconf_result
    dconf_result=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | \
      grep -A3 -B1 "voxt.*trigger-record" | grep "binding=" | head -n1 | cut -d"'" -f2)
    if [[ -n "$dconf_result" ]]; then
      echo "$dconf_result"
      return 0
    fi
  fi
  
  # Method 2: Use voxt --diagnose if available (suppress stderr)
  if command -v voxt >/dev/null; then
    local voxt_result
    voxt_result=$(voxt --diagnose 2>/dev/null | grep "Detected shortcut:" | cut -d: -f2 | xargs)
    if [[ -n "$voxt_result" && "$voxt_result" != "(none detected)" ]]; then
      echo "$voxt_result"
      return 0
    fi
  fi
  
  # Method 3: Direct gsettings search (fallback)
  if command -v gsettings >/dev/null; then
    local paths_raw
    paths_raw=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)
    if [[ -n "$paths_raw" && "$paths_raw" != "@as []" ]]; then
      python3 -c "
import json, subprocess, sys
try:
    paths_raw = '''$paths_raw'''
    paths = json.loads(paths_raw.replace(\"'\", '\"'))
    
    for path in paths:
        try:
            cmd = subprocess.check_output(['gsettings', 'get', path, 'command'], 
                                        text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
            if 'voxt --trigger-record' in cmd:
                binding = subprocess.check_output(['gsettings', 'get', path, 'binding'], 
                                                text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
                print(binding)
                break
        except subprocess.CalledProcessError:
            continue
except: pass
" 2>/dev/null
    fi
  fi
}

list_gnome_voxt_keybindings() {
  # Try dconf first (more reliable)
  if command -v dconf >/dev/null; then
    local dconf_result
    dconf_result=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null)
    
    if [[ -n "$dconf_result" ]]; then
      local voxt_found=false
      # Parse dconf output for VOXT keybindings
      echo "$dconf_result" | python3 -c "
import sys, re
content = sys.stdin.read()
sections = re.split(r'\n(?=\[)', content)
voxt_bindings = []

for section in sections:
    if 'voxt.*trigger-record' in section.lower() or 'voxt --trigger-record' in section:
        lines = section.strip().split('\n')
        if lines and lines[0].startswith('[custom-keybindings/'):
            path_match = re.search(r'\[(custom-keybindings/custom\d+)\]', lines[0])
            if path_match:
                path = '/org/gnome/settings-daemon/plugins/media-keys/' + path_match.group(1) + '/'
                binding = name = command = ''
                
                for line in lines[1:]:
                    if line.startswith('binding='):
                        binding = line.split('=', 1)[1].strip(\"'\")
                    elif line.startswith('name='):
                        name = line.split('=', 1)[1].strip(\"'\")
                    elif line.startswith('command='):
                        command = line.split('=', 1)[1].strip('\"').strip(\"'\")
                
                if binding and command:
                    voxt_bindings.append((path, name, binding, command))

if voxt_bindings:
    print('FOUND_VOXT_BINDINGS')
    for path, name, binding, cmd in voxt_bindings:
        print(f'{path}|{name}|{binding}|{cmd}')
" 2>/dev/null
      
      # Check if we found anything
      if echo "$dconf_result" | python3 -c "
import sys, re
content = sys.stdin.read()
if 'voxt.*trigger-record' in content.lower() or 'voxt --trigger-record' in content:
    print('FOUND')
" 2>/dev/null | grep -q "FOUND"; then
        return 0
      fi
    fi
  fi
  
  # Fallback to gsettings method
  if ! command -v gsettings >/dev/null; then
    return 1
  fi
  
  local paths_raw
  paths_raw=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null) || return 1
  
  if [[ "$paths_raw" == "@as []" || -z "$paths_raw" ]]; then
    return 1
  fi
  
  # Parse and check each keybinding
  python3 -c "
import json, subprocess, sys
try:
    paths_raw = '''$paths_raw'''
    paths = json.loads(paths_raw.replace(\"'\", '\"'))
    voxt_bindings = []
    
    for path in paths:
        try:
            cmd = subprocess.check_output(['gsettings', 'get', path, 'command'], 
                                        text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
            if 'voxt --trigger-record' in cmd:
                binding = subprocess.check_output(['gsettings', 'get', path, 'binding'], 
                                                text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
                name = subprocess.check_output(['gsettings', 'get', path, 'name'], 
                                             text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
                voxt_bindings.append((path, name, binding, cmd))
        except subprocess.CalledProcessError:
            continue
    
    if voxt_bindings:
        print('FOUND_VOXT_BINDINGS')
        for path, name, binding, cmd in voxt_bindings:
            print(f'{path}|{name}|{binding}|{cmd}')
except: pass
" 2>/dev/null
}

cleanup_orphaned_gnome_keybindings() {
  msg "Scanning for keybinding issues..."
  
  # First check if we're on GNOME - only run GNOME-specific cleanup on GNOME
  local desktop
  desktop=$(detect_desktop)
  
  if [[ "$desktop" != *"gnome"* ]]; then
    echo "Non-GNOME desktop environment detected ($desktop)"
    echo "Keybinding cleanup only applies to GNOME systems"
    echo ""
    
    # Just check if VOXT hotkey is working
    local detected_key
    detected_key=$(get_voxt_hotkey)
    if [[ -n "$detected_key" ]]; then
      echo "✅ VOXT hotkey detected and appears to be working: $detected_key"
    else
      echo "⚠️  No VOXT hotkey detected - you may need to set one up manually"
    fi
    return 0
  fi
  
  if ! command -v gsettings >/dev/null; then
    echo "gsettings not available, skipping GNOME cleanup"
    return 0
  fi
  
  local paths_raw
  paths_raw=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null) || {
    echo "Could not read GNOME keybindings"
    return 0
  }
  
  if [[ "$paths_raw" == "@as []" || -z "$paths_raw" ]]; then
    # Check if there are keybindings in dconf that aren't in the active list
    local dconf_entries
    dconf_entries=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | grep -E '^\[custom-keybindings/custom[0-9]+\]$' | wc -l)
    
    if [[ $dconf_entries -gt 0 ]]; then
      echo "Found $dconf_entries keybinding(s) in dconf but none in active list"
      echo "This usually means keybindings were accidentally deactivated"
      read -r -p "Restore them to active list? [Y/n]: " restore_reply
      restore_reply=${restore_reply:-Y}
      if [[ $restore_reply =~ ^[Yy]$ ]]; then
        restore_dconf_keybindings
      fi
    else
      echo "No custom keybindings found"
    fi
    return 0
  fi
  
  # CONSERVATIVE cleanup: Only remove entries that are truly broken
  # An entry is only considered "orphaned" if:
  # 1. It exists in the active list AND
  # 2. ALL of its required properties (name, command, binding) are completely missing/unreadable
  local cleanup_result
  cleanup_result=$(python3 -c "
import json, subprocess, sys
try:
    paths_raw = '''$paths_raw'''
    paths = json.loads(paths_raw.replace(\"'\", '\"'))
    valid_paths = []
    orphaned_paths = []
    voxt_paths = []
    
    for path in paths:
        # Check if ALL required properties are missing (truly orphaned)
        name_missing = command_missing = binding_missing = False
        cmd_content = name_content = binding_content = ''
        
        try:
            cmd_content = subprocess.check_output(['gsettings', 'get', path, 'command'], 
                                                stderr=subprocess.DEVNULL, text=True).strip().strip(\"'\")
        except subprocess.CalledProcessError:
            command_missing = True
            
        try:
            name_content = subprocess.check_output(['gsettings', 'get', path, 'name'], 
                                                 stderr=subprocess.DEVNULL, text=True).strip().strip(\"'\")
        except subprocess.CalledProcessError:
            name_missing = True
            
        try:
            binding_content = subprocess.check_output(['gsettings', 'get', path, 'binding'], 
                                                    stderr=subprocess.DEVNULL, text=True).strip().strip(\"'\")
        except subprocess.CalledProcessError:
            binding_missing = True
        
        # Only consider it orphaned if ALL properties are missing or empty
        if (command_missing or not cmd_content) and (name_missing or not name_content) and (binding_missing or not binding_content):
            orphaned_paths.append(path)
        else:
            # At least some properties exist - consider it valid
            valid_paths.append(path)
            if 'voxt --trigger-record' in cmd_content:
                voxt_paths.append(path)
    
    print(f'VALID_COUNT:{len(valid_paths)}')
    print(f'VOXT_COUNT:{len(voxt_paths)}')
    if orphaned_paths:
        print('CLEANUP_NEEDED')
        print(f'ORPHANED_COUNT:{len(orphaned_paths)}')
        print(f'VALID_PATHS:{json.dumps(valid_paths)}')
        for path in orphaned_paths:
            print(f'ORPHANED:{path}')
    else:
        print('CLEAN')
except Exception as e:
    print(f'ERROR:{e}')
" 2>/dev/null)
  
  local valid_count voxt_count
  valid_count=$(echo "$cleanup_result" | grep "VALID_COUNT:" | cut -d: -f2)
  voxt_count=$(echo "$cleanup_result" | grep "VOXT_COUNT:" | cut -d: -f2)
  
  echo "Active keybindings: $valid_count (including $voxt_count VOXT keybinding(s))"
  
  if [[ "$cleanup_result" == *"CLEANUP_NEEDED"* ]]; then
    local orphaned_count
    orphaned_count=$(echo "$cleanup_result" | grep "ORPHANED_COUNT:" | cut -d: -f2)
    echo "Found $orphaned_count truly orphaned entries (completely empty/broken schemas)"
    echo "These entries have no name, command, or binding properties"
    
    read -r -p "Remove these broken entries? [Y/n]: " cleanup_reply
    cleanup_reply=${cleanup_reply:-Y}
    if [[ $cleanup_reply =~ ^[Yy]$ ]]; then
      local valid_paths
      valid_paths=$(echo "$cleanup_result" | grep "VALID_PATHS:" | cut -d: -f2-)
      gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$valid_paths"
      msg "✅ Cleaned up $orphaned_count broken entries, preserved $valid_count working keybindings"
    fi
  else
    echo "✅ No broken entries found - all keybindings in active list have valid properties"
  fi
}

restore_dconf_keybindings() {
  msg "Restoring keybindings from dconf to active list..."
  
  # Get all custom keybinding paths from dconf
  local dconf_paths
  dconf_paths=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | \
    grep -E '^\[custom-keybindings/custom[0-9]+\]$' | \
    sed 's/\[\(.*\)\]/\/org\/gnome\/settings-daemon\/plugins\/media-keys\/\1\//')
  
  if [[ -n "$dconf_paths" ]]; then
    local paths_array="["
    local first=true
    while IFS= read -r path; do
      if [[ "$first" == true ]]; then
        first=false
      else
        paths_array+=", "
      fi
      paths_array+="'$path'"
    done <<< "$dconf_paths"
    paths_array+="]"
    
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$paths_array"
    local count=$(echo "$dconf_paths" | wc -l)
    msg "✅ Restored $count keybinding(s) to active list"
  else
    echo "No keybindings found in dconf to restore"
  fi
}

# ──────────────────────── GUI Setup Instructions ─────────────────────────

show_gui_instructions() {
  local desktop="$1"
  
  msg "🎯 Setting Up VOXT Hotkey in $desktop"
  echo ""
  echo "Command to use: bash -c 'voxt --trigger-record'"
  echo "Suggested keys: Super+R, Super+V, Ctrl+Alt+R, Super+Space"
  echo ""
  
  case "$desktop" in
    *gnome*|*ubuntu*|*pop*)
      show_gnome_instructions
      ;;
    *kde*|*plasma*)
      show_kde_instructions
      ;;
    *xfce*)
      show_xfce_instructions
      ;;
    *mate*)
      show_mate_instructions
      ;;
    *cinnamon*)
      show_cinnamon_instructions
      ;;
    *unity*)
      show_unity_instructions
      ;;
    *)
      show_generic_instructions "$desktop"
      ;;
  esac
  
  echo ""
  echo "📋 After setup:"
  echo "  1. Test with: voxt --diagnose"
  echo "  2. Run VOXT: voxt --tray (or voxt --gui)"
  echo "  3. Press your hotkey to record"
  echo ""
}

show_gnome_instructions() {
  echo "🐧 GNOME/Ubuntu Desktop Instructions:"
  echo ""
  echo "Method 1 - Settings GUI:"
  echo "  1. Open Settings (Super key → 'Settings')"
  echo "  2. Go to Keyboard section"
  echo "  3. Scroll down to 'Keyboard Shortcuts'"
  echo "  4. Click 'Custom Shortcuts' (or 'View and Customize Shortcuts')"
  echo "  5. Click '+' to add new shortcut"
  echo "  6. Name: 'VOXT Record'"
  echo "  7. Command: bash -c 'voxt --trigger-record'"
  echo "  8. Click 'Set Shortcut' and press your key combination"
  echo ""
  echo "Method 2 - Activities Overview:"
  echo "  1. Press Super key to open Activities"
  echo "  2. Type 'keyboard' and open Keyboard settings"
  echo "  3. Follow steps 3-8 above"
}

show_kde_instructions() {
  echo "🔷 KDE Plasma Instructions:"
  echo ""
  echo "  1. Open System Settings (Alt+F2 → 'systemsettings')"
  echo "  2. Go to Shortcuts section"
  echo "  3. Click 'Custom Shortcuts'"
  echo "  4. Right-click → New → Global Shortcut → Command/URL"
  echo "  5. In Trigger tab: Set your key combination"
  echo "  6. In Action tab: Command = bash -c 'voxt --trigger-record'"
  echo "  7. Apply settings"
  echo ""
  echo "Alternative:"
  echo "  1. Right-click desktop → Configure Desktop and Wallpaper"
  echo "  2. Shortcuts → Custom Shortcuts"
}

show_xfce_instructions() {
  echo "🖱️ XFCE Instructions:"
  echo ""
  echo "  1. Open Settings Manager (Alt+F2 → 'xfce4-settings-manager')"
  echo "  2. Click 'Keyboard'"
  echo "  3. Go to 'Application Shortcuts' tab"
  echo "  4. Click '+' to add new shortcut"
  echo "  5. Command: bash -c 'voxt --trigger-record'"
  echo "  6. Click OK and press your key combination"
  echo ""
  echo "Alternative:"
  echo "  1. Right-click desktop → Settings → Keyboard"
  echo "  2. Application Shortcuts tab"
}

show_mate_instructions() {
  echo "🧉 MATE Desktop Instructions:"
  echo ""
  echo "  1. Open Control Center (Alt+F2 → 'mate-control-center')"
  echo "  2. Click 'Keyboard Shortcuts'"
  echo "  3. Click 'Custom Shortcuts'"
  echo "  4. Click 'Add' to create new shortcut"
  echo "  5. Name: 'VOXT Record'"
  echo "  6. Command: bash -c 'voxt --trigger-record'"
  echo "  7. Click in the shortcut field and press your key combination"
}

show_cinnamon_instructions() {
  echo "🌿 Cinnamon Instructions:"
  echo ""
  echo "  1. Open System Settings (Menu → Preferences → System Settings)"
  echo "  2. Go to Keyboard section"
  echo "  3. Click 'Shortcuts' tab"
  echo "  4. Click 'Custom Shortcuts' category"
  echo "  5. Click '+' to add new shortcut"
  echo "  6. Name: 'VOXT Record'"
  echo "  7. Command: bash -c 'voxt --trigger-record'"
  echo "  8. Click in shortcut field and press your key combination"
}

show_unity_instructions() {
  echo "🔶 Unity Instructions:"
  echo ""
  echo "  1. Open System Settings (Super → 'System Settings')"
  echo "  2. Click 'Keyboard'"
  echo "  3. Go to 'Shortcuts' tab"
  echo "  4. Click 'Custom Shortcuts'"
  echo "  5. Click '+' to add shortcut"
  echo "  6. Name: 'VOXT Record'"
  echo "  7. Command: bash -c 'voxt --trigger-record'"
  echo "  8. Set your key combination"
}

show_generic_instructions() {
  local desktop="$1"
  echo "⚙️ Generic Instructions for $desktop:"
  echo ""
  echo "Look for these menu paths in your desktop environment:"
  echo "  • Settings → Keyboard → Shortcuts"
  echo "  • System Settings → Shortcuts"
  echo "  • Control Center → Keyboard Shortcuts"
  echo "  • Preferences → Keyboard → Custom Shortcuts"
  echo ""
  echo "Create a custom shortcut with:"
  echo "  Name: VOXT Record"
  echo "  Command: bash -c 'voxt --trigger-record'"
  echo "  Key: Your preferred combination"
}

show_hotkey_guide() {
  local desktop
  desktop=$(detect_desktop)
  
  msg "🎯 VOXT Hotkey Setup Guide"
  echo "Desktop environment: $desktop"
  echo "Session type: ${XDG_SESSION_TYPE:-unknown}"
  echo ""
  
  # Check for existing hotkey first
  local existing_key
  existing_key=$(get_voxt_hotkey)
  if [[ -n "$existing_key" ]]; then
    echo "✅ Existing VOXT hotkey detected: $existing_key"
    echo ""
    
    # Verify it's working
    local voxt_bindings dconf_check
    if [[ "$desktop" == *"gnome"* ]]; then
      voxt_bindings=$(list_gnome_voxt_keybindings 2>/dev/null)
      dconf_check=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | grep -q "voxt.*trigger-record"; echo $?)
      
      if [[ "$voxt_bindings" == *"FOUND_VOXT_BINDINGS"* ]] || [[ "$dconf_check" == "0" ]]; then
        echo "✅ Hotkey appears to be properly configured and active"
        echo ""
        echo "🧪 To test your hotkey:"
        echo "  1. Run: voxt --tray (in background)"
        echo "  2. Press: $existing_key"
        echo "  3. Check: voxt --diagnose (for troubleshooting)"
        echo ""
        read -r -p "Do you want to see setup instructions anyway? [y/N]: " show_anyway
        if [[ ! $show_anyway =~ ^[Yy]$ ]]; then
          return 0
        fi
      else
        echo "⚠️  Hotkey detected but may not be active in desktop settings"
        echo "   Consider running: $0 cleanup (to restore broken keybindings)"
      fi
    else
      echo "✅ Non-GNOME desktop - manual verification recommended"
    fi
    echo ""
  fi
  
  # Test if voxt command is available
  if command -v voxt >/dev/null; then
    echo "✅ voxt command is available"
  else
    echo "⚠️  voxt command not found - complete VOXT installation first"
    echo "   Run: ./setup.sh"
    echo ""
  fi
  
  # Show desktop-specific instructions
  show_gui_instructions "$desktop"
  
  # Show troubleshooting tips
  echo ""
  echo "🔧 Troubleshooting:"
  echo "  • If hotkey doesn't work: $0 diagnose"
  echo "  • If you have broken entries: $0 cleanup" 
  echo "  • To check current status: $0 list"
  echo "  • To remove all VOXT hotkeys: $0 remove"
}

remove_voxt_hotkeys() {
  msg "Removing VOXT hotkeys..."
  
  local desktop
  desktop=$(detect_desktop)
  
  if [[ "$desktop" == *"gnome"* ]] && command -v gsettings >/dev/null; then
    local voxt_bindings
    voxt_bindings=$(list_gnome_voxt_keybindings)
    
    if [[ "$voxt_bindings" == *"FOUND_VOXT_BINDINGS"* ]]; then
      echo "Found VOXT keybindings:"
      echo "$voxt_bindings" | grep -v "FOUND_VOXT_BINDINGS" | while IFS='|' read -r path name binding cmd; do
        echo "  $name ($binding): $cmd"
      done
      
      read -r -p "Remove these VOXT keybindings? [Y/n]: " remove_confirm
      remove_confirm=${remove_confirm:-Y}
      if [[ $remove_confirm =~ ^[Yy]$ ]]; then
        # Get current array and remove VOXT entries
        local current_bindings new_bindings
        current_bindings=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
        
        new_bindings=$(python3 -c "
import json, subprocess, sys
try:
    paths_raw = '''$current_bindings'''
    paths = json.loads(paths_raw.replace(\"'\", '\"'))
    remaining_paths = []
    
    for path in paths:
        try:
            cmd = subprocess.check_output(['gsettings', 'get', path, 'command'], 
                                        text=True, stderr=subprocess.DEVNULL).strip().strip(\"'\")
            if 'voxt --trigger-record' not in cmd:
                remaining_paths.append(path)
        except subprocess.CalledProcessError:
            continue
    
    print(json.dumps(remaining_paths))
except: pass
")
        
        gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new_bindings"
        msg "✅ Removed VOXT keybindings"
      fi
    else
      echo "No VOXT keybindings found in GNOME"
    fi
  else
    echo "Manual removal required for $desktop desktop environment"
    echo "Remove any shortcuts with command: bash -c 'voxt --trigger-record'"
  fi
}

diagnose_hotkeys() {
  msg "VOXT Hotkey Diagnostics"
  echo ""
  
  echo "1. Environment Information:"
  echo "   Desktop: $(detect_desktop)"
  echo "   Session: ${XDG_SESSION_TYPE:-unknown}"
  echo "   Display: ${DISPLAY:-none}"
  echo "   Wayland: ${WAYLAND_DISPLAY:-none}"
  echo ""
  
  echo "2. VOXT Command Status:"
  if command -v voxt >/dev/null; then
    echo "   ✅ voxt command available: $(command -v voxt)"
    # Test voxt --diagnose if available
    if voxt --diagnose >/dev/null 2>&1; then
      echo "   ✅ voxt --diagnose works"
    else
      echo "   ⚠️  voxt --diagnose failed"
    fi
  else
    echo "   ❌ voxt command not found"
  fi
  echo ""
  
  echo "3. Hotkey Detection Results:"
  detected_key=$(get_voxt_hotkey)
  if [[ -n "$detected_key" ]]; then
    echo "   ✅ Hotkey detected: $detected_key"
    
    # Test different detection methods individually
    echo "   Detection method results:"
    
    # dconf method
    if command -v dconf >/dev/null; then
      dconf_result=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | grep -A3 -B1 "voxt.*trigger-record" | grep "binding=" | head -n1 | cut -d"'" -f2)
      if [[ -n "$dconf_result" ]]; then
        echo "     ✅ dconf: $dconf_result"
      else
        echo "     ❌ dconf: not found"
      fi
    fi
    
    # voxt --diagnose method
    if command -v voxt >/dev/null; then
      voxt_result=$(voxt --diagnose 2>/dev/null | grep "Detected shortcut:" | cut -d: -f2 | xargs)
      if [[ -n "$voxt_result" && "$voxt_result" != "(none detected)" ]]; then
        echo "     ✅ voxt --diagnose: $voxt_result"
      else
        echo "     ❌ voxt --diagnose: not found"
      fi
    fi
    

  else
    echo "   ❌ No hotkey detected by any method"
  fi
  echo ""
  
  echo "4. Trigger Command Test:"
  if command -v voxt >/dev/null; then
    echo "   Testing: voxt --trigger-record"
    if timeout 2s voxt --trigger-record >/dev/null 2>&1; then
      echo "   ✅ Trigger command executed"
    else
      echo "   ⚠️  Trigger command may need VOXT to be running"
    fi
  fi
  echo ""
  
  echo "5. Desktop-Specific Checks:"
  local desktop
  desktop=$(detect_desktop)
  
  if [[ "$desktop" == *"gnome"* ]]; then
    echo "   GNOME keybinding system:"
    if command -v gsettings >/dev/null; then
      echo "   ✅ gsettings available"
      cleanup_orphaned_gnome_keybindings
      
      local voxt_bindings
      voxt_bindings=$(list_gnome_voxt_keybindings)
      if [[ "$voxt_bindings" == *"FOUND_VOXT_BINDINGS"* ]]; then
        echo "   ✅ VOXT keybindings found:"
        echo "$voxt_bindings" | grep -v "FOUND_VOXT_BINDINGS" | while IFS='|' read -r path name binding cmd; do
          echo "      $name: $binding"
        done
      else
        echo "   ⚠️  No VOXT keybindings found"
      fi
    else
      echo "   ❌ gsettings not available"
    fi
  else
    echo "   Manual check required for $desktop"
    echo "   Look for shortcuts with: bash -c 'voxt --trigger-record'"
  fi
  
  echo ""
  echo "6. Troubleshooting Suggestions:"
  if [[ -z "$(get_voxt_hotkey)" ]]; then
    echo "   → Run: $0 setup"
    echo "   → Or manually create shortcut (see README)"
  fi
  if ! command -v voxt >/dev/null; then
    echo "   → Complete VOXT installation first"
    echo "   → Run: ./setup.sh"
  fi
  echo "   → Test manually: gnome-terminal -- bash -c \"voxt --trigger-record; read\""
}

show_usage() {
  cat << EOF
VOXT Hotkey Management Tool

Usage: $0 <command>

Commands:
  guide      Show GUI instructions for setting up hotkeys in your desktop environment
  diagnose   Comprehensive hotkey troubleshooting and system analysis  
  cleanup    Clean up broken GNOME keybinding entries (safe, user-approved only)
  remove     Remove all VOXT hotkeys (with confirmation)
  list       Show current VOXT hotkeys and system status
  help       Show this help message

Examples:
  $0 guide                    # Get GUI setup instructions for your desktop
  $0 diagnose                 # Troubleshoot hotkey issues
  $0 list                     # Check current hotkey status
  
This tool provides:
- Detection of existing VOXT hotkeys across all desktop environments
- Clear GUI instructions for manual hotkey setup
- Safe cleanup of broken keybinding entries
- Comprehensive troubleshooting and system analysis

EOF
}

# ────────────────────────────── Main Logic ─────────────────────────────────

case "${1:-help}" in
  guide|setup)
    show_hotkey_guide
    ;;
  diagnose|debug)
    diagnose_hotkeys
    ;;
  cleanup)
    cleanup_orphaned_gnome_keybindings
    ;;
  remove|delete)
    remove_voxt_hotkeys
    ;;
  list)
    msg "Current VOXT hotkeys:"
    key=$(get_voxt_hotkey)
    if [[ -n "$key" ]]; then
      echo "✅ Detected: $key"
      
      # Verify the hotkey is properly configured
      desktop=$(detect_desktop)
      if [[ "$desktop" == *"gnome"* ]]; then
        voxt_bindings=$(list_gnome_voxt_keybindings 2>/dev/null)
        dconf_check=$(dconf dump /org/gnome/settings-daemon/plugins/media-keys/ 2>/dev/null | grep -q "voxt.*trigger-record"; echo $?)
        
        if [[ "$voxt_bindings" == *"FOUND_VOXT_BINDINGS"* ]] || [[ "$dconf_check" == "0" ]]; then
          echo "✅ Hotkey is active and properly configured"
          
          if [[ "$voxt_bindings" == *"FOUND_VOXT_BINDINGS"* ]]; then
            echo ""
            echo "GNOME keybinding details:"
            echo "$voxt_bindings" | grep -v "FOUND_VOXT_BINDINGS" | while IFS='|' read -r path name binding cmd; do
              if [[ -n "$path" ]]; then
                echo "  Name: $name"
                echo "  Key: $binding"
                echo "  Command: $cmd"
                echo "  Schema: $path"
                echo ""
              fi
            done
          fi
        else
          echo "⚠️  Hotkey detected but may not be active in GNOME settings"
          echo "   Try running: $0 cleanup"
        fi
      else
        echo "✅ Non-GNOME desktop - manual verification needed"
      fi
    else
      echo "❌ No hotkeys detected"
      echo ""
      echo "Checked detection methods:"
      echo "  • dconf database"
      echo "  • voxt --diagnose"
      echo "  • gsettings search"
      echo ""
      echo "To set up a hotkey, run: $0 setup"
    fi
    ;;
  help|--help|-h)
    show_usage
    ;;
  *)
    echo "Unknown command: $1"
    show_usage
    exit 1
    ;;
esac 