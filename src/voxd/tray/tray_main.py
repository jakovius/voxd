import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QLabel, QWidgetAction,
    QMessageBox
)
from PyQt6.QtGui import QIcon, QAction, QActionGroup, QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QObject, QTimer, QThread
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QStyle

from voxd.core.config import get_config
from voxd.core.logger import SessionLogger
from voxd.utils.ipc_server import start_ipc_server
from voxd.core.voxd_core import (
    CoreProcessThread,
    show_options_dialog,
    session_log_dialog,
    show_performance_dialog,
)
from voxd.utils.performance import update_last_perf_entry
from voxd.gui.settings_window import PROMPT_SLOTS, prompt_title

# ──────────────────────────────────────────────────────────────────────────────
#  Icon resources & animation frames
# -----------------------------------------------------------------------------
ASSETS_DIR = (Path(__file__).resolve().parent / ".." / "assets").resolve()

# Filename lists only – actual QIcon objects are created *after* QApplication
_IDLE_NAME = "voxd-0.png"
# Recording → calm, slow "breathing" pulse that always stays orange (= "listening").
_REC_FRAME_NUMS = [1, 2, 3, 4, 5, 4, 3, 2]
# Transcribing/Typing → fast, one-directional fade sweep that visibly "runs"
# (= "working"). Distinct speed + motion from the recording pulse so the user
# can instantly tell the hotkey press registered and processing has begun.
_TRANS_FRAME_NUMS = list(range(1, 10))  # 1 … 9
_REC_NAMES = [f"voxd-{i}.png" for i in _REC_FRAME_NUMS]
_TRANS_NAMES = [f"voxd-{i}.png" for i in _TRANS_FRAME_NUMS]


def _make_badged_icon(base_pixmap: QPixmap, kind: str) -> QIcon:
    """Composite a small status badge onto *base_pixmap* and return a QIcon.

    ``kind='rec'`` draws a red record dot (●); ``kind='proc'`` draws three
    blue dots (…) to signal post-processing. The badge sits in the
    bottom-right corner on a contrasting white disc so it reads clearly even
    at small tray sizes — an extra cue on top of the per-phase animation.
    """
    px = base_pixmap.copy()
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    w, h = px.width(), px.height()
    d = min(w, h) * 0.42  # badge diameter
    bx, by = w - d, h - d
    cx, cy = bx + d / 2, by + d / 2

    # Contrasting backdrop disc.
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawEllipse(int(bx), int(by), int(d), int(d))

    if kind == "rec":
        r = d * 0.30
        painter.setBrush(QColor(230, 30, 30))
        painter.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
    else:  # 'proc' → three dots
        painter.setBrush(QColor(40, 110, 230))
        dot = d * 0.11
        gap = d * 0.26
        for off in (-gap, 0.0, gap):
            painter.drawEllipse(int(cx + off - dot), int(cy - dot),
                                int(2 * dot), int(2 * dot))

    painter.end()
    return QIcon(px)

def _theme_icon(*names: str) -> QIcon:
    """First icon the desktop theme has among *names* (empty icon if none)."""
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return QIcon()


