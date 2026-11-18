# src/voxd/models.py
"""
Download, list, remove and activate Whisper and Parakeet GGML models.
`use` also switches asr_engine: Parakeet models → parakeet, any other → whisper.

CLI usage:
    python -m voxd.models list
    python -m voxd.models install  tiny.en              # catalogue key (base / medium.en / large …)
    python -m voxd.models install  https://…/ggml-x.bin # or a direct URL (community models)
    python -m voxd.models remove   tiny.en
    python -m voxd.models use      tiny.en              # catalogue key → marks it active
    python -m voxd.models use      ~/models/ggml-x.bin  # or a local .bin path / URL
"""

from __future__ import annotations
import argparse, sys, shutil, hashlib
from pathlib import Path
from voxd.paths import DATA_DIR
from voxd.core.config import AppConfig
from voxd.utils.setup_utils import print_section

# --------------------------------------------------------------------------- #
# 0.  Model catalogue – keep in sync with whisper.cpp/download-ggml-model.sh
# --------------------------------------------------------------------------- #
HF = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
PK = "https://huggingface.co/ggml-org/parakeet-GGUF/resolve/main/"
# key            size-MB  sha1-digest                                          url
CATALOGUE = {
    # tiny ───────────────────────────────────────────────────────────
    "tiny"           : (  75, "bd577a113a864445d4c299885e0cb97d4ba92b5f", HF+"ggml-tiny.bin"),
    "tiny-q5_1"      : (  31, "2827a03e495b1ed3048ef28a6a4620537db4ee51", HF+"ggml-tiny-q5_1.bin"),
    "tiny-q8_0"      : (  42, "19e8118f6652a650569f5a949d962154e01571d9", HF+"ggml-tiny-q8_0.bin"),
    "tiny.en"        : (  75, "c78c86eb1a8faa21b369bcd33207cc90d64ae9df", HF+"ggml-tiny.en.bin"),
    "tiny.en-q5_1"   : (  31, "3fb92ec865cbbc769f08137f22470d6b66e071b6", HF+"ggml-tiny.en-q5_1.bin"),
    "tiny.en-q8_0"   : (  42, "802d6668e7d411123e672abe4cb6c18f12306abb", HF+"ggml-tiny.en-q8_0.bin"),
    # Russian community fine-tune of multilingual tiny — small enough to run on a
    # nearly-full GPU where large-v3 (~3 GB) hits ErrorOutOfDeviceMemory.
    "tiny-ru"        : (  75, "d624a17fe80a250dcfca9937d622f92a1c783f3b",
                        "https://huggingface.co/wabisabisocial/whisper-tiny-russian-ggml/resolve/main/ggml-tiny-ru.bin"),

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

    # Parakeet (NVIDIA parakeet-tdt-0.6b-v3) — run by parakeet-cli, selecting
    # one sets asr_engine: parakeet. Cache filenames keep the upstream names
    # (see _pretty_name); paths.find_parakeet_model() looks for exactly these.
    "parakeet-tdt-0.6b-v3"      : (1256, "dee7f3a15ed28d0ab4dc28d55ce9f864a122d30b", PK+"ggml-parakeet-tdt-0.6b-v3-f16.bin"),
    "parakeet-tdt-0.6b-v3-q8_0" : ( 669, "0271fffe0d96faa791d97348837857c9a0092b33", PK+"ggml-parakeet-tdt-0.6b-v3-q8_0.bin"),
    "parakeet-tdt-0.6b-v3-q4_k" : ( 416, "cbabbb0bebca8cdcf621f5871d394fe01fcc3baa", PK+"ggml-parakeet-tdt-0.6b-v3-q4_k.bin"),
}

# ~/.local/share/voxd/models (or $XDG_DATA_HOME/voxd/models)
CACHE_DIR   = DATA_DIR / "models"  # renamed variable kept for minimal diff
REPO_MODELS = Path(__file__).resolve().parents[2] / "whisper.cpp" / "models"   # keeps legacy path working


# --------------------------------------------------------------------------- #
# 1.  Helpers
# --------------------------------------------------------------------------- #
def _human(n_mb: int) -> str:      # 142 → '142 MB'
    return f"{n_mb:,} MB".replace(",", " ")

def _pretty_name(key: str) -> str:
    """Cache filename for *key*: the catalogue URL's basename (e.g. Parakeet's
    ``…-f16.bin``), else ``ggml-<key>.bin``."""
    if key in CATALOGUE:
        return CATALOGUE[key][2].rsplit("/", 1)[-1]
    return f"ggml-{key}.bin"


def is_parakeet_model(path_or_key) -> bool:
    """True for Parakeet models (run by parakeet-cli, not whisper-cli)."""
    return "parakeet" in Path(str(path_or_key)).name.lower()

