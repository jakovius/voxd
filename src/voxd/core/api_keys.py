"""API keys for the cloud AIPP providers.

A provider reads its key from an environment variable (OPENAI_API_KEY, …).
A desktop session rarely has the variables a shell exports in ~/.bashrc, so a
key can also be stored in ``~/.config/voxd/keys.env`` (mode 0600, plain
``NAME=value`` lines) – that is what the settings window writes.  A stored key
is put into ``os.environ`` and overrides a variable of the same name.
"""
from __future__ import annotations

import os
from pathlib import Path

# provider → environment variable holding its key
PROVIDER_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    "gigachat": "GIGACHAT_CREDENTIALS",
}

_original_env: dict[str, str | None] = {}   # what the process had before we overrode it


def keys_path() -> Path:
    from voxd.core import config
    return Path(config.CONFIG_DIR) / "keys.env"


def read_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    try:
        lines = keys_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return keys
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip("'\"")
        if name.strip() and value:
            keys[name.strip()] = value
    return keys


def _write_keys(keys: dict[str, str]) -> None:
    path = keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("# API keys saved by VOXD. Keep this file private.\n")
        for name in sorted(keys):
            f.write(f"{name}={keys[name]}\n")
    os.chmod(path, 0o600)


def load_into_env() -> None:
    """Export every stored key (a stored key wins over the inherited variable)."""
    for name, value in read_keys().items():
        if name not in _original_env:
            _original_env[name] = os.environ.get(name)
        os.environ[name] = value


def save_key(env_name: str, value: str) -> None:
    """Store (or, with an empty value, forget) a key and apply it to this process."""
    value = (value or "").strip()
    keys = read_keys()
    if value:
        keys[env_name] = value
        _write_keys(keys)
        if env_name not in _original_env:
            _original_env[env_name] = os.environ.get(env_name)
        os.environ[env_name] = value
        return
    if env_name in keys:
        del keys[env_name]
        _write_keys(keys)
    if env_name in _original_env:             # fall back to what the session exported
        inherited = _original_env.pop(env_name)
        if inherited is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = inherited


def key_source(env_name: str) -> str | None:
    """"file" (saved by VOXD), "environment" (inherited variable) or None."""
    if read_keys().get(env_name):
        return "file"
    return "environment" if os.environ.get(env_name) else None
