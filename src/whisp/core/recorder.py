import sounddevice as sd
import numpy as np
import wave
from datetime import datetime
from pathlib import Path
import tempfile
from whisp.utils.libw import verbo


class AudioRecorder:
    def __init__(self, samplerate=16000, channels=1):
        self.fs = samplerate
        self.channels = channels
        self.recording = []
        self.is_recording = False
        self.temp_dir = Path(tempfile.gettempdir()) / "whisp_temp"
        self.temp_dir.mkdir(exist_ok=True)
        self.last_temp_file = None

    def _timestamped_filename(self):
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{dt}_recording.wav"

    def start_recording(self):
        verbo("[recorder] Recording started...")
        self.is_recording = True
        self.recording = []

        def callback(indata, frames, time, status):
            if status:
                verbo(f"[recorder] Warning: {status}")
            self.recording.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=self.fs,
            channels=self.channels,
            callback=callback
        )
        self.stream.start()

    def stop_recording(self, preserve=False):
        if not self.is_recording:
            return None

        verbo("[recorder] Stopping recording...")
        self.stream.stop()
        self.stream.close()
        self.is_recording = False

        audio_data = np.concatenate(self.recording, axis=0)

        from whisp.paths import OUTPUT_DIR
        if preserve:
            rec_dir = OUTPUT_DIR / "recordings"
            rec_dir.mkdir(exist_ok=True)
            output_path = rec_dir / self._timestamped_filename()
        else:
            output_path = self.temp_dir / "last_recording.wav"

        self._save_wav(audio_data, output_path)
        self.last_temp_file = output_path

        verbo(f"[recorder] Saved to {output_path}")
        return output_path

    def _save_wav(self, data, path):
        with wave.open(str(path), 'w') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.fs)
            wf.writeframes((data * 32767).astype(np.int16).tobytes())
            
    def get_last_temp_file(self):
        return self.last_temp_file

    def cleanup_temp(self):
        if self.last_temp_file and self.last_temp_file.exists():
            verbo(f"[recorder] Cleaning up temporary file {self.last_temp_file}")
            self.last_temp_file.unlink()
