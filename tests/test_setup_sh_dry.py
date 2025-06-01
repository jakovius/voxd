from pathlib import Path, PurePosixPath

def test_local_bin_priority(monkeypatch, tmp_path):
    fake_bin = tmp_path / "whisper.cpp" / "build" / "bin"
    fake_bin.mkdir(parents=True)
    (fake_bin / "whisper-cli").touch(mode=0o755)
    monkeypatch.setenv("WHISP_REPO_ROOT", str(tmp_path))
    from importlib import reload, import_module
    m = import_module("whisp_cpp_runtime")
    reload(m)
    assert m.binary_path() == fake_bin / "whisper-cli"
