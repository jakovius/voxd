import sounddevice as sd
import numpy as np
import wave
from datetime import datetime
from pathlib import Path
import tempfile
from voxd.utils.libw import verbo, verr


# whisper.cpp's whisper-cli requires 16 kHz mono input and rejects anything
# else. Many capture devices (bare ALSA) can't open a 16 kHz stream, so we may
# record at the device's native rate and resample down to this before saving.
WHISPER_FS = 16000


class AudioRecorder:
    def __init__(self, samplerate=16000, channels=1, *, record_chunked: bool | None = None, chunk_seconds: int | None = None):
        from voxd.core.config import AppConfig
        cfg = AppConfig()
        self.fs = samplerate
        self.channels = channels
        self.recording = []
        self.is_recording = False
        self.temp_dir = Path(tempfile.gettempdir()) / "voxd_temp"
        self.temp_dir.mkdir(exist_ok=True)
        self.last_temp_file = None
        # Chunking configuration
        self.record_chunked = cfg.data.get("record_chunked", True) if record_chunked is None else record_chunked
        self.chunk_seconds = cfg.data.get("record_chunk_seconds", 300) if chunk_seconds is None else int(chunk_seconds)
        self._chunk_wave = None
        self._chunk_index = 0
        self._chunk_written_frames = 0
        self._chunk_target_frames = self.chunk_seconds * self.fs
        self._chunk_paths: list[Path] = []

    def _timestamped_filename(self):
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{dt}_recording.wav"

    def start_recording(self):
        verbo("[recorder] Recording started...")
        self.is_recording = True
        self.recording = []
        self._chunk_paths = []
        self._chunk_index = 0
        self._chunk_written_frames = 0

        # Resolve the input device (configured → pulse if present → default).
        try:
            from voxd.core.config import AppConfig
            cfg = AppConfig()
        except Exception:
            cfg = None
        device = self._resolve_input_device(cfg)

        def callback(indata, frames, time, status):
            if status:
                verbo(f"[recorder] Warning: {status}")
            if self.record_chunked:
                try:
                    x = np.clip(indata.copy(), -1.0, 1.0)
                    pcm = (x * 32767.0).astype(np.int16).tobytes()
                    self._chunk_wave.writeframes(pcm)
                    self._chunk_written_frames += frames
                    # Rotate chunk if needed
                    if self._chunk_written_frames >= self._chunk_target_frames:
                        self._chunk_wave.close()
                        self._chunk_wave = None
                        self._chunk_written_frames = 0
                        self._open_new_chunk()
                except Exception as e:
                    verr(f"[recorder] Chunk write failed: {e}")
            else:
                self.recording.append(indata.copy())

        # Open the stream at a sample rate the device actually supports. The
        # capture is resampled to 16 kHz on save (see _save_wav/_stitch_chunks),
        # so a non-16 kHz capture rate is fine and avoids hammering devices
        # (bare ALSA) that reject 16 kHz with a noisy paInvalidSampleRate.
        self.stream, self.fs = self._open_stream(device, callback)
        self._chunk_target_frames = self.chunk_seconds * self.fs
        if self.record_chunked:
            self._open_new_chunk()
        self.stream.start()

    def _resolve_input_device(self, cfg):
        """Pick the input device: configured value → a real 'pulse' device if
        preferred and present → system default (None). Avoids requesting a
        'pulse' device that doesn't exist (noisy 'No input device matching')."""
        if cfg is None:
            return None
        configured = cfg.data.get("audio_input_device")
        if configured:
            return configured
        if cfg.data.get("audio_prefer_pulse", True):
            try:
                for d in sd.query_devices():
                    if d.get("max_input_channels", 0) > 0 and "pulse" in str(d.get("name", "")).lower():
                        return "pulse"
            except Exception:
                pass
        return None

    def _candidate_rates(self, device):
        """Ordered sample rates to try for `device`.

        Sound servers (pulse/pipewire/jack) resample internally, so prefer
        16 kHz to skip an extra resample. Raw ALSA/hardware devices often
        reject 16 kHz, so try their native default rate first and resample to
        16 kHz on save."""
        default_sr = None
        try:
            info = sd.query_devices(device, 'input') if device is not None else sd.query_devices(kind='input')
            default_sr = int(info.get('default_samplerate') or 0) or None
        except Exception:
            pass
        server_like = isinstance(device, str) and any(
            k in device.lower() for k in ("pulse", "pipe", "jack", "default")
        )
        if server_like or default_sr in (None, WHISPER_FS):
            order = [WHISPER_FS, default_sr, 48000, 44100]
        else:
            order = [default_sr, WHISPER_FS, 48000, 44100]
        seen: set[int] = set()
        return [r for r in order if r and not (r in seen or seen.add(r))]

    def _describe_device(self, dev):
        """Human-readable label for a device handle (index/name/None)."""
        if dev is None:
            return "system default"
        try:
            info = sd.query_devices(dev, 'input')
            return f"{info.get('name', dev)!r}"
        except Exception:
            return repr(dev)

    def _open_stream(self, device, callback):
        """Open (but don't start) an InputStream. Returns (stream, samplerate).

        Tries the requested device, then the system default, then every other
        input-capable device, so a missing/renamed `audio_input_device` (common
        with raw-ALSA + PipeWire setups where enumeration shifts) degrades to a
        working mic instead of crashing. Raises a clean RuntimeError with an
        actionable message only when nothing can be opened."""
        # Build the device try-order: requested → default → all input devices.
        order: list = []
        if device is not None:
            order.append(device)
        order.append(None)
        try:
            for idx, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0 and idx not in order:
                    order.append(idx)
        except Exception:
            pass

        last_err = None
        for dev in order:
            for fs in self._candidate_rates(dev):
                try:
                    kw = {"samplerate": fs, "channels": self.channels, "callback": callback}
                    if dev is not None:
                        kw["device"] = dev
                    stream = sd.InputStream(**kw)
                    if device is not None and dev != device:
                        verr(f"[recorder] Requested input device {device!r} unavailable; "
                             f"falling back to {self._describe_device(dev)}.")
                    return stream, fs
                except Exception as e:
                    last_err = e
                    verbo(f"[recorder] open {self._describe_device(dev)} @ {fs} Hz failed: {e}")

        raise RuntimeError(
            "Could not open any audio input device. Check that a microphone is "
            "connected and not muted, run 'voxd --diagnose' to list devices, and "
            "set 'audio_input_device' in the config if the wrong one is picked. "
            f"(last error: {last_err})"
        )

    def stop_recording(self, preserve=False):
        if not self.is_recording:
            return None

        verbo("[recorder] Stopping recording...")
        self.stream.stop()
        self.stream.close()
        self.is_recording = False

        if self.record_chunked and self._chunk_wave is not None:
            try:
                self._chunk_wave.close()
            except Exception:
                pass
            self._chunk_wave = None

        audio_data = None if self.record_chunked else np.concatenate(self.recording, axis=0)

        from voxd.paths import RECORDINGS_DIR
        if preserve:
            rec_dir = RECORDINGS_DIR
            rec_dir.mkdir(exist_ok=True)
            output_path = rec_dir / self._timestamped_filename()
        else:
            output_path = self.temp_dir / "last_recording.wav"

        if self.record_chunked:
            self._stitch_chunks(output_path)
        else:
            self._save_wav(audio_data, output_path)
        self.last_temp_file = output_path

        verbo(f"[recorder] Saved to {output_path}")
        return output_path

    def _resample_i16(self, pcm: np.ndarray, src_fs: int, dst_fs: int) -> np.ndarray:
        """Linear-resample mono int16 PCM from src_fs to dst_fs.

        Mirrors the approach used in flux mode. Only used on the fallback path
        when the device couldn't open a 16 kHz stream; a no-op when rates match.
        """
        pcm = np.asarray(pcm).reshape(-1)
        if src_fs == dst_fs or pcm.size == 0:
            return pcm.astype(np.int16, copy=False)
        n_out = int(round(pcm.size * dst_fs / float(src_fs)))
        if n_out <= 0:
            return pcm[:0].astype(np.int16)
        x = np.linspace(0.0, 1.0, pcm.size, endpoint=False)
        xo = np.linspace(0.0, 1.0, n_out, endpoint=False)
        y = np.interp(xo, x, pcm.astype(np.float32))
        return np.clip(np.rint(y), -32768, 32767).astype(np.int16)

    def _save_wav(self, data, path):
        x = np.clip(data, -1.0, 1.0)
        pcm = (x * 32767.0).astype(np.int16)
        pcm = self._resample_i16(pcm, self.fs, WHISPER_FS)
        with wave.open(str(path), 'w') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(WHISPER_FS)
            wf.writeframes(pcm.tobytes())

    def _open_new_chunk(self):
        self._chunk_index += 1
        chunk_name = f"chunk_{self._chunk_index:04d}.wav"
        chunk_path = self.temp_dir / chunk_name
        self._chunk_paths.append(chunk_path)
        self._chunk_wave = wave.open(str(chunk_path), 'w')
        self._chunk_wave.setnchannels(self.channels)
        self._chunk_wave.setsampwidth(2)
        self._chunk_wave.setframerate(self.fs)
        verbo(f"[recorder] Opened new chunk: {chunk_path}")

    def _stitch_chunks(self, output_path: Path):
        if not self._chunk_paths:
            verr("[recorder] No chunks recorded; nothing to stitch.")
            return
        verbo(f"[recorder] Stitching {len(self._chunk_paths)} chunks → {output_path}")
        try:
            raw = bytearray()
            for p in self._chunk_paths:
                with wave.open(str(p), 'r') as in_wf:
                    raw += in_wf.readframes(in_wf.getnframes())
            pcm = np.frombuffer(bytes(raw), dtype=np.int16)
            pcm = self._resample_i16(pcm, self.fs, WHISPER_FS)
            with wave.open(str(output_path), 'w') as out_wf:
                out_wf.setnchannels(self.channels)
                out_wf.setsampwidth(2)
                out_wf.setframerate(WHISPER_FS)
                out_wf.writeframes(pcm.tobytes())
            # Cleanup chunks
            for p in self._chunk_paths:
                try:
                    p.unlink()
                except Exception:
                    pass
        except Exception as e:
            verr(f"[recorder] Failed to stitch chunks: {e}")
            raise
            
    def get_last_temp_file(self):
        return self.last_temp_file

    def cleanup_temp(self):
        if self.last_temp_file and self.last_temp_file.exists():
            verbo(f"[recorder] Cleaning up temporary file {self.last_temp_file}")
            self.last_temp_file.unlink()
