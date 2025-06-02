from whisp.utils.setup_utils import detect_backend

def test_detect_backend_env(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "1")
    assert detect_backend() == "wayland"
    monkeypatch.delenv("WAYLAND_DISPLAY")
    monkeypatch.setenv("DISPLAY", ":0")
    assert detect_backend() == "x11"
