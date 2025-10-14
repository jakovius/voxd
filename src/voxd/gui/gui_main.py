import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout, QHBoxLayout, 
    QSizePolicy, QInputDialog, QGroupBox, QSystemTrayIcon, QMenu, QDialog, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QIcon, QPainter, QColor, QPen
from pathlib import Path

from voxd.core.config import get_config, CONFIG_PATH
from voxd.core.logger import SessionLogger
from voxd.utils.ipc_server import start_ipc_server
from voxd.core.voxd_core import (
    CoreProcessThread, _create_styled_checkbox,
    show_manage_prompts, session_log_dialog, show_performance_dialog
)
from voxd.core.model_manager import show_model_manager
from voxd.gui.settings_dialog import SettingsDialog
from voxd.utils.performance import update_last_perf_entry

ASSETS_DIR = (Path(__file__).resolve().parent / ".." / "assets").resolve()

# Design constants
UI_GRAY_COLOR = "#3a3a3a"  # Primary gray color for UI elements


class VoxdApp(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)

        # Remove title bar - frameless window
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setWindowTitle("voxd")
        self.setFixedSize(340, 162)  # Adjusted for spacing after drag bar
        self.setStyleSheet("""
            QWidget {
                color: white;
            }
        """)
        self.setObjectName("VoxdMainWindow")

        self.status = "Ready"
        self.last_transcript = ""

        # Main Record button
        self.status_button = QPushButton("Ready")
        try:
            self.status_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        except Exception:
            pass
        self.status_button.setFixedSize(150, 40)
        self._idle_btn_style = """
            QPushButton {
                background-color: #FF4500;
                border-radius: 20px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:pressed {
                background-color: #FF6347;
            }
            """
        self.status_button.setStyleSheet(self._idle_btn_style)
        self.status_button.clicked.connect(self.on_button_clicked)

        # System tray icon & animations
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

        # Help button (circular with ?) - custom style with larger font
        self.help_button = QPushButton("?")
        help_btn_style = f"""
            QPushButton {{
                background-color: {UI_GRAY_COLOR};
                color: #1e1e1e;
                border-radius: 16px;
                font-size: 22px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
            QPushButton:pressed {{
                background-color: #555;
            }}
        """
        self.help_button.setFixedSize(32, 32)
        self.help_button.setStyleSheet(help_btn_style)
        self.help_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.help_button.clicked.connect(self.show_help_dialog)
        
        # Drag handle bar for easy window movement
        self.drag_bar = QLabel("voxd")
        self.drag_bar.setFixedHeight(18)
        self.drag_bar.setStyleSheet(f"""
            background-color: {UI_GRAY_COLOR}; 
            border-top-left-radius: 6px; 
            border-top-right-radius: 6px;
            color: #1e1e1e;
            font-weight: bold;
            font-size: 9pt;
            padding-left: 8px;
        """)
        self.drag_bar.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.drag_bar.setCursor(Qt.CursorShape.SizeAllCursor)
        
        # Instruction label (for row 2)
        self.instruction_label = QLabel("<b>Hit your hotkey</b> to rec/stop (leave this in background to type)")
        self.instruction_label.setStyleSheet("color: gray; font-size: 8pt; font-style: italic; margin-top: 0px; margin-bottom: 0px; padding-top: 0px; padding-bottom: 0px;")
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.instruction_label.setContentsMargins(0, 0, 0, 0)

        # Close button (circular with X) - custom style with larger font
        self.close_button = QPushButton("×")
        close_btn_style = f"""
            QPushButton {{
                background-color: {UI_GRAY_COLOR};
                color: #1e1e1e;
                border-radius: 16px;
                font-size: 28px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
            QPushButton:pressed {{
                background-color: #555;
            }}
        """
        self.close_button.setFixedSize(32, 32)
        self.close_button.setStyleSheet(close_btn_style)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.close_app)

        # Watch config file for external changes
        try:
            self._cfg_watcher = QFileSystemWatcher([str(CONFIG_PATH)])
            self._cfg_watcher.fileChanged.connect(self._on_cfg_file_changed)
        except Exception:
            self._cfg_watcher = None

        # Transcript display
        self.transcript_label = QLabel("Transcript preview")
        self.transcript_label.setStyleSheet("color: darkgray; font-size: 9pt; font-style: italic;")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse |
            Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.transcript_group = QGroupBox()
        self.transcript_group.setStyleSheet(
            "QGroupBox { border: 1px solid #333; border-radius: 6px; margin-top: 2px; }"
        )
        group_layout = QVBoxLayout()
        group_layout.addWidget(self.transcript_label)
        self.transcript_group.setLayout(group_layout)
        self.transcript_group.setFixedHeight(38)
        self.transcript_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.clipboard_notice = QLabel("")
        self.clipboard_notice.setStyleSheet("color: gray; font-size: 8pt;")
        self.clipboard_notice.setWordWrap(True)
        self.clipboard_notice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.clipboard_notice.setFixedHeight(10)

        # Options button with dropdown menu
        self.options_btn = QPushButton("Options")
        self.options_btn.setFixedSize(96, 32)  # 80% of main button width, 20% reduced height
        self.options_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {UI_GRAY_COLOR};
                color: white;
                border-radius: 16px;
                font-size: 12px;
                padding-left: 8px;
                padding-right: 8px;
            }}
            QPushButton:hover {{
                background-color: #4a4a4a;
            }}
        """)
        self.options_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.options_btn.clicked.connect(self.show_options_menu)

        # Placeholder for background processing thread
        self.runner_thread = None

        # Animation timer for status button
        self._anim_timer = QTimer(self)
        try:
            self._anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        except Exception:
            pass
        self._anim_timer.setInterval(33)  # ~30 FPS
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_phase_ms = 0
        self._anim_mode = "idle"

        self.build_ui()
        
        # Position window at lower-right corner of screen
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            x = screen_geometry.width() - self.width() - 20  # 20px margin from right
            y = screen_geometry.height() - self.height() - 20  # 20px margin from bottom
            self.move(x, y)

    def build_ui(self):
        """Build 3-row layout."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 6)  # No margin at top for drag bar
        main_layout.setSpacing(2)  # Compact spacing between rows
        
        # Add drag bar at the very top
        main_layout.addWidget(self.drag_bar)
        
        # Add small spacing after drag bar
        main_layout.addSpacing(4)

        # ═══════════════════════════════════════════════════════════════════
        # ROW 1: Main button + Options button + Circular buttons
        # ═══════════════════════════════════════════════════════════════════
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row1.setContentsMargins(6, 0, 6, 0)  # Horizontal margins for content inside rounded border
        
        # Main button
        row1.addWidget(self.status_button, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # Options button
        row1.addStretch(1)
        row1.addWidget(self.options_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        
        # Circular buttons
        row1.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row1.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        
        main_layout.addLayout(row1)
        
        # ═══════════════════════════════════════════════════════════════════
        # ROW 2: Instruction label
        # ═══════════════════════════════════════════════════════════════════
        # Direct add with minimal spacing
        instruction_row = QHBoxLayout()
        instruction_row.setContentsMargins(6, 0, 6, 0)
        instruction_row.setSpacing(0)
        instruction_row.addWidget(self.instruction_label)
        main_layout.addLayout(instruction_row)
        
        # ═══════════════════════════════════════════════════════════════════
        # ROW 3: Checkboxes (col 1) + Transcript/Clipboard (col 2)
        # ═══════════════════════════════════════════════════════════════════
        row3 = QHBoxLayout()
        row3.setSpacing(6)
        row3.setContentsMargins(6, 0, 6, 0)  # Horizontal margins for content inside rounded border
        
        # Column 1: Checkboxes (vertical) - compact version
        col1 = QVBoxLayout()
        col1.setSpacing(2)
        col1.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Create compact checkboxes
        def create_compact_checkbox(text: str, checked: bool):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setChecked(checked)
            btn.setFixedSize(16, 16)
            
            def _update():
                if btn.isChecked():
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #E03D00;
                            border: 2px solid #777;
                            border-radius: 3px;
                            color: white;
                            font-weight: bold;
                            font-size: 10px;
                        }
                    """)
                    btn.setText("✓")
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #555;
                            border: 2px solid #777;
                            border-radius: 3px;
                            color: white;
                        }
                    """)
                    btn.setText("")
            
            _update()
            btn.toggled.connect(lambda _: _update())
            
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)
            layout.addWidget(btn)
            label = QLabel(text)
            label.setStyleSheet("font-size: 9pt;")
            layout.addWidget(label)
            container.checkbox_button = btn  # type: ignore[attr-defined]
            container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            container.setMinimumWidth(85)  # Give enough space for longest label
            return container
        
        typing_widget = create_compact_checkbox("Typing", self.cfg.data.get("typing", True))
        self.typing_btn = typing_widget.checkbox_button  # type: ignore[attr-defined]
        self.typing_btn.toggled.connect(lambda state: self._on_toggle("typing", state))
        col1.addWidget(typing_widget)
        
        trailing_widget = create_compact_checkbox("Trail. space", self.cfg.data.get("append_trailing_space", True))
        self.trailing_btn = trailing_widget.checkbox_button  # type: ignore[attr-defined]
        self.trailing_btn.toggled.connect(lambda state: self._on_toggle("append_trailing_space", state))
        col1.addWidget(trailing_widget)

        aipp_widget = create_compact_checkbox("AIPP", self.cfg.data.get("aipp_enabled", False))
        self.aipp_btn = aipp_widget.checkbox_button  # type: ignore[attr-defined]
        self.aipp_btn.toggled.connect(lambda state: self._on_toggle("aipp_enabled", state))
        col1.addWidget(aipp_widget)
        
        row3.addLayout(col1, 0)  # 0 = minimum space, no stretch
        
        # Column 2: Transcript + Clipboard notice (vertical)
        col2 = QVBoxLayout()
        col2.setSpacing(3)
        
        # Transcript (expands to fill available width)
        col2.addWidget(self.transcript_group)
        
        # Clipboard notice
        col2.addWidget(self.clipboard_notice)
        
        row3.addLayout(col2, 1)  # 1 = stretch to fill remaining space
        
        main_layout.addLayout(row3)
        
        self.setLayout(main_layout)

    def _on_toggle(self, key, state):
        """Handle checkbox toggles."""
        self.cfg.data[key] = bool(state)
        if hasattr(self.cfg, key):
            setattr(self.cfg, key, bool(state))
        self.cfg.save()

    def close_app(self):
        """Close the application."""
        self.close()
        QApplication.quit()

    def show_help_dialog(self):
        """Show help instructions dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("VOXD Help")
        dialog.setMinimumWidth(450)
        dialog.setStyleSheet("background-color: #2e2e2e; color: white;")
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Create help text
        help_text = QLabel()
        help_text.setWordWrap(True)
        help_text.setTextFormat(Qt.TextFormat.RichText)
        help_text.setText("""
