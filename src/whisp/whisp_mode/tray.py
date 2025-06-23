import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QLabel, QWidgetAction,
    QMessageBox
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QObject, QTimer, QThread

from whisp.core.config import get_config, CONFIG_PATH
from whisp.core.logger import SessionLogger
from whisp.utils.ipc_server import start_ipc_server
from whisp.core.whisp_core import (
    CoreProcessThread,
    show_options_dialog,
    show_config_editor,
    show_manage_prompts,
    show_log_dialog,
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.png")
ICON_RECORDING_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icon_r.png")

class WhispTrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)
        self.status = "Whisp"
        self.last_transcript = ""
        self.thread = None

        self.tray = QSystemTrayIcon(QIcon(ICON_PATH))
        self.tray.setToolTip("Whisp - Ready")

        self.menu = QMenu()

        # Start/Stop Recording action
        self.record_action = QAction("Start Recording")
        self.record_action.triggered.connect(self.toggle_recording)
        self.menu.addAction(self.record_action)

        # --- New top-level actions --------------------------------------
        # Show Log (opens viewer with option to save)
        self.show_log_action = QAction("Show Log")
        self.show_log_action.triggered.connect(
            lambda _=False: show_log_dialog(None, self.logger)
        )

        # Settings (config editor)
        self.settings_action = QAction("Settings")
        self.settings_action.triggered.connect(
            lambda _=False: show_config_editor(
                None,
                str(CONFIG_PATH),
                after_save_cb=self.refresh_tray_menu,
            )
        )

        # Test stub
        self.test_action = QAction("Test")
        self.test_action.triggered.connect(
            lambda _=False: QMessageBox.information(
                None,
                "Testing",
                "Test utility not implemented yet.",
            )
        )

        # Quit action (kept as before)
        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit_app)

        self.menu.addMenu(self.build_aipp_menu())

        # Add the new flat actions right away
        self.menu.addAction(self.show_log_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.test_action)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def set_status(self, text):
        if QApplication.instance().thread() != QThread.currentThread():
            QTimer.singleShot(0, lambda: self.set_status(text))
            return
        self.status = text
        self.tray.setToolTip(f"Whisp - {text}")
        # Change icon based on status
        if text == "Recording":
            self.tray.setIcon(QIcon(ICON_RECORDING_PATH))
        else:
            self.tray.setIcon(QIcon(ICON_PATH))
        self.record_action.setText(
            "Start Recording" if text == "Whisp" else ("Stop Recording" if text == "Recording" else f"{text}...")
        )
        self.refresh_tray_menu()
        QApplication.processEvents()

    def toggle_recording(self):
        if self.status == "Recording":
            if self.thread and self.thread.isRunning():
                self.thread.stop_recording()
            return
        if self.status in ("Transcribing", "Typing"):
            return
        self.set_status("Recording")
        self.thread = CoreProcessThread(self.cfg, self.logger)
        self.thread.status_changed.connect(self.set_status, Qt.ConnectionType.QueuedConnection)
        self.thread.finished.connect(self.on_transcript_ready)
        self.thread.start()

    def on_transcript_ready(self, tscript):
        if tscript:
            self.last_transcript = tscript
            # Optionally, show a notification here
        self.set_status("Whisp")

    def show_options(self):
        show_options_dialog(None, self.logger, cfg=self.cfg)

    def quit_app(self):
        print()
        QApplication.quit()

    def build_aipp_menu(self):
        aipp_menu = QMenu("AI Post-Processing", self.menu)

        # Enabled checkbox with dynamic label and checkmark
        aipp_enabled = self.cfg.data.get("aipp_enabled", False)
        enabled_action = QAction("Enabled" if aipp_enabled else "Enable", self.menu, checkable=True)
        enabled_action.setChecked(aipp_enabled)
        enabled_action.toggled.connect(self.toggle_aipp_enabled)
        aipp_menu.addAction(enabled_action)
        aipp_menu.addSeparator()

        # Prompts action (opens shared manager dialog)
        prompts_action = QAction("Prompts", aipp_menu)
        prompts_action.triggered.connect(
            lambda _=False: show_manage_prompts(
                None,
                self.cfg,
                after_save_cb=self.refresh_tray_menu,
            )
        )
        aipp_menu.addAction(prompts_action)

        # Providers submenu
        providers_menu = QMenu("Providers", aipp_menu)
        providers = list(self.cfg.data.get("aipp_models", {"ollama":[]}).keys())
        current_provider = self.cfg.data.get("aipp_provider", "ollama")
        for prov in providers:
            act = QAction(prov, providers_menu, checkable=True)
            act.setChecked(current_provider == prov)
            act.triggered.connect(lambda checked, p=prov: self.set_aipp_provider(p))
            providers_menu.addAction(act)
        aipp_menu.addMenu(providers_menu)

        # Models submenu (NEW)
        models_menu = QMenu("Models", aipp_menu)
        models = self.cfg.data.get("aipp_models", {}).get(current_provider, [])
        selected_model = self.cfg.data.get("aipp_selected_models", {}).get(current_provider, "")
        for model in models:
            act = QAction(model, models_menu, checkable=True)
            act.setChecked(selected_model == model)
            act.triggered.connect(lambda checked, m=model: self.set_aipp_model(current_provider, m))
            models_menu.addAction(act)
        aipp_menu.addMenu(models_menu)

        return aipp_menu

    def toggle_aipp_enabled(self, checked):
        self.cfg.data["aipp_enabled"] = checked
        self.cfg.aipp_enabled = checked
        self.cfg.save()
        self.refresh_tray_menu()

    def set_aipp_provider(self, provider):
        self.cfg.data["aipp_provider"] = provider
        self.cfg.aipp_provider = provider
        self.cfg.save()
        self.refresh_tray_menu()

    def set_aipp_model(self, provider, model):
        self.cfg.data["aipp_selected_models"][provider] = model
        self.cfg.aipp_model = model
        self.cfg.save()
        self.refresh_tray_menu()

    def refresh_tray_menu(self):
        # Rebuild the menu to update checkmarks
        self.menu.clear()
        # Recording
        self.menu.addAction(self.record_action)
        # AIPP
        self.menu.addMenu(self.build_aipp_menu())
        # Top-level helpers (already created in __init__)
        self.menu.addAction(self.show_log_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.test_action)
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)

def main():
    app = QApplication(sys.argv)
    # Prevent tray-only sessions from quitting when the last dialog closes
    app.setQuitOnLastWindowClosed(False)
    tray_app = WhispTrayApp()

    def on_ipc_trigger():
        QTimer.singleShot(0, tray_app.toggle_recording)

    start_ipc_server(on_ipc_trigger)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
