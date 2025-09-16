def test_recorder_start_stop_creates_file(tmp_path, monkeypatch):
    # Use stubbed sounddevice from conftest
    from voxd.core.recorder import AudioRecorder
    # Force non-chunked (simplify)
    rec = AudioRecorder(samplerate=16000, channels=1, record_chunked=False)
    rec.start_recording()
    # Simulate no incoming data; stop should still create an empty WAV
    out = rec.stop_recording(preserve=False)
    assert out.exists()