<h3 style='color: #FF4500; margin-bottom: 10px;'>Setup Global Hotkey</h3>
<p style='margin-bottom: 15px;'>
Create a global <b>HOTKEY</b> shortcut in your system (e.g. <b>Super+Z</b>) that runs the command:<br>
<code style='background-color: #1e1e1e; padding: 4px 8px; border-radius: 3px; font-family: monospace;'>bash -c 'voxd --trigger-record'</code>
</p>

<h3 style='color: #FF4500; margin-top: 15px; margin-bottom: 10px;'>Dictation (Voice-Typing)</h3>
<ol style='margin-left: 20px; line-height: 1.6;'>
<li>Go to wherever you want to type and leave this app in the background</li>
<li>Hit the hotkey -> speak -> press the hotkey again -> types what you said!</li>
</ol>
        """)
        help_text.setStyleSheet("font-size: 10pt; line-height: 1.5;")
        
        layout.addWidget(help_text)
        
        # Close button
        close_btn = QPushButton("Got it!")
        close_btn.setFixedHeight(32)
        close_btn.setFixedWidth(60)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF4500;
                color: white;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FF6347;
            }
        """)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)
        
        dialog.exec()

    def show_whisper_models(self):
        show_model_manager(self)

    def show_aipp_settings(self):
        from voxd.core.voxd_core import show_aipp_dialog
        show_aipp_dialog(self, self.cfg)
        self._refresh_aipp_toggle_from_cfg()

    def show_session_log(self):
        session_log_dialog(self, self.logger)

    def show_settings(self):
        editor = SettingsDialog(self.cfg, parent=self)
        editor.exec()

    def show_performance(self):
        show_performance_dialog(self, self.cfg)

    def show_options_menu(self):
        """Show dropdown menu with all options."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2e2e2e;
                color: white;
                border: 1px solid #555;
            }
            QMenu::item {
                padding: 8px 20px;
            }
            QMenu::item:selected {
                background-color: #444;
            }
        """)
        
        # Add menu actions for each option
        whisper_action = menu.addAction("Whisper Models")
        whisper_action.triggered.connect(self.show_whisper_models)
        
        aipp_action = menu.addAction("AI Post-Processing")
        aipp_action.triggered.connect(self.show_aipp_settings)
        
        log_action = menu.addAction("Session Log")
        log_action.triggered.connect(self.show_session_log)
        
        settings_action = menu.addAction("Settings")
        settings_action.triggered.connect(self.show_settings)
        
        perf_action = menu.addAction("Performance")
        perf_action.triggered.connect(self.show_performance)
        
        # Show menu below the Options button
        menu.exec(self.options_btn.mapToGlobal(self.options_btn.rect().bottomLeft()))

    def set_status(self, text):
        self.status = text
        self.status_button.setText(text)
        if text == "Recording":
            self._start_button_anim("recording")
        elif text in ("Transcribing", "Typing"):
            self._start_button_anim("processing")
        else:
            self._stop_button_anim()
            self.status_button.setStyleSheet(self._idle_btn_style)
        QApplication.processEvents()
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
        self._anim_phase_ms = (self._anim_phase_ms + self._anim_timer.interval()) % 500
        import math
        phase = (self._anim_phase_ms / 500.0) * 2 * math.pi
        t = 0.5 * (1 + math.sin(phase))

        if self._anim_mode == "recording":
            base = (255, 69, 0)
            light = (255, 210, 180)
        elif self._anim_mode == "processing":
            base = (0, 200, 83)
            light = (235, 255, 244)
        else:
            return

        color = self._blend(base, light, t)
        style = f"""
            QPushButton {{
                background-color: {color};
                border-radius: 20px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }}
        """
        self.status_button.setStyleSheet(style)
        try:
            self.status_button.repaint()
        except Exception:
            pass
        try:
            self.status_button.update()
        except Exception:
            pass

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
            if self.runner_thread and self.runner_thread.isRunning():
                self.runner_thread.stop_recording()
            return
        self.clearFocus()
        if self.status in ("Transcribing", "Typing"):
            return
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
            self.transcript_label.setStyleSheet("color: white; font-size: 10pt; font-style: italic;")
            
            self.clipboard_notice.setText("Copied to clipboard")
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
        self.set_status("Ready")
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)

    def _refresh_aipp_toggle_from_cfg(self):
        try:
            desired = bool(self.cfg.data.get("aipp_enabled", False))
            if self.aipp_btn.isChecked() != desired:
                self.aipp_btn.setChecked(desired)
        except Exception:
            pass

    def _on_cfg_file_changed(self, path: str):
        try:
            if hasattr(self, "_cfg_watcher") and self._cfg_watcher is not None:
                files = set(self._cfg_watcher.files())
                if path and path not in files:
                    self._cfg_watcher.addPath(path)
            self.cfg.load()
            self._refresh_aipp_toggle_from_cfg()
        except Exception:
            pass

    def paintEvent(self, event):
        """Custom paint event to draw rounded background and border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background with rounded corners
        painter.setBrush(QColor("#1e1e1e"))
        painter.setPen(QPen(QColor(UI_GRAY_COLOR), 2))
        # Adjust rect to account for border width
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 8, 8)
    
    # Enable dragging the frameless window
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if click is on the drag bar or empty space
            widget = self.childAt(event.pos())
            if widget is self.drag_bar or widget is None:
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
            else:
                event.ignore()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


def main():
    app = QApplication(sys.argv)
    gui = VoxdApp()
    gui.show()

    def on_ipc_trigger():
        QTimer.singleShot(0, gui.on_button_clicked)

    start_ipc_server(on_ipc_trigger)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
