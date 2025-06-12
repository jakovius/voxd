import pytest
from whisp.core.config import AppConfig
from whisp.core.whisp_core import show_options_dialog
from PyQt6.QtWidgets import QApplication, QCheckBox, QDialog, QPushButton
from PyQt6.QtCore import Qt

@pytest.fixture
def cfg():
    # Use a fresh config for each test
    return AppConfig()

def test_toggle_aipp_enabled(qtbot, cfg):
    print("TEST CFG id:", id(cfg))
    cfg.data["aipp_enabled"] = False
    cfg.aipp_enabled = False
    dialog = show_options_dialog(None, logger=None, cfg=cfg, modal=False)
    dialog.show()
    qtbot.addWidget(dialog)
    qtbot.waitExposed(dialog)
    cb = dialog.findChild(QCheckBox, None)
    print("Checkbox object:", cb)
    print("Checkbox enabled:", cb.isEnabled())
    print("Checkbox visible:", cb.isVisible())
    print("Checkbox checked before:", cb.isChecked())
    assert cb is not None
    cb.setEnabled(True)
    cb.setVisible(True)
    dialog.activateWindow()
    cb.setFocus()
    qtbot.wait(100)
    qtbot.mouseClick(cb, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    qtbot.wait(100)
    print("Checkbox checked after:", cb.isChecked())
    print("Config after click:", cfg.data["aipp_enabled"])
    assert cb.isChecked() is True
    assert cfg.data["aipp_enabled"] is True

def test_manage_prompts_modal(qtbot, cfg):
    dialog = show_options_dialog(None, logger=None, modal=False)
    btns = dialog.findChildren(QPushButton)
    manage_btn = next((b for b in btns if "Manage prompts" in b.text()), None)
    assert manage_btn is not None
    # Instead of clicking, call the handler directly:
    dlg = dialog.findChild(QDialog)  # or keep a reference in your dialog
    if dlg:
        dlg.show()
        qtbot.waitExposed(dlg)