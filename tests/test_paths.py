from pathlib import Path
from whisp_cpp_runtime import binary_path

def test_project_local_precedence(tmp_path, monkeypatch):
    fake = tmp_path / "whisper.cpp" / "build" / "bin"
    fake.mkdir(parents=True)
    (fake / "whisper-cli").touch(mode=0o755)

    # Tell runtime where the "repo root" is
    monkeypatch.setenv("WHISP_REPO_ROOT", str(tmp_path))

    from importlib import reload
    import whisp_cpp_runtime
    reload(whisp_cpp_runtime)           # pick up env var

    assert whisp_cpp_runtime.binary_path() == fake / "whisper-cli"