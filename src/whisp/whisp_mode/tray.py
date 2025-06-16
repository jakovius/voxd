import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QLabel, QWidgetAction
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QObject, QTimer, QThread

from whisp.core.config import AppConfig
from whisp.core.logger import SessionLogger
from whisp.utils.ipc_server import start_ipc_server
from whisp.core.whisp_core import CoreProcessThread, show_options_dialog

ICON_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icon.png")
ICON_RECORDING_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "icon_r.png")

class WhispTrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = AppConfig()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_file)
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

        # Options action
        self.options_action = QAction("Options")
        self.options_action.triggered.connect(self.show_options)
        self.menu.addAction(self.options_action)

        # Quit action
        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(self.quit_action)

        self.menu.addMenu(self.build_aipp_menu())

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
        show_options_dialog(None, self.logger)

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

        # Prompts submenu
        prompts_menu = QMenu("Prompts", aipp_menu)
        prompt_keys = ["default", "prompt1", "prompt2", "prompt3"]
        current_prompt = self.cfg.data.get("aipp_active_prompt", "default")
        for key in prompt_keys:
            label = self.cfg.data.get("aipp_prompts", {}).get(key, key)
            act = QAction(label if label else key, prompts_menu, checkable=True)
            act.setChecked(current_prompt == key)
            act.triggered.connect(lambda checked, k=key: self.set_aipp_prompt(k))
            prompts_menu.addAction(act)
        aipp_menu.addMenu(prompts_menu)

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

    def set_aipp_prompt(self, key):
        self.cfg.data["aipp_active_prompt"] = key
        self.cfg.aipp_active_prompt = key
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
        # Options
        self.menu.addAction(self.options_action)
        # Quit
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)

def main():
    app = QApplication(sys.argv)
    tray_app = WhispTrayApp()

    def on_ipc_trigger():
        QTimer.singleShot(0, tray_app.toggle_recording)

    start_ipc_server(on_ipc_trigger)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
