from whisp.core.config import AppConfig

def test_aipp_defaults_are_there():
    cfg = AppConfig()
    assert isinstance(cfg.aipp_prompts, dict)
    assert "default" in cfg.aipp_prompts
    assert cfg.aipp_active_prompt in cfg.aipp_prompts
