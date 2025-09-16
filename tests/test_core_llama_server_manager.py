def test_llama_server_manager_status(monkeypatch):
    from voxd.core.llama_server_manager import get_server_manager
    mgr = get_server_manager()
    st = mgr.get_server_status()
    assert set(["process_running", "server_responding", "url", "pid"]).issubset(st.keys())


def test_ensure_server_running_handles_missing(monkeypatch, tmp_path):
    from voxd.core.llama_server_manager import ensure_server_running
    # Non-existent paths should return False, not raise
    ok = ensure_server_running(str(tmp_path / "missing_server"), str(tmp_path / "missing_model"))
    assert ok is False

