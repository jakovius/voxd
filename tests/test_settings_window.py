"""Unified settings window: Recognition page applies on change and follows the engine."""
import pytest


@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    import voxd.models as M
    cache = tmp_path / "cache"; cache.mkdir()
    monkeypatch.setattr(M, "CACHE_DIR", cache)
    monkeypatch.setattr(M, "REPO_MODELS", tmp_path / "repo")
    monkeypatch.delenv("VOXD_PARAKEET_MODEL_PATH", raising=False)
    whisper = cache / "ggml-tiny.bin"; whisper.write_bytes(b"x")
    parakeet = cache / "ggml-parakeet-tdt-0.6b-v3-q8_0.bin"; parakeet.write_bytes(b"x")

    from voxd.core.config import get_config
    cfg = get_config()
    cfg.data.update(asr_engine="whisper", whisper_model_path=str(whisper),
                    parakeet_model_path=str(parakeet), language="ru")
    saves = []
    monkeypatch.setattr(cfg, "save", lambda: saves.append(1))

    from voxd.gui.settings_window import SettingsWindow
    w = SettingsWindow(cfg)
    w.show()
    return w, cfg, saves, whisper, parakeet


def _shown(rows):
    return [not r.isHidden() for r in rows]


def test_opens_on_requested_page(win):
    w, *_ = win
    assert w.stack.currentIndex() == 0
    w.open_page("models")
    assert w.stack.currentIndex() == 1
    w.open_page("app")
    assert w.stack.currentIndex() == len(w.PAGES) - 1
    w.open_page("nonsense")
    assert w.stack.currentIndex() == 0


def test_loading_does_not_write_config(win):
    _, _, saves, *_ = win
    assert saves == []


def test_engine_switch_applies_and_hides_whisper_rows(win):
    w, cfg, saves, whisper, parakeet = win
    page = w.recognition
    assert all(_shown(page._whisper_rows)) and not any(_shown(page._parakeet_rows))
    assert page.model_label.text() == whisper.name

    page.engine.setCurrentIndex(page.engine.findData("parakeet"))
    assert cfg.data["asr_engine"] == "parakeet" and saves
    assert not any(_shown(page._whisper_rows)) and all(_shown(page._parakeet_rows))
    assert page.model_label.text() == parakeet.name


def test_missing_model_shows_warning(win, monkeypatch):
    w, cfg, _, _, parakeet = win
    import voxd.paths as P

    def _none():
        raise FileNotFoundError("no parakeet model")
    monkeypatch.setattr(P, "find_parakeet_model", _none)  # ignore the repo's own models dir
    parakeet.unlink()
    cfg.data["parakeet_model_path"] = ""
    page = w.recognition
    page.engine.setCurrentIndex(page.engine.findData("parakeet"))
    assert page.model_label.text() == "(none)"
    assert not page.model_warning.isHidden()


def test_recognition_controls_apply(win):
    w, cfg, saves, *_ = win
    page = w.recognition
    page.vram_check.setChecked(False)
    assert cfg.data["whisper_vram_check"] is False

    page.language.setCurrentIndex(page.language.findData("en"))
    page._on_language()
    assert cfg.data["language"] == "en"

    page.set_blocklist("  one phrase \n\n two\n")
    assert cfg.data["hallucination_blocklist"] == ["one phrase", "two"]
    assert page.blocklist_count.text() == "2 phrases"
    assert len(saves) == 3


def test_models_page_change_refreshes_recognition(win, monkeypatch):
    w, cfg, _, whisper, parakeet = win
    monkeypatch.setattr(cfg, "load", lambda: None)
    cfg.data["asr_engine"] = "parakeet"      # as if the Models page activated it
    w.models.changed.emit()
    assert w.recognition.engine.currentData() == "parakeet"
    assert w.recognition.model_label.text() == parakeet.name


def test_typing_and_audio_pages_apply(win):
    w, cfg, saves, *_ = win
    w.typing.typing.setChecked(not cfg.data.get("typing", False))
    w.audio.save_recordings.setChecked(True)
    assert cfg.data["save_recordings"] is True
    assert len(saves) == 2

    fired = []
    w.settingsChanged.connect(lambda: fired.append(1))
    w.audio.save_recordings.setChecked(False)
    assert cfg.data["save_recordings"] is False and fired


def test_every_page_key_is_a_known_config_key(win):
    """A typo in a bound key would silently create a junk config entry."""
    from voxd.core.config import DEFAULT_CONFIG
    w, cfg, *_ = win
    extra = set(cfg.data) - set(DEFAULT_CONFIG) - {"model_path"}
    assert not extra, extra


def test_aipp_model_selection_applies(win):
    w, cfg, saves, *_ = win
    cfg.data["aipp_models"] = {"ollama": ["a", "b"], "openai": ["x"]}
    cfg.data["aipp_selected_models"] = {"ollama": "a", "openai": "x"}
    cfg.data["aipp_provider"] = "ollama"
    page = w.aipp
    page.reload()
    assert [page.model.itemText(i) for i in range(page.model.count())] == ["a", "b"]
    page.model.setCurrentIndex(1)
    page._on_model()
    assert cfg.data["aipp_selected_models"]["ollama"] == "b"

    page.provider.setCurrentIndex(page.provider.findData("openai"))
    assert cfg.data["aipp_provider"] == "openai"
    assert page.model.currentText() == "x"


