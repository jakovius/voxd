from whisp.core.config import AppConfig
import pytest

def test_aipp_defaults_are_there():
    cfg = AppConfig()
    assert isinstance(cfg.aipp_prompts, dict)
    assert "default" in cfg.aipp_prompts
    assert cfg.aipp_active_prompt in cfg.aipp_prompts

def test_aipp_prompt_padding_and_limit():
    cfg = AppConfig()
    # Too many prompts: should trim to 4
    cfg.data["aipp_prompts"] = {f"prompt{i}": "" for i in range(10)}
    cfg._validate_aipp_config()
    assert len(cfg.data["aipp_prompts"]) == 4
    # Fewer than 4 prompts: should pad
    cfg.data["aipp_prompts"] = {"default": "A"}
    cfg._validate_aipp_config()
    assert len(cfg.data["aipp_prompts"]) == 4

def test_aipp_active_prompt_validation():
    cfg = AppConfig()
    cfg.data["aipp_prompts"] = {"default": "A", "prompt1": "B", "prompt2": "C", "prompt3": "D"}
    cfg.data["aipp_active_prompt"] = "not_a_key"
    cfg._validate_aipp_config()
    assert cfg.data["aipp_active_prompt"] == "default"
