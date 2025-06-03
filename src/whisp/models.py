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
# key            size-MB  sha1-digest                                          url
CATALOGUE = {
    # tiny ───────────────────────────────────────────────────────────
    "tiny"           : (  75, "bd577a113a864445d4c299885e0cb97d4ba92b5f", HF+"ggml-tiny.bin"),
    "tiny-q5_1"      : (  31, "2827a03e495b1ed3048ef28a6a4620537db4ee51", HF+"ggml-tiny-q5_1.bin"),
    "tiny-q8_0"      : (  42, "19e8118f6652a650569f5a949d962154e01571d9", HF+"ggml-tiny-q8_0.bin"),
    "tiny.en"        : (  75, "c78c86eb1a8faa21b369bcd33207cc90d64ae9df", HF+"ggml-tiny.en.bin"),
    "tiny.en-q5_1"   : (  31, "3fb92ec865cbbc769f08137f22470d6b66e071b6", HF+"ggml-tiny.en-q5_1.bin"),
    "tiny.en-q8_0"   : (  42, "802d6668e7d411123e672abe4cb6c18f12306abb", HF+"ggml-tiny.en-q8_0.bin"),

    # base ───────────────────────────────────────────────────────────
    "base"           : ( 142, "465707469ff3a37a2b9b8d8f89f2f99de7299dac", HF+"ggml-base.bin"),
    "base-q5_1"      : (  57, "a3733eda680ef76256db5fc5dd9de8629e62c5e7", HF+"ggml-base-q5_1.bin"),
    "base-q8_0"      : (  78, "7bb89bb49ed6955013b166f1b6a6c04584a20fbe", HF+"ggml-base-q8_0.bin"),
    "base.en"        : ( 142, "137c40403d78fd54d454da0f9bd998f78703390c", HF+"ggml-base.en.bin"),
    "base.en-q5_1"   : (  57, "d26d7ce5a1b6e57bea5d0431b9c20ae49423c94a", HF+"ggml-base.en-q5_1.bin"),
    "base.en-q8_0"   : (  78, "bb1574182e9b924452bf0cd1510ac034d323e948", HF+"ggml-base.en-q8_0.bin"),

    # small ──────────────────────────────────────────────────────────
    "small"          : ( 466, "55356645c2b361a969dfd0ef2c5a50d530afd8d5", HF+"ggml-small.bin"),
    "small-q5_1"     : ( 181, "6fe57ddcfdd1c6b07cdcc73aaf620810ce5fc771", HF+"ggml-small-q5_1.bin"),
    "small-q8_0"     : ( 252, "bcad8a2083f4e53d648d586b7dbc0cd673d8afad", HF+"ggml-small-q8_0.bin"),
    "small.en"       : ( 466, "db8a495a91d927739e50b3fc1cc4c6b8f6c2d022", HF+"ggml-small.en.bin"),
    "small.en-q5_1"  : ( 181, "20f54878d608f94e4a8ee3ae56016571d47cba34", HF+"ggml-small.en-q5_1.bin"),
    "small.en-q8_0"  : ( 252, "9d75ff4ccfa0a8217870d7405cf8cef0a5579852", HF+"ggml-small.en-q8_0.bin"),
    "small.en-tdrz"  : ( 465, "b6c6e7e89af1a35c08e6de56b66ca6a02a2fdfa1", HF+"ggml-small.en-tdrz.bin"),

    # medium (full list)
    "medium"         : (1500, "fd9727b6e1217c2f614f9b698455c4ffd82463b4", HF+"ggml-medium.bin"),
    "medium-q5_0"    : ( 514, "7718d4c1ec62ca96998f058114db98236937490e", HF+"ggml-medium-q5_0.bin"),
    "medium-q8_0"    : ( 785, "e66645948aff4bebbec71b3485c576f3d63af5d6", HF+"ggml-medium-q8_0.bin"),
    "medium.en"      : (1500, "8c30f0e44ce9560643ebd10bbe50cd20eafd3723", HF+"ggml-medium.en.bin"),
    "medium.en-q5_0" : ( 514, "bb3b5281bddd61605d6fc76bc5b92d8f20284c3b", HF+"ggml-medium.en-q5_0.bin"),
    "medium.en-q8_0" : ( 785, "b1cf48c12c807e14881f634fb7b6c6ca867f6b38", HF+"ggml-medium.en-q8_0.bin"),

    # large (v1/v2/v3)
    "large-v1"       : (2900, "b1caaf735c4cc1429223d5a74f0f4d0b9b59a299", HF+"ggml-large-v1.bin"),
    "large-v2"       : (2900, "0f4c8e34f21cf1a914c59d8b3ce882345ad349d6", HF+"ggml-large-v2.bin"),
    "large-v2-q5_0"  : (1100, "00e39f2196344e901b3a2bd5814807a769bd1630", HF+"ggml-large-v2-q5_0.bin"),
    "large-v2-q8_0"  : (1500, "da97d6ca8f8ffbeeb5fd147f79010eeea194ba38", HF+"ggml-large-v2-q8_0.bin"),
    "large-v3"       : (2900, "ad82bf6a9043ceed055076d0fd39f5f186ff8062", HF+"ggml-large-v3.bin"),
    "large-v3-q5_0"  : (1100, "e6e2ed78495d403bef4b7cff42ef4aaadcfea8de", HF+"ggml-large-v3-q5_0.bin"),
    "large-v3-turbo" : (1500, "4af2b29d7ec73d781377bfd1758ca957a807e941", HF+"ggml-large-v3-turbo.bin"),
    "large-v3-turbo-q5_0":( 547,"e050f7970618a659205450ad97eb95a18d69c9ee",HF+"ggml-large-v3-turbo-q5_0.bin"),
    "large-v3-turbo-q8_0":( 834,"01bf15bedffe9f39d65c1b6ff9b687ea91f59e0e",HF+"ggml-large-v3-turbo-q8_0.bin"),
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

def _verify_sha1(path: Path, sha_ref: str) -> bool:
    """Return True if file’s SHA-1 matches the reference digest (full length)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == sha_ref.lower()


# --------------------------------------------------------------------------- #
# 2.  Public API
# --------------------------------------------------------------------------- #
def ensure(key: str, quiet=False, *, no_check=False) -> Path:
    """Return local Path to the requested model, downloading if necessary."""
    if key not in CATALOGUE:
        raise ValueError(f"Unknown model '{key}'. See `whisp models list`")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / _pretty_name(key)
    if dest.exists():
        return dest

    size_mb, sha1, url = CATALOGUE[key]
    if not quiet:
        print(f"Downloading {key} ({_human(size_mb)}) …")
    _download(url, dest)
    if not no_check and not _verify_sha1(dest, sha1):
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
    p = argparse.ArgumentParser(
        prog="whisp models",
        description="Manage ggml Whisper models"
    )
    p.add_argument("--no-check", action="store_true",
                   help="Skip SHA-1 verification")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list",   help="show installed models")
    sp = sub.add_parser("install", help="download a model"); sp.add_argument("name")
    sp = sub.add_parser("fetch",   help="alias for install"); sp.add_argument("name")
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

    elif args.cmd in ("install", "fetch"):
        ensure(args.name, no_check=args.no_check)

    elif args.cmd == "remove":
        remove(args.name)

    elif args.cmd == "use":
        set_active(args.name)

if __name__ == "__main__":
    _cli()
