# pyright: reportMissingImports=false
from PyQt6.QtCore import QThread, pyqtSignal, Qt  # type: ignore
from PyQt6.QtWidgets import (  # type: ignore
    QDialog, QVBoxLayout, QPushButton, QFileDialog, QMessageBox,
    QGroupBox, QHBoxLayout, QCheckBox, QComboBox, QLineEdit, QLabel,
    QTextEdit, QDialogButtonBox, QRadioButton, QGridLayout, QLayout,
    QWidget
)
import yaml
from voxt.core.aipp import get_final_text
from voxt.core.model_manager import show_model_manager
from voxt.core.transcriber import WhisperTranscriber  # type: ignore

class CoreProcessThread(QThread):
    finished = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    
    def __init__(self, cfg, logger):
        super().__init__()
        self.cfg = cfg
        self.logger = logger
        self.should_stop = False

    def stop_recording(self):
        self.should_stop = True

    def run(self):
        from voxt.core.recorder import AudioRecorder
        from voxt.core.typer import SimulatedTyper
        from voxt.core.clipboard import ClipboardManager
        from time import time
        from datetime import datetime
        import psutil

        recorder = AudioRecorder()

        # Ensure whisper-cli exists – attempt auto-build when missing
        from voxt.utils.whisper_auto import ensure_whisper_cli  # local import to avoid GUI deps in headless tests

        try:
            transcriber = WhisperTranscriber(
                model_path=self.cfg.model_path,
                binary_path=self.cfg.whisper_binary,
            )
        except FileNotFoundError:
            # Try to build on the fly (GUI prompt)
            if ensure_whisper_cli("gui") is None:
                # User declined or build failed – abort gracefully
                self.status_changed.emit("VOXT")
                self.finished.emit("")
                return
            transcriber = WhisperTranscriber(
                model_path=self.cfg.model_path,
                binary_path=self.cfg.whisper_binary,
            )
        typer = SimulatedTyper(delay=self.cfg.typing_delay, start_delay=self.cfg.typing_start_delay)
        clipboard = ClipboardManager()

        # ── Recording ---------------------------------------------------
        rec_start_dt = datetime.now()
        recorder.start_recording()
        while not self.should_stop:
            self.msleep(100)
        rec_end_dt = datetime.now()

        self.status_changed.emit("Transcribing")
        rec_path = recorder.stop_recording(preserve=False)

        # ── Transcription ----------------------------------------------
        trans_start_ts = time()
        tscript, _ = transcriber.transcribe(rec_path)
        trans_end_ts = time()
        if not tscript:
            self.finished.emit("")
            return

        # --- Apply AIPP if enabled ---
        aipp_start_ts = aipp_end_ts = None
        final_text = get_final_text(tscript, self.cfg)
        if self.cfg.aipp_enabled and final_text and final_text != tscript:
            aipp_start_ts = time()
            # get_final_text already ran; so timing is approximated. We skip precise.
            aipp_end_ts = aipp_start_ts  # zero duration placeholder due to prior exec

        # === Logging ------------------------------------------------------
        try:
            if self.cfg.aipp_enabled:
                # Log both original and, if different, AIPP output
                self.logger.log_entry(f"[original] {tscript}")
                if final_text and final_text != tscript:
                    self.logger.log_entry(f"[aipp] {final_text}")
            else:
                # AIPP disabled → keep legacy single-line behaviour
                self.logger.log_entry(tscript)
        except Exception:
            pass  # logging failures should never crash the thread

        # Copy to clipboard unless typing is enabled with paste mode (delay <= 0)
        # to avoid double-copying to clipboard
        typing_will_paste = (self.cfg.simulate_typing and 
                           self.cfg.typing_delay <= 0)
        
        if not typing_will_paste and final_text:
            clipboard.copy(final_text)

        if self.cfg.simulate_typing and final_text:
            self.status_changed.emit("Typing")
            try:
                typer.type(final_text)
            except Exception as e:
                print(f"[core] Typing failed: {e}")
            print()

        # ── Accuracy rating (GUI prompt handled in main thread) ---------
        usr_trans_acc = None  # Will be updated by the GUI after the run

        # ── Performance logging ---------------------------------------
        if self.cfg.perf_collect:
            from pathlib import Path as _P
            from voxt.utils.performance import write_perf_entry

            perf_entry = {
                "date": rec_start_dt.strftime("%Y-%m-%d"),
                "rec_start_time": rec_start_dt.strftime("%H:%M:%S"),
                "rec_end_time": rec_end_dt.strftime("%H:%M:%S"),
                "rec_dur": (rec_end_dt - rec_start_dt).total_seconds(),
                "trans_start_time": datetime.fromtimestamp(trans_start_ts).strftime("%H:%M:%S"),
                "trans_end_time": datetime.fromtimestamp(trans_end_ts).strftime("%H:%M:%S"),
                "trans_dur": trans_end_ts - trans_start_ts,
                "trans_eff": (trans_end_ts - trans_start_ts) / max(len(tscript), 1),
                "transcript": tscript,
                "usr_trans_acc": usr_trans_acc,
                "trans_model": _P(self.cfg.model_path).name,
                "aipp_start_time": datetime.fromtimestamp(aipp_start_ts).strftime("%H:%M:%S") if aipp_start_ts else None,
                "aipp_end_time": datetime.fromtimestamp(aipp_end_ts).strftime("%H:%M:%S") if aipp_end_ts else None,
                "aipp_dur": (aipp_end_ts - aipp_start_ts) if aipp_start_ts and aipp_end_ts else None,
                "ai_model": self.cfg.aipp_model if self.cfg.aipp_enabled else None,
                "ai_provider": self.cfg.aipp_provider if self.cfg.aipp_enabled else None,
                "ai_prompt": self.cfg.aipp_active_prompt if self.cfg.aipp_enabled else None,
                "ai_transcript": final_text if self.cfg.aipp_enabled else None,
                "aipp_eff": ((aipp_end_ts - aipp_start_ts) / max(len(final_text), 1)) if self.cfg.aipp_enabled and aipp_start_ts and aipp_end_ts and final_text else None,
                "sys_mem": psutil.virtual_memory().total,
                "sys_cpu": psutil.cpu_freq().max,
                "total_dur": (trans_end_ts - trans_start_ts) + (rec_end_dt - rec_start_dt).total_seconds()
            }
            write_perf_entry(perf_entry)

        self.finished.emit(final_text)

