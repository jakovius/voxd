from whisp.core.config import AppConfig
from whisp.core.aipp import get_final_text

def test_get_final_text_disabled(monkeypatch):
    cfg = AppConfig()
    cfg.data["aipp_enabled"] = False
    assert get_final_text("hello", cfg) == "hello"

def test_get_final_text_enabled(monkeypatch):
    cfg = AppConfig()
    cfg.data["aipp_enabled"] = True
    cfg.data["aipp_prompts"]["default"] = "Echo:"
    # Patch run_aipp to avoid network
    from whisp.core import aipp
    monkeypatch.setattr(aipp, "run_aipp", lambda text, cfg, prompt_key=None: f"MOCKED:{text}")
    assert get_final_text("hello", cfg) == "MOCKED:hello"