import subprocess
import time
import shutil
import os
import sys
import select
from voxd.utils.libw import verbo
import pyperclip  # New: clipboard helper for instant paste
from pathlib import Path

def detect_backend():
    """
    Return a best-guess of the active graphical backend.

    Priority  1. $WAYLAND_DISPLAY  → "wayland"
              2. $DISPLAY         → "x11"
              3. $XDG_SESSION_TYPE
              4. "unknown"
    """
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    x11_display = os.environ.get("DISPLAY")
    session_type = os.environ.get("XDG_SESSION_TYPE")
    
    # Debug info for troubleshooting
    verbo(f"[typer] Environment: WAYLAND_DISPLAY={wayland_display}, DISPLAY={x11_display}, XDG_SESSION_TYPE={session_type}")
    
    if wayland_display:
        return "wayland"
    if x11_display:
        return "x11"
    if session_type:
        return session_type.lower()
    return "unknown"

class SimulatedTyper:
    def __init__(self, delay=None, start_delay=None, cfg=None):
        # Accept delay in milliseconds or seconds – treat ≤0 as instant paste.
        if delay is None:
            delay_val = 10
        else:
            delay_val = delay

        # Store as float for logic but keep string form for tool calls.
        try:
            self.delay_ms = float(delay_val)
        except (TypeError, ValueError):
            self.delay_ms = 10.0

        # For tool calls, use minimum 1ms delay to avoid ydotool buffer issues with 0ms
        self.delay_str = str(max(1, int(self.delay_ms)))
        # Extra delay (in seconds) inserted before the first keystroke so
        # that the key-release events from the hot-key that stopped the
        # recording have time to reach the focused window. Prevents the
        # first character from being interpreted as Ctrl/Alt+<char>.
        self.start_delay = float(start_delay) if start_delay is not None else 0.25
        self.backend = detect_backend()
        self.tool = None
        self.enabled = self._detect_typing_tool()
        
        # Ensure ydotool CLI uses the same user socket as our service
        if self.enabled and self.tool and os.path.basename(self.tool) == "ydotool":
            os.environ.setdefault("YDOTOOL_SOCKET", str(Path.home() / ".ydotool_socket"))
        
        # Check daemon status for ydotool and attempt auto-start if needed
        if self.enabled and not self._check_ydotool_daemon():
            print("[typer] ⚠️ ydotool available but daemon not running - attempting auto-start...")
            if self._auto_start_ydotool_daemon():
                print("[typer] ✅ ydotool daemon started successfully")
            else:
                print("[typer] ⚠️ ydotool daemon auto-start failed - typing may be unreliable")
                print("[typer] → Manual fix: 'systemctl --user start ydotoold.service' or re-run setup.sh")
        
        verbo(f"[typer] Typing {'enabled' if self.enabled else 'disabled'} (backend: {self.backend}, tool: {self.tool})")
        
        # Store config reference for real-time updates
        self.cfg = cfg

    def _detect_typing_tool(self):
        search_dirs = ["/usr/local/bin", "/usr/bin", str(Path.home() / ".local/bin")]

        def _which(cmd: str):
            """Return absolute path of *cmd* by searching PATH plus fallback dirs."""
            path = shutil.which(cmd)
            if path:
                return path
            for d in search_dirs:
                p = Path(d) / cmd
                if p.is_file() and os.access(p, os.X_OK):
                    return str(p)
            return None

        # Try to find the best tool regardless of backend detection issues
        if self.backend == "wayland":
            path = _which("ydotool")
            if path:
                self.tool = path
                return True
            print("[typer] ⚠️ ydotool not found in PATH or common dirs for Wayland.")
        elif self.backend == "x11":
            path = _which("xdotool")
            if path:
                self.tool = path
                return True
            print("[typer] ⚠️ xdotool not found in PATH or common dirs for X11.")
        else:
            print(f"[typer] ⚠️ Unknown backend: {self.backend}. Trying both tools...")
        
        # Fallback: if backend detection failed or tool not found, try both tools
        # Priority: ydotool first (more modern), then xdotool
        for tool_name in ["ydotool", "xdotool"]:
            path = _which(tool_name)
            if path:
                self.tool = path
                print(f"[typer] Found {tool_name} at {path}, using as fallback.")
                return True
        
        print("[typer] ⚠️ No typing tools found (tried ydotool and xdotool). Typing disabled.")
        return False

    def _check_ydotool_daemon(self):
        """Check if ydotoold daemon is running when using ydotool"""
        if not self.tool or "ydotool" not in os.path.basename(self.tool):
            return True
            
        # Ensure consistent socket path for checks
        os.environ.setdefault("YDOTOOL_SOCKET", str(Path.home() / ".ydotool_socket"))
        sock = os.environ.get("YDOTOOL_SOCKET")
        try:
            # Prefer a quick socket probe: if ydotool can talk, the daemon is usable
            if sock and os.path.exists(sock):
                try:
                    cp = subprocess.run(
                        ["ydotool", "sleep", "0"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2
                    )
                    if cp.returncode == 0:
                        return True
                except Exception:
                    pass

            # Check if systemd service exists and is active
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "ydotoold.service"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True
            else:
                verbo(f"[typer] ydotoold daemon not running (status: {result.stdout.strip()})")
                # Also check if daemon is running manually (not via systemd)
                try:
                    pgrep_result = subprocess.run(
                        ["pgrep", "-x", "ydotoold"],
                        capture_output=True, timeout=3
                    )
                    if pgrep_result.returncode == 0:
                        verbo("[typer] ydotoold daemon running manually")
                        return True
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            verbo("[typer] Cannot check ydotoold daemon status")
            return False
    
    def _auto_start_ydotool_daemon(self):
        """Attempt to automatically start ydotool daemon"""
        if not self.tool or "ydotool" not in os.path.basename(self.tool):
            return False
            
        try:
            # First try systemctl start
            result = subprocess.run(
                ["systemctl", "--user", "start", "ydotoold.service"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Poll for readiness (handles 'activating' race)
                for _ in range(6):
                    if self._check_ydotool_daemon():
                        return True
                    time.sleep(0.5)
            
            # If systemctl failed, try with sg input (for immediate group access)
            verbo("[typer] systemctl start failed, trying with sg input...")
            
            # Check if sg command is available
            if not shutil.which("sg"):
                verbo("[typer] sg command not available")
                return False
                
            # Get current user and socket path
            home_dir = os.path.expanduser("~")
            socket_path = os.environ.get("YDOTOOL_SOCKET", f"{home_dir}/.ydotool_socket")
            yd = shutil.which("ydotoold") or "ydotoold"
            uid = os.getuid()
            gid = os.getgid()
            
            # Try to start with sg input - background the daemon properly
            cmd_str = f"nohup {yd} --socket-path='{socket_path}' --socket-own={uid}:{gid} >/dev/null 2>&1 &"
            cmd = ["sg", "input", "-c", cmd_str]
            
            verbo(f"[typer] Starting ydotoold with command: {' '.join(cmd)}")
            
            # Start daemon in background
            subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            
            # Poll for readiness
            for _ in range(8):
                if self._check_ydotool_daemon():
                    verbo("[typer] ydotool daemon started with sg input")
                    return True
                time.sleep(0.5)
            verbo("[typer] ydotool daemon failed to start with sg input")
            return False
                
        except Exception as e:
            verbo(f"[typer] Failed to auto-start ydotool daemon: {e}")
            return False

    def _run_tool(self, cmd: list[str]):
        """Run *cmd* catching FileNotFoundError so GUI won't freeze."""
        try:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if result.returncode != 0:
                print(f"[typer] ⚠️ Typing tool exited with code {result.returncode}")
        except subprocess.TimeoutExpired:
            print(f"[typer] ⚠️ Typing tool timed out after 10 seconds")
        except FileNotFoundError:
            print(f"[typer] ⚠️ Typing tool executable not found: {cmd[0]} – falling back to clipboard only.")
            self.enabled = False
        except Exception as e:
            print(f"[typer] ⚠️ Typing tool failed: {e}")

    def flush_stdin(self):
        """Force clear stdin buffer using terminal control"""
        # Skip if no proper terminal (e.g., when launched via .desktop)
        if not sys.stdin.isatty():
            return
        try:
            os.system('stty -icanon -echo')  # Raw mode
            time.sleep(0.1)  # Small delay to let terminal catch up
            while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                os.read(sys.stdin.fileno(), 1024)
        finally:
            os.system('stty icanon echo')  # Restore normal mode

    def type(self, text):
        if not self.enabled:
            print("[typer] ⚠️ Typing disabled - required tool not available.")
            return

        # If delay ≤ 0, or typing tool is missing, use fast clipboard paste instead of typing
        if self.delay_ms <= 0 or not self.tool:
            self._paste(text)
            return

        # Give the window manager a moment to process key-release events
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        # Ensure lingering modifiers are up (mostly relevant for xdotool/X11)
        if self.tool == "xdotool":
            # Release common modifiers; ignore errors if any key is already up
            subprocess.run(["xdotool", "keyup", "ctrl", "alt", "shift", "super"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Normalize trailing whitespace and optionally append a single space
        t = text.rstrip()
        try:
            if self.cfg and bool(self.cfg.data.get("append_trailing_space", True)):
                t = t + " "
        except Exception:
            t = t

        verbo(f"[typer] Typing transcript using {self.tool}...")
        tool_name = os.path.basename(self.tool) if self.tool else ""
        if tool_name == "ydotool" and self.tool:
            self._run_tool([self.tool, "type", "-d", self.delay_str, t])
        elif tool_name == "xdotool" and self.tool:
            self._run_tool([self.tool, "type", "--delay", self.delay_str, t])
        else:
            print("[typer] ⚠️ No valid typing tool found.")
            return
        self.flush_stdin() # Flush pending input before any new prompt

    # ------------------------------------------------------------------
    # Helper: fast clipboard paste
    # ------------------------------------------------------------------
    def _paste(self, text: str):
        """Copy *text* to clipboard and use Ctrl+Shift+V (default) or Ctrl+V (when enabled)"""
        # Copy to clipboard first
        try:
            t = text.rstrip()
            try:
                if self.cfg and bool(self.cfg.data.get("append_trailing_space", True)):
                    t = t + " "
            except Exception:
                pass
            pyperclip.copy(t)
        except Exception as e:
            verbo(f"[typer] Clipboard copy failed: {e} – falling back to typing mode.")
            self._type_char_by_char(text)
            return

        # Allow clipboard daemon to update and window to process modifiers
        time.sleep(0.10)
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        # Determine paste shortcut: Check config for real-time updates
        use_ctrl_v = self.cfg and self.cfg.data.get("ctrl_v_paste", False)
        paste_keys = "ctrl+v" if use_ctrl_v else "ctrl+shift+v"
        
        verbo(f"[typer] Pasting transcript via {self.tool} using {paste_keys}...")

        try:
            tool_name = os.path.basename(self.tool) if self.tool else ""
            
            if "xdotool" in tool_name:
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", paste_keys],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
            elif "ydotool" in tool_name:
                if use_ctrl_v:
                    # Ctrl+V: Ctrl(29) + V(47)
                    subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=5)
                else:
                    # Default Ctrl+Shift+V: Ctrl(29) + Shift(42) + V(47)
                    subprocess.run(["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=5)
            else:
                print(f"[typer] ⚠️ Paste shortcut not supported for tool: {self.tool}")
                self._type_char_by_char(text)
                return
                
        except subprocess.TimeoutExpired:
            print("[typer] ⚠️ Paste operation timed out")
        except Exception as e:
            print(f"[typer] ⚠️ Paste operation failed: {e}")

        self.flush_stdin()

    def _type_char_by_char(self, text: str):
        """Fallback method to type character by character without recursion"""
        if not self.enabled:
            print("[typer] ⚠️ Typing disabled - required tool not available.")
            return
        
        # Give the window manager a moment to process key-release events
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        # Ensure lingering modifiers are up (mostly relevant for xdotool/X11)
        if self.tool == "xdotool":
            subprocess.run(["xdotool", "keyup", "ctrl", "alt", "shift", "super"], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        t = text.rstrip()
        try:
            if self.cfg and bool(self.cfg.data.get("append_trailing_space", True)):
                t = t + " "
        except Exception:
            pass

        verbo(f"[typer] Typing transcript character-by-character using {self.tool}...")
        tool_name = os.path.basename(self.tool) if self.tool else ""
        if tool_name == "ydotool" and self.tool:
            self._run_tool([self.tool, "type", "-d", "10", t])  # Use 10ms delay for fallback
        elif tool_name == "xdotool" and self.tool:
            self._run_tool([self.tool, "type", "--delay", "10", t])  # Use 10ms delay for fallback
        else:
            print("[typer] ⚠️ No valid typing tool found for fallback.")
            return
        
        self.flush_stdin()
