import yaml
import os
from pathlib import Path
import yaml, shutil, os
from pathlib import Path
from platformdirs import user_config_dir
from importlib.resources import files
from datetime import datetime

DEFAULT_CONFIG = {
    "aipp_enabled": False,
    "aipp_model": "llama2",
    "aipp_prompt_alt": "",
    "aipp_prompt_default": "Summarize the following text",
    "aipp_provider": "local",
    "app_mode": "whisp",
    "clipboard_backend": "auto",
    "collect_metrics": False,
    "hotkey_record": "ctrl+alt+r",
    "log_enabled": True,
    "log_file": "",
    "performance_log_file": "performance_data.csv",
    "simulate_typing": True,
    "typing_delay": 10,
    "verbosity": True,
    "whisper_binary": "whisper.cpp/build/bin/whisper-cli",
    "model_path": "whisper.cpp/models/ggml-base.en.bin"
}

CONFIG_DIR = Path(user_config_dir("whisp"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.yaml"
_TPL = files("whisp.defaults").joinpath("config.yaml")
# first run?  copy pristine template
if not CONFIG_PATH.exists():
    shutil.copy(_TPL, CONFIG_PATH)

def default_log_filename():
    ts = datetime.now().strftime("%Y-%m-%d %H%M")
    return f"{ts} whisp_log.txt"


class AppConfig:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                user_config = yaml.safe_load(f) or {}
                self.data.update(user_config)

        # Assign config values to attributes
        for k, v in self.data.items():
            setattr(self, k, v)

        if not self.log_file:
            self.log_file = default_log_filename()

    def save(self):
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(self.data, f, default_flow_style=False)
        print("[config] Configuration saved.")

    def set(self, key, value):
        if key not in DEFAULT_CONFIG:
            print(f"[config] Unknown key: {key}")
            return
        self.data[key] = value
        setattr(self, key, value)
        print(f"[config] Updated: {key} = {value}")

    def validate(self):
        print("[config] Validating config...")

        def check_file(path, label):
            if not os.path.exists(path):
                print(f"  ❌ {label} not found: {path}")
            else:
                print(f"  ✅ {label} found: {path}")

        check_file(self.model_path, "Model file")
        check_file(self.whisper_binary, "Whisper binary")

        if self.aipp_provider not in ("local", "remote"):
            print(f"  ⚠️ Invalid AIPP provider: {self.aipp_provider}")

        if not isinstance(self.typing_delay, (int, float)) or not (0.001 <= self.typing_delay <= 1):
            print(f"  ⚠️ Typing delay out of range: {self.typing_delay}")

        print("[config] Validation complete.")

    def print_summary(self):
        print("\n[config] Current Settings:")
        for k, v in self.data.items():
            print(f"  {k}: {v}")

    def list_models(self):
        model_dir = Path("whisper.cpp/models")
        print("\nAvailable models:")
        if not model_dir.exists():
            print("  No model directory found.")
            return []

        models = sorted(model_dir.glob("*.bin"))
        for m in models:
            print(f"  {m.name}")
        return models

    def select_model(self, model_name):
        model_path = Path("whisper.cpp/models") / model_name
        if not model_path.exists():
            print(f"[config] Model not found: {model_path}")
            return
        self.set("model_path", str(model_path))
        self.save()
        print(f"[config] Model switched to {model_name}")
