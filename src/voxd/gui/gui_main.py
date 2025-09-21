import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QInputDialog, QGroupBox, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QIcon
from pathlib import Path

from voxd.core.config import get_config, CONFIG_PATH
from voxd.core.logger import SessionLogger
from voxd.utils.ipc_server import start_ipc_server  # <-- Add this import
from voxd.core.voxd_core import CoreProcessThread, show_options_dialog, _create_styled_checkbox
from voxd.utils.performance import update_last_perf_entry

ASSETS_DIR = (Path(__file__).resolve().parent / ".." / "assets").resolve()


class VoxdApp(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)  # type: ignore[attr-defined]

        self.setWindowTitle("voxd")
        self.setFixedWidth(230)
        self.setMinimumHeight(180)
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        self.status = "Record"
        self.last_transcript = ""

        self.status_button = QPushButton("Record")
        # Ensure stylesheet background paints reliably across styles
        try:
            self.status_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        self.status_button.setFixedSize(180, 45)
        self._idle_btn_style = (
            """
            QPushButton {
                background-color: #FF4500;
                border-radius: 22px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
            """
        )
        self.status_button.setStyleSheet(self._idle_btn_style)
        self.status_button.clicked.connect(self.on_button_clicked)

        # System tray icon & animations (so window can stay background)
        self.icon_idle = QIcon(str(ASSETS_DIR / "voxd-0.png"))
        self.icons_recording = [QIcon(str(ASSETS_DIR / f"voxd-{i}.png")) for i in range(1, 10)]
        self.icons_transcribing = [
            QIcon(str(ASSETS_DIR / n)) for n in ["voxd-0.png", "voxd-9.png", "voxd-1.png", "voxd-9.png"]
        ]
        self.tray = QSystemTrayIcon(self.icon_idle, self)
        self.tray.setToolTip("VOXD")
        self.tray.show()
        self._tray_anim_timer = QTimer(self)
        self._tray_anim_timer.timeout.connect(self._tray_advance_frame)
        self._tray_frames = []
        self._tray_index = 0

        # Small toggles row (AIPP / Trailing space)
        self.toggle_container = QWidget()
        toggles_layout = QHBoxLayout(self.toggle_container)
        toggles_layout.setContentsMargins(0, 0, 0, 0)
        toggles_layout.setSpacing(10)

        aipp_widget = _create_styled_checkbox("AIPP", self.cfg.data.get("aipp_enabled", False))
        self.aipp_btn = aipp_widget.checkbox_button  # type: ignore[attr-defined]
        def _on_aipp_toggled(state: bool):
            self.cfg.data["aipp_enabled"] = bool(state)
            try:
                self.cfg.aipp_enabled = bool(state)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.cfg.save()
        self.aipp_btn.toggled.connect(_on_aipp_toggled)

        trailing_widget = _create_styled_checkbox("Trailing space", self.cfg.data.get("append_trailing_space", True))
        self.trailing_btn = trailing_widget.checkbox_button  # type: ignore[attr-defined]
        def _on_trailing_toggled(state: bool):
            self.cfg.data["append_trailing_space"] = bool(state)
            try:
                self.cfg.append_trailing_space = bool(state)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.cfg.save()
        self.trailing_btn.toggled.connect(_on_trailing_toggled)

        toggles_layout.addWidget(aipp_widget)
        toggles_layout.addWidget(trailing_widget)
        toggles_layout.addStretch(1)

        # Watch config file for external changes and refresh toggle state
        try:
            self._cfg_watcher = QFileSystemWatcher([str(CONFIG_PATH)])
            self._cfg_watcher.fileChanged.connect(self._on_cfg_file_changed)
        except Exception:
            self._cfg_watcher = None

        # Transcript display wrapped in a group-box for padding & visual separation
        self.transcript_label = QLabel("The transcript will be shown here.")
        self.transcript_label.setStyleSheet("color: darkgray; font-size: 9pt; font-style: italic;")
        self.transcript_label.setWordWrap(True)
        from PyQt6.QtCore import Qt as _Qt
        self.transcript_label.setTextInteractionFlags(_Qt.TextInteractionFlag.TextSelectableByMouse |
                                                      _Qt.TextInteractionFlag.TextSelectableByKeyboard)
        # Put the label inside a group-box so we get default margins/border
        self.transcript_group = QGroupBox()
        self.transcript_group.setStyleSheet("QGroupBox { border: 1px solid #333; border-radius: 6px; margin-top: 2px; }")
        group_layout = QVBoxLayout()
        group_layout.addWidget(self.transcript_label)
        
        self.transcript_group.setLayout(group_layout)
        # Set fixed size for the transcript group box
        self.transcript_group.setFixedSize(210, 54)
        self.transcript_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.hotkey_notice = QLabel("<b>Hit your hotkey</b> to rec/stop<br>(leave this in background to type)")
        self.hotkey_notice.setStyleSheet("color: gray; font-size: 8pt;")
        self.hotkey_notice.setWordWrap(True)
        self.hotkey_notice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.clipboard_notice = QLabel("")
        self.clipboard_notice.setStyleSheet("color: gray; font-size: 8pt;")
        self.clipboard_notice.setWordWrap(True)
        self.clipboard_notice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.options_button = QPushButton("Options")
        self.options_button.setFixedSize(135, 18)
        self.options_button.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: white;
                border-radius: 5px;
            }
        """)
        self.options_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.options_button.clicked.connect(self.show_options)

        # Placeholder for background processing thread
        self.runner_thread = None  # type: CoreProcessThread | None

        # Animation timer for status button
        self._anim_timer = QTimer(self)
        try:
            # Use precise timer for smoother, reliable updates even when busy
            self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        except Exception:
            pass
        self._anim_timer.setInterval(33)  # ~30 FPS
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_phase_ms = 0
        self._anim_mode = "idle"  # idle | recording | processing

        self.build_ui()

    def build_ui(self):
        self.main_layout = QVBoxLayout()
        # Top alignment, consistent spacing/margins
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        # self.main_layout.setContentsMargins(6, 6, 6, 6)
        # self.main_layout.setSpacing(12)

        for widget in [self.status_button, self.hotkey_notice, self.toggle_container, self.transcript_group,
                        self.clipboard_notice, self.options_button]:
            self.main_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)

        self.setLayout(self.main_layout)

    def set_status(self, text):
        self.status = text
        self.status_button.setText(text)
        # Update animation mode based on state
        if text == "Recording":
            self._start_button_anim("recording")
        elif text in ("Transcribing", "Typing"):
            self._start_button_anim("processing")
        else:
            self._stop_button_anim()
            self.status_button.setStyleSheet(self._idle_btn_style)
        # Force update the UI
        QApplication.processEvents()
        # Update tray tooltip and animation
        try:
            self.tray.setToolTip(f"VOXD - {text}")
            if text == "Recording":
                self._tray_start_animation(self.icons_recording, total_period_ms=500)
            elif text in ("Transcribing", "Typing"):
                self._tray_start_animation(self.icons_transcribing, total_period_ms=1000)
            else:
                self._tray_stop_animation()
        except Exception:
            pass
        # Only minimize when about to type to prevent intercepting keystrokes
        if text == "Typing":
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMinimized)

    def _start_button_anim(self, mode: str):
        self._anim_mode = mode
        self._anim_phase_ms = 0
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _stop_button_anim(self):
        if self._anim_timer.isActive():
            self._anim_timer.stop()
        self._anim_mode = "idle"

    def _blend(self, c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        return f"rgb({r},{g},{b})"

    def _on_anim_tick(self):
        # 500 ms full cycle → use sine for smooth in/out
        self._anim_phase_ms = (self._anim_phase_ms + self._anim_timer.interval()) % 500
        import math
        phase = (self._anim_phase_ms / 500.0) * 2 * math.pi
        t = 0.5 * (1 + math.sin(phase))  # 0..1

        if self._anim_mode == "recording":
            base = (255, 69, 0)       # #FF4500 current orange
            light = (255, 210, 180)   # lighter, higher-contrast orange
        elif self._anim_mode == "processing":
            base = (0, 200, 83)       # bright green (#00C853)
            light = (235, 255, 244)   # very pale green (#EBFFF4)
        else:
            return

        color = self._blend(base, light, t)
        style = f"""
            QPushButton {{
                background-color: {color};
                border-radius: 22px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }}
        """
        self.status_button.setStyleSheet(style)
        try:
            # Force immediate repaint for visible feedback
            self.status_button.repaint()
        except Exception:
            pass
        # Nudge a repaint in case the compositor throttles background widgets
        try:
            self.status_button.update()
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────
    #  Tray animation helpers
    # ------------------------------------------------------------------
    def _tray_start_animation(self, frames, total_period_ms: int):
        if not frames:
            return
        interval = max(1, total_period_ms // max(1, len(frames)))
        self._tray_frames = frames
        self._tray_index = 0
        try:
            self.tray.setIcon(frames[0])
        except Exception:
            pass
        self._tray_anim_timer.stop()
        self._tray_anim_timer.start(interval)

    def _tray_stop_animation(self):
        if self._tray_anim_timer.isActive():
            self._tray_anim_timer.stop()
        try:
            self.tray.setIcon(self.icon_idle)
        except Exception:
            pass

    def _tray_advance_frame(self):
        if not self._tray_frames:
            return
        self._tray_index = (self._tray_index + 1) % len(self._tray_frames)
        try:
            self.tray.setIcon(self._tray_frames[self._tray_index])
        except Exception:
            pass

    def on_button_clicked(self):
        if self.status == "Recording":
            # Stop recording
            if self.runner_thread and self.runner_thread.isRunning():
                self.runner_thread.stop_recording()
            return
        # Ensure the VOXD window does **not** receive the keystrokes we
        # are about to send with ydotool/xdotool.
        self.clearFocus()            # drop keyboard-focus
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
            short = tscript[:80] + (" …" if len(tscript) > 80 else "")
            self.transcript_label.setText(short)
            # Switch style to brighter color while keeping italics
            self.transcript_label.setStyleSheet("color: white; font-size: 10pt; font-style: italic;")
            
            self.clipboard_notice.setText("Copied to clipboard")
            # Prompt user for accuracy rating (optional)
            if getattr(self.cfg, "perf_collect", False) and getattr(self.cfg, "perf_accuracy_rating_collect", False):
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
        self.set_status("Record")
        # Restore window after typing (optional; comment out if you prefer it
        # to stay minimised)
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)

    def show_options(self):
        # Open Options (modal); when it closes, refresh AIPP toggle from config
        show_options_dialog(self, self.logger, cfg=self.cfg)
        self._refresh_aipp_toggle_from_cfg()

    def _refresh_aipp_toggle_from_cfg(self):
        """Sync the AIPP checkbox button with the current config value."""
        try:
            desired = bool(self.cfg.data.get("aipp_enabled", False))
            if self.aipp_btn.isChecked() != desired:
                self.aipp_btn.setChecked(desired)
        except Exception:
            pass

    def _on_cfg_file_changed(self, path: str):
        """Reload config on disk change and refresh dependent UI bits."""
        try:
            # Re-add path in case editors replace the file atomically
            if hasattr(self, "_cfg_watcher") and self._cfg_watcher is not None:
                files = set(self._cfg_watcher.files())
                if path and path not in files:
                    self._cfg_watcher.addPath(path)
            # Reload and sync UI
            self.cfg.load()
            self._refresh_aipp_toggle_from_cfg()
        except Exception:
            pass


def main():
    app = QApplication(sys.argv)
    gui = VoxdApp()
    gui.show()

    # IPC server triggers the same as clicking the main button
    def on_ipc_trigger():
        # Ensure GUI actions run on the main thread
        QTimer.singleShot(0, gui.on_button_clicked)

    start_ipc_server(on_ipc_trigger)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