def test_autostart_goes_through_the_cli_handler(win, monkeypatch):
    import voxd.gui.settings_window as SW
    w, cfg, *_ = win
    calls = []

    def _fake(enabled):
        calls.append(enabled)
        cfg.data["autostart"] = enabled
        return True, ""
    monkeypatch.setattr(SW, "apply_autostart", _fake)
    monkeypatch.setattr(cfg, "load", lambda: None)
    w.app.autostart.setChecked(True)
    assert calls == [True]
    assert w.app.autostart_status.isHidden()

    monkeypatch.setattr(SW, "apply_autostart", lambda e: (False, "nope"))
    w.app.autostart.setChecked(False)
    assert w.app.autostart_status.text() == "nope" and not w.app.autostart_status.isHidden()
    assert w.app.autostart.isChecked()          # config unchanged → toggle snaps back


def test_prompt_editor_follows_slot_and_saves(win):
    from voxd.core.config import DEFAULT_CONFIG
    w, cfg, *_ = win
    page = w.aipp
    cfg.data["aipp_prompts"] = {"default": "d", "prompt1": "one", "prompt2": "", "prompt3": ""}
    cfg.data["aipp_active_prompt"] = "default"
    page.reload()
    assert page.prompt_text.toPlainText() == "d"

    page.prompt_text.setPlainText("d edited")
    page.prompt.setCurrentIndex(page.prompt.findData("prompt1"))   # switching saves the old slot
    assert cfg.data["aipp_prompts"]["default"] == "d edited"
    assert cfg.data["aipp_active_prompt"] == "prompt1"
    assert page.prompt_text.toPlainText() == "one"

    page.prompt_text.setPlainText("one edited")
    page.save_prompt()
    assert cfg.data["aipp_prompts"]["prompt1"] == "one edited"

    assert page.prompt_reset.isEnabled()
    page.reset_prompt()
    assert cfg.data["aipp_prompts"]["prompt1"] == DEFAULT_CONFIG["aipp_prompts"]["prompt1"]
    assert not page.prompt_reset.isEnabled()


def test_api_key_row_follows_provider_and_saves(win, monkeypatch):
    import os
    from voxd.core import api_keys
    w, cfg, *_ = win
    page = w.aipp
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(api_keys, "_original_env", {})

    page.provider.setCurrentIndex(page.provider.findData("ollama"))       # local → no key rows
    assert page.api_key_row.isHidden() and page.compat_url_row.isHidden()

    page.provider.setCurrentIndex(page.provider.findData("openrouter"))
    assert not page.api_key_row.isHidden()
    assert "OPENROUTER_API_KEY" in page.api_key_row.hint.text()
    assert "No key found" in page.api_key_row.hint.text()

    page.api_key.setText("sk-test")
    page._on_api_key()
    assert api_keys.read_keys() == {"OPENROUTER_API_KEY": "sk-test"}
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test"
    assert (api_keys.keys_path().stat().st_mode & 0o777) == 0o600
    assert "Saved in" in page.api_key_row.hint.text()

    page.api_key.setText("")
    page._on_api_key()
    assert api_keys.read_keys() == {} and "OPENROUTER_API_KEY" not in os.environ

    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    page._show_key()
    assert "environment variable" in page.api_key_row.hint.text()

    page.provider.setCurrentIndex(page.provider.findData("openai_compatible"))
    assert page.api_key_row.isHidden() and not page.compat_url_row.isHidden()
    page.compat_url.setText("https://host/v1/")
    page.compat_url.editingFinished.emit()
    assert cfg.data["aipp_openai_compatible_base_url"] == "https://host/v1"


def test_stored_key_overrides_and_restores_environment(monkeypatch):
    import os
    from voxd.core import api_keys
    monkeypatch.setattr(api_keys, "_original_env", {})
    monkeypatch.setenv("XAI_API_KEY", "shell")
    api_keys.save_key("XAI_API_KEY", "stored")
    assert os.environ["XAI_API_KEY"] == "stored" and api_keys.key_source("XAI_API_KEY") == "file"
    monkeypatch.setattr(api_keys, "_original_env", {})
    monkeypatch.setenv("XAI_API_KEY", "shell")
    api_keys.load_into_env()                       # what a fresh process does
    assert os.environ["XAI_API_KEY"] == "stored"
    api_keys.save_key("XAI_API_KEY", "")
    assert os.environ["XAI_API_KEY"] == "shell" and api_keys.key_source("XAI_API_KEY") == "environment"


def test_typed_model_id_joins_the_list(win):
    w, cfg, *_ = win
    cfg.data["aipp_models"] = {"openrouter": ["a"]}
    cfg.data["aipp_selected_models"] = {"openrouter": "a"}
    cfg.data["aipp_provider"] = "openrouter"
    page = w.aipp
    page.reload()
    page.model.setEditText("vendor/new-model")
    page._on_model()
    assert cfg.data["aipp_models"]["openrouter"] == ["a", "vendor/new-model"]
    assert cfg.data["aipp_selected_models"]["openrouter"] == "vendor/new-model"
    assert page.model.currentText() == "vendor/new-model"


def test_proxy_row_saves_validates_and_tests(win, monkeypatch):
    import voxd.core.aipp as A
    w, cfg, *_ = win
    page = w.aipp
    monkeypatch.setattr(A, "socks_supported", lambda: True)
    page.provider.setCurrentIndex(page.provider.findData("ollama"))
    assert page.proxy_row.isHidden()
    page.provider.setCurrentIndex(page.provider.findData("openrouter"))
    assert not page.proxy_row.isHidden()

    page.proxy.setText("socks5://127.0.0.1:1080")
    page._on_proxy()
    assert cfg.data["aipp_proxy"] == "socks5://127.0.0.1:1080"
    assert page.proxy_row.hint.property("warn") is False

    page.proxy.setText("ftp://x:1")
    page._on_proxy()
    assert page.proxy_row.hint.property("warn") is True

    monkeypatch.setattr(A, "check_connection", lambda cfg, provider: (True, "Reached host."))
    assert page.test_connection() is True
    assert page.proxy_row.hint.text() == "Reached host."
