import threading
import queue
import tempfile
import wave
import time
import numpy as np
from pathlib import Path
from typing import Callable, Optional
from voxd.core.transcriber import WhisperTranscriber
from voxd.utils.libw import verbo, verr


class StreamingWhisperTranscriber:
    """Transcriber that processes audio in chunks and emits incremental text updates.

    Can emit text based on:
    - Time interval
    - Word count
    - Supports rewriting previous text when transcription changes
    """
    
    def __init__(
        self,
        model_path: str,
        binary_path: str,
        language: Optional[str] = None,
        chunk_seconds: float = 3.0,
        overlap_seconds: float = 0.5,
        emit_interval_seconds: float = 2.0,
        emit_word_count: int = 3,
        on_partial_text: Optional[Callable[[str], None]] = None,
        on_final_text: Optional[Callable[[str], None]] = None,
    ):
        self.transcriber = WhisperTranscriber(
            model_path=model_path,
            binary_path=binary_path,
            delete_input=True,
            language=language,
        )
        self.chunk_seconds = chunk_seconds
        self.overlap_seconds = overlap_seconds
        self.emit_interval_seconds = emit_interval_seconds
        self.emit_word_count = emit_word_count
        self.on_partial_text = on_partial_text
        self.on_final_text = on_final_text

        self.transcription_queue = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.audio_buffer: list[np.ndarray] = []
        self.samplerate = 16000
        self.channels = 1

        self.accumulated_text = ""
        self.last_emitted_text = ""
        self.last_emitted_time = 0.0
        self.last_emitted_word_count = 0
        self.chunk_timestamps: dict[str, float] = {}  # Track when chunks were transcribed
        self.chunk_texts: dict[str, str] = {}  # Track text for each chunk
        
        # Threshold constants for chunk queuing logic (calculated once in constructor)
        # 0.7 = 70% of chunk_seconds: minimum time between chunks to avoid too-frequent processing
        # 0.8 = 0.8 seconds: absolute minimum time between chunks (safety floor)
        self.min_time_between_chunks = max(0.8, self.chunk_seconds * 0.7)
        
        # 0.6 = 60% of chunk_frames: minimum buffer size to queue when time threshold is met
        #     This allows processing smaller chunks if enough time has passed, preventing delays
        self.min_frames_for_time_based_queue = 0.6
        
        # 0.5 = 50% of chunk_frames: absolute minimum chunk size to queue (safety floor)
        #     Prevents queuing tiny chunks that would waste processing time
        self.min_frames_to_queue = 0.5
        
        # Frame-based values (calculated in start() when samplerate is known)
        self.chunk_frames = 0
        self.overlap_frames = 0

    def start(self, samplerate: int = 16000, channels: int = 1):
        """Start the streaming transcriber."""
        self.samplerate = samplerate
        self.channels = channels
        self.is_running = True
        self.audio_buffer = []
        self.accumulated_text = ""
        self.last_emitted_text = ""
        self.last_emitted_time = time.time()
        self.last_emitted_word_count = 0
        self.chunk_timestamps.clear()
        self.chunk_texts.clear()
        
        # Calculate frame-based values now that samplerate is known
        self.chunk_frames = int(self.chunk_seconds * self.samplerate)
        self.overlap_frames = int(self.overlap_seconds * self.samplerate)

        self.worker_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self.worker_thread.start()
        verbo("[streaming_transcriber] Started")

    def stop(self):
        """Stop the streaming transcriber."""
        self.is_running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.transcription_queue.put(None)
            self.worker_thread.join(timeout=5.0)
        verbo("[streaming_transcriber] Stopped")

    def add_audio_chunk(self, audio_data: np.ndarray):
        """Add an audio chunk for transcription."""
        if not self.is_running:
            return

        self.audio_buffer.append(audio_data.copy())
        concatenated = np.concatenate(self.audio_buffer, axis=0) if len(self.audio_buffer) > 1 else self.audio_buffer[0]
        total_frames = len(concatenated)

        # Calculate time since last chunk was emitted.
        current_time = time.time()
        time_since_last = current_time - self.last_emitted_time if self.last_emitted_time > 0 else float('inf')

        # Determine if we should queue the chunk for transcription.
        should_queue = False
        if total_frames >= self.chunk_frames:
            should_queue = True
        elif time_since_last >= self.min_time_between_chunks and total_frames >= self.chunk_frames * self.min_frames_for_time_based_queue:
            should_queue = True

        if should_queue:
            chunk_to_transcribe = concatenated[-self.chunk_frames:] if total_frames >= self.chunk_frames else concatenated
            if len(chunk_to_transcribe) >= self.chunk_frames * self.min_frames_to_queue:
                chunk_seconds = len(chunk_to_transcribe) / self.samplerate
                self.transcription_queue.put(chunk_to_transcribe)
                verbo(f"[streaming_transcriber] Queued chunk for transcription ({len(chunk_to_transcribe)} frames, {chunk_seconds:.2f}s, queue size: {self.transcription_queue.qsize()})")

                if total_frames >= self.overlap_frames:
                    overlap_data = concatenated[-self.overlap_frames:]
                    self.audio_buffer = [overlap_data]
                elif total_frames >= self.chunk_frames:
                    self.audio_buffer = []
                else:
                    self.audio_buffer = [concatenated]

    def _transcription_worker(self):
        """Worker thread that processes transcription tasks."""
        while self.is_running:
            try:
                audio_chunk = self.transcription_queue.get(timeout=0.1)
                if audio_chunk is None:
                    break

                trans_start = time.time()
                chunk_seconds = len(audio_chunk) / self.samplerate
                verbo(f"[streaming_transcriber] Starting transcription of chunk ({len(audio_chunk)} frames, {chunk_seconds:.2f}s)")
                self._transcribe_chunk(audio_chunk)
                trans_duration = time.time() - trans_start
                verbo(f"[streaming_transcriber] Transcription completed in {trans_duration:.2f}s (chunk: {chunk_seconds:.2f}s)")
            except queue.Empty:
                continue
            except Exception as e:
                verr(f"[streaming_transcriber] Transcription worker error: {e}")
    
    def _transcribe_chunk(self, audio_chunk: np.ndarray):
        """Transcribe a single audio chunk."""
        try:
            chunk_start_time = time.time()
            chunk_seconds = len(audio_chunk) / self.samplerate
            chunk_id = f"{id(audio_chunk)}_{len(audio_chunk)}"
            
            temp_file = self._save_chunk_to_file(audio_chunk)
            if temp_file is None:
                return

            tscript, _ = self.transcriber.transcribe(temp_file)

            if tscript:
                tscript = self._filter_blank_audio(tscript)
                if tscript:
                    # Store chunk metadata
                    self.chunk_timestamps[chunk_id] = chunk_start_time
                    self.chunk_texts[chunk_id] = tscript
                    
                    timestamp_str = time.strftime("%H:%M:%S", time.localtime(chunk_start_time))
                    verbo(f"[streaming_transcriber] Got transcript at {timestamp_str} (chunk: {chunk_seconds:.2f}s): '{tscript[:50]}...'")
                    self._process_transcript(tscript, chunk_id, chunk_start_time)
        except Exception as e:
            verr(f"[streaming_transcriber] Failed to transcribe chunk: {e}")
    
    def _filter_blank_audio(self, text: str) -> str:
        """Filter out [BLANK_AUDIO] artifacts from transcription."""
        if not text:
            return text
        text = text.replace("[BLANK_AUDIO]", "")
        text = text.replace("BLANK_AUDIO", "")
        return text.strip()
    
    def _save_chunk_to_file(self, audio_data: np.ndarray) -> Optional[Path]:
        """Save audio chunk to temporary WAV file."""
        try:
            temp_dir = Path(tempfile.gettempdir()) / "voxd_temp"
            temp_dir.mkdir(exist_ok=True)
            
            temp_file = temp_dir / f"stream_chunk_{threading.get_ident()}_{id(audio_data)}.wav"
            
            with wave.open(str(temp_file), 'w') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.samplerate)
                x = np.clip(audio_data, -1.0, 1.0)
                wf.writeframes((x * 32767.0).astype(np.int16).tobytes())
            
            return temp_file
        except Exception as e:
            verr(f"[streaming_transcriber] Failed to save chunk: {e}")
            return None
    
    def _should_emit_text(self, new_text: str) -> bool:
        """Determine if text should be emitted based on time or word count."""
        current_time = time.time()
        time_since_last = current_time - self.last_emitted_time
        
        current_word_count = len(new_text.split())
        words_since_last = current_word_count - self.last_emitted_word_count
        
        should_emit = False
        if time_since_last >= self.emit_interval_seconds:
            should_emit = True
            verbo(f"[streaming_transcriber] Time-based emission trigger ({time_since_last:.2f}s >= {self.emit_interval_seconds}s)")
        elif words_since_last >= self.emit_word_count:
            should_emit = True
            verbo(f"[streaming_transcriber] Word-based emission trigger ({words_since_last} words >= {self.emit_word_count} words)")
        
        return should_emit
    
    def _process_transcript(self, new_text: str, chunk_id: str = "", chunk_time: float = 0.0):
        """Process new transcript and emit incremental updates.
        
        Args:
            new_text: The transcribed text
            chunk_id: Unique identifier for this chunk
            chunk_time: Timestamp when chunk transcription started
        """
        if not new_text or not new_text.strip():
            return
        
        new_text = new_text.strip()
        
        # Skip if this text is already fully contained in accumulated text
        if self.accumulated_text and new_text in self.accumulated_text:
            verbo(f"[streaming_transcriber] Skipping duplicate transcript (already in accumulated): '{new_text[:50]}...'")
            return
        
        verbo(f"[streaming_transcriber] Processing transcript: '{new_text[:50]}...', accumulated: '{self.accumulated_text[:50] if self.accumulated_text else ''}...'")
        
        if self.accumulated_text:
            accumulated_clean = self.accumulated_text.strip()
            
            if new_text == accumulated_clean:
                return
            
            if new_text.startswith(accumulated_clean):
                suffix = new_text[len(accumulated_clean):].strip()
                if suffix:
                    suffix = self._ensure_space_before(accumulated_clean, suffix)
                    self.accumulated_text = new_text
                    if self._should_emit_text(new_text):
                        verbo(f"[streaming_transcriber] Emitting suffix: '{suffix[:50]}...'")
                        if self.on_partial_text:
                            self.on_partial_text(suffix)
                        self._update_emission_state(new_text)
            else:
                words_accumulated = accumulated_clean.split()
                words_new = new_text.split()
                
                common_prefix_len = 0
                for i in range(min(len(words_accumulated), len(words_new))):
                    if words_accumulated[i] == words_new[i]:
                        common_prefix_len += 1
                    else:
                        break
                
                if common_prefix_len > 0 and common_prefix_len < len(words_accumulated):
                    # Transcription changed for part of the text - just continue with new text
                    # (We don't rewrite because it's complex and error-prone)
                    diff_text = " ".join(words_new[common_prefix_len:]) if common_prefix_len < len(words_new) else ""
                    if diff_text:
                        diff_text = self._ensure_space_before(" ".join(words_accumulated[:common_prefix_len]), diff_text)
                        self.accumulated_text = new_text
                        if self._should_emit_text(new_text):
                            verbo(f"[streaming_transcriber] Transcription changed (common prefix: {common_prefix_len} words), emitting diff: '{diff_text[:50]}...'")
                            if self.on_partial_text:
                                self.on_partial_text(diff_text)
                            self._update_emission_state(new_text)
                    else:
                        self.accumulated_text = new_text
                else:
                    diff_text = " ".join(words_new[common_prefix_len:]) if common_prefix_len < len(words_new) else new_text
                    if diff_text:
                        diff_text = self._ensure_space_before(accumulated_clean, diff_text)
                        self.accumulated_text = new_text
                        if self._should_emit_text(new_text):
                            verbo(f"[streaming_transcriber] Emitting diff: '{diff_text[:50]}...'")
                            if self.on_partial_text:
                                self.on_partial_text(diff_text)
                            self._update_emission_state(new_text)
                    else:
                        self.accumulated_text = new_text
        else:
            self.accumulated_text = new_text
            if self._should_emit_text(new_text):
                verbo(f"[streaming_transcriber] First transcript, emitting: '{new_text[:50]}...'")
                if self.on_partial_text:
                    self.on_partial_text(new_text)
                self._update_emission_state(new_text)
        
        # Clean up old chunk metadata periodically
        if chunk_time > 0:
            self._cleanup_old_chunks(chunk_time)
    
    
    def _ensure_space_before(self, previous: str, new: str) -> str:
        """Ensure proper spacing between previous and new text.
        
        Returns new text with leading space if needed, preserving the space in the string.
        """
        if not previous or not new:
            return new
        
        previous = previous.rstrip()
        new_original = new
        new = new.lstrip()
        
        if not previous or not new:
            return new_original  # Return original to preserve spacing
        
        prev_last = previous[-1] if previous else ""
        new_first = new[0] if new else ""
        
        needs_space = False
        if prev_last.isalnum() and new_first.isalnum():
            needs_space = True
        elif prev_last in ".,!?;:" and new_first.isalnum():
            needs_space = True
        elif prev_last == "." and new_first.isupper():
            needs_space = True
        
        if needs_space and not new_original.startswith(" "):
            return " " + new
        
        return new_original  # Return original to preserve any existing spacing
    
    def _cleanup_old_chunks(self, current_time: float):
        """Remove chunk metadata older than 2x chunk_seconds to prevent memory leaks."""
        cutoff_time = current_time - (self.chunk_seconds * 2)
        chunks_to_remove = [
            chunk_id for chunk_id, chunk_time in self.chunk_timestamps.items()
            if chunk_time < cutoff_time
        ]
        for chunk_id in chunks_to_remove:
            self.chunk_timestamps.pop(chunk_id, None)
            self.chunk_texts.pop(chunk_id, None)
    
    def _update_emission_state(self, text: str):
        """Update emission tracking state after emitting text."""
        self.last_emitted_text = text
        self.last_emitted_time = time.time()
        self.last_emitted_word_count = len(text.split())
    
    def get_accumulated_text(self) -> str:
        """Get the accumulated transcript so far."""
        return self.accumulated_text
    
    def finalize(self) -> str:
        """Finalize transcription and return complete text."""
        # Process any remaining chunks in the queue
        while not self.transcription_queue.empty():
            try:
                audio_chunk = self.transcription_queue.get_nowait()
                if audio_chunk is not None:
                    self._transcribe_chunk(audio_chunk)
            except queue.Empty:
                break
        
        # Process any remaining audio in buffer (only if it's substantial and not already processed)
        if self.audio_buffer:
            concatenated = np.concatenate(self.audio_buffer, axis=0)
            # Only process if buffer has meaningful audio (at least 0.5 seconds)
            min_final_frames = int(0.5 * self.samplerate)
            if len(concatenated) >= min_final_frames:
                verbo(f"[streaming_transcriber] Finalizing: processing remaining buffer ({len(concatenated)} frames, {len(concatenated)/self.samplerate:.2f}s)")
                self._transcribe_chunk(concatenated)
        
        final_text = self.accumulated_text
        if self.on_final_text and final_text:
            self.on_final_text(final_text)
        
        return final_text
