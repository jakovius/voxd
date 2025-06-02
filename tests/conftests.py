import os, pathlib, pytest, tempfile

@pytest.fixture(autouse=True)
def stub_whisper_cli(monkeypatch):
    stub = pathlib.Path(tempfile.gettempdir()) / "whisp_stub_cli"
    stub.write_text("#!/bin/sh\necho stub\n")
    stub.chmod(0o755)
    monkeypatch.setenv("WHISP_REPO_ROOT", str(stub.parent.parent))  # any unused dir
    monkeypatch.setenv("WHISP_SKIP_AUTO_BUILD", "1")                # can wire this later