def show_options_dialog(parent, logger, cfg=None, modal=True):
    if cfg is None:
        from voxt.core.config import get_config
        cfg = get_config()
    dialog = QDialog(parent)
    dialog.setWindowTitle("Options")
    dialog.setStyleSheet("background-color: #2e2e2e; color: white;")
    # Let the dialog width adapt automatically to its contents.
    # We'll rely on the layout's fixed-size constraint after we know
    # the natural size of the widest button.
    layout = QVBoxLayout()

    # ------------------------------------------------------------------
    # Buttons (keep list order for UI)
    # ------------------------------------------------------------------

    def _show_whisper_models():
        show_model_manager(dialog)

    def _show_aipp_dialog():
        show_aipp_dialog(dialog, cfg)

    def session_log():
        """Open a window that shows the current session log with Save/Close."""

        log_view = QDialog(dialog)
        log_view.setWindowTitle("Session Log")
        log_view.setMinimumSize(600, 400)
        log_view.setStyleSheet("background-color: #2e2e2e; color: white;")

        vbox = QVBoxLayout(log_view)

        from PyQt6.QtWidgets import QTextEdit, QDialogButtonBox

        text_area = QTextEdit()
        text_area.setReadOnly(True)
        text_area.setStyleSheet("background-color: #1e1e1e; color: white;")
        if logger.entries:
            text_area.setText("\n".join(logger.entries))
        else:
            text_area.setText("No entries logged yet.")
        vbox.addWidget(text_area)

        btn_box = QDialogButtonBox()
        save_btn = btn_box.addButton("Save log…", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Close)

        def on_save():
            # logger.save() will pop the system save dialog in the right folder
            logger.save()

        save_btn.clicked.connect(on_save)
        close_btn.clicked.connect(log_view.close)
        vbox.addWidget(btn_box)

        log_view.setLayout(vbox)
        log_view.exec()

    def edit_config():
        """Open the Settings form dialog."""
        from voxt.gui.settings_dialog import SettingsDialog
        editor = SettingsDialog(cfg, parent=dialog)
        editor.exec()

    # ------------------------------------------------------------------
    # Performance dialog ------------------------------------------------
    def show_performance():
        from voxt.core.voxt_core import show_performance_dialog as _perf
        _perf(dialog, cfg)

    def quit_app():
        dialog.close()
        parent.close() if hasattr(parent, "close") else None

    for label, action in [
        ("Whisper Models", _show_whisper_models),
        ("AI Post-Processing", _show_aipp_dialog),
        ("Session Log", session_log),
        ("Settings", edit_config),
        ("Performance", show_performance),
        ("Quit", quit_app),
    ]:
        btn = QPushButton(label)
        # Slightly wider buttons so long labels are not truncated
        btn.setFixedSize(140, 28)
        btn.setStyleSheet("background-color: #444; color: white; border-radius: 5px;")
        btn.clicked.connect(action)
        layout.addWidget(btn)

    dialog.setLayout(layout)
    # Make the dialog adopt the minimum size that fits the layout
    layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
    # Persist any changes once when dialog closes/finishes
    dialog.finished.connect(lambda _=None: cfg.save())

    if modal:
        dialog.exec()
    else:
        dialog.show()
    return dialog

