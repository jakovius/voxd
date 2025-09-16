from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Literal

import importlib.resources as pkg

# Build-time dependencies required for compiling whisper.cpp
REQUIRED_TOOLS: tuple[str, ...] = (
    "git",
    "gcc",
    "g++",
    "make",
    "cmake",
    "curl",
)

# ────────────────────────────── UI helpers ────────────────────────────────

def _ask_cli(prompt: str) -> bool:
    """CLI yes/no question returning *True* when the answer is Yes."""
    try:
        return input(f"{prompt} [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:
        return False


def _ask_gui(prompt: str) -> bool:
    """Qt dialog yes/no question. Returns *True* for Yes."""
    from PyQt6.QtWidgets import QMessageBox  # type: ignore

    btn = QMessageBox.question(
        None,
        "VOXD setup",
        prompt,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return btn == QMessageBox.StandardButton.Yes


def _info_cli(msg: str) -> None:  # noqa: D401
    print(msg)


def _info_gui(msg: str) -> None:  # noqa: D401
    from PyQt6.QtWidgets import QMessageBox  # type: ignore

    QMessageBox.information(None, "VOXD", msg)


# ───────────────────── prerequisite checks & helpers ──────────────────────

def _missing_tools() -> list[str]:
    """Return a list of required tools not found on *PATH*."""
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def _auto_install(tools: list[str]) -> bool:
    """Attempt non-interactive install of *tools* on apt/dnf/pacman systems."""
    if not tools:
        return True

    sudo_prefix: list[str] = ["sudo"] if os.geteuid() != 0 and shutil.which("sudo") else []

    if shutil.which("apt"):
        # Quiet update first – ignore failures
        subprocess.run(sudo_prefix + ["apt", "update", "-qq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd = sudo_prefix + ["apt", "install", "-y", *tools]
    elif shutil.which("dnf"):
        cmd = sudo_prefix + ["dnf", "install", "-y", *tools]
    elif shutil.which("pacman"):
        cmd = sudo_prefix + ["pacman", "-Sy", "--noconfirm", *tools]
    else:
        return False  # Unsupported distro

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        return False

    return not _missing_tools()


# ───────────────────────── public entry point ─────────────────────────────

def ensure_whisper_cli(ui: Literal["cli", "gui"] = "cli") -> Path | None:
    """Return Path to *whisper-cli*, building it if necessary.

    If the binary still cannot be located or the user declines installation,
    *None* is returned. Callers should treat that as a terminal condition for
    the current action (recording/transcribing) but keep the application
    running.
    """

    from voxd.paths import whisper_cli, _locate_whisper_cli

    ask = _ask_gui if ui == "gui" else _ask_cli
    info = _info_gui if ui == "gui" else _info_cli

    # 0. Fast path – binary already present ---------------------------------
    try:
        return whisper_cli()
    except FileNotFoundError:
        pass  # Need to build

    # 1. Check tool-chain dependencies -------------------------------------
    missing = _missing_tools()
    if missing:
        info(
            "The following build tools are required but missing:\n  "
            + "  ".join(missing)
        )
        if ask("Attempt to install them automatically?"):
            if not _auto_install(missing):
                info("Automatic install failed or partially succeeded.")
        else:
            if ask("Open the README with manual instructions?"):
                webbrowser.open("https://github.com/voxd-app/voxd#dependencies")
            return None

        # Re-check after attempted install
        missing = _missing_tools()
        if missing:
            info("Still missing: " + ", ".join(missing) + "\nCannot continue.")
            return None

    # 2. Ask permission to compile whisper.cpp -----------------------------
    if not ask("whisper-cli not found. Build it now (this can take a few minutes)?"):
        return None

    # 3. Locate packaged *setup.sh* inside the wheel/editable checkout ------
    try:
        with pkg.path("voxd", "setup.sh") as p:
            script_path = p
    except FileNotFoundError:
        # Editable install fallback – parent directories up to repo root
        script_path = Path(__file__).parents[3] / "setup.sh"

    if not script_path.exists():
        info("setup.sh not found – cannot build whisper-cli automatically.")
        return None

    # 4. Run setup.sh (inherits user's stdin/stdout – progress visible) -----
    try:
        subprocess.run(["bash", str(script_path)], check=True)
    except subprocess.CalledProcessError:
        info("setup.sh failed – whisper-cli could not be built.")
        return None

    # 5. Discover the freshly built binary ----------------------------------
    try:
        return _locate_whisper_cli()
    except FileNotFoundError:
        info("Build finished but whisper-cli still not found on PATH.")
        return None 