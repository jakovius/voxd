import subprocess
import os
from pathlib import Path
import re
from whisp.utils.libw import verbo
from whisp.paths import find_whisper_cli


class WhisperTranscriber:
    def __init__(self, model_path, binary_path, delete_input=True):
        self.model_path = model_path
        self.binary_path = binary_path or find_whisper_cli()
        self.delete_input = delete_input
        from whisp.paths import OUTPUT_DIR
        self.output_dir = OUTPUT_DIR

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
            "-of", str(self.output_dir / audio_file.stem),
            "-otxt"  # <-- THIS is necessary to actually generate the .txt file
        ]

        verbo(f"[transcriber] Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("[transcriber] whisper.cpp failed:")
            print(f"stderr: {result.stderr}")
            print(f"stdout: {result.stdout}")
            return None, None

        if not output_txt.exists():
            print(f"[transcriber] Transcription failed: Expected output not found at {output_txt}")
            return None, None

        verbo(f"[transcriber] Transcription complete: {output_txt}")

        # Optionally delete the input audio
        if self.delete_input:
            try:
                audio_file.unlink()
                verbo(f"[transcriber] Deleted input file: {audio_file}")
            except Exception as e:
                print(f"[transcriber] Could not delete input file: {e}")

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

        return tscript, orig_tscript
