"""
Runtime helper that returns the path of the embedded whisper.cpp binary
(or raises ImportError if this wheel was built without one).
"""

from importlib.resources import files
from platform import machine, system
from pathlib import Path

def binary_path() -> Path:
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