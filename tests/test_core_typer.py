def test_detect_backend_env(monkeypatch):
    from voxd.core.typer import detect_backend
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert detect_backend() == "wayland"


def test_typer_paste_path(monkeypatch):
    from voxd.core.typer import SimulatedTyper
    # Disable tools so it falls back to paste
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    monkeypatch.setenv("DISPLAY", "")
    t = SimulatedTyper(delay=0, start_delay=0)
    # Emulate no tool available
    t.tool = None
    # Should not raise
    t.type("hello")

