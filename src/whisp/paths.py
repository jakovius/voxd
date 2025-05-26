# src/whisp/paths.py
"""
Whisp path helpers – single source of truth.

Usage:
    from whisp.paths import CONFIG_FILE, ASSETS, resource_path
"""
from __future__ import annotations
from pathlib import Path
from importlib.resources import files
from platformdirs import user_config_dir, user_cache_dir
from functools import lru_cache
from whisp_cpp_runtime import binary_path as _bin_path

@lru_cache(maxsize=1)
def bundled_cli_lazy() -> Path | None:
    try:
        return _bin_path()
    except ImportError:
        return None

# ----- user-writable locations (follow XDG spec) ----------------------------
CONFIG_DIR = Path(user_config_dir("whisp"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.yaml"

CACHE_DIR = Path(user_cache_dir("whisp"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_DIR = CACHE_DIR / "whisp_output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ----- read-only package data ------------------------------------------------
ASSETS = files("whisp.assets")          # a Traversable object

def resource_path(name: str) -> Path:
    """Return a Path to a file shipped inside whisp.assets/ …"""
    return ASSETS.joinpath(name)

# ----- whisper-cli discovery -------------------------------------------------
from shutil import which

def find_whisper_cli() -> Path | None:
    """
    Resolution order:
      1. Explicit path in config.yaml
      2. System-wide whisper-cli in $PATH
      3. Bundled binary from whisp_cpp_runtime
      4. None (caller will trigger fallback build)
    """
    from whisp.core.config import AppConfig   # local import to avoid cycles
    cfg = AppConfig()

    # 1. config
    if cfg.whisper_binary and Path(cfg.whisper_binary).is_file():
        return Path(cfg.whisper_binary)

    # 2. system PATH
    sys_bin = which("whisper-cli")
    if sys_bin:
        return Path(sys_bin)

    # 3. bundled (or auto-built) binary
    b = bundled_cli_lazy()
    if b:
        return b

