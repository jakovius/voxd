from pathlib import Path


def test_models_ensure_downloads(monkeypatch, tmp_path):
    import voxd.models as M

    def _fake_download(url, dest, progress_cb=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")

    monkeypatch.setattr(M, "_download", _fake_download)
    monkeypatch.setattr(M, "REPO_MODELS", tmp_path / "repo_models")

    path = M.ensure("tiny", no_check=True)
    assert path.exists()
    assert (tmp_path / "repo_models" / path.name).is_symlink()


def test_models_list_remove_set_active(monkeypatch, tmp_path):
    import voxd.models as M

    # Prepare a fake cached model file
    cache = (tmp_path / "data" / "models")
    cache.mkdir(parents=True, exist_ok=True)
    model_name = "ggml-tiny.en.bin"
    model_path = cache / model_name
    model_path.write_bytes(b"x")

    # Redirect module-level CACHE_DIR to our temp cache
    monkeypatch.setattr(M, "CACHE_DIR", cache)

    # list_local sees the file
    files = M.list_local()
    assert model_name in files

    # set_active writes to AppConfig; stub ensure to return our path
    monkeypatch.setattr(M, "ensure", lambda key, **_: model_path)

    # Stub AppConfig to a minimal in-memory object
    class DummyCfg:
        def __init__(self):
            self.data = {}
        def set(self, k, v):
            self.data[k] = v
        def save(self):
            pass

    monkeypatch.setattr(M, "AppConfig", DummyCfg)
    M.set_active("tiny.en")

    # remove deletes it
    M.remove("tiny.en")
    assert not model_path.exists()


