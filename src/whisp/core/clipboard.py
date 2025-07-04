import os, shutil, subprocess, pyperclip, logging
from whisp.utils.libw import verbo


class ClipboardManager:
    def __init__(self, backend: str | None = None):
        # Accept optional override but default to automatic detection.
        self.backend = (backend or "auto").lower()
        self._resolve_backend()

    def _resolve_backend(self):
        if self.backend == "auto":
            # Detect clipboard backend automatically
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
                self.backend = "wl-copy"
            elif shutil.which("xclip"):
                self.backend = "xclip"
            elif shutil.which("xsel"):
                self.backend = "xsel"                
            elif shutil.which("wl-copy"):
                self.backend = "wl-copy"
            else:
                self.backend = "pyperclip"

        verbo(f"[clipboard] Using backend: {self.backend}")

    def copy(self, text: str):
        if not text.strip():
            print("[clipboard] Warning: Tried to copy empty text.")
            return

        if self.backend == "pyperclip":
            try:
                pyperclip.copy(text)
            except pyperclip.PyperclipException as e:
                logging.warning(
                    "Clipboard copy failed (%s). "
                    "Install xclip, xsel or wl-clipboard to enable copy-&-paste.",
                    e,
                )
        elif self.backend in ("xclip", "xsel"):
            # xclip/xsel need a flag to specify the clipboard selection
            flag = "-selection clipboard" if self.backend == "xclip" else "-i"
            self._run_cmd(f"{self.backend} {flag}", input=text)
        elif self.backend == "wl-copy":
            self._run_cmd("wl-copy", input=text)
        else:
            raise ValueError(f"Unsupported clipboard backend: {self.backend}")

    def _run_cmd(self, cmd, input):
        try:
            subprocess.run(cmd.split(), input=input.encode(), check=True)
        except subprocess.CalledProcessError as e:
            logging.warning("[clipboard] Error using '%s': %s", cmd, e)
