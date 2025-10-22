from pathlib import Path


def _stub_run_factory(calls_store):
    def _run(cmd, capture_output=True, text=True):
        calls_store.append(cmd[:])
        # Create expected output file based on -of
        if "-of" in cmd:
            of_idx = cmd.index("-of")
            prefix = cmd[of_idx + 1]
            out_txt = f"{prefix}.txt"
            Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
            with open(out_txt, "w", encoding="utf-8") as f:
                f.write("[00:00.000] Hello world\n")
        class CP:
            returncode = 0
            stdout = ""
            stderr = ""
        return CP()
    return _run


def test_transcriber_injects_default_en(monkeypatch, tmp_path):
    from voxd.core.transcriber import WhisperTranscriber

    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    calls = []
    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _stub_run_factory(calls))

    t = WhisperTranscriber(str(model), str(binary), delete_input=True)
    text, _ = t.transcribe(str(audio))

    assert text == "Hello world"
    # Verify -l en was passed
    flat = " ".join(calls[-1])
    assert " -l en " in f" {flat} ", f"expected '-l en' in cmd, got: {flat}"


def test_transcriber_accepts_auto_language(monkeypatch, tmp_path):
    from voxd.core.transcriber import WhisperTranscriber

    audio = tmp_path / "b.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "m.bin"; model.write_bytes(b"x")
    binary = tmp_path / "whisper-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)

    calls = []
    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _stub_run_factory(calls))

    t = WhisperTranscriber(str(model), str(binary), delete_input=False, language="auto")
    text, _ = t.transcribe(str(audio))
    assert text == "Hello world"
    flat = " ".join(calls[-1])
    assert " -l auto " in f" {flat} ", f"expected '-l auto' in cmd, got: {flat}"


