import requests
import json


def run_aipp(text: str, cfg) -> str:
    if not cfg.aipp_enabled:
        return text

    prompt = cfg.aipp_prompt_default or "Summarize this text:"
    full_prompt = f"{prompt}\n{text.strip()}"

    if cfg.aipp_provider == "local":
        return run_ollama_aipp(full_prompt, cfg.aipp_model)
    elif cfg.aipp_provider == "remote":
        return run_openai_aipp(full_prompt, cfg.aipp_model)
    else:
        print(f"[aipp] Unsupported provider: {cfg.aipp_provider}")
        return text


def run_ollama_aipp(prompt: str, model: str = "llama2") -> str:
    url = "http://localhost:11434/api/generate"
    try:
        response = requests.post(url, json={
            "model": model,
            "prompt": prompt,
            "stream": False
        })
        if response.ok:
            return response.json().get("response", "")
        else:
            print(f"[aipp] Ollama error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[aipp] Ollama request failed: {e}")
    return ""


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
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        if response.ok:
            return response.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"[aipp] OpenAI error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[aipp] OpenAI request failed: {e}")
    return ""
