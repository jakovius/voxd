"""asr_engine: parakeet — parakeet-cli via WhisperTranscriber, paths, voxd-model."""
from pathlib import Path


def _files(tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00\x00")
    model = tmp_path / "ggml-parakeet-tdt-0.6b-v3-f16.bin"; model.write_bytes(b"x")
    binary = tmp_path / "parakeet-cli"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    return audio, model, binary


def _capture(monkeypatch, fake_whisper_run):
    calls = []

    def _run(cmd, *a, **kw):
        calls.append(list(cmd))
        return fake_whisper_run(cmd, *a, **kw)

    monkeypatch.setattr("voxd.core.transcriber.subprocess.run", _run)
    return calls


def test_parakeet_command_and_text(tmp_path, monkeypatch, fake_whisper_run):
    from voxd.core.transcriber import WhisperTranscriber
    audio, model, binary = _files(tmp_path)
    calls = _capture(monkeypatch, fake_whisper_run)

    # whisper paths are bogus on purpose: they must be ignored for parakeet
    t = WhisperTranscriber("/nope/ggml-base.bin", "/nope/whisper-cli", engine="parakeet",
                           parakeet_model_path=str(model), parakeet_binary=str(binary),
                           language="ru", gpu_enabled=True, vram_check=False, flash_attn=True)
    text, _ = t.transcribe(str(audio))

    assert text == "Hello world"
    cmd = calls[-1]
    assert cmd[0] == str(binary)
    assert cmd[cmd.index("-m") + 1] == str(model)
    assert "-otxt" in cmd and "-of" in cmd
    assert "-l" not in cmd   # parakeet auto-detects the language
    assert "-fa" not in cmd  # whisper-only flag
    assert "-ng" not in cmd


def test_parakeet_respects_gpu_disabled(tmp_path, monkeypatch, fake_whisper_run):
    from voxd.core.transcriber import WhisperTranscriber
    audio, model, binary = _files(tmp_path)
    calls = _capture(monkeypatch, fake_whisper_run)

    t = WhisperTranscriber(None, None, engine="parakeet", parakeet_model_path=str(model),
                           parakeet_binary=str(binary), gpu_enabled=False)
    t.transcribe(str(audio))
    assert "-ng" in calls[-1]
    assert t.last_backend == "CPU (-ng forced)"


def test_engine_comes_from_config(tmp_path, monkeypatch):
    import voxd.core.transcriber as T
    _, model, binary = _files(tmp_path)
    monkeypatch.setattr(T, "_config_data", lambda: {
        "asr_engine": "parakeet",
        "parakeet_model_path": str(model),
        "parakeet_binary": str(binary),
    })
    t = T.WhisperTranscriber("/nope/m.bin", "/nope/whisper-cli")
    assert t.engine == "parakeet"
    assert t.model_path == str(model)
    assert t.binary_path == str(binary)


def test_parakeet_autodetect_via_env(tmp_path, monkeypatch):
    import voxd.core.transcriber as T
    _, model, binary = _files(tmp_path)
    monkeypatch.setenv("VOXD_PARAKEET_BIN", str(binary))
    monkeypatch.setenv("VOXD_PARAKEET_MODEL_PATH", str(model))
    monkeypatch.setattr(T, "_config_data", lambda: {"asr_engine": "parakeet",
                                                    "parakeet_model_path": "",
                                                    "parakeet_binary": ""})
    t = T.WhisperTranscriber(None, None)
    assert Path(t.binary_path) == binary.resolve()
    assert Path(t.model_path) == model.resolve()


def test_find_parakeet_model_prefers_f16_in_data_dir(tmp_path, monkeypatch):
    import voxd.paths as P
    monkeypatch.delenv("VOXD_PARAKEET_MODEL_PATH", raising=False)
    models = P.DATA_DIR / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / "ggml-parakeet-tdt-0.6b-v3-q8_0.bin").write_bytes(b"x")
    (models / "ggml-parakeet-tdt-0.6b-v3-f16.bin").write_bytes(b"x")
    assert P.find_parakeet_model().endswith("-f16.bin")


def test_unknown_engine_falls_back_to_whisper():
    from voxd.core.transcriber import normalize_engine
    assert normalize_engine("Parakeet ") == "parakeet"
    assert normalize_engine("vosk") == "whisper"
    assert normalize_engine(None) == "whisper"


def test_models_catalogue_names():
    import voxd.models as M
    assert M._pretty_name("parakeet-tdt-0.6b-v3") == "ggml-parakeet-tdt-0.6b-v3-f16.bin"
    assert M._pretty_name("parakeet-tdt-0.6b-v3-q8_0") == "ggml-parakeet-tdt-0.6b-v3-q8_0.bin"
    assert M._pretty_name("tiny") == "ggml-tiny.bin"  # whisper names unchanged
    assert M._pretty_name("not-in-catalogue") == "ggml-not-in-catalogue.bin"


class _DummyCfg:
    def __init__(self):
        self.data = {}

    def set(self, k, v):
        self.data[k] = v

    def save(self):
        pass


def test_use_parakeet_switches_engine(tmp_path, monkeypatch):
    import voxd.models as M
    _, model, _ = _files(tmp_path)
    cfg = _DummyCfg()
    monkeypatch.setattr(M, "AppConfig", lambda: cfg)
    monkeypatch.setattr(M, "ensure", lambda key, **_: model)

    M.set_active("parakeet-tdt-0.6b-v3")
    assert cfg.data["asr_engine"] == "parakeet"
    assert cfg.data["parakeet_model_path"] == str(model)
    assert "whisper_model_path" not in cfg.data


def test_use_whisper_switches_back(tmp_path, monkeypatch):
    import voxd.models as M
    whisper_model = tmp_path / "ggml-tiny.bin"; whisper_model.write_bytes(b"x")
    cfg = _DummyCfg()
    cfg.data["asr_engine"] = "parakeet"
    monkeypatch.setattr(M, "AppConfig", lambda: cfg)
    M.set_active(str(whisper_model))
    assert cfg.data["asr_engine"] == "whisper"
    assert cfg.data["whisper_model_path"] == str(whisper_model.resolve())
