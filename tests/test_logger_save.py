import os
from pathlib import Path
from whisp.core.logger import SessionLogger


def test_logger_save_uses_dialog(tmp_path, monkeypatch):
    """
    When save() is called without an explicit path, SessionLogger must
    ask the user (_ask_user_for_path).  We monkey-patch that method so
    the test runs head-less.
    """
    log_target = tmp_path / "session.txt"

    # --- patch the dialog helper to return our temp path -------------
    monkeypatch.setattr(
        SessionLogger,
        "_ask_user_for_path",
        lambda self: log_target,
        raising=True,
    )

    logger = SessionLogger(enabled=True, log_location=str(tmp_path))
    logger.log_entry("Hello, Whisp!")
    logger.save()                       # should create <tmp>/session.txt

    assert log_target.exists(), "save() did not create the file"
    text = log_target.read_text(encoding="utf-8")
    assert "Hello, Whisp!" in text


def test_logger_save_cancel(monkeypatch, tmp_path):
    """
    If the user cancels the file-save dialog (helper returns None), no
    file must be written.
    """
    monkeypatch.setattr(
        SessionLogger,
        "_ask_user_for_path",
        lambda self: None,   # simulate "Cancel"
        raising=True,
    )

    logger = SessionLogger(enabled=True, log_location=str(tmp_path))
    logger.log_entry("Should not be written")
    logger.save()

    # directory should stay empty
    assert not any(tmp_path.iterdir()), "File was created despite cancel"
