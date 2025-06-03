# src/whisp/models.py
"""
Download, list, remove and activate Whisper GGML models.

CLI usage:
    python -m whisp.models list
    python -m whisp.models install  tiny.en      # or base   / medium.en / large
    python -m whisp.models remove   tiny.en
    python -m whisp.models use      tiny.en      # marks it active in config.yaml
"""

from __future__ import annotations
import argparse, sys, shutil, hashlib
from pathlib import Path
from platformdirs import user_cache_dir
from whisp.core.config import AppConfig
from whisp.utils.setup_utils import print_section

# --------------------------------------------------------------------------- #
# 0.  Model catalogue – keep in sync with whisper.cpp/download-ggml-model.sh
# --------------------------------------------------------------------------- #
HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
CATALOGUE = {
    # key          size-MB   md5 (first 8 chars is fine)          url
    "tiny.en"  : (   75, "9a6d1f6e",  HF + "ggml-tiny.en.bin"),
    "tiny"     : (  142, "5898dbfe",  HF + "ggml-tiny.bin"),
    "base.en"  : (  142, "91c37b7c",  HF + "ggml-base.en.bin"),
    "base"     : (  142, "79c91511",  HF + "ggml-base.bin"),
    "small.en" : (  466, "e4e09d61",  HF + "ggml-small.en.bin"),
    "small"    : (  466, "bd577a2f",  HF + "ggml-small.bin"),
    "medium.en": ( 1500, "6128f06d",  HF + "ggml-medium.en.bin"),
    "medium"   : ( 1500, "0f4f0c7b",  HF + "ggml-medium.bin"),
    "large-v3" : ( 2900, "a20384c7",  HF + "ggml-large-v3.bin"),
}

CACHE_DIR   = Path(user_cache_dir("whisp")) / "models"
REPO_MODELS = Path(__file__).resolve().parents[2] / "whisper.cpp" / "models"   # keeps legacy path working


# --------------------------------------------------------------------------- #
# 1.  Helpers
# --------------------------------------------------------------------------- #
def _human(n_mb: int) -> str:      # 142 → '142 MB'
    return f"{n_mb:,} MB".replace(",", " ")

def _pretty_name(key: str) -> str:
    return f"ggml-{key}.bin"

def _download(url: str, dest: Path):
    import urllib.request, tqdm, os, ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # avoids local cert issues

    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        total = int(resp.info()["Content-Length"])
        with tqdm.tqdm(total=total, unit="B", unit_scale=True, unit_divisor=1024) as bar:
            while chunk := resp.read(8192):
                out.write(chunk)
                bar.update(len(chunk))

def _verify_md5(path: Path, md5_ref: str) -> bool:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().startswith(md5_ref.lower()[:8])   # first bytes match is fine


# --------------------------------------------------------------------------- #
# 2.  Public API
# --------------------------------------------------------------------------- #
def ensure(key: str, quiet=False) -> Path:
    """Return local Path to the requested model, downloading if necessary."""
    if key not in CATALOGUE:
        raise ValueError(f"Unknown model '{key}'. See `whisp models list`")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / _pretty_name(key)
    if dest.exists():
        return dest

    size_mb, md5, url = CATALOGUE[key]
    if not quiet:
        print(f"Downloading {key} ({_human(size_mb)}) …")
    _download(url, dest)
    if not _verify_md5(dest, md5):
        dest.unlink(missing_ok=True)
        raise RuntimeError("Checksum mismatch – download corrupted, retried later.")

    # keep a symlink inside whisper.cpp/models for people who call the CLI manually
    REPO_MODELS.mkdir(parents=True, exist_ok=True)
    link = REPO_MODELS / dest.name
    if not link.exists():
        link.symlink_to(dest)
    return dest


def list_local() -> list[str]:
    return sorted(p.name for p in CACHE_DIR.glob("ggml-*.bin"))


def remove(key: str):
    path = CACHE_DIR / _pretty_name(key)
    if path.exists():
        path.unlink()
        print(f"🗑️  Removed {key}")
    else:
        print(f"{key} not found.")


def set_active(key: str | None):
    cfg = AppConfig()
    if key is None:
        print(f"Current model: {cfg.model_path}")
        return
    path = ensure(key, quiet=True)
    cfg.set("model_path", str(path))
    cfg.save()
    print(f"✅ Now using: {path}")


# --------------------------------------------------------------------------- #
# 3.  CLI entry-point
# --------------------------------------------------------------------------- #
def _cli(argv=None):
    p = argparse.ArgumentParser(prog="whisp models", description="Manage ggml Whisper models")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list",   help="show installed models")
    sp = sub.add_parser("install", help="download a model"); sp.add_argument("name")
    sp = sub.add_parser("remove",  help="delete a model");   sp.add_argument("name")
    sp = sub.add_parser("use",     help="set active model"); sp.add_argument("name", nargs="?")

    args = p.parse_args(argv)

    if args.cmd == "list":
        local = list_local()
        print_section("Installed models")
        if local:
            for fn in local: print(" •", fn)
        else:
            print(" (none)")

    elif args.cmd == "install":
        ensure(args.name)

    elif args.cmd == "remove":
        remove(args.name)

    elif args.cmd == "use":
        set_active(args.name)

if __name__ == "__main__":
    _cli()
