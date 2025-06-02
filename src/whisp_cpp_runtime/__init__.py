"""
whisp_cpp_runtime.__init__
--------------------------

Returns a Path to a working `whisper-cli` binary in the following order
(earliest match wins):

  1. $WHISP_WC_BIN env-var                   – power-user override
  2. Project-local repo build:
        <repo root>/whisper.cpp/build/bin/whisper-cli
  3. Embedded wheel asset inside whisp_cpp_runtime/bin/<plat_arch>/
  4. User-cache auto-build:
        ~/.cache/whisp/whisper.cpp/build/bin/whisper-cli
     (the code clones & builds whisper.cpp once)

Raises ImportError if nothing works.
"""

from __future__ import annotations

import os
import subprocess
from importlib.resources import files
from pathlib import Path
from platform import machine, system

from platformdirs import user_cache_dir


# --------------------------------------------------------------------------- #
# 0. Helpers
# --------------------------------------------------------------------------- #
def _embedded_binary() -> Path | None:
    """Return embedded binary if wheel shipped one; else None."""
    plat = system().lower()          # linux | darwin | windows
    arch = machine().lower()         # x86_64 | aarch64 | arm64 …

    mapping = {
        ("linux",  {"x86_64", "amd64"}): "linux_x86_64",
        ("linux",  {"aarch64", "arm64"}): "linux_aarch64",
        ("darwin", {"arm64"}): "macos_arm64",
    }
    for (p, arches), subdir in mapping.items():
        if plat == p and arch in arches:
            exe = files(__package__).joinpath(f"bin/{subdir}/whisper-cli")
            return Path(exe) if exe.is_file() else None
    return None


def _repo_local_binary() -> Path | None:
    """
    If we’re running from a git-clone / editable install there may already
    be a built binary under `whisper.cpp/build/bin`.

    During unit-tests the test harness sets WHISP_REPO_ROOT to a temporary
    directory so we look for that first.
    """
    repo_root = Path(os.getenv("WHISP_REPO_ROOT", ""))  # test override
    if not repo_root:
        here = Path(__file__).resolve()
        # <repo>/src/whisp_cpp_runtime/__init__.py → ascend three times
        repo_root = here.parent.parent.parent
    candidate = repo_root / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    return candidate if candidate.is_file() else None


def _cached_build() -> Path | None:
    """Return build from ~/.cache/whisp if it exists, else None."""
    cache_dir = Path(user_cache_dir("whisp")) / "whisper.cpp"
    bin_path  = cache_dir / "build" / "bin" / "whisper-cli"
    return bin_path if bin_path.is_file() else None


def _auto_build() -> Path:
    """Clone + build whisper.cpp in ~/.cache/whisp, then return the binary path."""
    cache_dir = Path(user_cache_dir("whisp")) / "whisper.cpp"
    bin_path  = cache_dir / "build" / "bin" / "whisper-cli"

    print("[whisp] No whisper-cli yet – cloning & building whisper.cpp …")

    if not cache_dir.exists():
        subprocess.check_call(
            ["git", "clone", "--depth=1",
             "https://github.com/ggml-org/whisper.cpp", str(cache_dir)]
        )

    subprocess.check_call(["cmake", "-S", ".", "-B", "build"], cwd=cache_dir)
    subprocess.check_call(["cmake", "--build", "build", "-j"], cwd=cache_dir)

    if not bin_path.is_file():
        raise ImportError("whisper.cpp auto-build failed")
    return bin_path


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def binary_path() -> Path:
    """
    Resolve a working whisper.cpp binary for the current platform.
    Order: env-var → repo-local → embedded in wheel → cached build/auto-build.
    """
    # 1. Env override
    env = os.getenv("WHISP_WC_BIN")
    if env and Path(env).is_file():
        return Path(env)

    # 2. Inside the git repo (editable install)
    local = _repo_local_binary()
    if local:
        return local

    # 3. Shipped with the wheel
    wheel = _embedded_binary()
    if wheel:
        return wheel

    # 4. Previously built in cache, or build it now
    cached = _cached_build()
    if cached:
        return cached

    # 4b. Build from source (one-time)
    return _auto_build()
