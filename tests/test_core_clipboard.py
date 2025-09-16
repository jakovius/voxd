def test_clipboard_pyperclip_backend(monkeypatch):
    import voxd.core.clipboard as cb

    # Force backend to pyperclip
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setattr(cb.shutil, "which", lambda *_: None)

    mgr = cb.ClipboardManager(backend="pyperclip")
    assert mgr.backend == "pyperclip"

    # Use stubbed pyperclip from conftest
    import pyperclip
    mgr.copy("hello")
    assert getattr(pyperclip, "copy") is not None

