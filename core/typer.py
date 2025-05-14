import subprocess
import time
import shutil
import os
import sys
import select

def detect_backend():
    # Try to detect the graphical backend (Wayland or X11)
    if os.environ.get("XDG_SESSION_TYPE"):
        return os.environ["XDG_SESSION_TYPE"].lower()
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"

class SimulatedTyper:
    def __init__(self, delay=None):
        self.delay = str(delay or 10)
        self.backend = detect_backend()
        self.tool = None
        self.enabled = self._detect_typing_tool()
        print(f"[typer] Typing {'enabled' if self.enabled else 'disabled'} (backend: {self.backend}, tool: {self.tool})")

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

        text = text.rstrip() # to eliminate any unwanted trailing characters added by the typer

        print(f"[typer] Typing transcript using {self.tool}...")
        if self.tool == "ydotool":
            subprocess.run(["ydotool", "type", "-d", self.delay, text])
        elif self.tool == "xdotool":
            subprocess.run(["xdotool", "type", "--delay", self.delay, text])
        else:
            print("[typer] ⚠️ No valid typing tool found.")
            return
        self.flush_stdin() # Flush pending input before any new prompt
