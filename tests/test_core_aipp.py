def test_get_final_text_disabled(monkeypatch):
    from voxd.core.aipp import get_final_text
    class Cfg:
        def __init__(self):
            self.data = {"aipp_enabled": False}
    cfg = Cfg()
    assert get_final_text("hello", cfg) == "hello"


def test_get_final_text_enabled_routes(monkeypatch):
    from voxd.core import aipp
    class Cfg:
        def __init__(self):
            self.data = {
                "aipp_enabled": True,
                "aipp_provider": "ollama",
                "aipp_active_prompt": "default",
                "aipp_prompts": {"default": "Rewrite:"},
            }
            self.get_aipp_selected_model = lambda prov=None: "llama3.2:latest"

    cfg = Cfg()
    monkeypatch.setattr(aipp, "run_ollama_aipp", lambda prompt, model: "OK")
    out = aipp.get_final_text("hello", cfg)
    assert out == "OK"

