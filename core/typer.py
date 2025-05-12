import subprocess
import time
import shutil
import os
import sys
import select


class SimulatedTyper:
    def __init__(self, delay=None):
        self.delay = str(delay or 10)
        self.enabled = self._check_ydotool()
        print(f"[typer] Typing {'enabled' if self.enabled else 'disabled'}")

    def _check_ydotool(self):
        if shutil.which("ydotool"):
            return True
        print("[typer] ⚠️ ydotool not found. Please install it to enable typing.")
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
            print("[typer] ⚠️ Typing disabled - ydotool not available.")
            return

        print("[typer] Typing transcript...")
        subprocess.run(["ydotool", "type", "-d", self.delay, text])
        self.flush_stdin() # Flush pending input before any new prompt
