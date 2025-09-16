from datetime import datetime
from pathlib import Path
from voxd.utils.libw import verbo, verr


class SessionLogger:
    def __init__(self, enabled=True, log_location: str = ""):
        self.enabled = enabled
        self.log_location = log_location or str(Path.home())  # fall-back "~/"
        self.entries: list[str] = []
        if not self.enabled:
            verbo("[logger] Logging disabled.")
        else:
            verbo(f"[logger] Logging enabled. Initial dir: {self.log_location}")

    def _ask_user_for_path(self):
        """
        Open a native "Save File" dialog.
        • If a Qt application is *already* running (GUI / tray) we use QFileDialog.
          We DO NOT spin up a new QApplication inside CLI mode because that would
          keep an extra Qt event-loop alive and freeze the terminal after the
          dialog closes.
        • Otherwise we fall back to Tkinter which creates its own transient
          root window and cleans it up immediately.
        Returns a Path chosen by the user or None if they cancelled.
        """
        # --- Prefer Qt *only* when an app instance already exists ------------
        try:
            from PyQt6.QtWidgets import QFileDialog, QApplication
            qt_app = QApplication.instance()
            if qt_app is not None:  # we are inside GUI / tray → safe to use Qt
                file_name, _ = QFileDialog.getSaveFileName(
                    parent=None,
                    caption="Save VOXD Session Log",
                    directory=self.log_location or str(Path.home()),
                    filter="Text files (*.txt);;All files (*)",
                )
                return Path(file_name) if file_name else None
        except ModuleNotFoundError:
            # PyQt6 not installed – fall back to Tk
            pass

        # --- Tkinter fallback (CLI / headless) ------------------------------
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        # Prevent the dialog from appearing behind other windows on some DEs
        root.attributes('-topmost', True)

        file_name = filedialog.asksaveasfilename(
            parent=root,
            initialdir=self.log_location or str(Path.home()),
            title="Save VOXD Session Log",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )

        # Ensure the window is fully destroyed so the terminal doesn't freeze
        root.update_idletasks()
        root.destroy()

        return Path(file_name) if file_name else None

    def log_entry(self, text: str):
        if not self.enabled:
            return

        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        entry = f"{timestamp} {text.strip()}"
        self.entries.append(entry)
        verbo(f"[logger] Logged entry: {entry[:60]}...")

    def save(self, path: str | None = None):
        if not self.enabled or not self.entries:
            return

        if path:
            out_path = Path(path)
        else:
            out_path = self._ask_user_for_path()
            if out_path is None:          # user pressed "Cancel"
                print("[logger] Save cancelled.")
                return

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a", encoding="utf-8") as f:
                f.write("\n".join(self.entries) + "\n")
            print(f"[logger] Saved log to {out_path}")
        except Exception as e:
            verr(f"[logger] Failed to write log: {e}")

    def show(self):
        if not self.entries:
            print("[logger] No entries logged yet.")
            return

        print("\n--- Session Log ---")
        for entry in self.entries:
            print(entry)
        print("--- End ---\n")

    def clear(self):
        self.entries = []
        print("[logger] Session log cleared.")