def show_config_editor(parent, config_path, after_save_cb=None):
    dlg = QDialog(parent)
    dlg.setWindowTitle("Edit Config")
    dlg.setMinimumSize(600, 400)
    layout = QVBoxLayout(dlg)

    # Load config file
    try:
        with open(config_path, "r") as f:
            text = f.read()
    except Exception as e:
        text = ""
        QMessageBox.warning(dlg, "Error", f"Could not load config:\n{e}")

    editor = QTextEdit()
    editor.setPlainText(text)
    layout.addWidget(editor)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(buttons)

    def save():
        try:
            # Validate YAML before saving
            yaml.safe_load(editor.toPlainText())
            with open(config_path, "w") as f:
                f.write(editor.toPlainText())
            # Reload shared config so changes apply immediately
            from voxt.core.config import get_config
            get_config().load()
            if after_save_cb is not None:
                after_save_cb()          # propagate changes to Options UI
            dlg.accept()  # Close dialog after successful save (no popup)
        except Exception as e:
            QMessageBox.warning(dlg, "Error", f"Invalid YAML:\n{e}")

    buttons.accepted.connect(save)
    buttons.rejected.connect(dlg.reject)

    dlg.setLayout(layout)
    dlg.exec()

def show_manage_prompts(parent, cfg, after_save_cb=None, modal=True):
    """Open the AIPP-prompt manager dialog.

    Parameters
    ----------
    parent : QWidget | None
        Parent window (can be *None* for tray mode).
    cfg : AppConfig
        Shared application config instance.
    after_save_cb : callable | None
        Optional callback that will be invoked *after* the user presses
        Save and the config has been written & re-loaded.  Typical use-case
        is refreshing some UI element (e.g. the tray menu) so the newly
        selected prompt becomes visible immediately.
    modal : bool, default *True*
        Whether to run the dialog modally (exec) or modeless (show).
    """

    prompt_keys = ["default", "prompt1", "prompt2", "prompt3"]
    prompts = cfg.data.get("aipp_prompts", {})
    active_key = cfg.data.get("aipp_active_prompt", "default")

    dlg = QDialog(parent)
    dlg.setWindowTitle("Manage AIPP Prompts")
    dlg.setMinimumWidth(300)

    grid = QGridLayout(dlg)

    radio_buttons = []
    text_edits = []

    for i, key in enumerate(prompt_keys):
        rb = QRadioButton()
        rb.setChecked(active_key == key)
        radio_buttons.append(rb)

        te = QTextEdit(prompts.get(key, ""))
        text_edits.append(te)

        grid.addWidget(rb, i, 0)
        grid.addWidget(QLabel(key), i, 1)
        grid.addWidget(te, i, 2)

    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                  QDialogButtonBox.StandardButton.Cancel)
    grid.addWidget(button_box, len(prompt_keys), 0, 1, 3)

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _save_and_close():
        # Determine selected radio
        for i, rb in enumerate(radio_buttons):
            if rb.isChecked():
                selected_key = prompt_keys[i]
                break
        else:
            selected_key = "default"

        # Update prompts in config
        for i, key in enumerate(prompt_keys):
            cfg.data["aipp_prompts"][key] = text_edits[i].toPlainText()

        cfg.data["aipp_active_prompt"] = selected_key
        cfg.aipp_active_prompt = selected_key  # type: ignore[attr-defined]

        # Persist changes
        cfg.save()

        # Reload the global singleton so every running component sees
        # up-to-date data immediately.
        from voxt.core.config import get_config
        get_config().load()

        if after_save_cb is not None:
            after_save_cb()

        dlg.accept()

    def _cancel():
        dlg.reject()

    button_box.accepted.connect(_save_and_close)
    button_box.rejected.connect(_cancel)

    if modal:
        dlg.exec()
    else:
        dlg.show()

    return dlg

