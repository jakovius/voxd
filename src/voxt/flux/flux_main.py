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
from voxt.core.aipp import get_final_text
from voxt.utils.whisper_auto import ensure_whisper_cli
from voxt.utils.libw import verbo, verr


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voxt --flux", description="VOXT Flux: VAD-triggered continuous dictation")
    # Energy-only backend
    p.add_argument("--min-silence-ms", type=int, help="Pause length to cut segment")
    p.add_argument("--min-speech-ms", type=int, help="Minimum speech length to start a segment")
    p.add_argument("--pre-roll-ms", type=int, help="Audio to prepend before detected speech")
    p.add_argument("--save-audio", action="store_true", help="Preserve per-utterance WAVs")
    p.add_argument("--debug-vad", action="store_true", help="Print VAD debug info (probs/RMS, transitions)")
    p.add_argument("--no-resample", action="store_true", help="Do not resample to 16 kHz before transcription")
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


class EnergyVAD:
    def __init__(self, fs=16000, frame_ms=30, *,
                 start_margin_db=6.0, keep_margin_db=3.0,
                 abs_start_db=-33.0, abs_keep_db=-37.0,
                 init_noise_db=-60.0, noise_ema=0.05):
        self.fs = fs
        self.N = int(fs * frame_ms / 1000)
        self.start_margin_db = float(start_margin_db)
        self.keep_margin_db = float(keep_margin_db)
        self.abs_start_db = float(abs_start_db)
        self.abs_keep_db = float(abs_keep_db)
        self.noise_db = float(init_noise_db)
        self.noise_ema = float(noise_ema)
        self._speaking = False

    @staticmethod
    def _dbfs_of(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        return 20.0 * np.log10(rms)

    def is_speech(self, frame: np.ndarray) -> bool:
        lvl = self._dbfs_of(frame)
        # Update noise floor only when not speaking (to avoid tracking speech as noise)
        if not self._speaking:
            self.noise_db = (1.0 - self.noise_ema) * self.noise_db + self.noise_ema * lvl

        # Dynamic thresholds relative to noise floor, clamped by absolute bounds
        start_thr = max(self.noise_db + self.start_margin_db, self.abs_start_db)
        keep_thr  = max(self.noise_db + self.keep_margin_db,  self.abs_keep_db)
        if self._speaking:
            self._speaking = lvl >= keep_thr
        else:
            self._speaking = lvl >= start_thr
        return self._speaking


## Silero backend removed


class FluxRunner:
    def __init__(self, cfg: AppConfig, *, min_silence_ms: int | None, min_speech_ms: int | None, pre_roll_ms: int | None, save_audio: bool, debug_vad: bool = False, no_resample: bool = False):
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

        # Energy VAD
        start_margin = float(cfg.data.get("flux_energy_start_margin_db", 6.0))
        keep_margin  = float(cfg.data.get("flux_energy_keep_margin_db", 3.0))
        abs_start    = float(cfg.data.get("flux_energy_abs_start_db", -33.0))
        abs_keep     = float(cfg.data.get("flux_energy_abs_keep_db",  -37.0))
        self.vad = EnergyVAD(fs=self.fs, frame_ms=self.frame_ms,
                             start_margin_db=start_margin,
                             keep_margin_db=keep_margin,
                             abs_start_db=abs_start,
                             abs_keep_db=abs_keep)
        verbo("[flux] Using Energy VAD backend.")

        # Transcription + output
        self.transcriber = WhisperTranscriber(cfg.model_path, cfg.whisper_binary, delete_input=not self.save_audio)
        self.clipboard = ClipboardManager()
        self.typer = SimulatedTyper(delay=cfg.typing_delay, start_delay=cfg.typing_start_delay, cfg=cfg)

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

            speaking = bool(self.vad.is_speech(frame))
            if self.debug_vad:
                if not hasattr(self, "_dbg_cnt"):
                    self._dbg_cnt = 0
                self._dbg_cnt += 1
                if self._dbg_cnt % 10 == 0:
                    rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-9)
                    # Try to show probability if Silero backend
                    prob = None
                    try:
                        prob = self.vad.speech_prob(frame)
                    except Exception:
                        pass
                    if prob is not None:
                        print(f"[vad] {'S' if speaking else 's'} p={prob:.2f} rms={20*np.log10(max(rms,1e-12)):.1f} dBFS")
                    else:
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
        self.worker.start()
        try:
            with sd.InputStream(samplerate=self.fs, channels=1, dtype="float32", blocksize=self.N, callback=self._callback):
                try:
                    while True:
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    print("\n[flux] Stopping…")
        except Exception as e:
            verr(f"[flux] Failed to open audio input stream: {e}")
        self.stop.set()
        self.worker.join(timeout=1.0)


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
    )
    runner.run()


