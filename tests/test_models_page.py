"""Model inventory helpers (voxd.models) and the Qt models page."""
import pytest


def _setup_dirs(monkeypatch, tmp_path):
    import voxd.models as M
    cache = tmp_path / "cache"; cache.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    monkeypatch.setattr(M, "CACHE_DIR", cache)
    monkeypatch.setattr(M, "REPO_MODELS", repo)
    return M, cache, repo


def _model(d, name, size=10):
    p = d / name
    p.write_bytes(b"x" * size)
    return p


# ── voxd.models helpers ─────────────────────────────────────────────────────

def test_installed_models_cache_repo_and_dedupe(monkeypatch, tmp_path):
    M, cache, repo = _setup_dirs(monkeypatch, tmp_path)
    tiny = _model(cache, "ggml-tiny.bin", 30)
    (repo / "ggml-tiny.bin").symlink_to(tiny)                  # mirror → not a 2nd model
    _model(repo, "ggml-parakeet-tdt-0.6b-v3-f16.bin", 50)      # real file only in repo
    _model(repo, "for-tests-ggml-base.bin")                    # whisper.cpp fixture → ignored
    (repo / "ggml-gone.bin").symlink_to(cache / "missing.bin")  # dangling → ignored
    _model(cache, "ggml-custom-ru.bin", 20)

    models = M.installed_models()
    assert [m.name for m in models] == [
        "ggml-custom-ru.bin", "ggml-parakeet-tdt-0.6b-v3-f16.bin", "ggml-tiny.bin"]
    by = {m.name: m for m in models}
    assert by["ggml-tiny.bin"].key == "tiny" and by["ggml-tiny.bin"].engine == "whisper"
    assert by["ggml-parakeet-tdt-0.6b-v3-f16.bin"].key == "parakeet-tdt-0.6b-v3"
    assert by["ggml-parakeet-tdt-0.6b-v3-f16.bin"].engine == "parakeet"
    assert by["ggml-custom-ru.bin"].key is None
    assert by["ggml-tiny.bin"].size_bytes == 30


def test_remove_file_drops_repo_symlink(monkeypatch, tmp_path):
    M, cache, repo = _setup_dirs(monkeypatch, tmp_path)
    tiny = _model(cache, "ggml-tiny.bin")
    link = repo / "ggml-tiny.bin"; link.symlink_to(tiny)
    M.remove_file(tiny)
    assert not tiny.exists()
    assert not link.is_symlink()
    assert M.installed_models() == []


def test_active_model_path_follows_engine(tmp_path):
    import voxd.models as M
    w = _model(tmp_path, "ggml-tiny.bin"); p = _model(tmp_path, "ggml-parakeet-x.bin")
    cfg = {"asr_engine": "whisper", "whisper_model_path": str(w), "parakeet_model_path": str(p)}
    assert M.active_model_path(cfg) == w.resolve()
    cfg["asr_engine"] = "parakeet"
    assert M.active_model_path(cfg) == p.resolve()
    assert M.active_model_path({"asr_engine": "whisper", "whisper_model_path": ""}) is None


def test_replacement_prefers_same_engine_then_largest(tmp_path):
    import voxd.models as M
    mk = lambda name, eng, size: M.InstalledModel(tmp_path / name, None, eng, size)
    a, b, c = mk("a", "whisper", 10), mk("b", "whisper", 30), mk("c", "parakeet", 99)
    assert M.replacement_for(a, [a, b, c]) is b          # same engine wins over bigger
    assert M.replacement_for(c, [a, b, c]) is b          # no parakeet left → largest
    assert M.replacement_for(a, [a]) is None


def test_human_size():
    import voxd.models as M
    assert M.human_size(75 * 1024 * 1024) == "75 MB"
    assert M.human_size(1536 * 1024 * 1024) == "1.5 GB"


# ── Qt page ─────────────────────────────────────────────────────────────────

