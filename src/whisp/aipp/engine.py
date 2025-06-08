"""
AIPP – AI Post-Processing engine.
Each provider gets a tiny adapter so other parts of Whisp can call:
    processed = await get_aipp_client(cfg).process(text, prompt)
If anything fails we fall back to the original text.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Protocol, Dict, Callable

logger = logging.getLogger("whisp.aipp")

# --------------------------------------------------------------------- #
#   Provider “drivers”
# --------------------------------------------------------------------- #
class AIPPDriver(Protocol):
    async def process(self, text: str, prompt: str) -> str: ...

# fallback – does nothing
class NoopDriver:
    async def process(self, text: str, prompt: str) -> str:         # noqa: D401
        return text

# --- local Ollama ----------------------------------------------------- #
try:
    import httpx
except ImportError:  # httpx is an *optional* dependency
    httpx = None

class OllamaDriver:
    def __init__(self, cfg):
        if httpx is None:
            raise RuntimeError("httpx is not installed but required for Ollama")
        self.url = cfg.get("ollama_url", "http://localhost:11434/api/generate")
        self.model = cfg["aipp_model"]

    async def process(self, text: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": f"{prompt}\n\n{text}",
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(self.url, json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("response", text)

# --- OpenAI ----------------------------------------------------------- #
try:
    import openai
except ImportError:
    openai = None

# --- xAI (Grok) ------------------------------------------------------- #
try:
    # openai-python ≥ 1.0 exposes this helper.  For older versions
    # there is no `AsyncOpenAI`, so we fall back to None.
    from openai import AsyncOpenAI           # type: ignore
except Exception:
    AsyncOpenAI = None

# … existing drivers: OpenAIDriver, AnthropicDriver …

class XAIDriver:
    """
    Uses xAI's Grok models via their OpenAI-compatible REST endpoint.
    Docs: https://docs.x.ai/reference
    """
    def __init__(self, cfg):
        if AsyncOpenAI is None:
            raise RuntimeError(
                "openai>=1.0 is required for xAI; "
                "pip install --upgrade openai"
            )

        self.client = AsyncOpenAI(
            api_key=cfg.get("xai_api_key"),
            base_url="https://api.x.ai/v1",
            timeout=120,
        )
        self.model = cfg.get("xai_model", "grok-3")

    async def process(self, text: str, prompt: str) -> str:
        try:
            rsp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=4096,
            )
            return rsp.choices[0].message.content.strip()
        except Exception as exc:
            raise RuntimeError(f"xAI API call failed: {exc}") from exc


class OpenAIDriver:
    def __init__(self, cfg):
        if openai is None:
            raise RuntimeError("openai python pkg missing")
        openai.api_key = cfg.get("openai_api_key")  # env fallback anyway
        self.model = cfg["aipp_model"]

    async def process(self, text: str, prompt: str) -> str:
        rsp = await openai.ChatCompletion.acreate(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
        )
        return rsp.choices[0].message.content.strip()

# --- Anthropic (Claude) ---------------------------------------------- #
try:
    import anthropic
except ImportError:
    anthropic = None

class AnthropicDriver:
    def __init__(self, cfg):
        if anthropic is None:
            raise RuntimeError("anthropic pkg missing")
        self.client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key"))
        self.model = cfg["aipp_model"]

    async def process(self, text: str, prompt: str) -> str:
        rsp = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=prompt,
            messages=[{"role": "user", "content": text}],
        )
        return rsp.content[0].text.strip()

# --------------------------------------------------------------------- #
#   Factory
# --------------------------------------------------------------------- #
_PROVIDER_MAP: Dict[str, Callable[[dict], AIPPDriver]] = {
    "local": OllamaDriver,
    "openai": OpenAIDriver,
    "anthropic": AnthropicDriver,
    "xai": XAIDriver,
}

def get_aipp_client(cfg) -> AIPPDriver:
    if not cfg.get("aipp_enabled", False):
        return NoopDriver()                     # fast short-circuit

    provider = cfg.get("aipp_provider", "local")
    ctor = _PROVIDER_MAP.get(provider, NoopDriver)
    try:
        return ctor(cfg)
    except Exception as exc:
        logger.warning("AIPP provider init failed: %s – falling back to Noop", exc)
        return NoopDriver()
