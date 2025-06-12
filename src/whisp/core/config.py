import yaml
import shutil
import os
from pathlib import Path
from platformdirs import user_config_dir
from importlib.resources import files
from datetime import datetime

DEFAULT_CONFIG = {
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
    "model_path": "whisper.cpp/models/ggml-base.en.bin",

    # --- ✨ AIPP (AI post-processing) ------------------------------------------
    "aipp_enabled": False,
    "aipp_provider": "ollama",           # ollama / lmstudio / openai / anthropic / xai
    "aipp_active_prompt": "default",
    "aipp_model": "llama3.2:latest",
    "aipp_prompts": {
        "default": "Summarize the following text",
        "prompt1": "",
        "prompt2": "",
        "prompt3": "",
    }
}

CONFIG_DIR = Path(user_config_dir("whisp"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.yaml"
_TPL = files("whisp.defaults").joinpath("default_config.yaml")
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
        self._validate_aipp_config()  # <-- Add this line

    def load(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                user_config = yaml.safe_load(f) or {}
                self.data.update(user_config)
        # for diagnostics
        print(f"--- diagnostic --- Config dir: {CONFIG_DIR} | Config path: {CONFIG_PATH}")

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

        if self.aipp_provider not in ("ollama", "lmstudio", "openai", "anthropic", "xai"):
            print(f"  ⚠️ Invalid AIPP provider: {self.aipp_provider}")

        if not isinstance(self.typing_delay, (int, float)) or not (0.001 <= self.typing_delay <= 1):
            print(f"  ⚠️ Typing delay out of range: {self.typing_delay}")

        if self.aipp_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            print("  ⚠️ OPENAI_API_KEY not set in environment.")
        if self.aipp_provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            print("  ⚠️ ANTHROPIC_API_KEY not set in environment.")
        if self.aipp_provider == "xai" and not os.getenv("XAI_API_KEY"):
            print("  ⚠️ XAI_API_KEY not set in environment.")

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
    
    # ---- AIPP helpers --------------------------------------------------
    def current_prompt(self) -> str:
        return self.data["aipp_prompts"].get(self.data["aipp_active_prompt"], "")

    def set_prompt(self, key: str, value: str):
        if key not in self.data["aipp_prompts"]:
            print(f"[config] Unknown prompt slot: {key}")
            return
        self.data["aipp_prompts"][key] = value
        self.save()

    def _validate_aipp_config(self):
        """Ensure aipp_prompts has exactly 4 slots and active_prompt is valid."""
        prompts = self.data.get("aipp_prompts", {})
        # Ensure all 4 keys exist
        for slot in ["default", "prompt1", "prompt2", "prompt3"]:
            if slot not in prompts:
                prompts[slot] = ""
        # Remove extra keys if any
        for k in list(prompts.keys()):
            if k not in ["default", "prompt1", "prompt2", "prompt3"]:
                del prompts[k]
        self.data["aipp_prompts"] = prompts

        # Validate active_prompt
        active = self.data.get("aipp_active_prompt", "default")
        if active not in prompts:
            print(f"[config] Invalid aipp_active_prompt '{active}', resetting to 'default'")
            self.data["aipp_active_prompt"] = "default"
        # Refined provider validation
        provider = self.data.get("aipp_provider", "ollama")
        valid_providers = ["ollama", "lmstudio", "openai", "anthropic", "xai"]
        if provider not in valid_providers:
            print(f"[config] Invalid aipp_provider '{provider}', resetting to 'ollama'")
            self.data["aipp_provider"] = "ollama"