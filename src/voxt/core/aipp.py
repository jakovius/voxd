import requests
import json
import os
import time
from voxt.utils.libw import verbo, verr
from pathlib import Path


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
            elif provider == "llamacpp_server":
                return run_llamacpp_server_aipp(full_prompt, model)
            elif provider == "llamacpp_direct":
                return run_llamacpp_direct_aipp(full_prompt, model, cfg)
            elif provider == "openai":
                return run_openai_aipp(full_prompt, model)
            elif provider == "anthropic":
                return run_anthropic_aipp(full_prompt, model)
            elif provider == "xai":
                return run_xai_aipp(full_prompt, model)
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


def run_llamacpp_server_aipp(prompt: str, model: str = "gemma-3-270m") -> str:
    """Use llama.cpp server API (OpenAI-compatible)."""
    from voxt.core.config import get_config
    from voxt.core.llama_server_manager import ensure_server_running
    
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


def run_llamacpp_direct_aipp(prompt: str, model: str, cfg) -> str:
    """Use llama.cpp Python bindings directly."""
    try:
        from llama_cpp import Llama
        from voxt.paths import LLAMACPP_MODELS_DIR
        
        # Get model path
        model_path = Path(cfg.get_llamacpp_model_path(model))
        
        if not model_path.exists():
            raise FileNotFoundError(f"llama.cpp model not found: {model_path}")
        
        # Initialize or reuse cached model (memory optimization)
        cache_key = f"llamacpp_direct_{model}"
        if not hasattr(cfg, '_llamacpp_cache'):
            cfg._llamacpp_cache = {}
        
        if cache_key not in cfg._llamacpp_cache:
            cfg._llamacpp_cache[cache_key] = Llama(
                model_path=str(model_path),
                n_ctx=2048,       # Context window
                n_batch=512,      # Batch size
                n_threads=4,      # CPU threads
                verbose=False,
                chat_format="gemma"  # Use Gemma chat format
            )
        
        llm = cfg._llamacpp_cache[cache_key]
        output = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.7,
            top_p=0.9
        )
        return output['choices'][0]['message']['content'].strip()
        
    except ImportError:
        # In pipx environment, try to import from user/system locations
        import sys
        import site
        
        # Add user site-packages to path
        user_site = site.getusersitepackages()
        if user_site not in sys.path:
            sys.path.append(user_site)
            
        # Try importing again
        try:
            from llama_cpp import Llama
            from voxt.paths import LLAMACPP_MODELS_DIR
            
            # Get model path
            model_path = Path(cfg.get_llamacpp_model_path(model))
            
            if not model_path.exists():
                raise FileNotFoundError(f"llama.cpp model not found: {model_path}")
            
            # Initialize or reuse cached model (memory optimization)
            cache_key = f"llamacpp_direct_{model}"
            if not hasattr(cfg, '_llamacpp_cache'):
                cfg._llamacpp_cache = {}
            
            if cache_key not in cfg._llamacpp_cache:
                cfg._llamacpp_cache[cache_key] = Llama(
                    model_path=str(model_path),
                    n_ctx=2048,       # Context window
                    n_batch=512,      # Batch size
                    n_threads=4,      # CPU threads
                    verbose=False,
                    chat_format="gemma"  # Use Gemma chat format
                )
            
            llm = cfg._llamacpp_cache[cache_key]
            output = llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.7,
                top_p=0.9
            )
            return output['choices'][0]['message']['content'].strip()
            
        except ImportError:
            # Fallback to llamacpp_server if llama-cpp-python not available
            verr("[aipp] llama-cpp-python not available, falling back to llamacpp_server")
            return run_llamacpp_server_aipp(prompt, model)
    except Exception as e:
        verr(f"[aipp] llamacpp_direct failed: {e}, falling back to llamacpp_server")
        return run_llamacpp_server_aipp(prompt, model)


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
