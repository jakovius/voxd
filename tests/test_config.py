
def test_aipp_provider_validation_resets_invalid():
    from voxt.core.config import AppConfig
    cfg = AppConfig()
    cfg.data["aipp_provider"] = "invalid"
    cfg._validate_aipp_config()
    assert cfg.data["aipp_provider"] in (
        "ollama", "openai", "anthropic", "xai", "llamacpp_server", "llamacpp_direct"
    )


def test_llamacpp_status_flags_do_not_crash():
    from voxt.core.config import AppConfig
    cfg = AppConfig()
    status = cfg.validate_llamacpp_setup()
    assert {
        "server_available",
        "cli_available",
        "default_model_available",
        "python_bindings_available",
    } <= set(status.keys())


