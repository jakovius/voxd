import argparse
import queue
import threading
import time
from pathlib import Path
import numpy as np
import sounddevice as sd

from voxt.core.config import AppConfig
from voxt.core.transcriber import WhisperTranscriber
from voxt.core.typer import SimulatedTyper
from voxt.core.clipboard import ClipboardManager
from voxt.core.logger import SessionLogger
from voxt.core.aipp import get_final_text
from voxt.utils.ipc_server import start_ipc_server
from voxt.utils.whisper_auto import ensure_whisper_cli
from voxt.utils.libw import verbo, verr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voxt --flux", description="VOXT Flux: VAD-triggered continuous dictation")
    # Flux VAD options
    p.add_argument("--min-silence-ms", type=int, help="Pause length to cut segment")
    p.add_argument("--min-speech-ms", type=int, help="Minimum speech length to start a segment")
    p.add_argument("--pre-roll-ms", type=int, help="Audio to prepend before detected speech")
    p.add_argument("--save-audio", action="store_true", help="Preserve per-utterance WAVs")
    p.add_argument("--debug-vad", action="store_true", help="Print VAD debug info (probs/RMS, transitions)")
    p.add_argument("--no-resample", action="store_true", help="Do not resample to 16 kHz before transcription")
    # New monitor + calibration + noise suppression
    p.add_argument("--no-monitor", action="store_true", help="Disable live monitor window")
    p.add_argument("--monitor", action="store_true", help="Force-enable live monitor window")
    p.add_argument("--calib-sec", type=float, help="Calibration duration in seconds (baseline noise)")
    p.add_argument("--no-noise-suppress", action="store_true", help="Disable spectral noise subtraction on segments")
    return p


