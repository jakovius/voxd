import os
import sys
import importlib
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolate_xdg_dirs(monkeypatch, tmp_path):
    # Ensure the package src/ is importable even without an editable install
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    # Isolate XDG directories per-test to avoid touching real user files
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # Run Qt headless for any accidental GUI imports
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    # Reload modules that compute paths at import-time so they pick up XDG_* envs
    if "voxt.paths" in sys.modules:
        importlib.reload(sys.modules["voxt.paths"])  # type: ignore[arg-type]
    else:
        import voxt.paths  # noqa: F401

    if "voxt.core.config" in sys.modules:
        importlib.reload(sys.modules["voxt.core.config"])  # type: ignore[arg-type]
    else:
        import voxt.core.config  # noqa: F401

    yield


@pytest.fixture(autouse=True)
def stub_sounddevice(monkeypatch):
    """Provide a minimal stub for the sounddevice module so imports succeed."""
    import types

    sd = types.ModuleType("sounddevice")

    class _InputStream:
        def __init__(self, *args, **kwargs):
            self.callback = kwargs.get("callback")
        def start(self):
            # Synthesize a tiny chunk so non-chunked recording has data
            try:
                import numpy as _np
                frames = 160
                indata = _np.zeros((frames, 1), dtype=_np.float32)
            except Exception:
                frames = 1
                indata = [[0.0]]
            if callable(self.callback):
                try:
                    self.callback(indata, frames, None, None)
                except Exception:
                    pass
            return None
        def stop(self):
            return None
        def close(self):
            return None

    sd.InputStream = _InputStream  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sounddevice", sd)

    yield


@pytest.fixture(autouse=True)
def stub_numpy(monkeypatch):
    """Prefer the real numpy if available; only stub when truly missing."""
    try:
        import numpy  # noqa: F401
        # Real numpy is available – do not stub
        yield
        return
    except Exception:
        pass

    import types, math
    np = types.ModuleType("numpy")
    # Minimal attributes used in import-time paths; not used for numeric ops
    np.int16 = int
    np.ndarray = object
    np.inf = float("inf")
    np.log10 = lambda x: math.log10(x)
    def _noop(*a, **k):
        return a[0] if a else None
    np.clip = _noop
    np.concatenate = _noop
    # Provide frombuffer to avoid AttributeError during import; return empty list
    np.frombuffer = lambda *a, **k: []
    monkeypatch.setitem(sys.modules, "numpy", np)
    yield


@pytest.fixture(autouse=True)
def stub_pyperclip(monkeypatch):
    """Provide a minimal stub for pyperclip used by clipboard/typer."""
    import types

    if "pyperclip" in sys.modules:
        yield
        return

    pc = types.ModuleType("pyperclip")
    class _PyperclipException(Exception):
        pass
    pc.PyperclipException = _PyperclipException
    store = {"last": None}
    def copy(text):
        store["last"] = text
    pc.copy = copy
    monkeypatch.setitem(sys.modules, "pyperclip", pc)
    yield


@pytest.fixture
def fake_whisper_run(monkeypatch, tmp_path):
    """Patch whisper subprocess.run to simulate success and create expected .txt output."""
    def _run(cmd, capture_output=True, text=True):
        # Find output prefix from '-of'
        if "-of" in cmd:
            of_idx = cmd.index("-of")
            prefix = cmd[of_idx + 1]
            out_txt = f"{prefix}.txt"
            Path(out_txt).parent.mkdir(parents=True, exist_ok=True)
            with open(out_txt, "w", encoding="utf-8") as f:
                f.write("[00:00.000] Hello world\n")
        class CP:
            returncode = 0
            stdout = ""
            stderr = ""
        return CP()

    monkeypatch.setattr("voxt.core.transcriber.subprocess.run", _run)
    return _run


