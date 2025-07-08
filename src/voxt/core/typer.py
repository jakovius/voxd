import subprocess
import time
import shutil
import os
import sys
import select
from voxt.utils.libw import verbo
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
    def __init__(self, delay=None, start_delay=None):
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
        self.start_delay = float(start_delay) if start_delay is not None else 0.15
        self.backend = detect_backend()
        self.tool = None
        self.enabled = self._detect_typing_tool()
        verbo(f"[typer] Typing {'enabled' if self.enabled else 'disabled'} (backend: {self.backend}, tool: {self.tool})")

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

        # If delay ≤ 0 → use fast clipboard paste instead of typing
        if self.delay_ms <= 0:
            self._paste(text)
            return

        # Give the window manager a moment to process key-release events
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        # Ensure lingering modifiers are up (mostly relevant for xdotool/X11)
        if self.tool == "xdotool":
            # Release common modifiers; ignore errors if any key is already up
            subprocess.run(["xdotool", "keyup", "ctrl", "alt", "shift", "super"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        text = text.rstrip() # to eliminate any unwanted trailing characters added by the typer

        verbo(f"[typer] Typing transcript using {self.tool}...")
        tool_name = os.path.basename(self.tool) if self.tool else ""
        if tool_name == "ydotool" and self.tool:
            self._run_tool([self.tool, "type", "-d", self.delay_str, text])
        elif tool_name == "xdotool" and self.tool:
            self._run_tool([self.tool, "type", "--delay", self.delay_str, text])
        else:
            print("[typer] ⚠️ No valid typing tool found.")
            return
        self.flush_stdin() # Flush pending input before any new prompt

    # ------------------------------------------------------------------
    # Helper: fast clipboard paste
    # ------------------------------------------------------------------
    def _paste(self, text: str):
        """Copy *text* to clipboard and hit Ctrl+V/ydotool key sequence"""
        # Copy to clipboard first
        try:
            pyperclip.copy(text.rstrip())
        except Exception as e:
            verbo(f"[typer] Clipboard copy failed: {e} – falling back to typing mode.")
            # Fall back to character-by-character typing with minimal delay
            # but prevent infinite recursion by calling _type_char_by_char directly
            self._type_char_by_char(text)
            return

        # Allow clipboard daemon to update and window to process modifiers
        time.sleep(0.10)  # clipboard settle
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        verbo(f"[typer] Pasting transcript via {self.tool}…")

        try:
            # Determine which tool to use based on the actual tool path, not just backend
            tool_name = os.path.basename(self.tool) if self.tool else ""
            
            if "xdotool" in tool_name:
                # Try Ctrl+V first (most common)
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
            elif "ydotool" in tool_name:
                # Use Ctrl+V sequence for ydotool
                subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5)
            else:
                print(f"[typer] ⚠️ Paste shortcut not supported for tool: {self.tool}")
                # Fall back to typing if paste not supported
                self._type_char_by_char(text)
                return
        except subprocess.TimeoutExpired:
            print("[typer] ⚠️ Paste operation timed out")
        except Exception as e:
            print(f"[typer] ⚠️ Paste operation failed: {e}")

        # Clean up stdin to avoid stray inputs next prompt
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

        text = text.rstrip()  # eliminate any unwanted trailing characters

        verbo(f"[typer] Typing transcript character-by-character using {self.tool}...")
        tool_name = os.path.basename(self.tool) if self.tool else ""
        if tool_name == "ydotool" and self.tool:
            self._run_tool([self.tool, "type", "-d", "10", text])  # Use 10ms delay for fallback
        elif tool_name == "xdotool" and self.tool:
            self._run_tool([self.tool, "type", "--delay", "10", text])  # Use 10ms delay for fallback
        else:
            print("[typer] ⚠️ No valid typing tool found for fallback.")
            return
        
        self.flush_stdin()
