from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
import sys
import threading
import time

from voxd.core.config import AppConfig, CONFIG_PATH
from voxd.paths import DATA_DIR, LLAMACPP_MODELS_DIR


def _ensure_dir(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _download_with_progress(url: str, dest: Path, label: str, timeout: int = 60, retries: int = 3) -> bool:
    """Download URL to dest with a simple progress bar. Returns True on success."""
    try:
        import requests  # type: ignore
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[setup] {label}: {dest}")
        attempt = 0
        while attempt < retries:
            attempt += 1
            try:
                with requests.get(url, stream=True, timeout=timeout) as r:  # type: ignore
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk = 1024 * 1024
                    tmp = dest.with_suffix(dest.suffix + ".tmp")
                    with open(tmp, "wb") as f:
                        for part in r.iter_content(chunk_size=chunk):
                            if part:
                                f.write(part)
                                downloaded += len(part)
                                if total > 0 and sys.stdout.isatty():
                                    pct = downloaded * 100 // total
                                    bar_len = 30
                                    filled = int(bar_len * downloaded / total)
                                    bar = "#" * filled + "-" * (bar_len - filled)
                                    sys.stdout.write(f"\r[setup] downloading [{bar}] {pct}%")
                                    sys.stdout.flush()
                        if total > 0 and sys.stdout.isatty():
                            sys.stdout.write("\n")
                    tmp.replace(dest)
                break
            except Exception as e:
                if attempt >= retries:
                    raise
                print(f"[setup] {label}: retrying ({attempt}/{retries})…", flush=True)
        print(f"[setup] {label}: done")
        return True
    except Exception as e:
        print(f"[setup] {label}: failed ({e})")
        return False


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
        _download_with_progress(
            url,
            model_file,
            label="Whisper base model",
            timeout=60,
        )
    except Exception as e:
        print(f"[setup] Whisper model download failed ({e}).", flush=True)


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
    """Ensure ydotoold user service is present and running.

    Prefer the packaged unit at /usr/lib/systemd/user/ydotoold.service.
    Fallback to a per-user unit only if the packaged unit is absent.
    Always ensure the client is reachable on PATH if we manage prebuilts.
    """
    # Ensure permissions for /dev/uinput and socket env
    _ensure_input_group_membership()
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
    os.environ.setdefault("YDOTOOL_SOCKET", str(Path.home() / ".ydotool_socket"))

    pkg_unit = Path("/usr/lib/systemd/user/ydotoold.service")
    user_systemd = Path.home() / ".config/systemd/user"
    _ensure_dir(user_systemd)

    if not pkg_unit.exists():
        # Need a binary first (system or prebuilt)
        yd = shutil.which("ydotoold")
        if not yd:
            yd = _ensure_ydotool_prebuilt() or ""
            if yd:
                try:
                    # Put client on PATH for runtime
                    bin_dir = Path.home() / ".local/share/voxd/bin"
                    local_bin = Path.home() / ".local/bin"
                    _ensure_dir(local_bin)
                    if (bin_dir / "ydotool").exists():
                        try:
                            (local_bin / "ydotool").unlink(missing_ok=True)  # type: ignore[attr-defined]
                        except Exception:
                            try:
                                (local_bin / "ydotool").unlink()
                            except Exception:
                                pass
                        try:
                            (local_bin / "ydotool").symlink_to(bin_dir / "ydotool")
                        except Exception:
                            pass
                except Exception:
                    pass
        if not yd:
            print("[setup] ydotoold not found and prebuilt fetch failed", flush=True)
            return

        # Create per-user unit
        svc = user_systemd / "ydotoold.service"
        try:
            svc.write_text(
                (
                    "[Unit]\n"
                    "Description=ydotool user daemon\n"
                    "After=default.target\n\n"
                    "[Service]\n"
                    f"ExecStart={yd} --socket-path=%h/.ydotool_socket --socket-own=%U:%G\n"
                    "Restart=on-failure\n"
                    "RestartSec=1s\n\n"
                    "[Install]\n"
                    "WantedBy=default.target\n"
                )
            )
        except Exception:
            return

    # Enable and start with retries; fallback to sg input
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "ydotoold.service"], check=False)
        started = False
        for _ in range(3):
            subprocess.run(["systemctl", "--user", "start", "ydotoold.service"], check=False)
            time.sleep(1.0)
            r = subprocess.run(["systemctl", "--user", "is-active", "ydotoold.service"], check=False)
            if r.returncode == 0:
                started = True
                break
        if not started and shutil.which("sg"):
            uid, gid = os.getuid(), os.getgid()
            ydbin = shutil.which("ydotoold") or str(Path.home() / ".local/share/voxd/bin/ydotoold")
            cmd = ["sg", "input", "-c", f"{ydbin} --socket-path='$HOME/.ydotool_socket' --socket-own={uid}:{gid} &"]
            subprocess.run(cmd, check=False)
        if not started:
            print("[setup] ydotoold may require a logout/login after joining 'input' group.", flush=True)
    except Exception:
        pass


