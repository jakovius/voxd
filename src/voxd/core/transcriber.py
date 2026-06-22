import subprocess
import os
import json
from pathlib import Path
import re
from voxd.utils.libw import verbo, verr
from voxd.paths import find_whisper_cli, find_base_model
from voxd.utils.languages import normalize_lang_code, is_valid_lang


# Whisper.cpp occasionally hallucinates "YouTube boilerplate" (subscribe/like
# phrases from its training data) when fed silence or noise. These helpers let
# us drop a transcript that consists *solely* of such a known phrase.
_PUNCT_STRIP = " \t\n.,!?…\"'«»—–-:;()"


def _normalize_for_match(text: str) -> str:
    """Lower-case, collapse whitespace, strip edge punctuation for comparison."""
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text.strip(_PUNCT_STRIP)


# whisper.cpp logs its backend/device selection and timing breakdown to stderr.
# These helpers turn that noise into a one-line answer to "was the GPU used?".
def detect_compute_backend(stderr: str) -> str:
    """Best-effort identification of the compute backend whisper.cpp actually used.

    whisper.cpp emits backend-init lines on stderr at run time. A GPU-built binary
    that can't find a device/driver silently falls back to CPU, so the only reliable
    signal is what it printed for *this* run — not the build flags or the config.
    """
    s = (stderr or "").lower()
    if "ggml_cuda_init" in s or "using cuda backend" in s or "cuda devices" in s:
        return "CUDA"
    if "ggml_vulkan" in s or "using vulkan backend" in s or "vulkan devices" in s:
        return "Vulkan"
    if "ggml_metal" in s or "using metal backend" in s:
        return "Metal"
    return "CPU"


def _extract_whisper_timings(stderr: str) -> str | None:
    """Return whisper.cpp's 'total time' timing line from stderr, if present."""
    for line in (stderr or "").splitlines():
        if "total time" in line.lower():
            return line.strip()
    return None


def probe_whisper_gpu_capability(binary_path) -> dict:
    """Statically determine whether a *whisper-cli* binary was built with GPU support.

    Returns ``{"capable": bool | None, "backend": str | None, "detail": str}``.
    ``capable`` is ``None`` when it cannot be determined. This does not run inference;
    it inspects the GPU backend shared libs shipped next to the binary, ``ldd`` output,
    and (for repo-local builds) the CMake cache.
    """
    info: dict = {"capable": None, "backend": None, "detail": ""}
    try:
        bin_path = Path(binary_path)
    except Exception:
        return info
    if not bin_path.is_file():
        info["detail"] = "binary not found"
        return info

    found: list[str] = []

    # 1. ggml backend shared libs shipped next to the binary (build/bin/*.so).
    try:
        siblings = " ".join(p.name.lower() for p in bin_path.parent.glob("*"))
        if "ggml-cuda" in siblings:
            found.append("CUDA")
        if "ggml-vulkan" in siblings:
            found.append("Vulkan")
    except Exception:
        pass

    # 2. ldd – does the binary (or its libs) link CUDA/Vulkan runtimes?
    try:
        ldd = subprocess.run(["ldd", str(bin_path)], capture_output=True, text=True, timeout=10)
        out = (ldd.stdout + ldd.stderr).lower()
        if ("libcudart" in out or "libcublas" in out) and "CUDA" not in found:
            found.append("CUDA")
        if "libvulkan" in out and "Vulkan" not in found:
            found.append("Vulkan")
    except Exception:
        pass

    # 3. CMakeCache for a repo-local build (whisper.cpp/build/CMakeCache.txt).
    try:
        cache = bin_path.parent.parent / "CMakeCache.txt"  # build/bin/.. -> build/
        if cache.is_file():
            txt = cache.read_text(errors="ignore")
            if re.search(r"GGML_CUDA:BOOL=(ON|1|TRUE)", txt, re.I) and "CUDA" not in found:
                found.append("CUDA")
            if re.search(r"GGML_VULKAN:BOOL=(ON|1|TRUE)", txt, re.I) and "Vulkan" not in found:
                found.append("Vulkan")
    except Exception:
        pass

    if found:
        info["capable"] = True
        info["backend"] = "+".join(dict.fromkeys(found))
        info["detail"] = "GPU backend libraries detected"
    else:
        info["capable"] = False
        info["detail"] = "CPU-only build (no CUDA/Vulkan backend found)"
    return info


