import requests
import json
import os
import time


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
    # Use the selected model for the current provider
    model = cfg.get_aipp_selected_model(provider) if hasattr(cfg, "get_aipp_selected_model") else cfg.data.get("aipp_model", "llama3.2:latest")

    for attempt in (1, 2):
        try:
            if provider == "local":
                return text
            elif provider == "ollama":
                return run_ollama_aipp(full_prompt, model)
            elif provider == "openai":
                return run_openai_aipp(full_prompt, model)
            elif provider == "anthropic":
                return run_anthropic_aipp(full_prompt, model)
            elif provider == "xai":
                return run_xai_aipp(full_prompt, model)
            else:
                print(f"[aipp] Unsupported provider: {provider}")
                return text
        except (requests.RequestException, ConnectionError) as e:
            if attempt == 2:
                print(f"[aipp] Network error after retry: {e}")
                return text
            print("[aipp] Network error, retrying once...")
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


def run_openai_aipp(prompt: str, model: str = "gpt-3.5-turbo") -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
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
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
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
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=20)
    if response.ok:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        raise requests.RequestException(f"XAI error {response.status_code}: {response.text}")


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
        print(f"[aipp] Error: {e}")
        return transcript
