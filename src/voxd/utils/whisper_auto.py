from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
import tarfile
import tempfile
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

    # Helper: attempt to fetch a prebuilt whisper-cli into XDG data dir
    def _fetch_prebuilt() -> Path | None:
        try:
            import requests  # type: ignore
        except Exception:
            return None

        # Resolve arch/variant
        def _detect_cpu_variant() -> tuple[str, str]:
            m = (os.uname().machine or "").lower()
            if m in ("x86_64", "amd64"):
                # Prefer lscpu when available
                try:
                    out = subprocess.check_output(["lscpu"], text=True)
                except Exception:
                    out = ""
                flags = out
                if not flags:
                    try:
                        flags = Path("/proc/cpuinfo").read_text()
                    except Exception:
                        flags = ""
                if "avx2" in flags:
                    return ("amd64", "avx2")
                if "sse4_2" in flags or "sse4.2" in flags:
                    return ("amd64", "sse42")
                # Fallback: no supported simd → return unknown
                return ("amd64", "none")
            if m in ("aarch64", "arm64"):
                return ("arm64", "neon")
            return (m, "none")

        arch, variant = _detect_cpu_variant()
        if arch == "amd64" and variant not in ("avx2", "sse42"):
            return None
        if arch not in ("amd64", "arm64"):
            return None

        bin_repo = os.environ.get("VOXD_BIN_REPO", "Jacob8472/voxd-prebuilts")
        bin_tag = os.environ.get("VOXD_BIN_TAG", "")

        if arch == "amd64":
            base = f"whisper-cli_linux_{arch}_{variant}"
        else:
            base = f"whisper-cli_linux_{arch}"
        asset = f"{base}.tar.gz"

        if bin_tag:
            api = f"https://api.github.com/repos/{bin_repo}/releases/tags/{bin_tag}"
        else:
            api = f"https://api.github.com/repos/{bin_repo}/releases/latest"

        try:
            r = requests.get(api, timeout=15)
            r.raise_for_status()
            url = None
            for a in r.json().get("assets", []):
                if a.get("name") == asset:
                    url = a.get("browser_download_url")
                    break
            if not url:
                return None
        except Exception:
            return None

        # Download and extract
        data_home = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        out_dir = data_home / "voxd" / "bin"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
        tmpd = Path(tempfile.mkdtemp())
        tar_path = tmpd / asset
        try:
            with requests.get(url, stream=True, timeout=60) as resp:  # type: ignore
                resp.raise_for_status()
                with open(tar_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        if chunk:
                            f.write(chunk)
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(out_dir)
            bin_path = out_dir / "whisper-cli"
            try:
                os.chmod(bin_path, 0o755)
            except Exception:
                pass
            # Make discoverable in this process
            os.environ["VOXD_WC_BIN"] = str(bin_path)
            # Best-effort symlink to ~/.local/bin
            try:
                local_bin = Path.home() / ".local/bin"
                local_bin.mkdir(parents=True, exist_ok=True)
                link = local_bin / "whisper-cli"
                if link.exists() or link.is_symlink():
                    if link.is_symlink() or link.name == "whisper-cli":
                        try:
                            link.unlink()
                        except Exception:
                            pass
                try:
                    link.symlink_to(bin_path)
                except Exception:
                    pass
            except Exception:
                pass
            return bin_path
        except Exception:
            return None
        finally:
            try:
                for p in tmpd.glob("*"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                tmpd.rmdir()
            except Exception:
                pass

    # 0. Fast path – binary already present ---------------------------------
    try:
        return whisper_cli()
    except FileNotFoundError:
        pass  # Need to build

    # 0.5 Try to fetch a prebuilt binary (packaging-friendly) ----------------
    pre = _fetch_prebuilt()
    if pre and pre.exists():
        return pre

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