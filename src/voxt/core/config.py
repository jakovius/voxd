import yaml
import shutil
import os
from pathlib import Path
import re
from platformdirs import user_config_dir
from importlib.resources import files
from voxt.paths import resolve_whisper_binary, resolve_model_path, DATA_DIR, resolve_llamacpp_server, LLAMACPP_MODELS_DIR  # <-- add this import

DEFAULT_CONFIG = {
    "perf_collect": False,
    "perf_accuracy_rating_collect": True,
    "log_enabled": True,
    "log_location": "",
    "simulate_typing": True,
    "typing_delay": 1,
    "typing_start_delay": 0.15,
    "ctrl_v_paste": False,  # Use Ctrl+V instead of default Ctrl+Shift+V
    "append_trailing_space": True,
    "verbosity": True,
    "save_recordings": False,
    # Recording behavior
    "record_chunked": True,
    "record_chunk_seconds": 300,
    # Audio preprocessing
    "audio_preproc_enabled": True,
    "audio_peak_dbfs": -3.0,
    "audio_clip_warn_threshold": 0.01,
    "whisper_binary": "whisper.cpp/build/bin/whisper-cli",
    "model_path": "whisper.cpp/models/ggml-base.en.bin",

    # --- Flux (VAD-driven continuous dictation) ------------------------------
    # Defaults are conservative and CPU-light; Energy VAD is built-in
    # and requires no extra dependencies.
    "flux_min_silence_ms": 500,   # pause to finalize an utterance
    "flux_min_speech_ms": 200,    # minimum speech before opening a segment
    "flux_pre_roll_ms": 150,      # prepend audio before detection to avoid clipping leading phonemes
    "flux_vad_backend": "energy", # energy | silero (silero requires onnxruntime and a small .onnx model)
    "silero_onnx_model": "",     # path to silero VAD .onnx (optional)
    # Energy VAD dynamic thresholds (margins above noise floor)
    "flux_energy_start_margin_db": 6.0,
    "flux_energy_keep_margin_db": 3.0,
    # Silero hysteresis thresholds (probability)
    "flux_start_threshold": 0.6,
    "flux_end_threshold": 0.4,
    # Energy absolute thresholds (optional, normalized 0..1)
    "flux_energy_use_absolute": False,
    "flux_energy_start_p": 0.55,
    "flux_energy_keep_p": 0.50,
    # Segment smoothing
    "flux_post_roll_ms": 150,     # keep this much trailing silence
    "flux_min_segment_ms": 600,   # drop segments shorter than this
    "flux_cooldown_ms": 250,      # wait this long after closing before reopening
    "flux_min_rms_dbfs": -45.0,   # skip segment if overall RMS below this

    # --- ✨ AIPP (AI post-processing) ------------------------------------------
    "aipp_enabled": False,
    "aipp_provider": "ollama",           # ollama / openai / anthropic / xai / llamacpp_server / llamacpp_direct
    "aipp_active_prompt": "default",

    # New: List of models per provider
    "aipp_models": {
        "ollama": ["llama3.2:latest", "mistral:latest", "gemma3:latest", "qwen2.5-coder:1.5b"],
        "openai": ["gpt-4o-mini-2024-07-18"],
        "anthropic": ["claude-3-opus-20240229", "claude-3-haiku"],
        "xai": ["grok-3-latest"],
        "llamacpp_server": ["gemma-3-270m"],
        "llamacpp_direct": ["gemma-3-270m"]
    },

    # New: Selected model per provider
    "aipp_selected_models": {
        "ollama": "gemma3:latest",
        "openai": "gpt-4o-mini-2024-07-18",
        "anthropic": "claude-3-opus-20240229",
        "xai": "grok-3-latest",
        "llamacpp_server": "gemma-3-270m",
        "llamacpp_direct": "gemma-3-270m"
    },

    # llama.cpp settings
    "llamacpp_server_path": "llama.cpp/build/bin/llama-server",
    "llamacpp_cli_path": "llama.cpp/build/bin/llama-cli", 
    "llamacpp_default_model": "llamacpp_models/qwen2.5-3b-instruct-q4_k_m.gguf",
    "llamacpp_server_url": "http://localhost:8080",
    "llamacpp_server_timeout": 30,
    


    "aipp_prompts": {
        "default": "Rewrite the following text to appear as if Yoda from Star Wars is saying it",
        "prompt1": "",
        "prompt2": "",
        "prompt3": "",
    }
}

