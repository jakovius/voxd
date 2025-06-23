from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QFileDialog, QMessageBox,
    QGroupBox, QHBoxLayout, QCheckBox, QComboBox, QLineEdit, QLabel,
    QTextEdit, QDialogButtonBox, QRadioButton, QGridLayout
)
import yaml
from whisp.core.aipp import get_final_text

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
        from whisp.core.recorder import AudioRecorder
        from whisp.core.transcriber import WhisperTranscriber
        from whisp.core.typer import SimulatedTyper
        from whisp.core.clipboard import ClipboardManager

        recorder = AudioRecorder()
        transcriber = WhisperTranscriber(
            model_path=self.cfg.model_path,
            binary_path=self.cfg.whisper_binary
        )
        typer = SimulatedTyper(delay=self.cfg.typing_delay)
        clipboard = ClipboardManager()

        recorder.start_recording()
        while not self.should_stop:
            self.msleep(100)
        self.status_changed.emit("Transcribing")
        rec_path = recorder.stop_recording(preserve=False)
        tscript, _ = transcriber.transcribe(rec_path)
        if not tscript:
            self.finished.emit("")
            return

        # --- Apply AIPP if enabled ---
        final_text = get_final_text(tscript, self.cfg)

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

        clipboard.copy(final_text)
        if self.cfg.simulate_typing and final_text:
            self.status_changed.emit("Typing")
            typer.type(final_text)
            print()
        self.finished.emit(final_text)

def show_options_dialog(parent, logger, cfg=None, modal=True):
    if cfg is None:
        from whisp.core.config import get_config
        cfg = get_config()
    dialog = QDialog(parent)
    dialog.setWindowTitle("Options")
    dialog.setStyleSheet("background-color: #2e2e2e; color: white;")
    layout = QVBoxLayout()

    # --- AIPP Settings Group ---
    aipp_group = QGroupBox("AI Post-Processing")
    aipp_layout = QVBoxLayout()

    # Enable AIPP
    aipp_enable_cb = QCheckBox("Enable AIPP")
    aipp_enable_cb.setChecked(cfg.data.get("aipp_enabled", False))
    def on_aipp_enable(state):
        cfg.data["aipp_enabled"] = bool(state)
        cfg.aipp_enabled = bool(state)
    aipp_enable_cb.stateChanged.connect(on_aipp_enable)
    aipp_layout.addWidget(aipp_enable_cb)

    # Provider dropdown
    aipp_provider_combo = QComboBox()
    providers = list(cfg.data.get("aipp_models", {"ollama":[]}).keys())
    aipp_provider_combo.addItems(providers)
    current_provider = cfg.data.get("aipp_provider", "ollama")
    aipp_provider_combo.setCurrentText(current_provider)

    # Model dropdown (NEW)
    aipp_model_combo = QComboBox()

    # Helper to (re)populate model combo and select current model
    def update_model_combo(provider):
        aipp_model_combo.clear()
        models = cfg.data.get("aipp_models", {}).get(provider, [])
        aipp_model_combo.addItems(models)
        selected = cfg.data.get("aipp_selected_models", {}).get(provider, "")
        if selected in models:
            aipp_model_combo.setCurrentText(selected)
        elif models:
            aipp_model_combo.setCurrentIndex(0)

    # Helper that syncs all AIPP widgets with cfg (called after external edits)
    def refresh_aipp_ui():
        """Update all AIPP widgets so they reflect current cfg values."""
        prov = cfg.data.get("aipp_provider", "ollama")
        # Provider combo
        aipp_provider_combo.blockSignals(True)
        aipp_provider_combo.setCurrentText(prov)
        aipp_provider_combo.blockSignals(False)

        # Enabled checkbox
        enabled_state = bool(cfg.data.get("aipp_enabled", False))
        aipp_enable_cb.blockSignals(True)
        aipp_enable_cb.setChecked(enabled_state)
        aipp_enable_cb.blockSignals(False)

        # Model list
        update_model_combo(prov)

        # Active prompt label
        aipp_prompt_label.setText(cfg.data.get("aipp_active_prompt", "default"))

    # Populate model combo for initial provider now that helper exists
    update_model_combo(current_provider)

    def on_aipp_provider(text):
        cfg.data["aipp_provider"] = text
        cfg.aipp_provider = text
        update_model_combo(text)        # refresh model list/selection
        cfg.save()                      # persist immediately
    aipp_provider_combo.currentTextChanged.connect(on_aipp_provider)
    aipp_layout.addWidget(QLabel("Provider:"))
    aipp_layout.addWidget(aipp_provider_combo)

    def on_aipp_model(text):
        provider = aipp_provider_combo.currentText()
        cfg.data["aipp_selected_models"][provider] = text
        cfg.aipp_model = text
        cfg.save()
    aipp_model_combo.currentTextChanged.connect(on_aipp_model)
    aipp_layout.addWidget(QLabel("Model:"))
    aipp_layout.addWidget(aipp_model_combo)

    # Active prompt label and manage button
    aipp_prompt_label = QLabel(cfg.data.get("aipp_active_prompt", "default"))
    manage_btn = QPushButton("Manage prompts…")
    manage_btn.clicked.connect(
        lambda _=False: show_manage_prompts(
            dialog,
            cfg,
            after_save_cb=refresh_aipp_ui,
        )
    )
    row = QHBoxLayout()
    row.addWidget(QLabel("Active prompt:"))
    row.addWidget(aipp_prompt_label)
    row.addWidget(manage_btn)
    aipp_layout.addLayout(row)

    aipp_group.setLayout(aipp_layout)
    layout.addWidget(aipp_group)

    # --- Existing options buttons ---
    def show_log():
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
        from whisp.core.config import CONFIG_PATH
        show_config_editor(dialog, str(CONFIG_PATH), after_save_cb=refresh_aipp_ui)

    def run_test():
        QMessageBox.information(dialog, "Testing", "Test utility not implemented yet.")

    def quit_app():
        dialog.close()
        parent.close() if hasattr(parent, "close") else None

    for label, action in [
        ("Show Log", show_log),
        ("Settings", edit_config),
        ("Test", run_test),
        ("Quit", quit_app)
    ]:
        btn = QPushButton(label)
        btn.setFixedSize(100, 20)
        btn.setStyleSheet("background-color: #444; color: white; border-radius: 5px;")
        btn.clicked.connect(action)
        layout.addWidget(btn)

    dialog.setLayout(layout)
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
            from whisp.core.config import get_config
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
    dlg.setMinimumWidth(400)

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
        cfg.aipp_active_prompt = selected_key

        # Persist changes
        cfg.save()

        # Reload the global singleton so every running component sees
        # up-to-date data immediately.
        from whisp.core.config import get_config
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

def show_log_dialog(parent, logger):
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