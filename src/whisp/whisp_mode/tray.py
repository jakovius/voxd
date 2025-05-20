import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QLabel, QWidgetAction
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QObject

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

        # Status label at the top of the menu
        self.status_label = QLabel(self.status)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_action = QWidgetAction(self.menu)
        status_action.setDefaultWidget(self.status_label)
        self.menu.addAction(status_action)
        self.menu.addSeparator()

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

        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def set_status(self, text):
        self.status = text
        self.status_label.setText(text)
        self.tray.setToolTip(f"Whisp - {text}")
        # Change icon based on status
        if text == "Recording":
            self.tray.setIcon(QIcon(ICON_RECORDING_PATH))
        else:
            self.tray.setIcon(QIcon(ICON_PATH))
        self.record_action.setText(
            "Start Recording" if text == "Whisp" else ("Stop Recording" if text == "Recording" else f"{text}...")
        )
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
        self.thread.status_changed.connect(self.set_status)
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

def main():
    app = QApplication(sys.argv)
    tray_app = WhispTrayApp()

    def on_ipc_trigger():
        tray_app.toggle_recording()

    start_ipc_server(on_ipc_trigger)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
