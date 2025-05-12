import pyperclip
import subprocess
import os
import shutil


class ClipboardManager:
    def __init__(self, backend="auto"):
        self.backend = backend.lower()
        self._resolve_backend()

    def _resolve_backend(self):
        if self.backend == "auto":
            # Detect clipboard backend automatically
            if shutil.which("xclip"):
                self.backend = "xclip"
            elif shutil.which("wl-copy"):
                self.backend = "wl-copy"
            else:
                self.backend = "pyperclip"

        print(f"[clipboard] Using backend: {self.backend}")

    def copy(self, text: str):
        if not text.strip():
            print("[clipboard] Warning: Tried to copy empty text.")
            return

        if self.backend == "pyperclip":
            pyperclip.copy(text)
        elif self.backend == "xclip":
            self._run_cmd("xclip -selection clipboard", input=text)
        elif self.backend == "wl-copy":
            self._run_cmd("wl-copy", input=text)
        else:
            raise ValueError(f"Unsupported clipboard backend: {self.backend}")

    def _run_cmd(self, cmd, input):
        try:
            subprocess.run(
                cmd.split(),
                input=input.encode(),
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"[clipboard] Error using '{cmd}': {e}")
