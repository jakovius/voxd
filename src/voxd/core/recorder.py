import sounddevice as sd
import numpy as np
import wave
from datetime import datetime
from pathlib import Path
import tempfile
from voxd.utils.libw import verbo, verr


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
        if self.record_chunked:
            self._open_new_chunk()

        # Prefer configured device or PulseAudio on Linux
        try:
            from voxd.core.config import AppConfig
            cfg = AppConfig()
            dev_pref = cfg.data.get("audio_input_device") or ("pulse" if cfg.data.get("audio_prefer_pulse", True) else None)
        except Exception:
            dev_pref = "pulse"

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

        # Helper to open stream with optional device and samplerate
        def _open(device, fs):
            kw = {"samplerate": fs, "channels": self.channels, "callback": callback}
            if device:
                kw["device"] = device
            return sd.InputStream(**kw)

        # Try preferred sample rate on preferred device; then robust fallbacks
        tried_pulse = False
        try:
            self.stream = _open(dev_pref, self.fs)
            self.stream.start()
        except Exception as e:
            verr(f"[recorder] Opening stream at {self.fs} Hz failed ({e}); trying device default rate")
            # Determine device default samplerate
            try:
                indev = dev_pref if dev_pref else (sd.default.device[0] if sd.default.device else None)
            except Exception:
                indev = None
            try:
                info = sd.query_devices(indev, 'input') if indev is not None else sd.query_devices(kind='input')
                fallback_fs = int(info.get('default_samplerate') or 48000)
            except Exception:
                fallback_fs = 48000
            self.fs = fallback_fs
            self._chunk_target_frames = self.chunk_seconds * self.fs
            if self.record_chunked and self._chunk_wave is not None:
                try:
                    self._chunk_wave.close()
                except Exception:
                    pass
                self._open_new_chunk()
            # If not yet tried, attempt with pulse explicitly
            if dev_pref != "pulse":
                try:
                    self.stream = _open("pulse", self.fs)
                    self.stream.start()
                    tried_pulse = True
                    return
                except Exception:
                    tried_pulse = True
                    pass
            # Last resort: open without device hint
            self.stream = _open(None, self.fs)
            self.stream.start()

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

    def _save_wav(self, data, path):
        with wave.open(str(path), 'w') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.fs)
            x = np.clip(data, -1.0, 1.0)
            wf.writeframes((x * 32767.0).astype(np.int16).tobytes())

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
            with wave.open(str(output_path), 'w') as out_wf:
                out_wf.setnchannels(self.channels)
                out_wf.setsampwidth(2)
                out_wf.setframerate(self.fs)
                for p in self._chunk_paths:
                    with wave.open(str(p), 'r') as in_wf:
                        frames = in_wf.readframes(in_wf.getnframes())
                        out_wf.writeframes(frames)
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