def _download(url: str, dest: Path, *, progress_cb=None):
    """Download *url* to *dest*.

    Parameters
    ----------
    url : str
        File URL.
    dest : pathlib.Path
        Destination path (will be overwritten).
    progress_cb : callable | None, optional
        If given, it will be called as ``progress_cb(downloaded_bytes, total_bytes)``
        after every chunk.  When *None* (default) a tqdm progress-bar is shown.
    """
    import urllib.request, tqdm, os, ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # avoids local cert issues

    with urllib.request.urlopen(url) as resp, open(dest, "wb") as out:
        total = int(resp.info()["Content-Length"])
        downloaded = 0

        if progress_cb is None:
            bar = tqdm.tqdm(total=total, unit="B", unit_scale=True, unit_divisor=1024)

        while chunk := resp.read(8192):
            out.write(chunk)
            downloaded += len(chunk)
            if progress_cb is not None:
                progress_cb(downloaded, total)
            else:
                bar.update(len(chunk))

        if progress_cb is None:
            bar.close()

def _verify_sha1(path: Path, sha_ref: str) -> bool:
    """Return True if file's SHA-1 matches the reference digest (full length)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest() == sha_ref.lower()


def _looks_like_url(s: str) -> bool:
    return str(s).startswith(("http://", "https://"))


def _filename_from_url(url: str) -> str:
    """Cache filename for a direct model URL.

    list_local() only shows ``ggml-*.bin``, so normalise the basename to keep the
    cache discoverable by the rest of the tooling.
    """
    name = url.split("?")[0].rstrip("/").split("/")[-1]
    if not name.endswith(".bin"):
        raise ValueError(f"URL does not point to a .bin model file: {url}")
    if not name.startswith("ggml-"):
        name = "ggml-" + name
    return name


# --------------------------------------------------------------------------- #
# 2.  Public API
# --------------------------------------------------------------------------- #
def ensure(key: str, quiet=False, *, no_check=False, progress_cb=None) -> Path:
    """Return local Path to the requested model, downloading if necessary.

    The optional *progress_cb* is forwarded to the internal downloader and
    therefore allows GUI callers to receive live byte counts while keeping
    the original tqdm behaviour for CLI usage (when *progress_cb* is None).
    """
    if key not in CATALOGUE:
        raise ValueError(f"Unknown model '{key}'. See `voxd models list`")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / _pretty_name(key)
    if dest.exists():
        return dest

    size_mb, sha1, url = CATALOGUE[key]
    if not quiet:
        print(f"Downloading {key} ({_human(size_mb)}) …")
    _download(url, dest, progress_cb=progress_cb)
    if not no_check and not _verify_sha1(dest, sha1):
        dest.unlink(missing_ok=True)
        raise RuntimeError("Checksum mismatch – download corrupted, retried later.")

    # keep a symlink inside whisper.cpp/models for people who call the CLI manually
    _symlink_into_repo(dest)
    return dest


def install_url(url: str, *, progress_cb=None) -> Path:
    """Download a ggml model from a direct *url* into the model cache.

    For community models that aren't in CATALOGUE. The filename is derived from
    the URL; there is no reference digest, so the checksum is not verified.
    Returns the local Path (re-using an existing download if present).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / _filename_from_url(url)
    if dest.exists():
        return dest
    print(f"Downloading {dest.name} from {url} …")
    print("  (custom URL → no checksum to verify)")
    _download(url, dest, progress_cb=progress_cb)
    _symlink_into_repo(dest)
    return dest


def _symlink_into_repo(dest: Path):
    """Mirror a cached model into whisper.cpp/models for manual CLI callers.

    Best effort: a packaged install lives in /opt/voxd, which the user cannot
    write to.  The model in the cache is all voxd itself needs.
    """
    try:
        REPO_MODELS.mkdir(parents=True, exist_ok=True)
        link = REPO_MODELS / dest.name
        if not link.exists():
            link.symlink_to(dest)
    except OSError:
        pass


def list_local() -> list[str]:
    return sorted(p.name for p in CACHE_DIR.glob("ggml-*.bin"))


def remove(key: str):
    path = CACHE_DIR / _pretty_name(key)
    if path.exists():
        remove_file(path)
        print(f"🗑️  Removed {key}")
    else:
        print(f"{key} not found.")


# --------------------------------------------------------------------------- #
# 2b.  Inventory of models on disk (used by the GUI models page and the tray)
# --------------------------------------------------------------------------- #
from dataclasses import dataclass


@dataclass(frozen=True)
class InstalledModel:
    path: Path          # real file
    key: str | None     # catalogue key, None for custom files
    engine: str         # "whisper" | "parakeet"
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name


def human_size(n_bytes: int) -> str:
    """1536 MiB → '1.5 GB'; below 1 GiB in whole MB."""
    mb = n_bytes / (1024 * 1024)
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{max(1, round(mb))} MB"


def _key_for_filename(fname: str) -> str | None:
    for key in CATALOGUE:
        if _pretty_name(key) == fname:
            return key
    return None


