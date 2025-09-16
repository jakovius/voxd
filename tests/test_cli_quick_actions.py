import sys


def test_cli_transcribe_quick_action(monkeypatch, tmp_path, capsys):
    import voxd.cli.cli_main as cli

    audio = tmp_path / "t.wav"; audio.write_bytes(b"x")

    class _T:
        def __init__(self, *a, **k): pass
        def transcribe(self, f): return "hi", "hi"

    monkeypatch.setattr(cli, "WhisperTranscriber", _T)
    monkeypatch.setattr(cli, "ensure_whisper_cli", lambda *_: str(tmp_path/"bin"))
    monkeypatch.setattr(sys, "argv", ["prog", "--transcribe", str(audio)])

    cli.main()
    out = capsys.readouterr().out
    assert "hi" in out


