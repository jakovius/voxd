"""
Runtime helper that returns the path of the embedded whisper.cpp binary
(or raises ImportError if this wheel was built without one).
"""

from importlib.resources import files
from platform import machine, system
from pathlib import Path
import os

def binary_path() -> Path:
    # 0. Explicit override for tests / advanced users
    if "WHISP_REPO_ROOT" in os.environ:
        root = Path(os.environ["WHISP_REPO_ROOT"]).expanduser()
        cand = root / "whisper.cpp" / "build" / "bin" / "whisper-cli"
        if cand.is_file():
            return cand

    plat = system().lower()       # "linux", "darwin", "windows"
    arch = machine().lower()      # "x86_64", "aarch64", "arm64", …

    # normalise to the folder names you’ll create
    if plat == "linux" and arch in {"x86_64", "amd64"}:
        subdir = "linux_x86_64"
    elif plat == "linux" and arch in {"aarch64", "arm64"}:
        subdir = "linux_aarch64"
    elif plat == "darwin" and arch == "arm64":
        subdir = "macos_arm64"
    else:
       raise ImportError("no embedded whisper-cli for this platform")
    exe = files(__package__).joinpath(f"bin/{subdir}/whisper-cli")
    if exe.is_file():
        return Path(exe)

    # ---- 1. project-local build (repo_root/whisper.cpp/…) ------------
    repo_root = Path(__file__).resolve().parents[3]
    local_bin = repo_root / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    if local_bin.is_file():
        return local_bin

    # ---- Fallback : build whisper.cpp in user cache -----------------
    from subprocess import check_call, CalledProcessError
    from platformdirs import user_cache_dir
    cache_dir = Path(user_cache_dir("whisp")) / "whisper.cpp"

    built_bin = cache_dir / "build/bin/whisper-cli"
    if built_bin.is_file():
        return built_bin

    print("[whisp] No bundled whisper-cli for this CPU – building whisper.cpp once…")
    try:
        import git, shutil                            # gitpython, stdlib
    except ImportError:
        raise ImportError("whisper-cli missing and gitpython not installed")

    repo = cache_dir
    if not repo.exists():
        check_call(["git", "clone", "--depth=1",
                    "https://github.com/ggml-org/whisper.cpp", str(repo)])
    # minimal build
    check_call(["cmake", "-B", "build"], cwd=repo)
    check_call(["cmake", "--build", "build", "-j"], cwd=repo)

    if built_bin.is_file():
        return built_bin
    raise ImportError("auto-build of whisper.cpp failed")