# --- Vulkan multi-GPU driver selection --------------------------------------
# A laptop/desktop with both an integrated GPU (Intel/AMD iGPU) and a discrete
# NVIDIA card exposes *two* Vulkan devices. whisper.cpp always uses gpu_device 0,
# and the Vulkan device-enumeration order is NOT stable — it was observed
# flipping between consecutive runs on the same boot — so whisper silently lands
# on the slow integrated GPU (encode ~30x slower, feels like CPU).
#
# Selecting by index (e.g. GGML_VK_VISIBLE_DEVICES) is therefore unreliable. We
# instead restrict the Vulkan *loader* to the discrete GPU's driver via
# VK_DRIVER_FILES / VK_ICD_FILENAMES, pointing them at the NVIDIA ICD manifest.
# That hides the iGPU entirely (whisper sees a single device) and is stable
# across reboots/driver updates because it keys off the driver, not an index.
_VK_DRIVER_FILES_ENV = "VK_DRIVER_FILES"     # Vulkan loader >= 1.3.207
_VK_ICD_FILENAMES_ENV = "VK_ICD_FILENAMES"   # older loaders (kept for compat)

# Standard Vulkan ICD manifest directories.
_VULKAN_ICD_DIRS = (
    "/usr/share/vulkan/icd.d",
    "/usr/local/share/vulkan/icd.d",
    "/etc/vulkan/icd.d",
)


def _list_vulkan_icd_files() -> list[Path]:
    """Vulkan ICD manifest files visible to the loader, in discovery order.

    Respects an existing VK_DRIVER_FILES/VK_ICD_FILENAMES override; otherwise
    scans the standard manifest directories plus the XDG data dirs.
    """
    for env in (_VK_DRIVER_FILES_ENV, _VK_ICD_FILENAMES_ENV):
        v = os.environ.get(env)
        if v:
            return [Path(p) for p in v.split(os.pathsep) if p]
    dirs = list(_VULKAN_ICD_DIRS)
    for part in os.environ.get("XDG_DATA_DIRS", "").split(os.pathsep):
        if part:
            dirs.append(str(Path(part) / "vulkan" / "icd.d"))
    files: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.glob("*.json")):
            if str(f) not in seen:
                seen.add(str(f))
                files.append(f)
    return files


def _icd_vendor(path: Path) -> str:
    """Classify an ICD manifest as 'nvidia' | 'amd' | 'intel' | 'other'."""
    blob = Path(path).name.lower()
    try:
        data = json.loads(Path(path).read_text())
        icd = data.get("ICD") if isinstance(data, dict) else None
        if isinstance(icd, dict):
            blob += " " + str(icd.get("library_path", "")).lower()
    except Exception:
        pass
    if "nvidia" in blob and "nouveau" not in blob:
        return "nvidia"
    if "radeon" in blob or "amdvlk" in blob or "amd_icd" in blob or "amd_pro" in blob:
        return "amd"
    if "intel" in blob or "anv" in blob:
        return "intel"
    return "other"


def _preferred_vendor(preference: str = "auto") -> str:
    """Map a ``whisper_gpu_device`` preference to a target ICD vendor."""
    pref = (preference or "auto").strip().lower()
    if "nvidia" in pref:
        return "nvidia"
    if "amd" in pref or "radeon" in pref:
        return "amd"
    if "intel" in pref:
        return "intel"
    return "nvidia"  # "auto" → prefer the discrete NVIDIA card


def find_gpu_icd(preference: str = "auto") -> tuple[Path | None, str]:
    """Return ``(icd_path, vendor)`` to restrict Vulkan to, or ``(None, "")``.

    Only intervenes when more than one GPU driver is installed (i.e. there's
    actually an iGPU to avoid). Stable across reboots because it keys off the
    driver manifest, not the unstable Vulkan device index.
    """
    gpu_icds = [(p, _icd_vendor(p)) for p in _list_vulkan_icd_files()]
    gpu_icds = [(p, v) for (p, v) in gpu_icds if v in ("nvidia", "amd", "intel")]
    if len(gpu_icds) < 2:
        return None, ""
    target = _preferred_vendor(preference)
    wants = [target, "amd"] if target == "nvidia" else [target]
    for want in wants:
        for p, v in gpu_icds:
            if v == want:
                return p, v
    return None, ""


def _parse_vulkan_devices_from_stderr(stderr: str) -> list[dict]:
    """Parse whisper.cpp's own ``ggml_vulkan: N = <name>`` list from stderr.

    This is the *authoritative* enumeration order ggml actually used for the run,
    so we prefer it over vulkaninfo once we've seen it.
    """
    devices: list[dict] = []
    for line in (stderr or "").splitlines():
        m = re.match(r"\s*ggml_vulkan:\s*(\d+)\s*=\s*(.+)", line)
        if m:
            name = m.group(2).split("|")[0].strip()
            devices.append({"index": int(m.group(1)), "name": name,
                            "type": "", "vendor_id": ""})
    return devices


