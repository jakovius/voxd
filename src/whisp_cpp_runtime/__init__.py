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
    if not exe.is_file():
        raise ImportError("embedded whisper-cli missing")

    return Path(exe)
