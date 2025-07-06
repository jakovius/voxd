import subprocess
import time
import shutil
import os
import sys
import select
from whisp.utils.libw import verbo
import pyperclip  # New: clipboard helper for instant paste

def detect_backend():
    """
    Return a best-guess of the active graphical backend.

    Priority  1. $WAYLAND_DISPLAY  → "wayland"
              2. $DISPLAY         → "x11"
              3. $XDG_SESSION_TYPE
              4. "unknown"
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    if os.environ.get("XDG_SESSION_TYPE"):
        return os.environ["XDG_SESSION_TYPE"].lower()
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

        self.delay_str = str(int(self.delay_ms))
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
        if self.backend == "wayland":
            if shutil.which("ydotool"):
                self.tool = "ydotool"
                return True
            print("[typer] ⚠️ ydotool not found. Please install it to enable typing on Wayland.")
        elif self.backend == "x11":
            if shutil.which("xdotool"):
                self.tool = "xdotool"
                return True
            print("[typer] ⚠️ xdotool not found. Please install it to enable typing on X11.")
        else:
            print("[typer] ⚠️ Unknown backend. Typing disabled.")
        return False

    def flush_stdin(self):
        """Force clear stdin buffer using terminal control"""
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
        if self.tool == "ydotool":
            subprocess.run(["ydotool", "type", "-d", self.delay_str, text])
        elif self.tool == "xdotool":
            subprocess.run(["xdotool", "type", "--delay", self.delay_str, text])
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
        except Exception:
            verbo("[typer] Clipboard copy failed – falling back to typing mode.")
            # set minimal key delay and fall back
            self.delay_ms = 10.0
            self.delay_str = "10"
            self.type(text)
            return

        # Allow clipboard daemon to update and window to process modifiers
        time.sleep(0.10)  # clipboard settle
        if self.start_delay > 0:
            time.sleep(self.start_delay)

        verbo(f"[typer] Pasting transcript via {self.tool}…")

        if self.tool == "xdotool":
            # Try common paste shortcuts; Shift+Insert removed (caused stray dash)
            for seq in ("ctrl+v", "ctrl+shift+v"):
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers", seq],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        elif self.tool == "ydotool":
            sequences = [
                ["29:1", "47:1", "47:0", "29:0"],  # ctrl+v
                ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],  # ctrl+shift+v (42=Shift)
            ]
            for seq in sequences:
                subprocess.run(["ydotool", "key", *seq],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print("[typer] ⚠️ Paste shortcut not supported for this backend.")

        # Clean up stdin to avoid stray inputs next prompt
        self.flush_stdin()
