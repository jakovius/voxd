import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QInputDialog, QGroupBox
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
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)  # type: ignore[attr-defined]

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

        # Transcript display wrapped in a group-box for padding & visual separation
        self.transcript_label = QLabel("")
        self.transcript_label.setStyleSheet("color: white; font-size: 10pt;")
        self.transcript_label.setWordWrap(True)
        # Put the label inside a group-box so we get default margins/border
        self.transcript_group = QGroupBox()
        self.transcript_group.setStyleSheet("QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 4px; }")
        group_layout = QVBoxLayout()
        group_layout.addWidget(self.transcript_label)
        group_layout.setContentsMargins(6, 4, 6, 4)  # extra padding inside box
        self.transcript_group.setLayout(group_layout)
        self.transcript_group.setFixedWidth(270)  # align with other widgets
        self.transcript_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

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

        # Placeholder for background processing thread
        self.runner_thread = None  # type: CoreProcessThread | None

        self.build_ui()

    def build_ui(self):
        self.main_layout = QVBoxLayout()
        # Align widgets to top; consistent vertical gaps via spacing
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 12, 0, 12)  # top/bottom padding
        self.main_layout.setSpacing(12)  # fixed spacing between stacked items

        # For each button/widget, wrap it in a container layout
        for widget in [self.status_button, self.transcript_group, 
                      self.clipboard_notice, self.options_button]:
            container = QHBoxLayout()
            container.addStretch()
            container.addWidget(widget)
            container.addStretch()
            self.main_layout.addLayout(container)

        self.setLayout(self.main_layout)

    def set_status(self, text):
        self.status = text
        self.status_button.setText(text)
        # Force update the UI
        QApplication.processEvents()

    def on_button_clicked(self):
        if self.status == "Recording":
            # Stop recording
            if self.runner_thread and self.runner_thread.isRunning():
                self.runner_thread.stop_recording()
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
        self.runner_thread = CoreProcessThread(self.cfg, self.logger)
        self.runner_thread.status_changed.connect(self.set_status)
        self.runner_thread.finished.connect(self.on_transcript_ready)
        self.runner_thread.start()

    def on_transcript_ready(self, tscript):
        if tscript:
            self.last_transcript = tscript
            short = tscript[:420] + "..." if len(tscript) > 420 else tscript
            self.transcript_label.setText(short)
            self.clipboard_notice.setText("Copied to clipboard")
            # Prompt user for accuracy rating (optional)
            if getattr(self.cfg, "collect_metrics", False) and getattr(self.cfg, "collect_accuracy_rating", False):
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