# ----------------------------------------------------------------------------
#   Shared session-log viewer
# ----------------------------------------------------------------------------

def session_log_dialog(parent, logger):
    """Open a (modal) window that shows the current session log and offers
    the user to save it via a native file-dialog.

    Parameters
    ----------
    parent : QWidget | None
        Parent for the dialog (can be *None* in tray mode).
    logger : SessionLogger
        Logger instance whose current entries should be displayed and offered
        for saving.
    """

    log_view = QDialog(parent)
    log_view.setWindowTitle("Session Log")
    log_view.setMinimumSize(600, 400)
    log_view.setStyleSheet("background-color: #2e2e2e; color: white;")

    vbox = QVBoxLayout(log_view)

    text_area = QTextEdit()
    text_area.setReadOnly(True)
    text_area.setStyleSheet("background-color: #1e1e1e; color: white;")
    if logger.entries:
        text_area.setText("\n".join(logger.entries))
    else:
        text_area.setText("No entries logged yet.")
    vbox.addWidget(text_area)

    btn_box = QDialogButtonBox()
    save_btn = btn_box.addButton("Save log…", QDialogButtonBox.ButtonRole.ActionRole)
    close_btn = btn_box.addButton(QDialogButtonBox.StandardButton.Close)

    save_btn.clicked.connect(lambda _=False: logger.save())
    close_btn.clicked.connect(log_view.close)

    vbox.addWidget(btn_box)

    log_view.setLayout(vbox)
    log_view.exec()

    return log_view

# ----------------------------------------------------------------------------
#   Performance viewer dialog (shared between GUI & tray)
# ----------------------------------------------------------------------------

