"""
whisp.paths – all filesystem look-ups live here.

✓  Works whether the optional wheel `whisp_cpp_runtime` is present or not.
✓  Provides modern constants (`WHISPER_CLI`, `OUTPUT_DIR`, …) **and**
   the legacy helper `find_whisper_cli()` required by older code.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Final

# ──────────────────────────────────────────────────────────────────────────────
# XDG-compatible base dirs
HOME: Final = Path.home()
CONFIG_DIR: Final = Path(os.getenv("XDG_CONFIG_HOME", HOME / ".config")) / "whisp"
CACHE_DIR:  Final = Path(os.getenv("XDG_CACHE_HOME",  HOME / ".cache"))  / "whisp"
DATA_DIR:   Final = Path(os.getenv("XDG_DATA_HOME",   HOME / ".local" / "share")) / "whisp"

CONFIG_FILE:  Final = CONFIG_DIR / "config.yaml"
HISTORY_FILE: Final = DATA_DIR  / "history.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# Whisper-cpp binary discovery
def _locate_whisper_cli() -> Path:
    """Return an absolute Path to *whisper-cli* (raises FileNotFoundError if absent)."""
    # 1) bundled runtime wheel
    try:
        from whisp_cpp_runtime import binary_path as _p  # type: ignore
        return Path(_p())
    except ModuleNotFoundError:
        pass

    # 2) executable somewhere on $PATH
    if (exe := shutil.which("whisper-cli")):
        return Path(exe).resolve()

    # 3) repo-local build (editable/dev install)
    repo_candidate = (Path(__file__).parents[1] /
                      "whisper.cpp" / "build" / "bin" / "whisper-cli")
    if repo_candidate.exists():
        return repo_candidate.resolve()

    raise FileNotFoundError(
        "Could not locate *whisper-cli*.\n"
        "Either install the `whisp_cpp_runtime` wheel, build whisper.cpp "
        "inside the repo, or place a compiled whisper-cli somewhere on $PATH."
    )

WHISPER_CLI: Final = _locate_whisper_cli()

# legacy helper – kept for old imports
def find_whisper_cli() -> str:          # noqa: N802  (keep original name)
    """Return the absolute path to *whisper-cli* as a string (legacy API)."""
    return str(WHISPER_CLI)

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
