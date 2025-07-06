import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QLabel, QWidgetAction,
    QMessageBox
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QObject, QTimer, QThread

from whisp.core.config import get_config
from whisp.core.logger import SessionLogger
from whisp.utils.ipc_server import start_ipc_server
from whisp.core.whisp_core import (
    CoreProcessThread,
    show_options_dialog,
    show_manage_prompts,
    session_log_dialog,
    show_performance_dialog,
)
from whisp.core.model_manager import show_model_manager  # NEW
from whisp.utils.performance import update_last_perf_entry
from whisp.gui.settings_dialog import SettingsDialog

# ──────────────────────────────────────────────────────────────────────────────
#  Icon resources & animation frames
# -----------------------------------------------------------------------------
ASSETS_DIR = (Path(__file__).resolve().parent / ".." / "assets").resolve()

# Filename lists only – actual QIcon objects are created *after* QApplication
_IDLE_NAME = "whisp-0.png"
_REC_NAMES = [f"whisp-{i}.png" for i in range(1, 10)]  # 1 … 9
_TRANS_ORDER = ["whisp-0.png", "whisp-9.png", "whisp-1.png", "whisp-9.png"]

class WhispTrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)
        self.status = "Whisp"
        self.last_transcript = ""
        self.thread = None

        # ── Icon creation (needs QApplication to exist) ───────────────────
        self.icon_idle = QIcon(str(ASSETS_DIR / _IDLE_NAME))
        self.icons_recording = [QIcon(str(ASSETS_DIR / n)) for n in _REC_NAMES]
        self.icons_transcribing = [QIcon(str(ASSETS_DIR / n)) for n in _TRANS_ORDER]

        # ── Tray icon & animation timer ────────────────────────────────────
        self.tray = QSystemTrayIcon(self.icon_idle)

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._advance_frame)
        self._anim_frames: list[QIcon] = []
        self._anim_index: int = 0

        self.menu = QMenu()

        # Start/Stop Recording action
        self.record_action = QAction("Start Recording")
        self.record_action.triggered.connect(self.toggle_recording)
        self.menu.addAction(self.record_action)

        # --- New top-level actions --------------------------------------
        # Session Log (opens viewer with option to save)
        self.session_log_action = QAction("Session Log")
        self.session_log_action.triggered.connect(
            lambda _=False: session_log_dialog(None, self.logger)
        )

        # Settings (config editor)
        self.settings_action = QAction("Settings")
        self.settings_action.triggered.connect(
            lambda _=False: self._open_settings()
        )

        # Performance window
        self.performance_action = QAction("Performance")
        self.performance_action.triggered.connect(
            lambda _=False: show_performance_dialog(None, self.cfg)
        )

        # Quit action (kept as before)
        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit_app)

        # Voice model management submenu (lightweight label + dialog launcher)
        self.menu.addMenu(self.build_model_menu())
        # ── Visual separation
        self.menu.addSeparator()
        # AIPP
        self.menu.addMenu(self.build_aipp_menu())
        self.menu.addSeparator()

        # Add the new flat actions right away
        self.menu.addAction(self.session_log_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.performance_action)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def set_status(self, text):
        if QApplication.instance().thread() != QThread.currentThread():
            QTimer.singleShot(0, lambda: self.set_status(text))
            return
        self.status = text
        self.tray.setToolTip(f"Whisp - {text}")
        # ── Animation handling based on status ─────────────────────────────
        if text == "Recording":
            self._start_animation(self.icons_recording, total_period_ms=500)
        elif text in ("Transcribing", "Typing"):
            self._start_animation(self.icons_transcribing, total_period_ms=1000)
        else:  # idle or unknown → stop anim
            self._stop_animation()
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
            # ── Prompt for accuracy rating (GUI thread safe) -------------
            if self.cfg.perf_collect and self.cfg.perf_accuracy_rating_collect:
                from PyQt6.QtWidgets import QInputDialog
                s, ok = QInputDialog.getText(
                    None,
                    "Accuracy Rating",
                    "Rate transcription accuracy (0-100 %):",
                )
                if ok and s.strip():
                    try:
                        val = float(s.strip())
                        update_last_perf_entry(val)
                    except ValueError:
                        pass  # ignore invalid input
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
        aipp_menu.addSeparator()

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
        # Voice model management
        self.menu.addMenu(self.build_model_menu())
        self.menu.addSeparator()
        # AIPP
        self.menu.addMenu(self.build_aipp_menu())
        self.menu.addSeparator()

        # Top-level helpers (already created in __init__)
        self.menu.addAction(self.session_log_action)
        self.menu.addAction(self.settings_action)
        self.menu.addAction(self.performance_action)
        self.menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.menu)

    # ──────────────────────────────────────────────────────────────────────
    #  Animation helpers
    # ----------------------------------------------------------------------
    def _start_animation(self, frames: list[QIcon], total_period_ms: int) -> None:
        """Start looping animation with *frames* covering *total_period_ms*."""
        if not frames:
            return
        interval = max(1, total_period_ms // len(frames))
        self._anim_frames = frames
        self._anim_index = 0
        self.tray.setIcon(frames[0])
        self._anim_timer.stop()
        self._anim_timer.start(interval)

    def _stop_animation(self) -> None:
        """Stop any running animation and restore idle icon."""
        if self._anim_timer.isActive():
            self._anim_timer.stop()
        self.tray.setIcon(self.icon_idle)

    def _advance_frame(self) -> None:
        """Slot: advance to next frame in the running animation."""
        if not self._anim_frames:
            return
        self._anim_index = (self._anim_index + 1) % len(self._anim_frames)
        self.tray.setIcon(self._anim_frames[self._anim_index])

    # ──────────────────────────────────────────────────────────────────────
    #  Model Management helpers (NEW)
    # ----------------------------------------------------------------------
    def build_model_menu(self):
        """Return a lightweight menu with current model and a Manage… action."""
        menu = QMenu("Whisper Models", self.menu)

        cur_name = Path(self.cfg.data.get("model_path", "")).name or "(none)"
        cur_act = QAction(f"Current: {cur_name}", menu)
        cur_act.setEnabled(False)
        menu.addAction(cur_act)
        menu.addSeparator()

        manage_act = QAction("Voice models", menu)
        manage_act.triggered.connect(lambda _=False: self._open_model_manager())
        menu.addAction(manage_act)
        return menu

    def _open_model_manager(self):
        show_model_manager(None)
        # reload config in case model changed
        self.cfg.load()
        self.refresh_tray_menu()

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, parent=None)
        if dlg.exec():
            # After saving, refresh menu and cfg instance
            self.cfg.load()  # reload from disk
            self.refresh_tray_menu()

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
