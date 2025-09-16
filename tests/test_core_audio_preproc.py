from pathlib import Path
import wave


def _write_pcm16_wav(path: Path, samples: bytes, channels=1, framerate=16000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(samples)


def test_dbfs_lin_roundtrip():
    from voxd.core.audio_preproc import dbfs_to_lin, lin_to_dbfs
    val = -6.0
    lin = dbfs_to_lin(val)
    back = lin_to_dbfs(lin)
    assert abs(back - val) < 1e-6


def test_analyze_and_preprocess_noop(tmp_path):
    from voxd.core.audio_preproc import analyze_wav, preprocess_wav
    # 100ms of silence PCM16
    samples = b"\x00\x00" * 1600
    wavp = tmp_path / "s.wav"
    _write_pcm16_wav(wavp, samples)

    stats = analyze_wav(wavp)
    assert stats["fs"] == 16000
    assert stats["duration_s"] == 0.1

    out = preprocess_wav(wavp, inplace=True)
    assert out == wavp


