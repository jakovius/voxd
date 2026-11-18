def test_recorder_start_stop_creates_file(tmp_path, monkeypatch):
    # Use stubbed sounddevice from conftest
    from voxd.core.recorder import AudioRecorder
    # Force non-chunked (simplify)
    rec = AudioRecorder(samplerate=16000, channels=1, record_chunked=False)
    rec.start_recording()
    # Simulate no incoming data; stop should still create an empty WAV
    out = rec.stop_recording(preserve=False)
    assert out.exists()


def _fake_cfg(**data):
    import types
    base = {"audio_prefer_pulse": True, "audio_input_device": ""}
    base.update(data)
    return types.SimpleNamespace(data=base)


def _patch_query_devices(monkeypatch, value):
    # Patch the sounddevice reference the recorder module actually uses;
    # the autouse stub swaps sys.modules["sounddevice"] per-test, but
    # recorder.sd is bound at import time.
    from voxd.core import recorder
    monkeypatch.setattr(recorder.sd, "query_devices",
                        lambda *a, **k: value, raising=False)


def test_resolve_input_device_prefers_existing_pulse(monkeypatch):
    from voxd.core.recorder import AudioRecorder
    _patch_query_devices(monkeypatch, [
        {"name": "HDA Intel Mic", "max_input_channels": 2},
        {"name": "pulse", "max_input_channels": 32},
    ])
    rec = AudioRecorder(record_chunked=False)
    assert rec._resolve_input_device(_fake_cfg()) == "pulse"


def test_resolve_input_device_falls_back_to_default_when_no_pulse(monkeypatch):
    from voxd.core.recorder import AudioRecorder
    _patch_query_devices(monkeypatch, [
        {"name": "HDA Intel Mic", "max_input_channels": 2},
    ])
    rec = AudioRecorder(record_chunked=False)
    assert rec._resolve_input_device(_fake_cfg()) is None


def test_resolve_input_device_respects_configured(monkeypatch):
    from voxd.core.recorder import AudioRecorder
    rec = AudioRecorder(record_chunked=False)
    assert rec._resolve_input_device(_fake_cfg(audio_input_device="USB Mic")) == "USB Mic"


def test_candidate_rates_raw_device_tries_native_rate_first(monkeypatch):
    from voxd.core.recorder import AudioRecorder, WHISPER_FS
    _patch_query_devices(monkeypatch, {"default_samplerate": 48000.0})
    rec = AudioRecorder(record_chunked=False)
    rates = rec._candidate_rates("HDA Intel Mic")
    assert rates[0] == 48000          # native rate first → no 16k paInvalidSampleRate
    assert WHISPER_FS in rates


def test_candidate_rates_server_device_tries_16k_first(monkeypatch):
    from voxd.core.recorder import AudioRecorder, WHISPER_FS
    _patch_query_devices(monkeypatch, {"default_samplerate": 48000.0})
    rec = AudioRecorder(record_chunked=False)
    assert rec._candidate_rates("pulse")[0] == WHISPER_FS


def test_open_stream_falls_back_when_configured_device_missing(monkeypatch):
    """A missing/renamed audio_input_device must degrade to a working device
    instead of crashing."""
    from voxd.core import recorder
    from voxd.core.recorder import AudioRecorder

    class FakeStream:
        def start(self):
            pass

    tried = []

    def fake_input_stream(**kw):
        tried.append(kw.get("device"))
        if kw.get("device") == "ghost":
            raise RuntimeError("No input device matching 'ghost'")
        return FakeStream()

    monkeypatch.setattr(recorder.sd, "InputStream", fake_input_stream, raising=False)
    monkeypatch.setattr(recorder.sd, "query_devices", lambda *a, **k: [], raising=False)

    rec = AudioRecorder(record_chunked=False)
    stream, fs = rec._open_stream("ghost", lambda *a: None)
    assert isinstance(stream, FakeStream)
    assert "ghost" in tried and None in tried   # requested device, then default


def test_open_stream_raises_clean_error_when_nothing_opens(monkeypatch):
    import pytest
    from voxd.core import recorder
    from voxd.core.recorder import AudioRecorder

    def always_fail(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(recorder.sd, "InputStream", always_fail, raising=False)
    monkeypatch.setattr(recorder.sd, "query_devices", lambda *a, **k: [], raising=False)

    rec = AudioRecorder(record_chunked=False)
    with pytest.raises(RuntimeError) as ei:
        rec._open_stream(None, lambda *a: None)
    # Actionable message, not a raw PortAudioError dump
    assert "voxd --diagnose" in str(ei.value)


def test_save_wav_resamples_fallback_rate_to_16k(tmp_path):
    """When capture fell back to a non-16 kHz rate, the saved WAV must be 16 kHz
    so whisper-cli (which only accepts 16 kHz) can read it."""
    import wave
    import numpy as np
    from voxd.core.recorder import AudioRecorder, WHISPER_FS

    rec = AudioRecorder(samplerate=16000, channels=1, record_chunked=False)
    rec.fs = 48000  # simulate the device-default-rate fallback

    # 1 s of audio at 48 kHz → expect ~16000 frames at 16 kHz output
    data = np.zeros((48000, 1), dtype=np.float32)
    out = tmp_path / "out.wav"
    rec._save_wav(data, out)

    with wave.open(str(out), "r") as wf:
        assert wf.getframerate() == WHISPER_FS
        assert abs(wf.getnframes() - 16000) <= 2

