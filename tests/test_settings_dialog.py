import sys

import pytest


_APP = None  # held at module level: an unreferenced QApplication is garbage-collected


def _make_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or _APP or QApplication(sys.argv)
    return _APP


def _patch_devices(monkeypatch, names):
    import sounddevice as sd
    devices = [{"name": n, "max_input_channels": 2} for n in names]
    monkeypatch.setattr(sd, "query_devices", lambda *a, **k: devices, raising=False)


def test_settings_dialog_lists_input_devices(monkeypatch):
    pytest.importorskip("PyQt6")
    _make_app()
    from voxd.core.config import AppConfig
    from voxd.gui.settings_dialog import SettingsDialog

    _patch_devices(monkeypatch, ["Built-in Mic", "USB Headset"])

    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    combo = dlg._widgets["audio_input_device"]

    # "System default" first, then enumerated devices
    assert combo.itemText(0) == "System default"
    assert combo.itemData(0) == ""
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert "Built-in Mic" in labels and "USB Headset" in labels


def test_settings_dialog_preselects_and_saves_device(monkeypatch):
    pytest.importorskip("PyQt6")
    _make_app()
    from voxd.core.config import AppConfig
    from voxd.gui.settings_dialog import SettingsDialog

    _patch_devices(monkeypatch, ["Built-in Mic", "USB Headset"])

    cfg = AppConfig()
    cfg.data["audio_input_device"] = "USB Headset"
    dlg = SettingsDialog(cfg)
    combo = dlg._widgets["audio_input_device"]

    # Pre-selected to the configured device
    assert combo.currentData() == "USB Headset"

    # Select "System default" and save → empty string persisted
    combo.setCurrentIndex(0)
    dlg._on_save()
    assert cfg.data["audio_input_device"] == ""


def test_settings_dialog_keeps_unknown_configured_device(monkeypatch):
    pytest.importorskip("PyQt6")
    _make_app()
    from voxd.core.config import AppConfig
    from voxd.gui.settings_dialog import SettingsDialog

    _patch_devices(monkeypatch, ["Built-in Mic"])

    cfg = AppConfig()
    cfg.data["audio_input_device"] = "Ghost Mic"  # not enumerated
    dlg = SettingsDialog(cfg)
    combo = dlg._widgets["audio_input_device"]

    # Stale value is preserved rather than silently dropped
    assert combo.currentData() == "Ghost Mic"
    dlg._on_save()
    assert cfg.data["audio_input_device"] == "Ghost Mic"
