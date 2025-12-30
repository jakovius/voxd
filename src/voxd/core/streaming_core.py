# pyright: reportMissingImports=false
from PyQt6.QtCore import QThread, pyqtSignal  # type: ignore
from voxd.core.streaming_transcriber import StreamingWhisperTranscriber
from voxd.core.recorder import AudioRecorder
from voxd.core.typer import SimulatedTyper
from voxd.core.aipp import get_final_text
from voxd.utils.libw import verbo, verr
from voxd.utils.whisper_auto import ensure_whisper_cli
from datetime import datetime
from time import time
from pathlib import Path
import numpy as np
import psutil


class StreamingCoreProcessThread(QThread):
    """Core process thread that orchestrates streaming recording, transcription, and typing."""
    
    finished = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    
    def __init__(self, cfg, logger):
        super().__init__()
        self.cfg = cfg
        self.logger = logger
        self.should_stop = False
        
        self.recorder: AudioRecorder | None = None
        self.transcriber: StreamingWhisperTranscriber | None = None
        self.typer: SimulatedTyper | None = None
        
        self.accumulated_text = ""
        self.last_typed_text = ""
        self.last_typed_length = 0
    
    def stop_recording(self):
        """Stop the streaming recording."""
        self.should_stop = True
    
    def run(self):
        """Main streaming process loop."""
        try:
            transcriber = StreamingWhisperTranscriber(
                model_path=self.cfg.whisper_model_path,
                binary_path=self.cfg.whisper_binary,
                language=getattr(self.cfg, "language", "en"),
                chunk_seconds=self.cfg.data.get("streaming_chunk_seconds", 3.0),
                overlap_seconds=self.cfg.data.get("streaming_overlap_seconds", 0.5),
                emit_interval_seconds=self.cfg.data.get("streaming_emit_interval_seconds", 2.0),
                emit_word_count=self.cfg.data.get("streaming_emit_word_count", 3),
                on_partial_text=self._on_partial_text,
                on_final_text=self._on_final_text,
            )
        except FileNotFoundError:
            if ensure_whisper_cli("gui") is None:
                self.status_changed.emit("VOXD")
                self.finished.emit("")
                return
            transcriber = StreamingWhisperTranscriber(
                model_path=self.cfg.whisper_model_path,
                binary_path=self.cfg.whisper_binary,
                language=getattr(self.cfg, "language", "en"),
                chunk_seconds=self.cfg.data.get("streaming_chunk_seconds", 3.0),
                overlap_seconds=self.cfg.data.get("streaming_overlap_seconds", 0.5),
                emit_interval_seconds=self.cfg.data.get("streaming_emit_interval_seconds", 2.0),
                emit_word_count=self.cfg.data.get("streaming_emit_word_count", 3),
                on_partial_text=self._on_partial_text,
                on_final_text=self._on_final_text,
            )
        
        self.transcriber = transcriber
        self.typer = SimulatedTyper(
            delay=self.cfg.data.get("streaming_typing_delay", 0.01),
            start_delay=self.cfg.typing_start_delay,
            cfg=self.cfg
        )
        
        recorder = AudioRecorder()
        self.recorder = recorder
        
        rec_start_dt = datetime.now()
        chunk_seconds = self.cfg.data.get("streaming_chunk_seconds", 3.0)
        
        self.status_changed.emit("Recording")
        
        def on_audio_chunk(audio_data: np.ndarray):
            """Callback for audio chunks from recorder."""
            if not self.should_stop:
                verbo(f"[streaming_core] Received audio chunk: {len(audio_data)} frames, {len(audio_data) / recorder.fs:.2f}s")
                transcriber.add_audio_chunk(audio_data)
        
        recorder.start_streaming_recording(on_audio_chunk, chunk_seconds=chunk_seconds)
        transcriber.start(samplerate=recorder.fs, channels=recorder.channels)
        
        verbo("[streaming_core] Started streaming recording and transcription")
        while not self.should_stop:
            self.msleep(100)
        
        rec_end_dt = datetime.now()
        
        self.status_changed.emit("Transcribing")
        recorder.stop_recording(preserve=False)
        transcriber.stop()
        
        final_text = transcriber.finalize()
        
        if not final_text:
            self.finished.emit("")
            return
        
        trans_start_ts = time()
        trans_end_ts = time()
        
        aipp_start_ts = aipp_end_ts = None
        processed_text = get_final_text(final_text, self.cfg)
        if self.cfg.aipp_enabled and processed_text and processed_text != final_text:
            aipp_start_ts = time()
            aipp_end_ts = time()
        
        try:
            if self.cfg.aipp_enabled:
                self.logger.log_entry(f"[original] {final_text}")
                if processed_text and processed_text != final_text:
                    self.logger.log_entry(f"[aipp] {processed_text}")
            else:
                self.logger.log_entry(processed_text)
        except Exception:
            pass
        
        # In streaming mode, text is already typed incrementally during recording
        # Only type final text if AIPP changed it and there's a difference
        if self.cfg.typing and processed_text:
            # Check if AIPP modified the text
            if self.cfg.aipp_enabled and processed_text != final_text:
                # AIPP changed the text - type the corrected version
                # But only the difference to avoid retyping everything
                if processed_text.startswith(self.last_typed_text):
                    # Only type the new suffix
                    suffix = processed_text[len(self.last_typed_text):]
                    if suffix:
                        self.status_changed.emit("Typing")
                        try:
                            self.typer.type_incremental(self.last_typed_text, processed_text)
                            self.last_typed_text = processed_text
                            self.last_typed_length = len(processed_text)
                        except Exception as e:
                            print(f"[streaming_core] Final typing failed: {e}")
                else:
                    # Text changed significantly - type the full corrected version
                    self.status_changed.emit("Typing")
                    try:
                        self.typer.type(processed_text)
                    except Exception as e:
                        print(f"[streaming_core] Typing failed: {e}")
            # If AIPP didn't change text, it's already been typed incrementally - do nothing
            print()
        
        if self.cfg.perf_collect:
            from voxd.utils.performance import write_perf_entry
            
            perf_entry = {
                "date": rec_start_dt.strftime("%Y-%m-%d"),
                "rec_start_time": rec_start_dt.strftime("%H:%M:%S"),
                "rec_end_time": rec_end_dt.strftime("%H:%M:%S"),
                "rec_dur": (rec_end_dt - rec_start_dt).total_seconds(),
                "trans_start_time": datetime.fromtimestamp(trans_start_ts).strftime("%H:%M:%S"),
                "trans_end_time": datetime.fromtimestamp(trans_end_ts).strftime("%H:%M:%S"),
                "trans_dur": trans_end_ts - trans_start_ts,
                "trans_eff": (trans_end_ts - trans_start_ts) / max(len(final_text), 1),
                "transcript": final_text,
                "usr_trans_acc": None,
                "trans_model": Path(self.cfg.whisper_model_path).name,
                "aipp_start_time": datetime.fromtimestamp(aipp_start_ts).strftime("%H:%M:%S") if aipp_start_ts else None,
                "aipp_end_time": datetime.fromtimestamp(aipp_end_ts).strftime("%H:%M:%S") if aipp_end_ts else None,
                "aipp_dur": (aipp_end_ts - aipp_start_ts) if aipp_start_ts and aipp_end_ts else None,
                "ai_model": self.cfg.aipp_model if self.cfg.aipp_enabled else None,
                "ai_provider": self.cfg.aipp_provider if self.cfg.aipp_enabled else None,
                "ai_prompt": self.cfg.aipp_active_prompt if self.cfg.aipp_enabled else None,
                "ai_transcript": processed_text if self.cfg.aipp_enabled else None,
                "aipp_eff": ((aipp_end_ts - aipp_start_ts) / max(len(processed_text), 1)) if self.cfg.aipp_enabled and aipp_start_ts and aipp_end_ts and processed_text else None,
                "sys_mem": psutil.virtual_memory().total,
                "sys_cpu": psutil.cpu_freq().max if psutil.cpu_freq() else None,
                "total_dur": (trans_end_ts - trans_start_ts) + (rec_end_dt - rec_start_dt).total_seconds()
            }
            write_perf_entry(perf_entry)
        
        self.finished.emit(processed_text)
    
    def _on_partial_text(self, text: str):
        """Handle partial text updates from transcriber."""
        if not text or not text.strip():
            return
        
        verbo(f"[streaming_core] Partial text received: '{text[:50]}...'")
        
        # The transcriber already handles spacing, so just concatenate
        # Preserve any leading space that was intentionally added
        if self.accumulated_text:
            new_accumulated = self.accumulated_text + text
        else:
            new_accumulated = text
        
        if self.cfg.typing and self.typer:
            try:
                self.typer.type_incremental(self.last_typed_text, new_accumulated)
                self.last_typed_text = new_accumulated
                self.last_typed_length = len(new_accumulated)
                verbo(f"[streaming_core] Typed incremental text, total length: {len(new_accumulated)}")
            except Exception as e:
                verr(f"[streaming_core] Incremental typing failed: {e}")
        
        self.accumulated_text = new_accumulated
    
    def _on_final_text(self, text: str):
        """Handle final text from transcriber."""
        self.accumulated_text = text

