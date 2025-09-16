from pathlib import Path


def test_paths_use_xdg_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    import importlib, sys
    if "voxd.paths" in sys.modules:
        importlib.reload(sys.modules["voxd.paths"])  # type: ignore[arg-type]
    else:
        import voxd.paths  # noqa: F401

    import voxd.paths as P
    assert str(P.CONFIG_DIR).startswith(str(tmp_path))
    assert str(P.DATA_DIR).startswith(str(tmp_path))

    # Ensure directories are auto-created
    assert P.OUTPUT_DIR.exists()
    assert P.RECORDINGS_DIR.exists()