def _write_wav_mono16(path: Path, samples: np.ndarray, fs: int = 16000):
    import wave
    x = np.clip(samples.astype(np.float32), -1.0, 1.0)
    pcm16 = (x * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(fs)
        wf.writeframes(pcm16.tobytes())


class NoiseSuppressor:
    """
    Lightweight magnitude spectral subtraction using numpy only.
    Calibrates a noise magnitude spectrum and subtracts it from voiced segments.
    """
    def __init__(self, fs: int, frame_len: int, *, hop_ratio: float = 0.5, floor_db: float = -80.0, oversub: float = 1.0, ema: float = 0.02):
        self.fs = int(fs)
        self.N = int(frame_len)
        self.hop = max(1, int(self.N * hop_ratio))
        self.win = np.hanning(self.N).astype(np.float32)
        self.floor = float(10 ** (floor_db / 20.0))
        self.oversub = float(oversub)
        self.ema = float(ema)
        self.noise_mag = None

    def calibrate_with(self, frame: np.ndarray):
        try:
            mag = np.abs(np.fft.rfft(frame.astype(np.float32) * self.win))
            if self.noise_mag is None:
                self.noise_mag = mag
            else:
                self.noise_mag = (1.0 - self.ema) * self.noise_mag + self.ema * mag
        except Exception:
            pass

    def update_noise(self, frame: np.ndarray):
        self.calibrate_with(frame)

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        if self.noise_mag is None:
            return audio
        x = audio.astype(np.float32)
        if x.size < self.N:
            return x
        # STFT
        frames = []
        for start in range(0, x.size - self.N + 1, self.hop):
            seg = x[start:start + self.N] * self.win
            X = np.fft.rfft(seg)
            mag = np.abs(X)
            phase = np.angle(X)
            # spectral subtraction
            clean_mag = np.maximum(mag - self.oversub * self.noise_mag, self.floor)
            Y = clean_mag * np.exp(1j * phase)
            frames.append(np.fft.irfft(Y, n=self.N))
        # Overlap-add
        y = np.zeros((self.hop * (len(frames) - 1) + self.N,), dtype=np.float32)
        wsum = np.zeros_like(y)
        for i, f in enumerate(frames):
            start = i * self.hop
            y[start:start + self.N] += f
            wsum[start:start + self.N] += (self.win ** 2)
        wsum[wsum == 0] = 1.0
        y /= wsum
        # Pad tail if needed
        if y.size < x.size:
            out = np.zeros_like(x)
            out[:y.size] = y
            return out
        return y[:x.size]


class FluxVAD:
    def __init__(self, fs=16000, frame_ms=30, *,
                 start_margin_db=6.0, keep_margin_db=3.0,
                 abs_start_db=-33.0, abs_keep_db=-37.0,
                 init_noise_db=-60.0, noise_ema=0.05):
        self.fs = fs
        self.frame_ms = frame_ms
        self.N = int(fs * frame_ms / 1000)
        self.start_margin_db = float(start_margin_db)
        self.keep_margin_db = float(keep_margin_db)
        self.abs_start_db = float(abs_start_db)
        self.abs_keep_db = float(abs_keep_db)
        self.noise_db = float(init_noise_db)
        self.noise_ema = float(noise_ema)
        self._speaking = False
        # Calibration state
        self.calibrating = False
        self._calib_frames_target = 0
        self._calib_frames_done = 0
        # Simple spectral baseline (magnitude)
        self._noise_spec = None  # type: ignore[var-annotated]
        self._noise_spec_ema = 0.02

    @staticmethod
    def _dbfs_of(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        return 20.0 * np.log10(rms)

    def begin_calibration(self, duration_sec: float, *, noise_spec_ema: float | None = None):
        self.calibrating = True
        self._calib_frames_done = 0
        self._calib_frames_target = max(1, int((duration_sec * 1000) // self.frame_ms))
        if noise_spec_ema is not None:
            self._noise_spec_ema = float(noise_spec_ema)

    def feed_calibration(self, frame: np.ndarray):
        # Update scalar noise floor
        lvl = self._dbfs_of(frame)
        if self._calib_frames_done == 0:
            self.noise_db = lvl
        else:
            self.noise_db = (1.0 - self.noise_ema) * self.noise_db + self.noise_ema * lvl
        # Update spectral baseline
        try:
            spec = np.abs(np.fft.rfft(frame.astype(np.float32)))
            if self._noise_spec is None:
                self._noise_spec = spec
            else:
                self._noise_spec = (1.0 - self._noise_spec_ema) * self._noise_spec + self._noise_spec_ema * spec
        except Exception:
            pass
        self._calib_frames_done += 1
        if self._calib_frames_done >= self._calib_frames_target:
            self.calibrating = False

    def get_thresholds_db(self) -> tuple[float, float]:
        start_thr = max(self.noise_db + self.start_margin_db, self.abs_start_db)
        keep_thr  = max(self.noise_db + self.keep_margin_db,  self.abs_keep_db)
        return float(start_thr), float(keep_thr)

    def is_speech(self, frame: np.ndarray) -> bool:
        lvl = self._dbfs_of(frame)
        # During calibration, do not trigger speech; just update baselines
        if self.calibrating:
            self.feed_calibration(frame)
            self._speaking = False
            return False

        # Update noise floor only when not speaking (to avoid tracking speech as noise)
        if not self._speaking:
            self.noise_db = (1.0 - self.noise_ema) * self.noise_db + self.noise_ema * lvl
            # Update spectral baseline slowly while idle
            try:
                spec = np.abs(np.fft.rfft(frame.astype(np.float32)))
                if self._noise_spec is None:
                    self._noise_spec = spec
                else:
                    self._noise_spec = (1.0 - self._noise_spec_ema) * self._noise_spec + self._noise_spec_ema * spec
            except Exception:
                pass

        # Dynamic thresholds relative to noise floor, clamped by absolute bounds
        start_thr, keep_thr = self.get_thresholds_db()
        if self._speaking:
            self._speaking = lvl >= keep_thr
        else:
            self._speaking = lvl >= start_thr
        return self._speaking

    def metrics(self, frame: np.ndarray) -> dict:
        """Return current metrics for monitoring: dbfs, noise_db, start/keep thresholds, speaking flag."""
        lvl = self._dbfs_of(frame)
        start_thr, keep_thr = self.get_thresholds_db()
        return {
            "db": float(lvl),
            "noise_db": float(self.noise_db),
            "start_thr_db": float(start_thr),
            "keep_thr_db": float(keep_thr),
            "speaking": bool(self._speaking),
        }


## Silero backend removed


class FluxRunner:
    def __init__(self, cfg: AppConfig, *, min_silence_ms: int | None, min_speech_ms: int | None, pre_roll_ms: int | None, save_audio: bool, debug_vad: bool = False, no_resample: bool = False, monitor: bool | None = None, calib_sec: float | None = None, noise_suppress: bool | None = None):
        self.cfg = cfg
        # Configure sample rate and frame size (energy only)
        try:
            default_fs = int(sd.query_devices(kind='input')['default_samplerate'])
        except Exception:
            default_fs = 16000
        self.fs = default_fs if default_fs > 0 else 16000
        self.frame_ms = 30
        self.N = int(self.fs * self.frame_ms / 1000)
        self.debug_vad = bool(debug_vad)
        self.min_silence_ms = int(min_silence_ms if min_silence_ms is not None else cfg.data.get("flux_min_silence_ms", 500))
        self.min_speech_ms  = int(min_speech_ms  if min_speech_ms  is not None else cfg.data.get("flux_min_speech_ms", 200))
        self.pre_roll_ms     = int(pre_roll_ms  if  pre_roll_ms  is not None else cfg.data.get("flux_pre_roll_ms", 150))
        self.min_silence_frames = max(1, self.min_silence_ms // self.frame_ms)
        self.min_speech_frames  = max(1, self.min_speech_ms // self.frame_ms)
        self.pre_roll_frames    = max(0, self.pre_roll_ms // self.frame_ms)
        self.save_audio = bool(save_audio or self.cfg.data.get("save_recordings", False))
        # Smoothing
        self.post_roll_ms = int(cfg.data.get("flux_post_roll_ms", 150))
        self.post_roll_frames = max(0, self.post_roll_ms // self.frame_ms)
        self.min_segment_ms = int(cfg.data.get("flux_min_segment_ms", 600))
        self.cooldown_ms = int(cfg.data.get("flux_cooldown_ms", 250))
        self.min_rms_dbfs = float(cfg.data.get("flux_min_rms_dbfs", -45.0))
        self.no_resample = bool(no_resample)

        # Flux VAD
        start_margin = float(cfg.data.get("flux_energy_start_margin_db", 6.0))
        keep_margin  = float(cfg.data.get("flux_energy_keep_margin_db", 3.0))
        abs_start    = float(cfg.data.get("flux_energy_abs_start_db", -33.0))
        abs_keep     = float(cfg.data.get("flux_energy_abs_keep_db",  -37.0))
        self.vad = FluxVAD(fs=self.fs, frame_ms=self.frame_ms,
                             start_margin_db=start_margin,
                             keep_margin_db=keep_margin,
                             abs_start_db=abs_start,
                             abs_keep_db=abs_keep,
                             noise_ema=float(cfg.data.get("flux_noise_ema", 0.05)))
        verbo("[flux] Using Flux VAD backend.")

        # Noise suppressor
        self.noise_suppress_enabled = bool(cfg.data.get("flux_noise_subtract_enabled", True)) if noise_suppress is None else bool(noise_suppress)
        # Noise suppressor retained for post-segment enhancement; spectrum monitor removed from GUI
        self.ns = NoiseSuppressor(self.fs, self.N, floor_db=float(cfg.data.get("flux_monitor_spectrum_floor_db", -85.0)), ema=float(cfg.data.get("flux_noise_spec_ema", 0.02)))

        # Transcription + output
        self.transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not self.save_audio)
        self.clipboard = ClipboardManager()
        self.typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay, cfg=cfg)
        self.logger = SessionLogger(cfg.log_enabled, cfg.log_location)

        # Buffers/state
        from collections import deque
        self.pre_roll = deque(maxlen=self.pre_roll_frames)
        self.seg_frames: list[np.ndarray] = []
        self.in_speech = False
        self.speech_run = 0
        self.silence_run = 0
        self.cooldown_run = 0

        # IO
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self._consume_loop, daemon=True)
        # Monitoring shared state
        self.monitor_enabled = bool(self.cfg.data.get("flux_monitor_enabled", True)) if monitor is None else bool(monitor)
        self._mon_frames = []  # recent frames for GUI (legacy)
        self.mon_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=1024)  # preferred for GUI drain
        self._mon_frames_max = max(1, int((self.cfg.data.get("flux_monitor_energy_window_s", 10)) * 1000 // self.frame_ms))
        self._mon_lock = threading.Lock()
        # Calibration
        self.calib_sec = float(self.cfg.data.get("flux_calibration_sec", 5.0)) if calib_sec is None else float(calib_sec)
        self._calibrating = True if self.calib_sec > 0 else False
        # Paused state
        self._paused = False

    def _callback(self, indata, frames, t, status):
        if status:
            verbo(f"[flux] sd status: {status}")
        x = indata[:, 0] if indata.ndim > 1 else indata
        try:
            self.q.put_nowait(x.copy())
        except queue.Full:
            verr("[flux] Audio queue overflow, dropping frame.")

    def _consume_loop(self):
        while not self.stop.is_set():
            try:
                frame = self.q.get(timeout=0.1)
            except queue.Empty:
                continue

            # Calibration: feed baselines and disable speech
            if self._calibrating:
                self.vad.feed_calibration(frame)
                try:
                    self.ns.calibrate_with(frame)
                except Exception:
                    pass
                speaking = False
                if not self.vad.calibrating:
                    self._calibrating = False
            else:
                if self._paused:
                    # Keep pre-roll and monitor, but do not detect speech
                    self.pre_roll.append(frame)
                    # monitor
                    if self.monitor_enabled:
                        with self._mon_lock:
                            self._mon_frames.append(frame)
                            if len(self._mon_frames) > self._mon_frames_max:
                                self._mon_frames = self._mon_frames[-self._mon_frames_max:]
                        self._last_metrics = self.vad.metrics(frame)
                    continue
                # Keep spectral noise baseline slowly updated while idle
                try:
                    self.ns.update_noise(frame)
                except Exception:
                    pass
                speaking = bool(self.vad.is_speech(frame))
            if self.debug_vad:
                if not hasattr(self, "_dbg_cnt"):
                    self._dbg_cnt = 0
                self._dbg_cnt += 1
                if self._dbg_cnt % 10 == 0:
                    rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-9)
                    # Probability output not used for Flux VAD
                    print(f"[vad] {'S' if speaking else 's'} rms={20*np.log10(max(rms,1e-12)):.1f} dBFS")
            if speaking:
                self.speech_run += 1
                self.silence_run = 0
                if self.cooldown_run > 0:
                    self.cooldown_run -= 1
                if not self.in_speech:
                    if self.speech_run >= self.min_speech_frames:
                        self.in_speech = True
                        # seed segment with pre-roll
                        self.seg_frames = list(self.pre_roll)
                        self.seg_frames.append(frame)
                        if self.debug_vad:
                            print("[vad] >>> start speech")
                else:
                    self.seg_frames.append(frame)
            else:
                self.silence_run += 1
                self.speech_run = 0
                if self.in_speech:
                    # still collect a little silence during hangover
                    self.seg_frames.append(frame)
                    # Add extra post-roll to avoid cutting breathy endings
                    needed = self.min_silence_frames + self.post_roll_frames
                    if self.silence_run >= needed:
                        # finalize: drop the trailing silence hangover
                        drop = min(self.silence_run, len(self.seg_frames))
                        if drop > 0:
                            self.seg_frames = self.seg_frames[:-drop]
                        audio = np.concatenate(self.seg_frames, axis=0) if self.seg_frames else np.zeros(0, dtype=np.float32)
                        self.seg_frames = []
                        self.in_speech = False
                        self.silence_run = 0
                        self.cooldown_run = max(1, self.cooldown_ms // self.frame_ms)
                        if self.debug_vad:
                            dur = audio.size / max(self.fs, 1)
                            print(f"[vad] <<< end speech, dur={dur:.2f}s frames={audio.size}")
                        self._transcribe_async(audio)
                else:
                    # idle -> keep pre-roll fresh
                    self.pre_roll.append(frame)

            # For monitor: push to queue (preferred) and keep last metrics
            if self.monitor_enabled:
                try:
                    self.mon_q.put_nowait(frame)
                except queue.Full:
                    pass
                with self._mon_lock:
                    self._mon_frames.append(frame)
                    if len(self._mon_frames) > self._mon_frames_max:
                        self._mon_frames = self._mon_frames[-self._mon_frames_max:]
                self._last_metrics = self.vad.metrics(frame)

    def _transcribe_async(self, audio: np.ndarray):
        if audio.size < self.N * 3:  # skip too-short segments (< ~90ms)
            return
        t = threading.Thread(target=self._do_transcribe, args=(audio,), daemon=True)
        t.start()

    def _do_transcribe(self, audio: np.ndarray):
        import tempfile, datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        tmp_dir = Path(tempfile.gettempdir()) / "voxt_temp"
        tmp_dir.mkdir(exist_ok=True)
        wav_path = (tmp_dir / f"flux_{ts}.wav") if self.save_audio else (tmp_dir / "flux_last.wav")
        try:
            # Drop too-short or too-quiet segments
            seg_ms = int(1000 * audio.size / max(self.fs, 1))
            if seg_ms < self.min_segment_ms:
                if self.debug_vad:
                    print(f"[seg] drop short {seg_ms}ms < {self.min_segment_ms}ms")
                return
            seg_rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)) + 1e-12)
            seg_db = 20.0 * np.log10(seg_rms)
            if seg_db < self.min_rms_dbfs:
                if self.debug_vad:
                    print(f"[seg] drop low-level {seg_db:.1f} dBFS < {self.min_rms_dbfs:.1f} dBFS")
                return

            # Optional spectral noise suppression (post-seg, off detection path)
            if self.noise_suppress_enabled:
                try:
                    audio = self.ns.enhance(audio)
                except Exception:
                    pass

            # Resample to 16k for whisper.cpp stability, unless disabled
            if not self.no_resample and self.fs != 16000:
                # simple linear resample
                import math
                ratio = 16000 / float(self.fs)
                n_out = int(math.floor(audio.size * ratio))
                t = np.linspace(0, 1, audio.size, endpoint=False)
                to = np.linspace(0, 1, n_out,   endpoint=False)
                audio = np.interp(to, t, audio.astype(np.float32)).astype(np.float32)
                local_fs = 16000
            else:
                local_fs = self.fs
            _write_wav_mono16(wav_path, audio, fs=local_fs)
            tscript, _ = self.transcriber.transcribe(str(wav_path))
            if not tscript:
                return
            # AIPP disabled in flux mode; get_final_text is a safe pass-through
            final_text = get_final_text(tscript, self.cfg)
            self.clipboard.copy(final_text)
            if self.cfg.simulate_typing:
                self.typer.type(final_text)
            print(f"📝 ---> {final_text}")
            try:
                self.logger.log_entry(final_text)
            except Exception:
                pass
        except Exception as e:
            verr(f"[flux] Transcription failed: {e}")

    def run(self):
        # Disable AIPP in flux mode to keep it dictation-only
        self.cfg.data["aipp_enabled"] = False
        self.cfg.aipp_enabled = False

        try:
            dev = sd.default.device
            indev = dev[0] if isinstance(dev, (list, tuple)) else dev
            dev_info = sd.query_devices(indev, kind='input') if indev is not None else sd.query_devices(kind='input')
            print(f"Flux mode: continuous VAD dictation @ {self.fs} Hz. Ctrl+C to stop.")
            print(f"[audio] Input device: {dev_info.get('name','unknown')} | channels={dev_info.get('max_input_channels')} | default_sr={dev_info.get('default_samplerate')}")
        except Exception:
            print(f"Flux mode: continuous VAD dictation @ {self.fs} Hz. Ctrl+C to stop.")
        # Begin calibration window if configured
        if self._calibrating:
            self.vad.begin_calibration(self.calib_sec, noise_spec_ema=float(self.cfg.data.get("flux_noise_spec_ema", 0.02)))
        self.worker.start()
        try:
            with sd.InputStream(samplerate=self.fs, channels=1, dtype="float32", blocksize=self.N, callback=self._callback):
                # Optionally show monitor window
                if self.monitor_enabled:
                    try:
                        from voxt.flux.flux_gui import show_gui
                        # Start IPC hotkey server: toggle listening/pause in Flux mode
                        def on_ipc_trigger():
                            try:
                                self.set_paused(not self._paused)
                            except Exception:
                                pass
                        start_ipc_server(on_ipc_trigger)
                        app, _ = show_gui(self)
                        app.exec()
                    except Exception as e:
                        print(f"[flux] Flux GUI unavailable: {e}")
                        # fallback to headless loop
                        try:
                            while True:
                                time.sleep(0.2)
                        except KeyboardInterrupt:
                            print("\n[flux] Stopping…")
                else:
                    try:
                        while True:
                            time.sleep(0.2)
                    except KeyboardInterrupt:
                        print("\n[flux] Stopping…")
        except Exception as e:
            verr(f"[flux] Failed to open audio input stream: {e}")
        self.stop.set()
        self.worker.join(timeout=1.0)

    # ---- Control API for Flux GUI -------------------------------------
    def set_paused(self, paused: bool):
        self._paused = bool(paused)

    def request_recalibration(self, duration: float = 5.0):
        try:
            self.vad.begin_calibration(duration, noise_spec_ema=float(self.cfg.data.get("flux_noise_spec_ema", 0.02)))
            self._calibrating = True
        except Exception:
            self._calibrating = False

    def set_noise_drift_enabled(self, enabled: bool):
        try:
            self.vad.noise_ema = float(self.cfg.data.get("flux_noise_ema", 0.05)) if enabled else 0.0
            self.vad._noise_spec_ema = float(self.cfg.data.get("flux_noise_spec_ema", 0.02)) if enabled else 0.0
        except Exception:
            pass


def main():
    args = build_parser().parse_args()
    cfg = AppConfig()
    ensure_whisper_cli("cli")  # build or confirm whisper-cli
    runner = FluxRunner(
        cfg,
        min_silence_ms=args.min_silence_ms,
        min_speech_ms=args.min_speech_ms,
        pre_roll_ms=args.pre_roll_ms,
        save_audio=bool(args.save_audio),
        debug_vad=bool(args.debug_vad),
        no_resample=bool(args.no_resample),
        monitor=(False if args.no_monitor else (True if args.monitor else None)),
        calib_sec=args.calib_sec,
        noise_suppress=(False if args.no_noise_suppress else None),
    )
    runner.run()