def elide_middle(text: str, limit: int) -> str:
    """Shorten *text* to *limit* chars by cutting the middle ("large-v3…q5_0")."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    keep = limit - 1
    head = (keep + 1) // 2
    return text[:head] + "…" + text[len(text) - (keep - head):]


def elide_end(text: str, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def short_model_name(fname: str, limit: int = 30) -> str:
    """Menu label for a model file: no ``ggml-`` prefix / ``.bin`` suffix, middle-elided."""
    name = str(fname)
    if name.startswith("ggml-"):
        name = name[5:]
    if name.endswith(".bin"):
        name = name[:-4]
    return elide_middle(name, limit)


# Plasma draws the tray menu itself (DBusMenu) and does not reserve room for
# the submenu arrow, so a long title runs into it.  Non-breaking spaces at the
# end keep the arrow clear of the text.
_ARROW_PAD = "\u00a0" * 4


def submenu_title(text: str) -> str:
    return f"{text}{_ARROW_PAD}"


class VoxdTrayApp(QObject):
    def __init__(self):
        super().__init__()
        self.cfg = get_config()
        self.logger = SessionLogger(self.cfg.log_enabled, self.cfg.log_location)
        self.status = "VOXD"
        self.last_transcript = ""
        self.thread = None
        # True while the user has already been notified that dictation fell
        # back to CPU (VRAM exhausted); reset once a run uses the GPU again.
        self._gpu_note_shown = False

        # ── Icon creation (needs QApplication to exist) ───────────────────
        self.icon_idle = QIcon(str(ASSETS_DIR / _IDLE_NAME))
        self.icons_recording = [
            _make_badged_icon(QPixmap(str(ASSETS_DIR / n)), "rec") for n in _REC_NAMES
        ]
        self.icons_transcribing = [
            _make_badged_icon(QPixmap(str(ASSETS_DIR / n)), "proc") for n in _TRANS_NAMES
        ]

        # ── Tray icon & animation timer ────────────────────────────────────
        self.tray = QSystemTrayIcon(self.icon_idle)

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._advance_frame)
        self._anim_frames: list[QIcon] = []
        self._anim_index: int = 0

        self.menu = QMenu()

        # Start/Stop Recording action
        self.record_action = QAction(_theme_icon("media-record"), "Start Recording")
        bold = self.record_action.font()
        bold.setBold(True)
        self.record_action.setFont(bold)  # the main action stands out
        self.record_action.triggered.connect(self.toggle_recording)

        # --- New top-level actions --------------------------------------
        # Session Log (opens viewer with option to save)
        self.session_log_action = QAction(_theme_icon("view-history", "document-open-recent"), "Session Log…")
        self.session_log_action.triggered.connect(
            lambda _=False: session_log_dialog(None, self.logger)
        )

        # Settings (config editor)
        self.settings_action = QAction(_theme_icon("configure", "preferences-system"), "Settings…")
        self.settings_action.triggered.connect(
            lambda _=False: self._open_settings()
        )

        # Performance window
        self.performance_action = QAction(_theme_icon("view-statistics", "office-chart-line", "utilities-system-monitor"), "Performance…")
        self.performance_action.triggered.connect(
            lambda _=False: show_performance_dialog(None, self.cfg)
        )

        # Quit action (kept as before)
        self.quit_action = QAction(_theme_icon("application-exit"), "Quit")
        self.quit_action.triggered.connect(self.quit_app)

        self._populate_menu()

        self.tray.setContextMenu(self.menu)
        self.tray.show()

    def set_status(self, text):
        if QApplication.instance().thread() != QThread.currentThread():
            QTimer.singleShot(0, lambda: self.set_status(text))
            return
        self.status = text
        self.tray.setToolTip(f"VOXD - {text}")
        # ── Animation handling based on status ─────────────────────────────
        if text == "Recording":
            # Calm, slow breathing pulse → "listening".
            self._start_animation(self.icons_recording, total_period_ms=1400)
        elif text in ("Transcribing", "Typing"):
            # Fast running fade → "working" (clearly distinct from recording).
            self._start_animation(self.icons_transcribing, total_period_ms=600)
        else:  # idle or unknown → stop anim
            self._stop_animation()
        self.record_action.setText(
            "Start Recording" if text == "VOXD" else ("Stop Recording" if text == "Recording" else f"{text}...")
        )
        self.record_action.setIcon(
            _theme_icon("media-playback-stop") if text == "Recording" else _theme_icon("media-record"))
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
        self.thread.gpu_note.connect(self.on_gpu_note, Qt.ConnectionType.QueuedConnection)
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
        self.set_status("VOXD")

    def on_gpu_note(self, note: str):
        """Desktop-notify when a dictation fell back to CPU (VRAM exhausted).

        Shown once per degradation episode: repeated CPU runs stay quiet until
        a run uses the GPU again (empty note), which re-arms the notification.
        """
        if not note:
            self._gpu_note_shown = False
            return
        if self._gpu_note_shown:
            return
        self._gpu_note_shown = True
        self.tray.showMessage(
            "VOXD — GPU not used",
            note,
            QSystemTrayIcon.MessageIcon.Warning,
            10_000,
        )

    def show_options(self):
        show_options_dialog(None, self.logger, cfg=self.cfg)

    def quit_app(self):
        print()
        QApplication.quit()

    def build_aipp_menu(self):
        aipp_enabled = bool(self.cfg.data.get("aipp_enabled", False))
        current_provider = self.cfg.data.get("aipp_provider", "ollama")
        selected_model = self.cfg.data.get("aipp_selected_models", {}).get(current_provider, "")
        state = elide_middle(selected_model or current_provider, 26) if aipp_enabled else "Off"
        aipp_menu = QMenu(submenu_title(f"AI Processing: {state}"), self.menu)
        aipp_menu.setIcon(_theme_icon("tools-wizard", "applications-science"))

        enabled_action = QAction("Enabled", aipp_menu, checkable=True)
        enabled_action.setChecked(aipp_enabled)
        enabled_action.toggled.connect(self.toggle_aipp_enabled)
        aipp_menu.addAction(enabled_action)
        aipp_menu.addSeparator()

        # Prompt slots, flat: the one thing worth switching from the tray
        active_prompt = self.cfg.data.get("aipp_active_prompt", "default")
        group = QActionGroup(aipp_menu)
        for key in PROMPT_SLOTS:
            text = " ".join(str(self.cfg.data.get("aipp_prompts", {}).get(key, "")).split())
            label = f"{prompt_title(key)}: {elide_end(text, 38)}" if text else f"{prompt_title(key)} (empty)"
            act = QAction(label, aipp_menu, checkable=True)
            act.setActionGroup(group)
            act.setChecked(key == active_prompt)
            act.triggered.connect(lambda checked, k=key: self.set_aipp_prompt(k))
            aipp_menu.addAction(act)
        aipp_menu.addSeparator()

        # Provider, model, API key and prompt texts live in the settings window
        using = QAction(elide_middle(f"{current_provider} · {selected_model or 'no model'}", 44), aipp_menu)
        using.setEnabled(False)
        aipp_menu.addAction(using)
        settings_action = QAction("Provider, model, prompts…", aipp_menu)
        settings_action.triggered.connect(lambda _=False: self._open_settings(page="aipp"))
        aipp_menu.addAction(settings_action)
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

    def refresh_tray_menu(self):
        # Rebuild the menu so titles and checkmarks follow the config
        self.menu.clear()
        self._populate_menu()
        self.tray.setContextMenu(self.menu)

    def _populate_menu(self):
        """Fill the tray menu. Layout: record · what is used (model, language,
        AI processing) · windows · quit. Submenu titles carry the current value
        so the state is readable without opening them."""
        m = self.menu
        m.addAction(self.record_action)
        m.addSeparator()

        m.addMenu(self.build_model_menu())
        if self.cfg.data.get("asr_engine") != "parakeet":  # Parakeet detects the language itself
            from voxd.utils.languages import code_to_name
            code = str(self.cfg.data.get("language", "en"))
            lang_action = QAction(_theme_icon("preferences-desktop-locale", "applications-education-language"),
                                  f"Language: {code_to_name(code)}…", m)  # parented: an orphan QAction is GC'd
            lang_action.triggered.connect(lambda _=False: self._open_language())
            m.addAction(lang_action)
        m.addMenu(self.build_aipp_menu())
        m.addSeparator()

        m.addAction(self.session_log_action)
        m.addAction(self.performance_action)
        m.addAction(self.settings_action)
        m.addSeparator()
        m.addAction(self.quit_action)

    def _open_language(self):
        from voxd.core.voxd_core import show_language_dialog
        show_language_dialog(None, self.cfg)
        self.refresh_tray_menu()

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
        """Submenu: installed models (click to switch model + engine) and Manage…"""
        from voxd import models as mdl

        models = mdl.installed_models()
        active = mdl.active_model_path(self.cfg.data)
        current = next((m for m in models if m.path == active), None)
        menu = QMenu(submenu_title(f"Model: {short_model_name(current.name) if current else '(none)'}"), self.menu)
        menu.setIcon(_theme_icon("audio-input-microphone"))
        menu.setToolTipsVisible(True)

        for m in models:
            act = QAction(f"{short_model_name(m.name, 40)}   ·   {mdl.human_size(m.size_bytes)}", menu)
            act.setToolTip(str(m.path))
            act.setCheckable(True)
            act.setChecked(m is current)
            act.triggered.connect(lambda _=False, mm=m: self._switch_model(mm.path))
            menu.addAction(act)
        if not models:
            none_act = QAction("No models installed", menu)
            none_act.setEnabled(False)
            menu.addAction(none_act)
        menu.addSeparator()

        manage_act = QAction("Manage models…", menu)
        manage_act.triggered.connect(lambda _=False: self._open_model_manager())
        menu.addAction(manage_act)
        return menu

    def _switch_model(self, path):
        """Activate an installed model (also selects its engine)."""
        from voxd.core.model_manager import activate_model
        activate_model(path)
        self.cfg.load()
        self.refresh_tray_menu()

    def _open_model_manager(self):
        self._open_settings(page="models")

    def _open_settings(self, page: str = "recognition"):
        from voxd.gui.settings_window import show_settings_window
        show_settings_window(self.cfg, None, page)
        # pages apply as you go – pick up whatever changed
        self.cfg.load()
        self.refresh_tray_menu()

def main():
    app = QApplication(sys.argv)
    # Prevent tray-only sessions from quitting when the last dialog closes
    app.setQuitOnLastWindowClosed(False)
    tray_app = VoxdTrayApp()

    def on_ipc_trigger():
        QTimer.singleShot(0, tray_app.toggle_recording)

    start_ipc_server(on_ipc_trigger)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