@pytest.fixture
def page_env(monkeypatch, tmp_path, qapp):
    from PyQt6.QtWidgets import QMessageBox
    M, cache, repo = _setup_dirs(monkeypatch, tmp_path)
    import voxd.core.model_manager as MM
    from voxd.core.config import get_config

    activated = []

    def _activate(path):
        activated.append(path)
        cfg = get_config()
        key = "parakeet_model_path" if M.is_parakeet_model(path) else "whisper_model_path"
        cfg.data[key] = str(path)
        cfg.data["asr_engine"] = "parakeet" if M.is_parakeet_model(path) else "whisper"

    monkeypatch.setattr(MM, "activate_model", _activate)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    return M, MM, cache, activated, get_config()


def test_page_lists_installed_and_catalogue(page_env):
    M, MM, cache, _, cfg = page_env
    tiny = _model(cache, "ggml-tiny.bin", 5)
    _model(cache, "ggml-parakeet-tdt-0.6b-v3-q8_0.bin", 7)
    cfg.data.update(asr_engine="whisper", whisper_model_path=str(tiny))

    page = MM.ModelsPage()
    assert page.installed.rowCount() == 2
    assert "2 models" in page.total_label.text()
    # installed models are not offered for download again
    keys = page._catalogue_keys()
    assert "tiny" not in keys and "parakeet-tdt-0.6b-v3-q8_0" not in keys
    assert page.catalogue.rowCount() == len(M.CATALOGUE) - 2

    # engine filter + search
    page.engine_filter.setCurrentIndex(page.engine_filter.findData("parakeet"))
    assert page._catalogue_keys() == ["parakeet-tdt-0.6b-v3", "parakeet-tdt-0.6b-v3-q4_k"]
    page.engine_filter.setCurrentIndex(0)
    page.search.setText("large turbo q5")
    assert page._catalogue_keys() == ["large-v3-turbo-q5_0"]


def test_page_delete_active_switches_to_successor(page_env):
    M, MM, cache, activated, cfg = page_env
    tiny = _model(cache, "ggml-tiny.bin", 5)
    base = _model(cache, "ggml-base.bin", 9)
    cfg.data.update(asr_engine="whisper", whisper_model_path=str(tiny))

    page = MM.ModelsPage()
    fired = []
    page.changed.connect(lambda: fired.append(1))
    page.delete(next(m for m in M.installed_models() if m.name == "ggml-tiny.bin"))

    assert not tiny.exists()
    assert activated == [base.resolve()]
    assert fired and page.installed.rowCount() == 1


def test_page_delete_inactive_keeps_active(page_env):
    M, MM, cache, activated, cfg = page_env
    tiny = _model(cache, "ggml-tiny.bin", 5)
    base = _model(cache, "ggml-base.bin", 9)
    cfg.data.update(asr_engine="whisper", whisper_model_path=str(tiny))

    page = MM.ModelsPage()
    page.delete(next(m for m in M.installed_models() if m.name == "ggml-base.bin"))
    assert not base.exists() and tiny.exists()
    assert activated == []


def test_page_delete_last_model_clears_config(page_env):
    M, MM, cache, activated, cfg = page_env
    tiny = _model(cache, "ggml-tiny.bin", 5)
    cfg.data.update(asr_engine="whisper", whisper_model_path=str(tiny))

    page = MM.ModelsPage()
    page.delete(M.installed_models()[0])
    assert activated == []
    assert cfg.data["whisper_model_path"] == ""
    assert page.installed.rowCount() == 0


def test_symlink_into_readonly_install_is_not_fatal(monkeypatch, tmp_path):
    """Packaged installs live in /opt/voxd: mirroring the model there must not fail the download."""
    M, cache, repo = _setup_dirs(monkeypatch, tmp_path)
    blocker = tmp_path / "opt"; blocker.write_text("")          # a file where a dir is expected
    monkeypatch.setattr(M, "REPO_MODELS", blocker / "whisper.cpp" / "models")
    M._symlink_into_repo(_model(cache, "ggml-tiny.bin"))        # must not raise
