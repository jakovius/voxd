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


def test_typer_chunking_long_text(monkeypatch):
    """Test that long text (>285 chars) gets chunked properly."""
    from voxd.core.typer import SimulatedTyper
    from unittest.mock import Mock

    # Mock config with chunking settings
    mock_cfg = Mock()
    mock_cfg.data = {
        "append_trailing_space": True,
        "typing_chunk_size": 250,
        "typing_inter_chunk_delay": 0.05
    }

    # Create typer with mocked tool
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    t = SimulatedTyper(delay=10, start_delay=0, cfg=mock_cfg)

    # Mock the tool path and _run_tool to track calls
    t.tool = "/usr/bin/ydotool"
    t.enabled = True
    call_log = []

    def mock_run_tool(cmd):
        call_log.append(cmd)

    t._run_tool = mock_run_tool

    # Create text longer than 285 characters (the truncation point)
    long_text = "a" * 300  # 300 chars should trigger chunking with default 250 chunk size

    # Type the long text
    t.type(long_text)

    # Verify multiple chunks were sent
    assert len(call_log) > 1, f"Expected multiple chunks, got {len(call_log)} calls"

    # Verify each chunk is <= 250 chars (plus trailing space)
    for i, cmd in enumerate(call_log):
        chunk_text = cmd[-1]  # Last element is the text
        assert len(chunk_text) <= 251, f"Chunk {i} too long: {len(chunk_text)} chars"

    # Verify all text was sent (combining all chunks minus trailing spaces)
    combined = "".join(cmd[-1] for cmd in call_log).rstrip()
    assert long_text in combined, "Original text not fully present in chunks"


def test_typer_no_chunking_short_text(monkeypatch):
    """Test that short text (<250 chars) doesn't get chunked."""
    from voxd.core.typer import SimulatedTyper
    from unittest.mock import Mock

    # Mock config
    mock_cfg = Mock()
    mock_cfg.data = {
        "append_trailing_space": True,
        "typing_chunk_size": 250,
        "typing_inter_chunk_delay": 0.05
    }

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    t = SimulatedTyper(delay=10, start_delay=0, cfg=mock_cfg)

    # Mock the tool
    t.tool = "/usr/bin/ydotool"
    t.enabled = True
    call_log = []

    def mock_run_tool(cmd):
        call_log.append(cmd)

    t._run_tool = mock_run_tool

    # Create short text
    short_text = "This is a short test message."

    # Type the short text
    t.type(short_text)

    # Verify only one call was made (no chunking)
    assert len(call_log) == 1, f"Expected single call for short text, got {len(call_log)} calls"

