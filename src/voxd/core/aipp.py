import requests
import json
import os
import sys
import time
from voxd.utils.libw import verbo, verr
from pathlib import Path
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
#   Proxy for the cloud providers (config key ``aipp_proxy``)
# ---------------------------------------------------------------------------
PROXY_SCHEMES = ("http", "https", "socks5", "socks5h", "socks4", "socks4a")

# where each cloud provider is reached (used for the connection test)
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "xai": "https://api.x.ai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
}

_proxy = ""   # normalized proxy URL for the request in progress (set by run_aipp)


def normalize_proxy(value) -> str:
    """Return a proxy URL usable by requests, or "" when none is configured.

    ``host:port`` is taken as an HTTP proxy. ``socks5://`` becomes ``socks5h://``
    (``socks4://`` → ``socks4a://``) so host names are resolved by the proxy and
    not by the local DNS. Raises ValueError for an unusable value.
    """
    value = str(value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in PROXY_SCHEMES:
        raise ValueError(f"unsupported proxy scheme '{scheme}' (use http, https, socks5 or socks4)")
    try:
        host, port = parts.hostname, parts.port
    except ValueError as e:
        raise ValueError(f"bad proxy address: {e}") from e
    if not host:
        raise ValueError("proxy address has no host")
    if scheme.startswith("socks") and port is None:
        raise ValueError("a SOCKS proxy needs a port, e.g. socks5://127.0.0.1:1080")
    scheme = {"socks5": "socks5h", "socks4": "socks4a"}.get(scheme, scheme)
    return f"{scheme}://{parts.netloc}"


def socks_supported() -> bool:
    try:
        import socks  # noqa: F401  (PySocks)
        return True
    except ImportError:
        return False


def _is_local(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")


def proxies_for(url: str, proxy: str) -> dict | None:
    """``proxies`` argument for requests: the proxy for remote hosts, none for local ones."""
    if not proxy or _is_local(url):
        return None
    return {"http": proxy, "https": proxy}


def _cloud_post(url: str, **kwargs):
    """requests.post through the configured proxy (if any)."""
    proxies = proxies_for(url, _proxy)
    if proxies:
        if _proxy.startswith("socks") and not socks_supported():
            raise RuntimeError("SOCKS proxy needs the PySocks package (pip install PySocks)")
        kwargs["proxies"] = proxies
    return requests.post(url, **kwargs)


def _short_error(e: Exception, timeout: float) -> str:
    """The human part of a requests/urllib3 error chain."""
    if isinstance(e, requests.Timeout):
        return f"no answer in {timeout:g} s"
    text = str(e)
    if "Caused by" in text:                      # urllib3 wraps the real reason
        text = text.split("Caused by")[-1]
        text = text.split(": ", 1)[-1] if ": " in text else text
    return text.strip(" ()'\"")[:160] or type(e).__name__


def check_connection(cfg, provider: str | None = None, timeout: float = 8.0) -> tuple[bool, str]:
    """Try to reach the provider (through the proxy, if set). Any HTTP answer counts."""
    provider = provider or cfg.data.get("aipp_provider", "")
    if provider == "openai_compatible":
        url = str(cfg.data.get("aipp_openai_compatible_base_url", "") or "").rstrip("/")
        if not url:
            return False, "Server address is not set."
        url += "/models"
    else:
        url = PROVIDER_URLS.get(provider, "")
    if not url:
        return False, f"{provider} does not use the proxy."
    try:
        proxy = normalize_proxy(cfg.data.get("aipp_proxy", ""))
    except ValueError as e:
        return False, f"Proxy: {e}"
    proxies = proxies_for(url, proxy)
    if proxies and proxy.startswith("socks") and not socks_supported():
        return False, "SOCKS proxy needs the PySocks package (pip install PySocks)."
    host = urlsplit(url).hostname
    via = f"through {urlsplit(proxy).scheme} proxy {urlsplit(proxy).hostname}" if proxies else "directly"
    start = time.time()
    try:
        requests.get(url, timeout=timeout, **({"proxies": proxies} if proxies else {}))
    except requests.RequestException as e:
        return False, f"Cannot reach {host} {via}: {_short_error(e, timeout)}"
    return True, f"Reached {host} {via} in {time.time() - start:.1f} s."


def run_aipp(text: str, cfg, prompt_key: str = None) -> str:
    """
    Run AIPP post-processing on the given text using the selected prompt.
    Retries once on network failure.
    """
    prompts = cfg.data.get("aipp_prompts", {})
    if prompt_key is None:
        prompt_key = cfg.data.get("aipp_active_prompt", "default")
    prompt = prompts.get(prompt_key, "")
    if not prompt:
        prompt = "Summarize this text:"
    full_prompt = f"{prompt}\n{text.strip()}"

    provider = cfg.data.get("aipp_provider", "local")
    global _proxy
    try:
        _proxy = normalize_proxy(cfg.data.get("aipp_proxy", ""))
    except ValueError as e:
        verr(f"[aipp] aipp_proxy ignored: {e}")
        _proxy = ""
    try:
        from voxd.core.api_keys import load_into_env
        load_into_env()          # keys saved from the settings window
    except Exception:
        pass
    # Use the selected model for the current provider
    model = cfg.get_aipp_selected_model(provider) if hasattr(cfg, "get_aipp_selected_model") else cfg.data.get("aipp_model", "llama3.2:latest")

    for attempt in (1, 2):
        try:
            if provider == "local":
                return text
            elif provider == "ollama":
                return run_ollama_aipp(full_prompt, model)
            elif provider == "llamacpp_server":
                return run_llamacpp_server_aipp(full_prompt, model)
            elif provider == "openai":
                return run_openai_aipp(full_prompt, model)
            elif provider == "openai_compatible":
                base_url = cfg.data.get("aipp_openai_compatible_base_url", "")
                api_key = cfg.data.get("aipp_openai_compatible_api_key", "")
                if not base_url or not api_key:
                    verr("[aipp] openai_compatible provider requires aipp_openai_compatible_base_url and aipp_openai_compatible_api_key")
                    return text
                return run_openai_aipp(full_prompt, model, base_url=base_url, api_key=api_key)
            elif provider == "openrouter":
                return run_openrouter_aipp(full_prompt, model)
            elif provider == "anthropic":
                return run_anthropic_aipp(full_prompt, model)
            elif provider == "xai":
                return run_xai_aipp(full_prompt, model)
            elif provider == "gigachat":
                return run_gigachat_aipp(full_prompt, model)
            else:
                verr(f"[aipp] Unsupported provider: {provider}")
                return text
        except (requests.RequestException, ConnectionError) as e:
            if attempt == 2:
                verr(f"[aipp] Network error after retry: {e}")
                return text
            verr("[aipp] Network error, retrying once...")
            time.sleep(0.5)


def run_ollama_aipp(prompt: str, model: str = "llama3.2:latest") -> str:
    url = "http://localhost:11434/api/generate"
    response = requests.post(url, json={
        "model": model,
        "prompt": prompt,
        "stream": False
    }, timeout=20)
    if response.ok:
        return response.json().get("response", "")
    else:
        raise requests.RequestException(f"Ollama error {response.status_code}: {response.text}")


def run_openai_aipp(prompt: str, model: str = "gpt-3.5-turbo", base_url: str = None, api_key: str = None) -> str:
    url = f"{base_url or 'https://api.openai.com/v1'}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key or os.getenv('OPENAI_API_KEY', '')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = _cloud_post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if response.ok:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise requests.RequestException(f"OpenAI error {response.status_code}: {response.text}")


def run_anthropic_aipp(prompt: str, model: str = "claude-3-opus-20240229") -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = _cloud_post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if response.ok:
        return response.json()["content"][0]["text"].strip()
    else:
        raise requests.RequestException(f"Anthropic error {response.status_code}: {response.text}")


def run_xai_aipp(prompt: str, model: str = "grok-3") -> str:
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('XAI_API_KEY', '')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = _cloud_post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if response.ok:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise requests.RequestException(f"XAI error {response.status_code}: {response.text}")


def run_openrouter_aipp(prompt: str, model: str = "openai/gpt-4o-mini") -> str:
    """OpenRouter (OpenAI-compatible API). Key from OPENROUTER_API_KEY.

    OpenRouter recommends the optional HTTP-Referer / X-Title headers so the
    request is attributed to the app on their dashboards; they are not required.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/deepbadger/voxd",
        "X-Title": "VOXD",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = _cloud_post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if response.ok:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise requests.RequestException(f"OpenRouter error {response.status_code}: {response.text}")


def run_llamacpp_server_aipp(prompt: str, model: str = "gemma-3-270m") -> str:
    """Use llama.cpp server API (OpenAI-compatible)."""
    from voxd.core.config import get_config
    from voxd.core.llama_server_manager import ensure_server_running
    
    cfg = get_config()
    url = cfg.data.get("llamacpp_server_url", "http://localhost:8080")
    timeout = cfg.data.get("llamacpp_server_timeout", 30)
    
    # Ensure server is running before making API calls
    server_path = cfg.data.get("llamacpp_server_path", "")
    model_path = cfg.get_llamacpp_model_path(model)
    
    if not ensure_server_running(server_path, model_path):
        raise RuntimeError("Failed to start llama-server")
    
    response = requests.post(f"{url}/v1/chat/completions", json={
        "model": model,  # Model name is mostly ignored by llama.cpp server
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 512,
        "temperature": 0.7
    }, timeout=timeout)
    
    if response.ok:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise requests.RequestException(f"llama.cpp server error {response.status_code}: {response.text}")


## llamacpp_direct support removed


_gigachat_clients: dict[tuple, object] = {}


def run_gigachat_aipp(prompt: str, model: str = "GigaChat-2-Max") -> str:
    """
    Sber GigaChat via langchain-gigachat. The GigaChat client owns its OAuth
    access-token lifecycle (auto-refresh on expiry), so we cache one client
    per (model, scope, verify_ssl) tuple to avoid re-issuing tokens every call.

    Requires `langchain-gigachat` (install via `pip install voxd[gigachat]`)
    and the GIGACHAT_CREDENTIALS env var (base64 client_id:secret).
    """
    creds = os.getenv("GIGACHAT_CREDENTIALS", "")
    if not creds:
        raise RuntimeError("GIGACHAT_CREDENTIALS not set in environment")

    from voxd.core.config import get_config
    cfg = get_config()
    scope = cfg.data.get("gigachat_scope", "GIGACHAT_API_PERS")
    verify_ssl = bool(cfg.data.get("gigachat_verify_ssl", True))

    key = (model, scope, verify_ssl, creds)
    client = _gigachat_clients.get(key)
    if client is None:
        # Distro-пакеты могут поставлять langchain-gigachat и его deps в
        # обособленный site-packages (например, /opt/voxd/aipp/gigachat),
        # чтобы pydantic/httpx-стек не попадали в системный Python.
        # Подтягиваем такой каталог в sys.path только перед импортом, а не
        # при загрузке модуля — это гарантирует, что общие зависимости
        # (requests и т.п.) уже импортированы из системы и не будут
        # затенены bundled-версией.
        _bundle_sp = os.environ.get(
            "VOXD_GIGACHAT_SITE_PACKAGES",
            "/opt/voxd/aipp/gigachat/site-packages",
        )
        if _bundle_sp and os.path.isdir(_bundle_sp) and _bundle_sp not in sys.path:
            sys.path.insert(0, _bundle_sp)
        try:
            from langchain_gigachat.chat_models import GigaChat
        except ImportError as e:
            raise RuntimeError(
                "langchain-gigachat is not installed. "
                "Install with: pip install voxd[gigachat]"
            ) from e
        kwargs = dict(credentials=creds, scope=scope, verify_ssl_certs=verify_ssl)
        if model:
            kwargs["model"] = model
        client = GigaChat(**kwargs)
        _gigachat_clients[key] = client

    result = client.invoke(prompt)
    content = getattr(result, "content", result)
    return content.strip() if isinstance(content, str) else str(content).strip()


def get_final_text(transcript: str, cfg) -> str:
    """
    Returns the final text after AIPP post-processing,
    or the raw transcript if AIPP is disabled.
    """
    if not cfg.data.get("aipp_enabled", False):
        return transcript
    prompt_key = cfg.data.get("aipp_active_prompt", "default")
    try:
        return run_aipp(transcript, cfg, prompt_key=prompt_key)
    except Exception as e:
        verr(f"[aipp] Error: {e}")
        return transcript