def show_performance_dialog(parent, cfg):
    """Open the Performance window showing metrics for the last run."""

    from voxt.paths import DATA_DIR as _DATA_DIR
    import csv
    from pathlib import Path

    dlg = QDialog(parent)
    dlg.setWindowTitle("Performance")
    dlg.setMinimumWidth(500)
    dlg.setStyleSheet("background-color: #2e2e2e; color: white;")

    vbox = QVBoxLayout(dlg)

    # --- Collect toggles (styled) -----------------------------------------
    perf_widget = _create_styled_checkbox("Collect performance data", cfg.data.get("perf_collect", False))
    perf_cb = perf_widget.checkbox_button  # type: ignore[attr-defined]

    acc_widget = _create_styled_checkbox(
        "Collect user transcript accuracy rating",
        cfg.data.get("perf_accuracy_rating_collect", True),
    )
    acc_cb = acc_widget.checkbox_button  # type: ignore[attr-defined]

    def on_perf_toggled(state: bool):
        cfg.data["perf_collect"] = bool(state)
        cfg.perf_collect = bool(state)
        cfg.save()

    def on_acc_toggled(state: bool):
        cfg.data["perf_accuracy_rating_collect"] = bool(state)
        cfg.perf_accuracy_rating_collect = bool(state)
        cfg.save()

    perf_cb.toggled.connect(on_perf_toggled)
    acc_cb.toggled.connect(on_acc_toggled)

    vbox.addWidget(perf_widget)
    vbox.addWidget(acc_widget)

    # --- Data ----------------------------------------------------------------
    data_group = QGroupBox("Last run data")
    grid = QGridLayout(data_group)
    row_idx = 0

    def _add(label, value, emphasize=False):
        nonlocal row_idx
        lbl = QLabel(f"{label}:")
        val_lbl = QLabel(str(value) if value is not None else "")
        if emphasize:
            val_lbl.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl, row_idx, 0)
        grid.addWidget(val_lbl, row_idx, 1)
        row_idx += 1

    last_entry = None
    csv_path = _DATA_DIR / "voxt_perf_data.csv"
    if cfg.perf_collect and csv_path.exists():
        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    last_entry = rows[-1]
        except Exception:
            last_entry = None

    if last_entry:
        from pathlib import Path as _P

        # Fallback: if the CSV row missed the value use current cfg
        trans_model_val = last_entry.get("trans_model") or _P(cfg.model_path).name

        _add("date", last_entry.get("date"))
        _add("rec_start_time", last_entry.get("rec_start_time"))
        _add("trans_eff (s/char)", last_entry.get("trans_eff"), True)
        _add("aipp_eff (s/char)", last_entry.get("aipp_eff"), True)
        _add("usr_trans_acc (%)", last_entry.get("usr_trans_acc"))
        _add("sys_mem", last_entry.get("sys_mem"))
        _add("trans_model", trans_model_val)
        _add("ai_provider", last_entry.get("ai_provider"))
        _add("ai_model", last_entry.get("ai_model"))

        def _short(key: str):
            """Return first 20 chars of value with ellipsis."""
            val = last_entry.get(key) or ""
            return val[:20] + ("…" if len(val) > 20 else "")

        def _length(key: str):
            return len(last_entry.get(key) or "")

        _add("transcript", _short("transcript"))
        _add("ai_prompt (chars)", _length("ai_prompt"))
        _add("ai_transcript (chars)", _length("ai_transcript"))
    else:
        notice = QLabel("The performance data for the last run in the current session. Toggle collect performance data ON to display the latest run performance.")
        notice.setStyleSheet("color: gray; font-size: 8pt;")
        vbox.addWidget(notice)

    vbox.addWidget(data_group)

    # --- Folder link --------------------------------------------------------
    row = QHBoxLayout()
    row.addWidget(QLabel("Any recorded performance data is found here:"))
    open_btn = QPushButton("Open folder…")

    def _open_folder():
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(csv_path.parent)))

    open_btn.clicked.connect(_open_folder)
    row.addWidget(open_btn)
    vbox.addLayout(row)

    dlg.setLayout(vbox)
    dlg.exec()

# ----------------------------------------------------------------------------
#   AIPP settings dialog (extracted from Options)
# ----------------------------------------------------------------------------

