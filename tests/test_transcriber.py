from pathlib import Path
import os


def test_transcriber_generates_text(tmp_path, fake_whisper_run):
    from voxt.core.transcriber import WhisperTranscriber

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary), delete_input=True)
    text, orig = t.transcribe(str(audio))

    assert text == "Hello world"
    assert "Hello world" in (orig or "")
    assert not audio.exists()


def test_transcriber_missing_input_raises(tmp_path):
    from voxt.core.transcriber import WhisperTranscriber

    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    t = WhisperTranscriber(str(model), str(binary))
    missing = tmp_path / "does_not_exist.wav"
    try:
        t.transcribe(str(missing))
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


