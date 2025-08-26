import wave
import numpy as np
from pathlib import Path
from voxt.utils.libw import verbo, verr


def dbfs_to_lin(db: float) -> float:
    """Convert dBFS to linear amplitude scale."""
    return 10.0 ** (db / 20.0)


def lin_to_dbfs(x: float) -> float:
    """Convert linear amplitude to dBFS. Returns -inf for non-positive values."""
    x = float(x)
    if x <= 0:
        return -np.inf
    return 20.0 * np.log10(x)


def _read_wav_float_mono(path: Path) -> tuple[np.ndarray, int, int]:
    """Read a 16-bit PCM WAV file and return mono float32 samples in [-1, 1].

    If the file has multiple channels, they are averaged to mono. Only PCM16 is
    supported to keep the implementation fast and simple.
    """
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        num_frames = wf.getnframes()
        frames = wf.readframes(num_frames)

    if sample_width != 2:
        raise ValueError(f"[audio] Only 16-bit PCM supported, got {8 * sample_width}-bit")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.float32)
    return samples, sample_rate, channels


def _write_wav_float_mono(path: Path, samples: np.ndarray, sample_rate: int, *, channels: int = 1) -> None:
    """Write mono float32 samples in [-1, 1] to a PCM16 WAV file."""
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)


def analyze_wav(path: str | Path) -> dict:
    """Compute simple stats useful for speech ASR preprocessing.

    Returns a dict with: fs, peak, peak_dbfs, rms, rms_dbfs, clip_frac, duration_s.
    """
    p = Path(path)
    samples, fs, _ = _read_wav_float_mono(p)
    if samples.size == 0:
        return {"fs": fs, "peak": 0.0, "peak_dbfs": -np.inf, "rms": 0.0, "rms_dbfs": -np.inf, "clip_frac": 0.0, "duration_s": 0.0}

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))
    clip_frac = float(np.mean(np.abs(samples) >= 0.999))
    stats = {
        "fs": fs,
        "peak": peak,
        "peak_dbfs": lin_to_dbfs(peak) if peak > 0 else -np.inf,
        "rms": rms,
        "rms_dbfs": lin_to_dbfs(rms) if rms > 0 else -np.inf,
        "clip_frac": clip_frac,
        "duration_s": samples.size / max(fs, 1),
    }
    verbo(
        f"[audio] peak={stats['peak_dbfs']:.1f} dBFS, rms={stats['rms_dbfs']:.1f} dBFS, clipped={clip_frac * 100:.2f}%"
    )
    return stats


def preprocess_wav(
    path: str | Path,
    *,
    peak_dbfs: float = -3.0,
    warn_clip_thresh: float = 0.01,
    inplace: bool = True,
) -> Path:
    """Attenuate audio that exceeds a target peak dBFS. Warn on clipping.

    - Attenuates only (no boosting) to avoid raising noise floor.
    - Emits a warning if clipped fraction exceeds warn_clip_thresh.
    - Returns the output path (same as input when inplace=True).
    """
    p = Path(path)
    samples, fs, _ = _read_wav_float_mono(p)
    if samples.size == 0:
        return p

    peak = float(np.max(np.abs(samples)))
    clip_frac = float(np.mean(np.abs(samples) >= 0.999))

    if clip_frac >= warn_clip_thresh:
        verr(
            f"[audio] Detected clipped audio ({clip_frac * 100:.1f}% samples). Consider lowering OS mic input gain."
        )

    target_lin = dbfs_to_lin(peak_dbfs)
    if peak > target_lin:
        scale = target_lin / max(peak, 1e-12)
        verbo(f"[audio] Attenuating by {20.0 * np.log10(scale):.1f} dB to cap peak at {peak_dbfs:.1f} dBFS")
        samples = (samples * scale).astype(np.float32)

    out_path = p if inplace else p.with_name(p.stem + "_norm").with_suffix(".wav")
    _write_wav_float_mono(out_path, samples, fs, channels=1)
    return out_path


