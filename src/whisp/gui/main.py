import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QInputDialog
)
from PyQt6.QtCore import Qt

from whisp.core.config import get_config
from whisp.core.logger import SessionLogger
from whisp.utils.ipc_server import start_ipc_server  # <-- Add this import
from whisp.core.whisp_core import CoreProcessThread, show_options_dialog
from whisp.utils.benchmark_utils import update_last_perf_entry


class WhispApp(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)

        self.setWindowTitle("whisp")
        self.setFixedWidth(300)  # Fix the width
        self.setMinimumHeight(160)  # Only set minimum height
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        self.status = "Whisp"
        self.last_transcript = ""

        self.status_button = QPushButton("Whisp")
        self.status_button.setFixedSize(200, 50)
        self.status_button.setStyleSheet("""
            QPushButton {
                background-color: #FF4500;
                border-radius: 25px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
        """)
        self.status_button.clicked.connect(self.on_button_clicked)

        self.transcript_label = QLabel("")
        self.transcript_label.setStyleSheet("color: white; font-size: 10pt;")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setFixedWidth(270)  # Set fixed width slightly less than window
        self.transcript_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.clipboard_notice = QLabel("")
        self.clipboard_notice.setStyleSheet("color: gray; font-size: 8pt;")
        self.clipboard_notice.setWordWrap(True)
        self.clipboard_notice.setFixedWidth(270)  # Set fixed width slightly less than window
        self.clipboard_notice.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.options_button = QPushButton("Options")
        self.options_button.setFixedSize(150, 20)
        self.options_button.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: white;
                border-radius: 10px;
            }
        """)
        self.options_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.options_button.clicked.connect(self.show_options)

        self.build_ui()

    def build_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # For each button/widget, wrap it in a container layout
        for widget in [self.status_button, self.transcript_label, 
                      self.clipboard_notice, self.options_button]:
            container = QHBoxLayout()
            container.addStretch()
            container.addWidget(widget)
            container.addStretch()
            self.layout.addLayout(container)

        self.setLayout(self.layout)

    def set_status(self, text):
        self.status = text
        self.status_button.setText(text)
        # Force update the UI
        QApplication.processEvents()

    def on_button_clicked(self):
        if self.status == "Recording":
            # Stop recording
            if hasattr(self, 'thread') and self.thread.isRunning():
                self.thread.stop_recording()
            return
        # Ensure the Whisp window does **not** receive the keystrokes we
        # are about to send with ydotool/xdotool.
        self.clearFocus()            # drop keyboard-focus
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMinimized)
        if self.status in ("Transcribing", "Typing"):
            return
        # Start recording
        self.set_status("Recording")
        self.clipboard_notice.setText("")
        self.thread = CoreProcessThread(self.cfg, self.logger)
        self.thread.status_changed.connect(self.set_status)
        self.thread.finished.connect(self.on_transcript_ready)
        self.thread.start()

    def on_transcript_ready(self, tscript):
        if tscript:
            self.last_transcript = tscript
            short = tscript[:420] + "..." if len(tscript) > 420 else tscript
            self.transcript_label.setText(short)
            self.clipboard_notice.setText("Copied to clipboard")
            # Prompt user for accuracy rating (optional)
            if self.cfg.collect_metrics and self.cfg.collect_accuracy_rating:
                s, ok = QInputDialog.getText(
                    self,
                    "Accuracy Rating",
                    "Rate transcription accuracy (0-100 %):",
                )
                if ok and s.strip():
                    try:
                        val = float(s.strip())
                        update_last_perf_entry(val)
                    except ValueError:
                        pass
        self.set_status("Whisp")
        # Restore window after typing (optional; comment out if you prefer it
        # to stay minimised)
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)

    def show_options(self):
        show_options_dialog(self, self.logger, cfg=self.cfg)


def main():
    app = QApplication(sys.argv)
    gui = WhispApp()
    gui.show()

    # IPC server triggers the same as clicking the main button
    def on_ipc_trigger():
        gui.on_button_clicked()

    start_ipc_server(on_ipc_trigger)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