def show_aipp_dialog(parent, cfg, modal=True):
    """Open the standalone *AI Post-Processing* settings window.

    This dialog contains exactly the same controls that were previously
    embedded inside the *Options* window, but is now shown from its own
    button so the main menu stays compact.
    """

    if cfg is None:
        from voxt.core.config import get_config  # lazy import to avoid cycles
        cfg = get_config()

    dlg = QDialog(parent)
    dlg.setWindowTitle("AI Post-Processing")
    dlg.setMinimumWidth(300)
    dlg.setStyleSheet("background-color: #2e2e2e; color: white;")

    layout = QVBoxLayout(dlg)

    # Enable AIPP -----------------------------------------------------------
    aipp_widget = _create_styled_checkbox("Enable AIPP", cfg.data.get("aipp_enabled", False))
    aipp_enable_cb = aipp_widget.checkbox_button  # type: ignore[attr-defined]

    def on_aipp_enable(state: bool):
        cfg.data["aipp_enabled"] = bool(state)
        cfg.aipp_enabled = bool(state)  # type: ignore[attr-defined]
        cfg.save()

    aipp_enable_cb.toggled.connect(on_aipp_enable)
    layout.addWidget(aipp_widget)

    # Provider --------------------------------------------------------------
    layout.addWidget(QLabel("Provider:"))
    provider_combo = QComboBox()
    providers = list(cfg.data.get("aipp_models", {"ollama": []}).keys())
    provider_combo.addItems(providers)
    cur_provider = cfg.data.get("aipp_provider", "ollama")
    provider_combo.setCurrentText(cur_provider)
    layout.addWidget(provider_combo)

    # Model list ------------------------------------------------------------
    layout.addWidget(QLabel("Model:"))
    model_combo = QComboBox()
    layout.addWidget(model_combo)

    def _refresh_models(provider: str):
        model_combo.clear()
        models = cfg.data.get("aipp_models", {}).get(provider, [])
        model_combo.addItems(models)
        selected = cfg.data.get("aipp_selected_models", {}).get(provider, "")
        if selected in models:
            model_combo.setCurrentText(selected)
        elif models:
            model_combo.setCurrentIndex(0)

    _refresh_models(cur_provider)

    def on_provider_changed(text):
        cfg.data["aipp_provider"] = text
        cfg.aipp_provider = text  # type: ignore[attr-defined]
        _refresh_models(text)
        cfg.save()

    provider_combo.currentTextChanged.connect(on_provider_changed)

    def on_model_changed(text):
        prov = provider_combo.currentText()
        cfg.data["aipp_selected_models"][prov] = text
        cfg.aipp_model = text  # type: ignore[attr-defined]
        cfg.save()

    model_combo.currentTextChanged.connect(on_model_changed)

    # Active prompt ---------------------------------------------------------
    prompt_row = QHBoxLayout()
    prompt_row.addWidget(QLabel("Active prompt:"))
    prompt_label = QLabel(cfg.data.get("aipp_active_prompt", "default"))
    prompt_row.addWidget(prompt_label)
    layout.addLayout(prompt_row)

    # Manage prompt button --------------------------------------------------
    manage_btn_row = QHBoxLayout()
    manage_btn = QPushButton("Manage prompts")

    def _open_manage_prompts():
        show_manage_prompts(dlg, cfg, after_save_cb=lambda: prompt_label.setText(cfg.data.get("aipp_active_prompt", "default")))

    manage_btn.clicked.connect(_open_manage_prompts)
    manage_btn_row.addWidget(manage_btn)
    layout.addLayout(manage_btn_row)

    dlg.setLayout(layout)

    # Persist changes when dialog closes
    dlg.finished.connect(lambda _=None: cfg.save())

    if modal:
        dlg.exec()
    else:
        dlg.show()

    return dlg

# ────────────────────────────────────────────────────────────────────────────
#  Tiny helper   (styled QPushButton acting as a checkbox)
# ---------------------------------------------------------------------------

def _create_styled_checkbox(text: str, checked: bool = False) -> QWidget:
    """Return a widget consisting of a styled, check-able QPushButton + label.

    The button shows a green background + tick when checked, grey otherwise.
    The returned widget exposes the *button* via attribute ``checkbox_button``
    so callers can connect to its ``toggled`` signal.
    """

    btn = QPushButton()
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setFixedSize(20, 20)

    def _update():
        if btn.isChecked():
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #E03D00;
                    border: 2px solid #777;
                    border-radius: 3px;
                    color: white;
                    font-weight: bold;
                }
                """
            )
            btn.setText("✓")
        else:
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #555;
                    border: 2px solid #777;
                    border-radius: 3px;
                    color: white;
                }
                """
            )
            btn.setText("")

    _update()
    btn.toggled.connect(lambda _: _update())

    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(btn)
    layout.addWidget(QLabel(text))
    layout.addStretch(1)

    # Expose the inner button to callers
    container.checkbox_button = btn  # type: ignore[attr-defined]

    return container