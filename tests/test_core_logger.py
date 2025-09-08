from pathlib import Path


def test_logger_log_and_show(capsys):
    from voxt.core.logger import SessionLogger
    lg = SessionLogger(enabled=True, log_location=str(Path.cwd()))
    lg.log_entry("hello")
    lg.show()
    out = capsys.readouterr().out
    assert "Session Log" in out
    assert "hello" in out


def test_logger_save_to_path(tmp_path, capsys):
    from voxt.core.logger import SessionLogger
    p = tmp_path / "out.txt"
    lg = SessionLogger(enabled=True, log_location=str(tmp_path))
    lg.log_entry("a")
    lg.save(str(p))
    assert p.exists()
    data = p.read_text()
    assert "a" in data

