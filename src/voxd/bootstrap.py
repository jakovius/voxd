from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Optional, Tuple

import requests

from voxd.core.config import AppConfig
from voxd.models import ensure as ensure_whisper_model


def _xdg_data_home() -> Path:
    base = os.getenv("XDG_DATA_HOME")
    return Path(base) if base else Path.home() / ".local" / "share"


def _bin_dir() -> Path:
    path = _xdg_data_home() / "voxd" / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cpu_variant() -> Tuple[str, str]:
    machine = (os.uname().machine or "").lower()
    if machine in ("x86_64", "amd64"):
        text = ""
        try:
            text = subprocess.check_output(["lscpu"], text=True)
        except Exception:
            try:
                text = Path("/proc/cpuinfo").read_text(errors="ignore")
            except Exception:
                text = ""
        if re.search(r"\bavx2\b", text, re.I):
            return "amd64", "avx2"
        if re.search(r"sse4_2", text, re.I):
            return "amd64", "sse42"
        return "amd64", "none"
    if machine in ("aarch64", "arm64"):
        return "arm64", "neon"
    return machine, "none"


def _gh_release_json(repo: str, tag: Optional[str]) -> Optional[dict]:
    api = (
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        if tag
        else f"https://api.github.com/repos/{repo}/releases/latest"
    )
    try:
        resp = requests.get(api, timeout=10)
        if resp.ok:
            return resp.json()
    except Exception:
        return None
    return None


def _find_asset_url(j: dict, asset_name: str) -> str:
    assets = j.get("assets", []) or []
    for a in assets:
        url = a.get("browser_download_url") or ""
        if url.endswith("/" + asset_name):
            return url
    return ""


def _download_to(path: Path, url: str) -> bool:
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception:
        return False