def installed_models() -> list[InstalledModel]:
    """Every ggml model on disk: the model cache plus real files dropped into
    whisper.cpp/models (symlinks back into the cache and whisper.cpp's
    ``for-tests-*`` fixtures are skipped). Sorted by name."""
    seen: dict[Path, InstalledModel] = {}
    for d in (CACHE_DIR, REPO_MODELS):
        if not d.is_dir():
            continue
        for p in d.glob("ggml-*.bin"):
            try:
                real = p.resolve(strict=True)
                size = real.stat().st_size
            except OSError:
                continue  # dangling symlink
            if real not in seen:
                seen[real] = InstalledModel(
                    path=real, key=_key_for_filename(real.name),
                    engine="parakeet" if is_parakeet_model(real) else "whisper",
                    size_bytes=size)
    return sorted(seen.values(), key=lambda m: m.name)


def active_model_path(cfg_data: dict) -> Path | None:
    """Resolved path of the model the configured asr_engine will use."""
    if cfg_data.get("asr_engine") == "parakeet":
        p = cfg_data.get("parakeet_model_path") or ""
        if not p:  # empty → the transcriber auto-detects
            try:
                from voxd.paths import find_parakeet_model
                p = find_parakeet_model()
            except FileNotFoundError:
                return None
    else:
        p = cfg_data.get("whisper_model_path") or ""
    if not p:
        return None
    try:
        return Path(p).expanduser().resolve()
    except OSError:
        return None


def remove_file(path: Path):
    """Delete a model file and any whisper.cpp/models symlink pointing at it."""
    real = Path(path).resolve()
    if REPO_MODELS.is_dir():
        for link in REPO_MODELS.glob("*.bin"):
            if link.is_symlink() and link.resolve() == real:
                try:
                    link.unlink()
                except OSError:
                    pass          # read-only install dir; a dangling link is ignored
    real.unlink(missing_ok=True)


def replacement_for(removed: InstalledModel, models: list[InstalledModel]) -> InstalledModel | None:
    """Model to activate after the active one is removed: the largest remaining
    model of the same engine, else the largest of the other engine."""
    rest = [m for m in models if m.path != removed.path]
    same = [m for m in rest if m.engine == removed.engine]
    pool = same or rest
    return max(pool, key=lambda m: m.size_bytes) if pool else None


def describe(key_or_name: str) -> str:
    """One-line hint for a model row."""
    n = str(key_or_name).lower()
    if "parakeet" in n:
        base = "Fast · 25 European languages incl. Russian"
    elif ".en" in n:
        base = "English only"
    elif "-ru" in n or "russian" in n:
        base = "Russian fine-tune"
    else:
        base = "Multilingual"
    if "-q" in n:
        base += " · quantized (smaller)"
    return base


def set_active(key: str | None):
    cfg = AppConfig()
    if key is None:
        # Using cfg.data avoids static analysis complaining about dynamic attrs
        engine = cfg.data.get("asr_engine", "whisper")
        model_key = "parakeet_model_path" if engine == "parakeet" else "whisper_model_path"
        print(f"Current engine: {engine}")
        print(f"Current model: {cfg.data.get(model_key) or '(auto-detect)'}")
        return
    # Accept a catalogue key, a local .bin path, or a direct URL — so community
    # models that aren't in CATALOGUE can be activated too.
    candidate = Path(key).expanduser()
    if candidate.suffix == ".bin" and candidate.is_file():
        path = candidate.resolve()
    elif _looks_like_url(key):
        path = install_url(key)
    else:
        path = ensure(key, quiet=True)
    # The model decides the engine: Parakeet models run on parakeet-cli.
    if is_parakeet_model(path):
        cfg.set("parakeet_model_path", str(path))
        cfg.set("asr_engine", "parakeet")
    else:
        cfg.set("whisper_model_path", str(path))
        cfg.set("asr_engine", "whisper")
    cfg.save()
    print(f"✅ Now using: {path} (engine: {cfg.data.get('asr_engine')})")


# --------------------------------------------------------------------------- #
# 3.  CLI entry-point
# --------------------------------------------------------------------------- #
def _cli(argv=None):
    p = argparse.ArgumentParser(
        prog="voxd models",
        description="Manage ggml Whisper and Parakeet models"
    )
    p.add_argument("--no-check", action="store_true",
                   help="Skip SHA-1 verification")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list",   help="show installed models")
    sp = sub.add_parser("install", help="download a model (catalogue key or direct URL)"); sp.add_argument("name")
    sp = sub.add_parser("fetch",   help="alias for install"); sp.add_argument("name")
    sp = sub.add_parser("remove",  help="delete a model");   sp.add_argument("name")
    sp = sub.add_parser("use",     help="set active model (catalogue key, local .bin path, or URL)"); sp.add_argument("name", nargs="?")

    args = p.parse_args(argv)

    if args.cmd == "list":
        local = list_local()
        print_section("Installed models")
        if local:
            for fn in local: print(" •", fn)
        else:
            print(" (none)")

    elif args.cmd in ("install", "fetch"):
        if _looks_like_url(args.name):
            install_url(args.name)
        else:
            ensure(args.name, no_check=args.no_check)

    elif args.cmd == "remove":
        remove(args.name)

    elif args.cmd == "use":
        set_active(args.name)

if __name__ == "__main__":
    _cli()
