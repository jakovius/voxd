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