CONFIG_DIR = Path(user_config_dir("voxt"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = CONFIG_DIR / "config.yaml"
_TPL = files("voxt.defaults").joinpath("default_config.yaml")
# first run?  copy pristine template
if not CONFIG_PATH.exists():
    shutil.copy(_TPL, CONFIG_PATH)


class AppConfig:
    def __init__(self):
        self.data = DEFAULT_CONFIG.copy()
        self.load()
        self._validate_aipp_config()
        self.update_available_llamacpp_models()

    def load(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r") as f:
                user_config = yaml.safe_load(f) or {}
                self.data.update(user_config)

        # Always resolve absolute paths for whisper_binary and model_path
        abs_whisper = str(resolve_whisper_binary(self.data.get("whisper_binary", "")))
        abs_model = str(resolve_model_path(self.data.get("model_path", "")))
        updated = False
        if self.data.get("whisper_binary") != abs_whisper:
            self.data["whisper_binary"] = abs_whisper
            updated = True
        if self.data.get("model_path") != abs_model:
            self.data["model_path"] = abs_model
            updated = True

        # Also resolve llama.cpp paths if they exist
        try:
            abs_llama_server = str(resolve_llamacpp_server(self.data.get("llamacpp_server_path", "")))
            if self.data.get("llamacpp_server_path") != abs_llama_server:
                self.data["llamacpp_server_path"] = abs_llama_server
                updated = True
        except FileNotFoundError:
            pass  # llama.cpp not installed yet

        # Sanitize types: fix malformed llamacpp_server_timeout (e.g., "30n")
        try:
            tval = self.data.get("llamacpp_server_timeout", 30)
            if isinstance(tval, str):
                m = re.match(r"^\s*(\d+(?:\.\d+)?)", tval)
                if m:
                    num = m.group(1)
                    self.data["llamacpp_server_timeout"] = float(num) if "." in num else int(num)
                else:
                    self.data["llamacpp_server_timeout"] = 30
                updated = True
            elif not isinstance(tval, (int, float)):
                self.data["llamacpp_server_timeout"] = 30
                updated = True
        except Exception:
            self.data["llamacpp_server_timeout"] = 30
            updated = True

        # Assign config values to attributes
        for k, v in self.data.items():
            setattr(self, k, v)

        self.log_location = self.data.get("log_location", "")

        # Save config if any path was updated
        if updated:
            self.save()

    def save(self):
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(self.data, f, default_flow_style=False)
        print("\n[config] Configuration saved.")

    def set(self, key, value):
        if key not in DEFAULT_CONFIG:
            print(f"\n[config] Unknown key: {key}")
            return
        self.data[key] = value
        setattr(self, key, value)
        print(f"\n[config] Updated: {key} = {value}")

    def validate(self):
        print("\n[config] Validating config...")

        def check_file(path, label):
            if not os.path.exists(path):
                print(f"  ❌ {label} not found: {path}")
            else:
                print(f"  ✅ {label} found: {path}")

        check_file(self.model_path, "Model file")
        check_file(self.whisper_binary, "Whisper binary")

        if self.aipp_provider not in ("ollama", "openai", "anthropic", "xai"):
            print(f"  ⚠️ Invalid AIPP provider: {self.aipp_provider}")

        # typing_delay: allow 0 (→ instant paste) up to 1 s per char
        if not isinstance(self.typing_delay, (int, float)) or not (0 <= self.typing_delay <= 1):
            print(f"  ⚠️ Typing delay out of range: {self.typing_delay} (allowed 0–1)")

        if not isinstance(self.typing_start_delay, (int, float)) or not (0.0 <= self.typing_start_delay <= 5):
            # Using .data avoids mypy complaints about dynamic attrs
            val = self.data.get("typing_start_delay", 0.15)
            if not isinstance(val, (int, float)) or not (0.0 <= val <= 5):
                print(f"  ⚠️ typing_start_delay out of range: {val}")

        if self.aipp_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            print("  ⚠️ OPENAI_API_KEY not set in environment.")
        if self.aipp_provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            print("  ⚠️ ANTHROPIC_API_KEY not set in environment.")
        if self.aipp_provider == "xai" and not os.getenv("XAI_API_KEY"):
            print("  ⚠️ XAI_API_KEY not set in environment.")

        # Validate llama.cpp setup
        if self.aipp_provider in ("llamacpp_server", "llamacpp_direct"):
            status = self.validate_llamacpp_setup()
            if self.aipp_provider == "llamacpp_server" and not status["server_available"]:
                print("  ⚠️ llama-server not found but llamacpp_server provider selected")
            if self.aipp_provider == "llamacpp_direct" and not status["python_bindings_available"]:
                print("  ⚠️ llama-cpp-python not installed but llamacpp_direct provider selected")
            if not status["default_model_available"]:
                print("  ⚠️ Default llama.cpp model not found")

        print("\n[config] Validation complete.")

    def print_summary(self):
        print("\n[config] Current Settings:")
        for k, v in self.data.items():
            print(f"  {k}: {v}")

    def list_models(self):
        """Return all model files in the canonical data dir."""
        model_dir = DATA_DIR / "models"
        print("\nAvailable models:")
        if not model_dir.exists():
            print("  No model directory found.")
            return []

        models = sorted(model_dir.glob("*.bin"))
        for m in models:
            print(f"  {m.name}")
        return models

    def select_model(self, model_name):
        """Set the active model to *model_name* found in DATA_DIR/models."""
        model_path = DATA_DIR / "models" / model_name
        if not model_path.exists():
            print(f"\n[config] Model not found: {model_path}")
            return
        abs_model_path = str(model_path.resolve())
        self.set("model_path", abs_model_path)
        self.save()
        print(f"\n[config] Model switched to {model_name}")
    
    # ---- AIPP helpers --------------------------------------------------
    def current_prompt(self) -> str:
        return self.data["aipp_prompts"].get(self.data["aipp_active_prompt"], "")

    def set_prompt(self, key: str, value: str):
        if key not in self.data["aipp_prompts"]:
            print(f"\n[config] Unknown prompt slot: {key}")
            return
        self.data["aipp_prompts"][key] = value
        self.save()

    def get_aipp_models(self, provider=None):
        """Return list of models for the given provider (or current provider)."""
        if provider is None:
            provider = self.data.get("aipp_provider", "ollama")
        return self.data.get("aipp_models", {}).get(provider, [])

    def get_aipp_selected_model(self, provider=None):
        """Return the selected model for the given provider (or current provider)."""
        if provider is None:
            provider = self.data.get("aipp_provider", "ollama")
        return self.data.get("aipp_selected_models", {}).get(provider, "")

    def set_aipp_selected_model(self, model_name, provider=None):
        """Set the selected model for the given provider (or current provider)."""
        if provider is None:
            provider = self.data.get("aipp_provider", "ollama")
        if model_name not in self.get_aipp_models(provider):
            print(f"\n[config] Model '{model_name}' not in aipp_models for provider '{provider}'")
            return
        self.data["aipp_selected_models"][provider] = model_name
        self.save()
        print(f"\n[config] AIPP model for {provider} set to {model_name}")

    def _validate_aipp_config(self):
        """Ensure aipp_prompts and aipp_models/selected_models are valid."""
        prompts = self.data.get("aipp_prompts", {})
        for slot in ["default", "prompt1", "prompt2", "prompt3"]:
            if slot not in prompts:
                prompts[slot] = ""
        for k in list(prompts.keys()):
            if k not in ["default", "prompt1", "prompt2", "prompt3"]:
                del prompts[k]
        self.data["aipp_prompts"] = prompts

        active = self.data.get("aipp_active_prompt", "default")
        if active not in prompts:
            print(f"\n[config] Invalid aipp_active_prompt '{active}', resetting to 'default'")
            self.data["aipp_active_prompt"] = "default"

        valid_providers = ["ollama", "openai", "anthropic", "xai", "llamacpp_server", "llamacpp_direct"]
        provider = self.data.get("aipp_provider", "ollama")
        if provider not in valid_providers:
            print(f"\n[config] Invalid aipp_provider '{provider}', resetting to 'ollama'")
            self.data["aipp_provider"] = "ollama"

        # Ensure aipp_models and aipp_selected_models have all providers
        for prov in valid_providers:
            if prov not in self.data.get("aipp_models", {}):
                self.data["aipp_models"][prov] = []
            if prov not in self.data.get("aipp_selected_models", {}):
                self.data["aipp_selected_models"][prov] = (
                    self.data["aipp_models"][prov][0] if self.data["aipp_models"][prov] else ""
                )

    @property
    def aipp_model(self):
        """Shortcut for current provider's selected model."""
        prov = self.data.get("aipp_provider", "ollama")
        return self.data.get("aipp_selected_models", {}).get(prov, "")

    @aipp_model.setter
    def aipp_model(self, value):
        prov = self.data.get("aipp_provider", "ollama")
        self.set_aipp_selected_model(value, prov)

    # ---- llama.cpp helpers --------------------------------------------------
    def get_llamacpp_model_path(self, model_name: str) -> str:
        """Get the full path to a llama.cpp model."""
        from voxt.paths import find_llamacpp_model_by_name
        
        model_path = find_llamacpp_model_by_name(model_name)
        if model_path:
            return str(model_path)
        
        # Fallback: assume it's in the models directory
        filename = model_name if model_name.endswith('.gguf') else f"{model_name}.gguf"
        return str(LLAMACPP_MODELS_DIR / filename)

    def update_available_llamacpp_models(self):
        """Update the aipp_models lists with available llama.cpp models."""
        from voxt.paths import get_available_llamacpp_model_names
        
        available_models = get_available_llamacpp_model_names()
        if not available_models:
            # If no models found, keep the default as fallback
            available_models = ["qwen2.5-3b-instruct-q4_k_m"]
        
        # Update both llamacpp providers
        if "aipp_models" not in self.data:
            self.data["aipp_models"] = {}
        
        self.data["aipp_models"]["llamacpp_server"] = available_models
        self.data["aipp_models"]["llamacpp_direct"] = available_models
        
        # Ensure selected models are valid
        if "aipp_selected_models" not in self.data:
            self.data["aipp_selected_models"] = {}
            
        for provider in ["llamacpp_server", "llamacpp_direct"]:
            current_selected = self.data["aipp_selected_models"].get(provider, "")
            if current_selected not in available_models:
                # Set to the first available model, or default
                if available_models:
                    self.data["aipp_selected_models"][provider] = available_models[0]
                else:
                    self.data["aipp_selected_models"][provider] = "qwen2.5-3b-instruct-q4_k_m"
        
        self.save()

    def validate_llamacpp_setup(self) -> dict[str, bool]:
        """Check llama.cpp installation status."""
        status = {
            "server_available": False,
            "cli_available": False, 
            "default_model_available": False,
            "python_bindings_available": False
        }
        
        try:
            from voxt.paths import llama_server
            llama_server()
            status["server_available"] = True
        except (FileNotFoundError, ImportError):
            pass
        
        try:
            from voxt.paths import llama_cli
            llama_cli()
            status["cli_available"] = True
        except (FileNotFoundError, ImportError):
            pass
        
        try:
            from voxt.paths import default_llamacpp_model
            default_llamacpp_model()
            status["default_model_available"] = True
        except (FileNotFoundError, ImportError):
            pass
        
        try:
            import llama_cpp
            status["python_bindings_available"] = True
        except ImportError:
            pass
        
        return status

# Global singleton holder (defined after AppConfig)
_APP_CONFIG = None

def get_config():
    """Return the shared AppConfig instance (create on first call)."""
    global _APP_CONFIG
    if _APP_CONFIG is None:
        _APP_CONFIG = AppConfig()
    return _APP_CONFIG