def _sha256sum(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_checksum_if_available(repo: str, tag: Optional[str], asset_name: str, file_path: Path, arch: str, variant: str) -> bool:
    j = _gh_release_json(repo, tag)
    if not j:
        return True
    sums_asset = (
        f"SHA256SUMS_{arch}_{variant}.txt" if arch == "amd64" else f"SHA256SUMS_{arch}.txt"
    )
    sums_url = _find_asset_url(j, sums_asset)
    if not sums_url:
        return True
    try:
        resp = requests.get(sums_url, timeout=10)
        if not resp.ok:
            return True
        expected = ""
        for line in resp.text.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and parts[1] == asset_name:
                expected = parts[0]
                break
        if not expected:
            return True
        return expected == _sha256sum(file_path)
    except Exception:
        return True


def _extract_tar_gz(tar_path: Path, dest_dir: Path) -> Optional[Path]:
    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            members = tf.getmembers()
            tf.extractall(dest_dir)
            # Return the first regular file that looks like a binary name we expect
            for m in members:
                name = Path(m.name).name
                if name in ("whisper-cli", "llama-server"):
                    return dest_dir / name
    except Exception:
        return None
    return None


def _fetch_prebuilt(kind: str, repo: str, tag: Optional[str]) -> Optional[Path]:
    arch, variant = _cpu_variant()
    if arch not in ("amd64", "arm64"):
        return None
    base = f"{kind}_linux_{arch}"
    if arch == "amd64" and variant in ("avx2", "sse42"):
        base = f"{base}_{variant}"
    asset = f"{base}.tar.gz"
    j = _gh_release_json(repo, tag)
    if not j:
        return None
    url = _find_asset_url(j, asset)
    if not url:
        return None
    tmp_dir = Path(os.getenv("TMPDIR", "/tmp"))
    tarball = tmp_dir / asset
    if not _download_to(tarball, url):
        return None
    if not _verify_checksum_if_available(repo, tag, asset, tarball, arch, variant):
        try:
            tarball.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    extracted = _extract_tar_gz(tarball, _bin_dir())
    try:
        tarball.unlink(missing_ok=True)
    except Exception:
        pass
    if extracted and extracted.exists():
        try:
            extracted.chmod(0o755)
        except Exception:
            pass
        return extracted
    return None


def _ensure_prebuilts(cfg: AppConfig) -> None:
    repo = os.getenv("VOXD_BIN_REPO", "Jacob8472/voxd-prebuilts")
    tag = os.getenv("VOXD_BIN_TAG") or None

    needs_whisper = not Path(cfg.whisper_binary).exists()
    needs_llama = not Path(cfg.llamacpp_server_path).exists()

    if needs_whisper:
        wb = _fetch_prebuilt("whisper-cli", repo, tag)
        if wb:
            cfg.set("whisper_binary", str(wb))

    if needs_llama:
        lb = _fetch_prebuilt("llama-server", repo, tag)
        if lb:
            cfg.set("llamacpp_server_path", str(lb))


def _ensure_model(cfg: AppConfig) -> None:
    model_path = Path(cfg.whisper_model_path)
    if not model_path.exists():
        try:
            ensure_whisper_model("base.en", quiet=True)
        except Exception:
            pass


def _is_wayland() -> bool:
    return os.getenv("XDG_SESSION_TYPE", "").startswith("wayland")


def _have_ydotool() -> bool:
    return bool(shutil.which("ydotool")) and bool(shutil.which("ydotoold"))


def _as_user_prefix(target_user: str) -> list[str]:
    # Prefer runuser to avoid dependency on sudo inside root context
    if shutil.which("runuser"):
        return ["runuser", "-u", target_user, "--"]
    return ["su", "-", target_user, "-c"]


def _setup_ydotool_noninteractive() -> None:
    # Escalate to root using pkexec (GUI) or sudo, then run packaged script.
    try:
        from importlib.resources import files
    except Exception:
        return
    try:
        script_path = files("voxd").joinpath("setup_ydotool.sh")
    except FileNotFoundError:
        return
    if not script_path.exists():
        return

    # Copy to a temp path to avoid read-only locations under AppImage squashfs
    tmp = Path("/tmp") / "voxd_setup_ydotool.sh"
    try:
        shutil.copy(script_path, tmp)
        tmp.chmod(0o755)
    except Exception:
        return

    cmd: list[str]
    if shutil.which("pkexec"):
        cmd = ["pkexec", str(tmp)]
    elif shutil.which("sudo"):
        cmd = ["sudo", str(tmp)]
    else:
        # Last resort: try running directly (works if already root)
        cmd = [str(tmp)]

    try:
        subprocess.run(cmd, check=False)
    except Exception:
        pass


def _attempt_host_utilities() -> None:
    # Non-interactive best-effort install of minimal utilities used by VOXD
    backend = os.getenv("XDG_SESSION_TYPE") or ("wayland" if os.getenv("WAYLAND_DISPLAY") else ("x11" if os.getenv("DISPLAY") else ""))

    want_packages: list[str] = []
    # Clipboard helpers
    if not (shutil.which("wl-copy") or shutil.which("xclip") or shutil.which("xsel")):
        if backend.startswith("wayland"):
            want_packages.append("wl-clipboard")
        else:
            want_packages.append("xclip")

    # X11 typing helper
    if (backend == "x11") and not shutil.which("xdotool"):
        want_packages.append("xdotool")

    if not want_packages:
        return

    pm = None
    if shutil.which("apt"):
        pm = ("apt", ["apt", "install", "-y", *want_packages])
    elif shutil.which("dnf5"):
        pm = ("dnf5", ["dnf5", "install", "-y", *want_packages])
    elif shutil.which("dnf"):
        pm = ("dnf", ["dnf", "install", "-y", *want_packages])
    elif shutil.which("pacman"):
        pm = ("pacman", ["pacman", "-Sy", "--noconfirm", *want_packages])

    if not pm:
        return

    installer = pm[1]
    if os.geteuid() != 0:
        if shutil.which("pkexec"):
            installer = ["pkexec"] + installer
        elif shutil.which("sudo"):
            installer = ["sudo"] + installer
        else:
            return

    try:
        subprocess.run(installer, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _fallback_build_if_needed(cfg: AppConfig) -> None:
    # If still missing whisper-cli, invoke packaged setup.sh non-interactively.
    need_whisper = not Path(cfg.whisper_binary).exists()
    need_llama = not Path(cfg.llamacpp_server_path).exists()
    if not (need_whisper or need_llama):
        return
    try:
        from importlib.resources import files
        setup = files("voxd").joinpath("setup.sh")
    except Exception:
        return
    if not setup.exists():
        return
    try:
        # Feed 'yes' to any prompts to avoid blocking; safe due to idempotency
        subprocess.run(["bash", "-lc", f"yes | bash '{str(setup)}'"], check=False)
    except Exception:
        pass


def bootstrap_if_needed() -> None:
    cfg = AppConfig()

    _ensure_prebuilts(cfg)
    _ensure_model(cfg)

    if _is_wayland() and not _have_ydotool():
        _setup_ydotool_noninteractive()

    _attempt_host_utilities()

    # Last resort build if prebuilts are unavailable
    _fallback_build_if_needed(cfg)

    cfg.save()


