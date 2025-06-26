"""
whisp.paths - all filesystem look-ups live here.

✓  Works whether the optional wheel `whisp_cpp_runtime` is present or not.
✓  Provides modern constants (`WHISPER_CLI`, `OUTPUT_DIR`, …).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Final
from functools import lru_cache
from whisp.utils.libw import diagn

# ──────────────────────────────────────────────────────────────────────────────
# XDG-compatible base dirs
HOME: Final = Path.home()
CONFIG_DIR: Final = Path(os.getenv("XDG_CONFIG_HOME", HOME / ".config")) / "whisp"
CACHE_DIR:  Final = Path(os.getenv("XDG_CACHE_HOME",  HOME / ".cache"))  / "whisp"
DATA_DIR:   Final = Path(os.getenv("XDG_DATA_HOME",   HOME / ".local" / "share")) / "whisp"

CONFIG_FILE:  Final = CONFIG_DIR / "config.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# Whisper-cli resolver (delegated)
def _locate_whisper_cli() -> Path:
    """Return absolute Path to *whisper-cli*, using whisp_cpp_runtime's logic."""
    try:
        from whisp_cpp_runtime import binary_path
        p = Path(binary_path()).resolve()
        return p
    except Exception as e:
        # Fallback to old repo path for clarity before we raise
        repo_candidate = (Path(__file__).parents[2] /
                          "whisper.cpp" / "build" / "bin" / "whisper-cli")
        raise FileNotFoundError(
            "Could not locate *whisper-cli* automatically "
            "(whisp_cpp_runtime failed). Tried legacy repo path as well:\n"
            f"  {repo_candidate}\n"
            "Consider running setup.sh or exporting WHISP_WC_BIN."
        ) from e

# --------------------------------------------------------------------------
# Lazy binary resolver – avoids crashing during import if the binary is
# not built yet.  First successful call is cached for the rest of the run.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def whisper_cli() -> Path:
    """Return an absolute Path to *whisper-cli* (raises if not found)."""
    return _locate_whisper_cli()

# ──────────────────────────────────────────────────────────────────────────────
# Output directory for transcripts, logs, temp files, …
OUTPUT_DIR: Final = DATA_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Convenience helper for packaged resources
def resource_path(*sub: str | os.PathLike[str]) -> Path:
    """
    Return an absolute Path to a data file shipped within the package.

    Example:
        icon = resource_path("icons", "app.svg")
    """
    return Path(__file__).with_suffix("").with_name("data").joinpath(*sub)

# ──────────────────────────────────────────────────────────────────────────────
# Base model discovery
def _locate_base_model() -> Path:
    """
    Return absolute Path to the default base model (ggml-base.en.bin).

    Search order:
      1. $WHISP_MODEL_PATH env-var
      2. XDG data dir  ~/.local/share/whisp/models/…
      3. Legacy cache dir (pre-0.6)
      4. Repo-local (editable/dev install)
    """
    # 1. Environment override -----------------------------------------------
    env = os.getenv("WHISP_MODEL_PATH")
    if env:
        env_path = Path(env).expanduser().resolve()
        if env_path.is_file():
            return env_path

    # 2. XDG data dir – new canonical location --------------------------------
    data_candidate = DATA_DIR / "models" / "ggml-base.en.bin"
    if data_candidate.exists():
        return data_candidate.resolve()

    # 3. Legacy cache dir (pre-0.6) -----------------------------------------
    cache_candidate = CACHE_DIR / "models" / "ggml-base.en.bin"
    if cache_candidate.exists():
        return cache_candidate.resolve()

    # 4. Repo-local (editable/dev install) -----------------------------------
    repo_candidate = (Path(__file__).parents[2] /
                      "whisper.cpp" / "models" / "ggml-base.en.bin")
    if repo_candidate.exists():
        return repo_candidate.resolve()

    # Nothing worked ---------------------------------------------------------
    raise FileNotFoundError(
        "Could not locate the default Whisper model (ggml-base.en.bin).\n"
        "Checked:\n"
        "  • $WHISP_MODEL_PATH\n"
        f"  • {data_candidate}\n"
        f"  • {cache_candidate}\n"
        f"  • {repo_candidate}\n"
        "Run setup.sh or download the model manually."
    )

@lru_cache(maxsize=1)
def base_model() -> Path:
    """Return an absolute Path to the default base model (raises if not found)."""
    return _locate_base_model()

# legacy helper – kept for old imports
def find_base_model() -> str:          # noqa: N802
    """Return the absolute path to the default base model as a string (legacy API)."""
    return str(base_model())

# NEW legacy shim – used by Transcriber & tests
def find_whisper_cli() -> str:         # noqa: N802
    """Return the absolute path to whisper-cli as a string (legacy API)."""
    return str(whisper_cli())

def resolve_whisper_binary(path_hint: str) -> Path:
    """
    Given a path hint (absolute or relative), return an absolute Path to whisper-cli.
    If the hint is absolute and exists, use it. Otherwise, try to locate it in the repo.
    """
    p = Path(path_hint)
    if p.is_absolute() and p.exists():
        return p
    try:
        return _locate_whisper_cli()
    except FileNotFoundError:
        return p.resolve()  # fallback: resolve whatever was given (may not exist)

def resolve_model_path(path_hint: str) -> Path:
    """
    Given a path hint (absolute or relative), return an absolute Path to the model.
    If the hint is absolute and exists, use it. Otherwise, try to locate it in the repo.
    """
    p = Path(path_hint)
    if p.is_absolute() and p.exists():
        return p
    try:
        return _locate_base_model()
    except FileNotFoundError:
        return p.resolve()  # fallback: resolve whatever was given (may not exist)
