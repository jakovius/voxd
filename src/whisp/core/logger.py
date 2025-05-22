from datetime import datetime
from pathlib import Path
from whisp.utils.libw import verbo


class SessionLogger:
    def __init__(self, enabled=True, log_file=None):
        self.enabled = enabled
        self.log_file = log_file or self._default_log_filename()
        self.entries = []

        if not self.enabled:
            verbo("[logger] Logging disabled.")
        else:
            verbo(f"[logger] Logging enabled. File: {self.log_file}")

    def _default_log_filename(self):
        from whisp.paths import LOG_DIR
        ts = datetime.now().strftime("%Y-%m-%d %H%M")
        return str((LOG_DIR / f"{ts} whisp_log.txt").resolve())

    def log_entry(self, text: str):
        if not self.enabled:
            return

        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        entry = f"{timestamp} {text.strip()}"
        self.entries.append(entry)
        verbo(f"[logger] Logged entry: {entry[:60]}...")

    def save(self, path: str = None):
        if not self.enabled or not self.entries:
            return

        out_path = Path(path or self.log_file)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a", encoding="utf-8") as f:
                f.write("\n".join(self.entries) + "\n")
            verbo(f"[logger] Saved log to {out_path}")
        except Exception as e:
            print(f"[logger] Failed to write log: {e}")

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