def _ensure_ydotool_prebuilt() -> str | None:
    """Download ydotool/ydotoold prebuilt into ~/.local/share/voxd/bin if missing.
    Returns path to ydotoold or None.
    """
    try:
        which_d = shutil.which("ydotoold")
        if which_d:
            return which_d
        bin_dir = Path.home() / ".local/share/voxd/bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        ydbin = bin_dir / "ydotoold"
        ycbin = bin_dir / "ydotool"
        if ydbin.exists() and os.access(ydbin, os.X_OK):
            return str(ydbin)
        # Determine asset name (no CPU feature variants)
        import platform, tempfile, tarfile, requests  # type: ignore
        arch = platform.machine().lower()
        if arch in ("x86_64", "amd64"):
            arch = "amd64"
        elif arch in ("aarch64", "arm64"):
            arch = "arm64"
        else:
            return None
        # Download daemon and client archives separately
        d_only = f"ydotoold_linux_{arch}.tar.gz"
        c_only = f"ydotool_linux_{arch}.tar.gz"
        repo = os.environ.get("VOXD_BIN_REPO", "jakovius/voxd-prebuilts")
        tag = os.environ.get("VOXD_BIN_TAG", None)
        with tempfile.TemporaryDirectory() as td:
            url_d = _gh_release_asset_url(repo, d_only, tag)
            url_c = _gh_release_asset_url(repo, c_only, tag)
            if url_d:
                tar_d = Path(td) / d_only
                if _download_with_progress(url_d, tar_d, label="ydotoold archive", timeout=60):
                    with tarfile.open(tar_d, "r:gz") as tf:
                        tf.extractall(bin_dir)
            if url_c:
                tar_c = Path(td) / c_only
                if _download_with_progress(url_c, tar_c, label="ydotool archive", timeout=60):
                    with tarfile.open(tar_c, "r:gz") as tf:
                        tf.extractall(bin_dir)
        try:
            ydbin.chmod(0o755)
            ycbin.chmod(0o755)
        except Exception:
            pass
        # Place client on PATH for app usage
        try:
            local_bin = Path.home() / ".local/bin"
            _ensure_dir(local_bin)
            if ycbin.exists():
                try:
                    (local_bin / "ydotool").unlink(missing_ok=True)  # type: ignore[attr-defined]
                except Exception:
                    try:
                        (local_bin / "ydotool").unlink()
                    except Exception:
                        pass
                try:
                    (local_bin / "ydotool").symlink_to(ycbin)
                except Exception:
                    pass
            # Optionally expose daemon on PATH for manual testing
            if ydbin.exists():
                try:
                    (local_bin / "ydotoold").unlink(missing_ok=True)  # type: ignore[attr-defined]
                except Exception:
                    try:
                        (local_bin / "ydotoold").unlink()
                    except Exception:
                        pass
                try:
                    (local_bin / "ydotoold").symlink_to(ydbin)
                except Exception:
                    pass
        except Exception:
            pass
        if ydbin.exists():
            return str(ydbin)
    except Exception:
        return None
    return None


def _detect_cpu_variant() -> tuple[str, str]:
    """Return (arch, variant) for prebuilt selection.
    arch: amd64|arm64; variant: avx2|sse42|neon|none
    """
    try:
        import platform
        machine = platform.machine().lower()
    except Exception:
        machine = ""
    arch = ""; variant = "none"
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
        # Try lscpu first
        try:
            out = subprocess.run(["lscpu"], capture_output=True, text=True, timeout=2)
            txt = (out.stdout or "") + (out.stderr or "")
        except Exception:
            try:
                txt = (Path("/proc/cpuinfo").read_text())
            except Exception:
                txt = ""
        t = txt.lower()
        if "avx2" in t:
            variant = "avx2"
        elif "sse4_2" in t or "sse4.2" in t:
            variant = "sse42"
        else:
            variant = "none"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
        variant = "neon"
    else:
        arch = machine or "unknown"
        variant = "none"
    return arch, variant


def _gh_release_asset_url(repo: str, asset_name: str, tag: str | None = None) -> str:
    api = f"https://api.github.com/repos/{repo}/releases/{'tags/' + tag if tag else 'latest'}"
    try:
        import requests  # type: ignore
        r = requests.get(api, timeout=15)
        r.raise_for_status()
        data = r.json()
        assets = data.get("assets", [])
        for a in assets:
            if a.get("name") == asset_name and a.get("browser_download_url"):
                return a["browser_download_url"]
    except Exception:
        pass
    return ""