def _parse_used_vulkan_device(stderr: str) -> tuple[int | None, str | None]:
    """Return ``(index, name)`` of the Vulkan device whisper.cpp actually used."""
    s = stderr or ""
    m = re.search(r"using Vulkan(\d+) backend", s)
    if not m:
        return None, None
    idx = int(m.group(1))
    for d in _parse_vulkan_devices_from_stderr(s):
        if d["index"] == idx:
            return idx, d["name"]
    return idx, None


def is_hallucination(text: str, blocklist) -> bool:
    """True if ``text`` is entirely one blocklisted phrase (or repeats of one)."""
    if not text or not blocklist:
        return False
    norm = _normalize_for_match(text)
    if not norm:
        return False
    for phrase in blocklist:
        pnorm = _normalize_for_match(str(phrase))
        if not pnorm:
            continue
        if norm == pnorm:
            return True
        # Whisper sometimes repeats the same hallucination back-to-back.
        # Remove every occurrence of the phrase; if nothing meaningful is
        # left, the transcript was nothing but repeats of that phrase.
        remainder = norm.replace(pnorm, "")
        if not remainder.strip(_PUNCT_STRIP):
            return True
    return False


class WhisperTranscriber:
    def __init__(self, model_path, binary_path, delete_input=True, language: str | None = None,
                 filter_hallucinations: bool | None = None,
                 hallucination_blocklist: list[str] | None = None,
                 gpu_enabled: bool | None = None,
                 gpu_device: str | None = None):
        # --- Model path: try config, else auto-discover ---
        if model_path and Path(model_path).is_file():
            self.model_path = model_path
        else:
            # Try to use the default model in cache
            self.model_path = find_base_model()
            verbo(f"[transcriber] Falling back to cached model: {self.model_path}")

        # --- Binary path: try config, else auto-discover ---
        if binary_path and Path(binary_path).is_file() and os.access(binary_path, os.X_OK):
            self.binary_path = binary_path
        else:
            self.binary_path = find_whisper_cli()
            verbo(f"[transcriber] Falling back to auto-detected whisper-cli: {self.binary_path}")

        self.delete_input = delete_input
        from voxd.paths import OUTPUT_DIR
        self.output_dir = OUTPUT_DIR

        # Language (default en)
        lang = normalize_lang_code(language or "en")
        if not is_valid_lang(lang):
            verr(f"[transcriber] Invalid language '{language}', using 'en'")
            lang = "en"
        self.language = lang

        # Hallucination filtering + GPU toggle (lazily pull defaults from config)
        if (filter_hallucinations is None or hallucination_blocklist is None
                or gpu_enabled is None or gpu_device is None):
            try:
                from voxd.core.config import get_config
                cfg = get_config()
                if filter_hallucinations is None:
                    filter_hallucinations = cfg.data.get("hallucination_filter_enabled", True)
                if hallucination_blocklist is None:
                    hallucination_blocklist = cfg.data.get("hallucination_blocklist", [])
                if gpu_enabled is None:
                    gpu_enabled = cfg.data.get("whisper_gpu_enabled", True)
                if gpu_device is None:
                    gpu_device = cfg.data.get("whisper_gpu_device", "auto")
            except Exception:
                pass
        self.filter_hallucinations = bool(filter_hallucinations) if filter_hallucinations is not None else True
        self.hallucination_blocklist = hallucination_blocklist or []
        # Default to GPU-on; a CPU-only whisper-cli simply ignores the absence of -ng.
        self.gpu_enabled = bool(gpu_enabled) if gpu_enabled is not None else True
        # Which GPU to use when several are present ("auto" → discrete NVIDIA).
        self.gpu_device = (gpu_device or "auto")
        # Backend whisper.cpp actually used on the most recent transcribe() call.
        self.last_backend: str | None = None
        # Set if VK_DRIVER_FILES turns out to be ignored by the Vulkan loader, so
        # we stop trying to pin instead of failing every run.
        self._pin_unsupported = False

        # Warn if likely mismatch with an English-only model
        try:
            mp = str(self.model_path).lower()
            if self.language != "en" and mp.endswith(".en.bin"):
                verr("[transcriber] Non-English language selected but an English-only (*.en) model is configured.")
        except Exception:
            pass

    def transcribe(self, audio_path):
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"[transcriber] Audio file not found: {audio_file}")

        verbo(f"[transcriber] Using binary: {self.binary_path}")
        verbo(f"[transcriber] Using model: {self.model_path}")
        verbo("[transcriber] Starting transcription...")

        # Output prefix (no extension!)
        output_prefix = self.output_dir / audio_file.stem
        output_txt = output_prefix.with_suffix(".txt")

        cmd = [
            self.binary_path,
            "-m", self.model_path,
            "-f", str(audio_file),
            "-l", self.language,
            "-of", str(self.output_dir / audio_file.stem),
            "-otxt"  # <-- THIS is necessary to actually generate the .txt file
        ]

        # Force CPU when GPU is disabled (a GPU-built whisper-cli uses GPU by default).
        if not self.gpu_enabled:
            cmd.append("-ng")

        # When several GPU drivers are present, restrict the Vulkan loader to the
        # discrete GPU's driver (NVIDIA by default) so whisper.cpp can't fall back
        # to a slow integrated GPU. We pin the *driver* (VK_DRIVER_FILES), not a
        # device index, because the Vulkan index order is unstable on such systems.
        env = None
        pinned_icd: Path | None = None
        pinned_vendor = ""
        if self.gpu_enabled and not self._pin_unsupported:
            pinned_icd, pinned_vendor = find_gpu_icd(self.gpu_device)
            if pinned_icd is not None:
                env = os.environ.copy()
                env[_VK_DRIVER_FILES_ENV] = str(pinned_icd)
                env[_VK_ICD_FILENAMES_ENV] = str(pinned_icd)
                verbo(f"[transcriber] Multiple GPU drivers present; pinning Vulkan to "
                      f"{pinned_vendor.upper()} via {_VK_DRIVER_FILES_ENV}={pinned_icd.name}")

        verbo(f"[transcriber] Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode != 0:
            verr("[transcriber] whisper.cpp failed:")
            verr(f"stderr: {result.stderr}")
            verr(f"stdout: {result.stdout}")
            return None, None

        # whisper.cpp prints its backend/device selection and timing breakdown to
        # stderr. Surface them so it's possible to tell whether the GPU is actually
        # being used: a GPU-built binary silently falls back to CPU when no device
        # or driver is available, and a CPU-only binary ignores whisper_gpu_enabled
        # entirely (so transcription stays slow even though the toggle reads "on").
        backend = detect_compute_backend(result.stderr)
        used_idx, used_name = _parse_used_vulkan_device(result.stderr)
        if not self.gpu_enabled:
            self.last_backend = "CPU (-ng forced)"
        elif used_name and backend == "Vulkan":
            self.last_backend = f"{backend} ({used_name})"
        else:
            self.last_backend = backend

        # Verify the driver restriction actually took effect: whisper should now
        # see a single device of the intended vendor. If it still sees the iGPU,
        # the loader ignored VK_DRIVER_FILES — stop pinning instead of failing
        # every run (and surface it so it can be diagnosed).
        if self.gpu_enabled and pinned_icd is not None:
            seen = _parse_vulkan_devices_from_stderr(result.stderr)
            landed_ok = bool(used_name) and pinned_vendor in used_name.lower()
            if len(seen) > 1 or (used_name and not landed_ok):
                verbo(f"[transcriber] {_VK_DRIVER_FILES_ENV} had no effect (whisper used "
                      f"'{used_name or 'unknown'}', saw {len(seen)} device(s)); GPU "
                      "driver pinning unsupported here — disabling it for this session.")
                self._pin_unsupported = True

        verbo(f"[transcriber] whisper.cpp compute backend: {self.last_backend}")
        if self.gpu_enabled and self.last_backend == "CPU":
            verbo("[transcriber] GPU is enabled in config but whisper.cpp ran on CPU "
                  "(CPU-only build or no usable GPU device). Run 'voxd --diagnose'.")
        timings = _extract_whisper_timings(result.stderr)
        if timings:
            verbo(f"[transcriber] {timings}")
        # Full whisper.cpp diagnostics (device list, model load, per-stage timings).
        if result.stderr.strip():
            verbo("[transcriber] whisper.cpp stderr:\n" + result.stderr.rstrip())

        if not output_txt.exists():
            verr(f"[transcriber] Transcription failed: Expected output not found at {output_txt}")
            return None, None

        verbo(f"[transcriber] Transcription complete: {output_txt}")

        # Optionally delete the input audio
        if self.delete_input:
            try:
                audio_file.unlink()
                verbo(f"[transcriber] Deleted input file: {audio_file}")
            except Exception as e:
                verr(f"[transcriber] Could not delete input file: {e}")

        return self._parse_transcript(output_txt)

    def _parse_transcript(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"[transcriber] Failed to read transcript file: {e}")
            return None, None

        orig_tscript = "".join(lines)

        # Strip timestamps like [00:00.000] or (00:00)
        tscript = re.sub(r"\[\d{2}:\d{2}[\.:]\d{3}\]|\(\d{2}:\d{2}\)", "", orig_tscript)
        tscript = re.sub(r"\s+", " ", tscript).strip()

        if self.filter_hallucinations and tscript and \
           is_hallucination(tscript, self.hallucination_blocklist):
            verbo(f"[transcriber] Dropped hallucination: {tscript!r}")
            return "", orig_tscript

        return tscript, orig_tscript
