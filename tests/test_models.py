from pathlib import Path


def test_tiny_ru_is_in_catalogue():
    import voxd.models as M

    assert "tiny-ru" in M.CATALOGUE
    size_mb, sha1, url = M.CATALOGUE["tiny-ru"]
    assert M._filename_from_url(url) == "ggml-tiny-ru.bin"
    assert len(sha1) == 40  # full SHA-1 digest


def test_filename_from_url_normalises():
    import voxd.models as M

    assert M._filename_from_url("https://x/ggml-tiny-ru.bin") == "ggml-tiny-ru.bin"
    # missing ggml- prefix is added so list_local() can find it
    assert M._filename_from_url("https://x/tiny-ru.bin?download=true") == "ggml-tiny-ru.bin"
    # non-.bin URLs are rejected
    try:
        M._filename_from_url("https://x/model.zip")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_install_url_downloads(monkeypatch, tmp_path):
    import voxd.models as M

    seen = {}

    def _fake_download(url, dest, progress_cb=None):
        seen["url"] = url
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"data")

    monkeypatch.setattr(M, "_download", _fake_download)
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path / "models")
    monkeypatch.setattr(M, "REPO_MODELS", tmp_path / "repo_models")

    url = "https://huggingface.co/x/resolve/main/ggml-tiny-ru.bin"
    path = M.install_url(url)
    assert path.name == "ggml-tiny-ru.bin"
    assert path.exists()
    assert seen["url"] == url
    assert (tmp_path / "repo_models" / path.name).is_symlink()


def test_set_active_accepts_local_path(monkeypatch, tmp_path):
    """A local .bin path is activated without requiring a catalogue entry."""
    import voxd.models as M

    model = tmp_path / "custom" / "ggml-tiny-ru.bin"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"x")

    # ensure() must NOT be called for a direct path — blow up if it is.
    def _boom(*a, **k):
        raise AssertionError("ensure() should not run for a local path")
    monkeypatch.setattr(M, "ensure", _boom)

    class DummyCfg:
        def __init__(self):
            self.data = {}
        def set(self, k, v):
            self.data[k] = v
        def save(self):
            pass

    dummy = DummyCfg()
    monkeypatch.setattr(M, "AppConfig", lambda: dummy)

    M.set_active(str(model))
    assert dummy.data["whisper_model_path"] == str(model.resolve())


def test_set_active_accepts_url(monkeypatch, tmp_path):
    import voxd.models as M

    downloaded = tmp_path / "models" / "ggml-tiny-ru.bin"
    monkeypatch.setattr(M, "install_url", lambda url, **_: downloaded)

    class DummyCfg:
        def __init__(self):
            self.data = {}
        def set(self, k, v):
            self.data[k] = v
        def save(self):
            pass

    dummy = DummyCfg()
    monkeypatch.setattr(M, "AppConfig", lambda: dummy)

    M.set_active("https://x/resolve/main/ggml-tiny-ru.bin")
    assert dummy.data["whisper_model_path"] == str(downloaded)


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