def _ensure_llamacpp_server_prebuilt() -> str | None:
    """Ensure llama-server exists, trying PATH then prebuilt download.
    Returns absolute path to llama-server or None on failure.
    """
    which = shutil.which("llama-server")
    if which:
        try:
            return str(Path(which).resolve())
        except Exception:
            return which

    # Try prebuilt download into ~/.local/share/voxd/bin
    bin_dir = Path.home() / ".local/share/voxd/bin"
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    dest = bin_dir / "llama-server"
    if dest.exists():
        return str(dest.resolve())

    arch, variant = _detect_cpu_variant()
    if arch not in ("amd64", "arm64"):
        return None
    if arch == "amd64" and variant not in ("avx2", "sse42"):
        # No compatible x86 feature → skip prebuilts
        return None

    if arch == "amd64":
        base = f"llama-server_linux_{arch}_{variant}"
    else:
        base = f"llama-server_linux_{arch}"
    asset = base + ".tar.gz"
    repo = os.environ.get("VOXD_BIN_REPO", "jakovius/voxd-prebuilts")
    tag = os.environ.get("VOXD_BIN_TAG", None)
    url = _gh_release_asset_url(repo, asset, tag)
    if not url:
        return None

    try:
        import tarfile
        import tempfile
        import requests  # type: ignore
        print("[setup] Ensuring llama-server binary…", flush=True)
        with tempfile.TemporaryDirectory() as td:
            tar_path = Path(td) / asset
            if not _download_with_progress(url, tar_path, label="llama-server archive", timeout=60):
                return None
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(bin_dir)
        try:
            dest.chmod(0o755)
        except Exception:
            pass
        if dest.exists():
            return str(dest.resolve())
    except Exception:
        return None
    return None


def _ensure_llamacpp_default_model() -> str | None:
    """Ensure the default llama.cpp model is available.
    Returns absolute path or None on failure.
    """
    try:
        model_dir = LLAMACPP_MODELS_DIR
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file = model_dir / "qwen2.5-3b-instruct-q4_k_m.gguf"
        if model_file.exists():
            return str(model_file.resolve())
        url = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true"
        if not _download_with_progress(url, model_file, label="AIPP model (qwen2.5-3b-instruct)", timeout=300):
            return None
        return str(model_file.resolve())
    except Exception:
        return None


def _setup_llamacpp_user_components() -> None:
    """Ensure llama-server binary and default model exist and write absolute paths to config.

    UX: Download of the model can be lengthy; we show a spinner. The app remains
    usable for transcription even if AIPP is not ready yet.
    """
    server_path = _ensure_llamacpp_server_prebuilt()
    # Download model synchronously so user sees progress and completes setup fully
    model_path = _ensure_llamacpp_default_model()
    if not server_path and not model_path:
        return
    try:
        cfg = AppConfig()
        updated = False
        if server_path:
            cfg.data["llamacpp_server_path"] = server_path
            cfg.llamacpp_server_path = server_path  # attribute mirror
            updated = True
        if model_path:
            cfg.data["llamacpp_default_model"] = model_path
            cfg.llamacpp_default_model = model_path
            updated = True
        if updated:
            cfg.save()
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


def run_user_setup(verbose: bool = False) -> None:
    # Create config if needed and load
    cfg = AppConfig()
    # Download default whisper model
    _download_default_model()
    # ydotool user service (ensure daemon exists and service is enabled)
    if verbose:
      try:
        print("[setup:v] ydotool on PATH:", shutil.which("ydotool"))
        print("[setup:v] ydotoold on PATH:", shutil.which("ydotoold"))
        bin_dir = Path.home() / ".local/share/voxd/bin"
        print("[setup:v] voxd-managed ydotoold:", (bin_dir / "ydotoold"))
      except Exception:
        pass
    _setup_ydotool_user_service()
    if verbose:
      try:
        pkg_unit = Path("/usr/lib/systemd/user/ydotoold.service")
        user_unit = Path.home() / ".config/systemd/user/ydotoold.service"
        print("[setup:v] packaged unit present:", pkg_unit.exists())
        print("[setup:v] user unit path:", str(user_unit))
        subprocess.run(["systemctl", "--user", "status", "ydotoold.service"], check=False)
        # Health checks
        yc = shutil.which("ydotool")
        if yc:
          print("[setup:v] ydotool debug (socket):")
          subprocess.run([yc, "debug"], check=False)
          # No-op key test (quick verification)
          print("[setup:v] ydotool key test (1:0)…")
          try:
            r = subprocess.run([yc, "key", "1:0"], timeout=3, check=False)
            print("[setup:v] ydotool key test:", "OK" if r.returncode == 0 else f"rc={r.returncode}")
          except Exception as _e:
            print("[setup:v] ydotool key test: error")
      except Exception:
        pass
    # Install desktop entries and icons
    _install_desktop_launchers()
    # Ensure whisper paths are resolved (AppConfig does this on save)
    try:
        cfg.save()
    except Exception:
        pass

    # Ensure llama.cpp server and model (best-effort, packaged installs)
    try:
        _setup_llamacpp_user_components()
        if verbose:
          try:
            print("[setup:v] llamacpp_server_path:", cfg.data.get("llamacpp_server_path"))
            print("[setup:v] llamacpp_default_model:", cfg.data.get("llamacpp_default_model"))
          except Exception:
            pass
    except Exception:
        pass


