"""
AIPP processing pipeline.

Usage:
    from whisp.aipp.pipeline import run_aipp

    out_text = await run_aipp(text, cfg)
"""

from .engine import get_driver  # the helper we wrote in engine.py

async def run_aipp(text: str, cfg) -> str:
    """
    Post-process *text* using the provider specified in cfg.
    Returns the transformed text.
    """
    if not cfg.get("aipp_enabled", False):
        return text  # short-circuit when AIPP is switched off

    provider_name = cfg.get("aipp_provider", "local")
    prompt_key = cfg.get("aipp_active_prompt", "default")
    prompt = cfg["aipp_prompts"].get(prompt_key, "")

    driver_cls = get_driver(provider_name)
    driver = driver_cls(cfg)

    return await driver.process(text, prompt)
