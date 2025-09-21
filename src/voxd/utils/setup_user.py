from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from voxd.core.config import AppConfig, CONFIG_PATH
from voxd.paths import DATA_DIR


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _download_default_model() -> None:
    model_dir = DATA_DIR / "models"
    _ensure_dir(model_dir)
    model_file = model_dir / "ggml-base.en.bin"
    if model_file.exists():
        return
    url = (
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
    )
    try:
        import requests  # type: ignore

        with requests.get(url, stream=True, timeout=30) as r:  # type: ignore
            r.raise_for_status()
            tmp = model_file.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.replace(model_file)
    except Exception:
        # Best-effort only; user can download later
        pass


def _ensure_input_group_membership() -> None:
    """Ensure the current user is in 'input' group (required for /dev/uinput)."""
    try:
        import grp, getpass
        user = os.environ.get("USER") or getpass.getuser()
        # Check membership
        in_group = False
        try:
            grp_info = grp.getgrnam("input")
            in_group = user in grp_info.gr_mem
        except KeyError:
            # Group may not exist on some systems
            return
        if not in_group:
            # Try to add via sudo; ignore failures (user will be prompted)
            subprocess.run(["sudo", "usermod", "-aG", "input", user], check=False)
            try:
                print("[setup] Added user to 'input' group (you must log out and back in to take effect).")
            except Exception:
                pass
    except Exception:
        pass


def _setup_ydotool_user_service() -> None:
    yd = shutil.which("ydotoold")
    if not yd:
        return

    # Ensure the user has permissions for /dev/uinput
    _ensure_input_group_membership()

    user_systemd = Path.home() / ".config/systemd/user"
    _ensure_dir(user_systemd)
    svc = user_systemd / "ydotoold.service"
    try:
        svc.write_text(
            """
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=%s --socket-path=%%h/.ydotool_socket --socket-own=%%U:%%G
Restart=on-failure
RestartSec=1s

[Install]
WantedBy=default.target
"""
            .strip()
            % yd
        )
    except Exception:
        return

    # Ensure env export in common shells
    socket_line = 'export YDOTOOL_SOCKET="$HOME/.ydotool_socket"\n'
    for rc in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        try:
            if rc.exists():
                txt = rc.read_text()
                if "YDOTOOL_SOCKET" not in txt:
                    with open(rc, "a") as f:
                        f.write("\n" + socket_line)
        except Exception:
            pass

    # Try to enable/start the service (ignore failures quietly)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "ydotoold.service"], check=False)
        # Retry start and fallback to sg similar to setup.sh
        started = False
        for _ in range(3):
            subprocess.run(["systemctl", "--user", "start", "ydotoold.service"], check=False)
            # Give time to settle
            try:
                import time as _t
                _t.sleep(1.0)
            except Exception:
                pass
            r = subprocess.run(["systemctl", "--user", "is-active", "ydotoold.service"], check=False)
            if r.returncode == 0:
                started = True
                break
        if not started and shutil.which("sg"):
            uid, gid = os.getuid(), os.getgid()
            cmd = [
                "sg", "input", "-c",
                f"ydotoold --socket-path='$HOME/.ydotool_socket' --socket-own={uid}:{gid} &",
            ]
            subprocess.run(cmd, check=False)
    except Exception:
        pass


def _install_desktop_launchers() -> None:
    # Copy icon
    try:
        from importlib.resources import files
        icon_src = files("voxd.assets").joinpath("voxd-0.png")
        icon_bytes = icon_src.read_bytes()  # type: ignore[attr-defined]
        icon_dir_256 = Path.home() / ".local/share/icons/hicolor/256x256/apps"
        icon_dir_64 = Path.home() / ".local/share/icons/hicolor/64x64/apps"
        _ensure_dir(icon_dir_256)
        _ensure_dir(icon_dir_64)
        (icon_dir_256 / "voxd.png").write_bytes(icon_bytes)
        (icon_dir_64 / "voxd.png").write_bytes(icon_bytes)
    except Exception:
        pass

    # Desktop entries
    apps_dir = Path.home() / ".local/share/applications"
    _ensure_dir(apps_dir)

    def write_desktop(mode: str, name: str) -> None:
        path = apps_dir / f"voxd-{mode}.desktop"
        try:
            path.write_text(
                (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    f"Name=VOXD ({name})\n"
                    f"Exec=voxd --{mode}\n"
                    "Icon=voxd\n"
                    "Terminal=false\n"
                    "Categories=Utility;AudioVideo;\n"
                )
            )
        except Exception:
            pass

    write_desktop("gui", "gui")
    write_desktop("tray", "tray")
    write_desktop("flux", "flux")

    # Update caches best-effort
    try:
        subprocess.run(["update-desktop-database", str(apps_dir)], timeout=10, check=False)
    except Exception:
        pass
    try:
        subprocess.run(["gtk-update-icon-cache", str(Path.home() / ".local/share/icons/hicolor")], timeout=10, check=False)
    except Exception:
        pass


def run_user_setup() -> None:
    # Create config if needed and load
    cfg = AppConfig()
    # Download default whisper model
    _download_default_model()
    # ydotool user service (if ydotoold is installed)
    _setup_ydotool_user_service()
    # Install desktop entries and icons
    _install_desktop_launchers()
    # Ensure whisper paths are resolved (AppConfig does this on save)
    try:
        cfg.save()
    except Exception:
        pass


