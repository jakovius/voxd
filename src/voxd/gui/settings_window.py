from __future__ import annotations

"""Unified settings window: a sidebar with one page per topic.

Every page applies a change the moment it is made (no Save button) by writing
the shared config and saving it.

Pages
  recognition – engine, model, language, GPU, transcript clean-up, binary paths.
                Rows that don't apply to the active engine are hidden.
  models      – voxd.core.model_manager.ModelsPage.
  typing      – how the transcript is typed or pasted.
  audio       – microphone, levels, recording.
  aipp        – AI post-processing: on/off, provider, model, prompts.
  app         – autostart, logging, performance metrics, global shortcut.

Rows are laid out by SettingRow (title + control, hint underneath, full width)
rather than QFormLayout: form layouts size their fields per desktop style, which
clipped the wrapped hints under Breeze.

Usage:
    from voxd.gui.settings_window import show_settings_window
    show_settings_window(cfg, parent, page="models")
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from voxd import models as mdl
from voxd.core.voxd_core import DARK_DIALOG_QSS
from voxd.utils.languages import ISO_639_1, normalize_lang_code

ENGINES = (("whisper", "Whisper"), ("parakeet", "Parakeet"))
AIPP_PROVIDERS = ("llamacpp_server", "ollama", "openai", "openrouter", "anthropic",
                  "xai", "gigachat", "openai_compatible")

_WINDOW_QSS = DARK_DIALOG_QSS + """
QListWidget#settingsSidebar {
    background-color: #262626; color: white; border: none; outline: none;
    border-right: 1px solid #444; font-size: 10.5pt;
}
QListWidget#settingsSidebar::item { padding: 9px 14px; }
QListWidget#settingsSidebar::item:selected { background-color: #E03D00; color: white; }
QTableWidget { background-color: #1e1e1e; color: white; gridline-color: #444; }
QHeaderView::section { background-color: #3a3a3a; color: white; border: 1px solid #555; padding: 4px; }
QLabel[hint="true"] { color: #a8a8a8; font-size: 9pt; }
QLabel[warn="true"] { color: #ffb74d; }
QScrollArea { border: none; }
"""

PROMPT_SLOTS = ("default", "prompt1", "prompt2", "prompt3")  # fixed by the config schema


def prompt_title(key: str) -> str:
    """"default" → "Default", "prompt2" → "Prompt 2"."""
    return "Default" if key == "default" else f"Prompt {key[len('prompt'):]}"


def _tilde(path) -> str:
    """Path with the home directory shown as ~."""
    p = str(path)
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


CONTROL_WIDTH = 300  # combos / spin boxes / line edits in a row's right column


class ToggleBox(QPushButton):
    """Checkbox drawn the way the rest of the VOXD dialogs draw theirs."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(22, 22)
        self.setChecked(checked)
        self.toggled.connect(lambda _=False: self._restyle())
        self._restyle()

    def _restyle(self):
        on = self.isChecked()
        self.setText("✓" if on else "")
        self.setStyleSheet(
            "QPushButton { background-color: %s; border: 2px solid #777; border-radius: 3px;"
            " color: white; font-weight: bold; padding: 0; }" % ("#E03D00" if on else "#555"))


def _hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("hint", True)
    lbl.setWordWrap(True)
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    return lbl


class SettingRow(QWidget):
    """One setting: title on the left, control on the right, grey hint below
    across the full width. ``wide`` puts the control on its own full-width line."""

    def __init__(self, title: str, control: QWidget | None, hint: str = "", wide: bool = False):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 3, 0, 3)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        self.title = QLabel(title)
        grid.addWidget(self.title, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        row = 1
        if control is not None:
            if wide:
                grid.addWidget(control, 1, 0, 1, 2)
                row = 2
            else:
                grid.addWidget(control, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.hint = _hint_label(hint) if hint else None
        if self.hint is not None:
            grid.addWidget(self.hint, row, 0, 1, 2)


def gpu_device_choices(current: str) -> list[tuple[str, str]]:
    """(label, value) pairs for whisper_gpu_device: Auto + installed Vulkan
    driver vendors; a configured value that no longer enumerates is kept."""
    choices = [("Auto (discrete NVIDIA)", "auto")]
    labels = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
    try:
        from voxd.core.transcriber import _list_vulkan_icd_files, _icd_vendor
        for p in _list_vulkan_icd_files():
            v = _icd_vendor(p)
            if v in labels and (labels[v], v) not in choices:
                choices.append((labels[v], v))
    except Exception:
        pass
    if current and current != "auto" and all(v != current for _, v in choices):
        choices.append((f"{current} (configured)", current))
    return choices


def input_device_choices(current: str) -> list[tuple[str, str]]:
    """(label, value) pairs for audio_input_device: System default + input
    devices; a configured device that is not plugged in right now is kept."""
    choices = [("System default", "")]
    try:
        import sounddevice as sd
        for d in sd.query_devices():
            if d.get("max_input_channels", 0) > 0:
                name = str(d.get("name", "")).strip()
                if name and (name, name) not in choices:
                    choices.append((name, name))
    except Exception:
        pass
    if current and all(v != current for _, v in choices):
        choices.append((f"{current} (configured)", current))
    return choices


# ---------------------------------------------------------------------------
#   Page base: groups, rows, bound controls
# ---------------------------------------------------------------------------
class SettingsPage(QWidget):
    """Scrollable page of grouped SettingRows whose controls are bound to config
    keys: a change is written and saved at once; ``reload()`` re-reads them."""

    changed = pyqtSignal()  # a setting was written to config

    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self._loading = False
        self._loaders: list = []  # callables that push config → widget

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("voxdDialogContent")
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.root = QVBoxLayout(inner)
        self.root.setSpacing(10)

    # ── structure ───────────────────────────────────────────────────────
    def group(self, title: str) -> QVBoxLayout:
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setSpacing(6)
        self.root.addWidget(box)
        return v

    def row(self, layout: QVBoxLayout, title: str, control: QWidget | None,
            hint: str = "", wide: bool = False) -> SettingRow:
        r = SettingRow(title, control, hint, wide)
        layout.addWidget(r)
        return r

    def finish(self):
        self.root.addStretch(1)
        self.reload()

    # ── config plumbing ─────────────────────────────────────────────────
    def set(self, key: str, value):
        """Write one setting and save (no-op while loading or when unchanged)."""
        if self._loading or self.cfg.data.get(key) == value:
            return
        self.cfg.data[key] = value
        if hasattr(self.cfg, key):
            setattr(self.cfg, key, value)
        self.cfg.save()
        self.changed.emit()

    def reload(self):
        self._loading = True
        try:
            for load in self._loaders:
                load()
        finally:
            self._loading = False
        self.after_reload()

    def after_reload(self):
        """Hook for pages with derived state."""

    # ── bound controls ──────────────────────────────────────────────────
    def toggle(self, layout, key: str, title: str, hint: str = "") -> ToggleBox:
        t = ToggleBox()
        t.toggled.connect(lambda state, k=key: self.set(k, bool(state)))
        self._loaders.append(lambda: t.setChecked(bool(self.cfg.data.get(key, False))))
        t.row = self.row(layout, title, t, hint)  # type: ignore[attr-defined]
        return t

    def spin(self, layout, key: str, title: str, hint: str, mn: int, mx: int,
             suffix: str = "") -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(mn, mx)
        sb.setSuffix(suffix)
        sb.setFixedWidth(130)
        sb.valueChanged.connect(lambda v, k=key: self.set(k, int(v)))
        self._loaders.append(lambda: sb.setValue(int(self.cfg.data.get(key, 0) or 0)))
        self.row(layout, title, sb, hint)
        return sb

    def dspin(self, layout, key: str, title: str, hint: str, mn: float, mx: float,
              step: float = 0.05, suffix: str = "") -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(mn, mx)
        sb.setSingleStep(step)
        sb.setDecimals(2)
        sb.setSuffix(suffix)
        sb.setFixedWidth(130)
        sb.valueChanged.connect(lambda v, k=key: self.set(k, round(float(v), 2)))
        self._loaders.append(lambda: sb.setValue(float(self.cfg.data.get(key, 0.0) or 0.0)))
        self.row(layout, title, sb, hint)
        return sb

    def choice(self, layout, key: str, title: str, hint: str, choices, default="") -> QComboBox:
        """Combo bound to *key*. ``choices``: list of (label, value) or a
        callable(current) returning one, re-evaluated on every reload."""
        combo = QComboBox()
        combo.setFixedWidth(CONTROL_WIDTH)

        def _load():
            current = self.cfg.data.get(key, default)
            current = default if current is None else current
            items = choices(current) if callable(choices) else choices
            combo.clear()
            for label, value in items:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(current)))

        def _changed(_=0):
            data = combo.currentData()
            self.set(key, default if data is None else data)

        combo.currentIndexChanged.connect(_changed)
        self._loaders.append(_load)
        combo.row = self.row(layout, title, combo, hint)  # type: ignore[attr-defined]
        return combo

    def path(self, layout, key: str, title: str, hint: str = "", placeholder: str = "",
             dir_only: bool = False, file_filter: str = "All files (*)") -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda k=key: self.set(k, edit.text().strip()))
        browse = QPushButton("Browse…")

        def _browse():
            cur = edit.text().strip()
            start = str(Path(cur).expanduser() if dir_only else Path(cur).expanduser().parent) \
                if cur else str(Path.home())
            if dir_only:
                picked = QFileDialog.getExistingDirectory(self, f"Select {title}", start)
            else:
                picked, _ = QFileDialog.getOpenFileName(self, f"Select {title}", start, file_filter)
            if picked:
                edit.setText(picked)
                self.set(key, picked)

        browse.clicked.connect(lambda _=False: _browse())
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        h.addWidget(browse)
        self._loaders.append(lambda: edit.setText(str(self.cfg.data.get(key, "") or "")))
        edit.row = self.row(layout, title, box, hint, wide=True)  # type: ignore[attr-defined]
        return edit


# ---------------------------------------------------------------------------
#   Recognition
# ---------------------------------------------------------------------------
class RecognitionPage(SettingsPage):
    open_models = pyqtSignal()  # user asked to pick/download a model

    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(cfg, parent)

        g = self.group("Engine and model")
        self.engine = self.choice(
            g, "asr_engine", "Engine",
            "Parakeet: several times faster, less GPU memory, 25 European languages. "
            "Whisper: more languages, best with English terms, slower.",
            [(label, value) for value, label in ENGINES], default="whisper")
        self.engine.currentIndexChanged.connect(lambda _=0: self._sync_engine_rows())

        model_box = QWidget()
        h = QHBoxLayout(model_box)
        h.setContentsMargins(0, 0, 0, 0)
        self.model_label = QLabel("")
        self.model_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        change = QPushButton("Change…")
        change.clicked.connect(lambda _=False: self.open_models.emit())
        h.addWidget(self.model_label)
        h.addWidget(change)
        self.row(g, "Model", model_box)
        self.model_warning = QLabel("")
        self.model_warning.setProperty("warn", True)
        self.model_warning.setWordWrap(True)
        g.addWidget(self.model_warning)

        self.language = QComboBox()
        self.language.setFixedWidth(CONTROL_WIDTH)
        self.language.setEditable(True)
        self.language.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.language.addItem("Auto (detect)", "auto")
        for code, name in sorted(ISO_639_1.items(), key=lambda kv: kv[1]):
            self.language.addItem(f"{name} ({code})", code)
        completer = self.language.completer()
        if completer is not None:
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.language.activated.connect(lambda _=0: self._on_language())
        self._loaders.append(lambda: self.language.setCurrentIndex(max(0, self.language.findData(
            normalize_lang_code(self.cfg.data.get("language", "en"))))))
        self.language_row = self.row(g, "Language", self.language, "Type to search.")
        self.language_note = self.row(g, "Language", QLabel("Detected automatically"),
                                      "Parakeet detects the language itself.")

        g = self.group("Graphics card")
        self.gpu_enabled = self.toggle(
            g, "whisper_gpu_enabled", "Use GPU when available",
            "Off forces CPU. A CPU-only build ignores this.")
        self.gpu_device = self.choice(
            g, "whisper_gpu_device", "GPU device",
            "Only matters with several GPU drivers on a Vulkan build.",
            gpu_device_choices, default="auto")
        self.vram_check = self.toggle(
            g, "whisper_vram_check", "Check free GPU memory first",
            "Goes straight to CPU when the model clearly cannot fit, instead of failing and retrying.")
        self.flash_attn = self.toggle(
            g, "whisper_flash_attn", "Flash attention",
            "Faster and smaller buffers; some Vulkan drivers handle it poorly.")

        g = self.group("Transcript clean-up")
        self.halluc = self.toggle(
            g, "hallucination_filter_enabled", "Drop known phantom phrases",
            "Discards a transcript that is only a phrase Whisper invents on silence "
            "(\"Subscribe to my channel…\").")
        phrases_box = QWidget()
        h = QHBoxLayout(phrases_box)
        h.setContentsMargins(0, 0, 0, 0)
        self.blocklist_count = QLabel("")
        edit = QPushButton("Edit phrases…")
        edit.clicked.connect(lambda _=False: self._edit_blocklist())
        h.addWidget(self.blocklist_count)
        h.addWidget(edit)
        self.row(g, "Phrases", phrases_box)

        g = self.group("Program paths")
        self.whisper_binary = self.path(g, "whisper_binary", "whisper-cli",
                                        file_filter="Executable (*)")
        self.parakeet_binary = self.path(g, "parakeet_binary", "parakeet-cli",
                                         "Empty: found automatically in whisper.cpp/build/bin or $PATH.",
                                         placeholder="auto-detect", file_filter="Executable (*)")
        self._whisper_rows = [self.language_row, self.flash_attn.row, self.whisper_binary.row]
        self._parakeet_rows = [self.language_note, self.parakeet_binary.row]
        self.finish()

    def after_reload(self):
        n = len(self.cfg.data.get("hallucination_blocklist") or [])
        self.blocklist_count.setText(f"{n} phrase{'s' if n != 1 else ''}")
        self._sync_engine_rows()

    def _sync_engine_rows(self):
        """Show only what applies to the active engine; report a missing model."""
        whisper = self.engine.currentData() != "parakeet"
        for r in self._whisper_rows:
            r.setVisible(whisper)
        for r in self._parakeet_rows:
            r.setVisible(not whisper)

        active = mdl.active_model_path(self.cfg.data)
        if active is not None and active.is_file():
            self.model_label.setText(active.name)
            self.model_label.setToolTip(str(active))
            self.model_warning.setVisible(False)
        else:
            self.model_label.setText("(none)")
            self.model_warning.setText(
                f"No {'Whisper' if whisper else 'Parakeet'} model is set up. "
                "Click Change… to pick or download one.")
            self.model_warning.setVisible(True)

    def _on_language(self):
        code = self.language.currentData()
        if code:
            self.set("language", normalize_lang_code(code))

    def _edit_blocklist(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Phantom phrases")
        dlg.setStyleSheet(DARK_DIALOG_QSS)
        dlg.resize(520, 360)
        v = QVBoxLayout(dlg)
        v.addWidget(_hint_label("One phrase per line. A transcript made only of one of these is dropped."))
        edit = QPlainTextEdit("\n".join(str(p) for p in (self.cfg.data.get("hallucination_blocklist") or [])))
        v.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        if dlg.exec():
            self.set_blocklist(edit.toPlainText())

    def set_blocklist(self, text: str):
        self.set("hallucination_blocklist", [ln.strip() for ln in text.splitlines() if ln.strip()])
        self.reload()


# ---------------------------------------------------------------------------
#   Typing
# ---------------------------------------------------------------------------
class TypingPage(SettingsPage):
    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(cfg, parent)
        g = self.group("Typing")
        self.typing = self.toggle(g, "typing", "Type the transcript",
                                  "Off: the text only goes to the clipboard.")
        self.spin(g, "typing_delay", "Delay between characters",
                  "0 pastes the whole text at once.", 0, 1000, " ms")
        self.dspin(g, "typing_start_delay", "Delay before typing",
                   "Time to let the target window regain focus.", 0, 5, 0.05, " s")
        self.toggle(g, "append_trailing_space", "Add a space after the text",
                    "So the next dictation doesn't stick to this one.")

        g = self.group("Paste")
        self.toggle(g, "ctrl_v_paste", "Paste with Ctrl+V",
                    "Off uses Ctrl+Shift+V, which terminals need.")
        self.toggle(g, "paste_unicode", "Paste non-Latin text instead of typing it",
                    "Key emulation drops characters that the active keyboard layout can't produce "
                    "(Cyrillic on a Latin layout).")
        self.toggle(g, "paste_preserve_clipboard", "Restore the clipboard after pasting",
                    "Puts back whatever you had copied before the dictation.")
        self.spin(g, "paste_restore_delay_ms", "Wait before restoring",
                  "Raise this if the old clipboard gets pasted instead of the transcript.",
                  0, 5000, " ms")
        self.finish()


# ---------------------------------------------------------------------------
#   Audio
# ---------------------------------------------------------------------------
class AudioPage(SettingsPage):
    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(cfg, parent)
        g = self.group("Microphone")
        self.device = self.choice(
            g, "audio_input_device", "Input device",
            "\"System default\" follows your PulseAudio/PipeWire default.",
            input_device_choices, default="")
        self.toggle(g, "audio_prefer_pulse", "Prefer the PulseAudio/PipeWire device",
                    "Records through the sound server rather than raw ALSA hardware.")
        self.toggle(g, "mic_autoset_enabled", "Set the microphone level when VOXD starts",
                    "Uses wpctl, pactl or amixer when present.")
        self.dspin(g, "mic_autoset_level", "Microphone level",
                   "0 to 1; applied at startup when the option above is on.", 0, 1, 0.05)

        g = self.group("Processing")
        self.toggle(g, "audio_preproc_enabled", "Tame recordings that are too loud",
                    "Attenuates a recording that peaks above the target below and warns about clipping.")
        self.dspin(g, "audio_peak_dbfs", "Peak level limit",
                   "0 dBFS is the loudest possible.", -30, 0, 0.5, " dBFS")

        g = self.group("Recording")
        from voxd.paths import RECORDINGS_DIR
        self.save_recordings = self.toggle(g, "save_recordings", "Keep audio recordings",
                                           f"Saves every dictation to {RECORDINGS_DIR}")
        self.toggle(g, "record_chunked", "Write long recordings in chunks",
                    "Keeps memory flat during long dictations.")
        self.spin(g, "record_chunk_seconds", "Chunk length", "", 10, 3600, " s")
        self.finish()


# ---------------------------------------------------------------------------
#   AI post-processing
# ---------------------------------------------------------------------------
class AippPage(SettingsPage):
    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(cfg, parent)
        g = self.group("AI post-processing")
        self.enabled = self.toggle(g, "aipp_enabled", "Rewrite the transcript with an AI model",
                                   "Runs the active prompt over every transcript before typing it.")
        self.provider = self.choice(
            g, "aipp_provider", "Provider",
            "llamacpp_server and ollama run on this computer; the others are cloud services.",
            lambda cur: [(p, p) for p in AIPP_PROVIDERS] +
                        ([] if cur in AIPP_PROVIDERS or not cur else [(f"{cur} (configured)", cur)]),
            default="llamacpp_server")
        self.provider.currentIndexChanged.connect(lambda _=0: self._on_provider())

        # API key of a cloud provider (kept in keys.env, not in config.yaml)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setFixedWidth(CONTROL_WIDTH)
        self.api_key.editingFinished.connect(self._on_api_key)
        self.api_key_row = self.row(g, "API key", self.api_key, " ")

        # openai_compatible keeps its endpoint and key in config.yaml
        self.compat_url = QLineEdit()
        self.compat_url.setFixedWidth(CONTROL_WIDTH)
        self.compat_url.setPlaceholderText("https://host/v1")
        self.compat_url.editingFinished.connect(
            lambda: self.set("aipp_openai_compatible_base_url", self.compat_url.text().strip().rstrip("/")))
        self._loaders.append(lambda: self.compat_url.setText(
            str(self.cfg.data.get("aipp_openai_compatible_base_url", "") or "")))
        self.compat_url_row = self.row(g, "Server address", self.compat_url,
                                       "Base URL of an OpenAI-compatible API; /chat/completions is appended.")
        self.compat_key = QLineEdit()
        self.compat_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.compat_key.setFixedWidth(CONTROL_WIDTH)
        self.compat_key.editingFinished.connect(
            lambda: self.set("aipp_openai_compatible_api_key", self.compat_key.text().strip()))
        self._loaders.append(lambda: self.compat_key.setText(
            str(self.cfg.data.get("aipp_openai_compatible_api_key", "") or "")))
        self.compat_key_row = self.row(g, "API key", self.compat_key, "Stored in config.yaml.")

        # proxy for the cloud providers
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText("socks5://127.0.0.1:1080")
        self.proxy.editingFinished.connect(self._on_proxy)
        self._loaders.append(lambda: self.proxy.setText(str(self.cfg.data.get("aipp_proxy", "") or "")))
        self.proxy_test = QPushButton("Test connection")
        self.proxy_test.clicked.connect(lambda _=False: self.test_connection())
        box = QWidget()
        hb = QHBoxLayout(box)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(self.proxy, 1)
        hb.addWidget(self.proxy_test)
        self.proxy_row = self.row(g, "Proxy server", box, " ", wide=True)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.model.setFixedWidth(CONTROL_WIDTH)
        self.model.activated.connect(lambda _=0: self._on_model())
        self.model.lineEdit().editingFinished.connect(self._on_model)
        self.row(g, "Model", self.model,
                 "Pick one from the list, or type the provider's model id and press Enter to add it.")

        g = self.group("Prompt")
        self.prompt = self.choice(
            g, "aipp_active_prompt", "Active prompt",
            "The instruction sent to the model together with every transcript. "
            "Four slots are kept so you can switch between tasks.",
            [(prompt_title(k), k) for k in PROMPT_SLOTS], default="default")
        self.prompt.currentIndexChanged.connect(lambda _=0: self._show_prompt())

        self.prompt_text = QPlainTextEdit()
        self.prompt_text.setMinimumHeight(150)
        self.prompt_text.setPlaceholderText("Empty: the transcript is sent to the model without an instruction.")
        self._prompt_key = "default"          # slot currently shown in the editor
        self._prompt_timer = QTimer(self)     # save shortly after typing stops
        self._prompt_timer.setSingleShot(True)
        self._prompt_timer.setInterval(600)
        self._prompt_timer.timeout.connect(self.save_prompt)
        self.prompt_text.textChanged.connect(self._on_prompt_edited)
        self.row(g, "Prompt text", self.prompt_text, "Saved as you type.", wide=True)

        self.prompt_reset = QPushButton("Restore original text")
        self.prompt_reset.clicked.connect(lambda _=False: self.reset_prompt())
        self.row(g, "", self.prompt_reset)
        self.finish()

    def after_reload(self):
        self._load_models()
        self._show_key()
        self._show_proxy()
        self._show_prompt()

    def _on_provider(self):
        self._load_models()
        self._show_key()
        self._show_proxy()

    # ── proxy ───────────────────────────────────────────────────────────
    PROXY_HINT = ("Requests to the provider go through this proxy; leave empty to connect directly. "
                  "SOCKS5 and HTTP are supported: socks5://host:1080, http://user:password@host:3128.")

    def _set_proxy_hint(self, text: str, warn: bool = False):
        hint = self.proxy_row.hint
        hint.setText(text)
        hint.setProperty("warn", warn)
        hint.style().unpolish(hint)
        hint.style().polish(hint)

    def _show_proxy(self):
        from voxd.core import aipp, api_keys
        provider = self.provider.currentData() or ""
        uses_proxy = provider == "openai_compatible" or provider in aipp.PROVIDER_URLS
        self.proxy_row.setVisible(uses_proxy)
        if not uses_proxy:
            return
        try:
            proxy = aipp.normalize_proxy(self.proxy.text())
        except ValueError as e:
            self._set_proxy_hint(f"Not used: {e}.", warn=True)
            return
        if proxy.startswith("socks") and not aipp.socks_supported():
            self._set_proxy_hint("SOCKS needs the PySocks Python package, which is not installed "
                                 "(pip install PySocks).", warn=True)
            return
        self._set_proxy_hint(self.PROXY_HINT)

    def _on_proxy(self):
        self.set("aipp_proxy", self.proxy.text().strip())
        self._show_proxy()

    def test_connection(self):
        """Reach the provider with the current proxy setting and report the result."""
        from voxd.core import aipp
        self._on_proxy()
        self._set_proxy_hint("Connecting…")
        self.proxy_test.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            ok, message = aipp.check_connection(self.cfg, self.provider.currentData())
        finally:
            QApplication.restoreOverrideCursor()
            self.proxy_test.setEnabled(True)
        self._set_proxy_hint(message, warn=not ok)
        return ok

    # ── API key ─────────────────────────────────────────────────────────
    def _show_key(self):
        """Show the key rows that apply to the provider and say where its key comes from."""
        from voxd.core import api_keys
        provider = self.provider.currentData() or ""
        env = api_keys.PROVIDER_KEY_ENV.get(provider)
        self.api_key_row.setVisible(env is not None)
        for r in (self.compat_url_row, self.compat_key_row):
            r.setVisible(provider == "openai_compatible")
        if env is None:
            return
        self.api_key_row.title.setText("Authorization key" if provider == "gigachat" else "API key")
        source = api_keys.key_source(env)
        self.api_key.blockSignals(True)
        self.api_key.setText(api_keys.read_keys().get(env, ""))
        self.api_key.blockSignals(False)
        if source == "file":
            self.api_key.setPlaceholderText("")
            hint, warn = f"Saved in {_tilde(api_keys.keys_path())}. Clear the field to remove it.", False
        elif source == "environment":
            self.api_key.setPlaceholderText("from the environment")
            hint, warn = (f"Taken from the environment variable {env}. "
                          "Paste a key here to use a different one."), False
        else:
            self.api_key.setPlaceholderText("paste the key")
            hint, warn = (f"No key found. Paste it here, or set {env} in the environment "
                          "VOXD starts with."), True
        self.api_key_row.hint.setText(hint)
        self.api_key_row.hint.setProperty("warn", warn)
        self.api_key_row.hint.style().unpolish(self.api_key_row.hint)
        self.api_key_row.hint.style().polish(self.api_key_row.hint)

    def _on_api_key(self):
        from voxd.core import api_keys
        env = api_keys.PROVIDER_KEY_ENV.get(self.provider.currentData() or "")
        value = self.api_key.text().strip()
        if env is None or self._loading or value == api_keys.read_keys().get(env, ""):
            return
        api_keys.save_key(env, value)
        self._show_key()
        self.changed.emit()

    # ── prompts ─────────────────────────────────────────────────────────
    def _show_prompt(self):
        """Put the active slot's text into the editor (saving the previous slot first)."""
        if not hasattr(self, "prompt_text"):
            return
        self.save_prompt()
        self._prompt_key = self.prompt.currentData() or "default"
        text = (self.cfg.data.get("aipp_prompts") or {}).get(self._prompt_key, "")
        if self.prompt_text.toPlainText() != text:
            self.prompt_text.blockSignals(True)
            self.prompt_text.setPlainText(text)
            self.prompt_text.blockSignals(False)
        self._update_prompt_reset()

    def _on_prompt_edited(self):
        self._prompt_timer.start()
        self._update_prompt_reset()

    def _update_prompt_reset(self):
        from voxd.core.config import DEFAULT_CONFIG
        original = DEFAULT_CONFIG["aipp_prompts"].get(self._prompt_key, "")
        self.prompt_reset.setEnabled(self.prompt_text.toPlainText() != original)

    def save_prompt(self):
        """Write the editor text into its slot (no-op when unchanged)."""
        self._prompt_timer.stop()
        prompts = self.cfg.data.setdefault("aipp_prompts", {})
        text = self.prompt_text.toPlainText()
        if self._loading or prompts.get(self._prompt_key, "") == text:
            return
        prompts[self._prompt_key] = text
        self.cfg.save()
        self.changed.emit()

    def reset_prompt(self):
        from voxd.core.config import DEFAULT_CONFIG
        self.prompt_text.setPlainText(DEFAULT_CONFIG["aipp_prompts"].get(self._prompt_key, ""))
        self.save_prompt()
        self._update_prompt_reset()

    def hideEvent(self, event):
        self.save_prompt()          # don't lose text typed just before closing
        super().hideEvent(event)

    def _load_models(self):
        provider = self.provider.currentData() or self.cfg.data.get("aipp_provider", "")
        selected = (self.cfg.data.get("aipp_selected_models") or {}).get(provider, "")
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems([str(m) for m in self.cfg.get_aipp_models(provider)])
        if selected:
            self.model.setCurrentIndex(max(0, self.model.findText(selected)))
        self.model.blockSignals(False)

    def _on_model(self):
        provider = self.provider.currentData()
        name = self.model.currentText().strip()
        if self._loading or not provider or not name:
            return
        models = self.cfg.data.setdefault("aipp_models", {}).setdefault(provider, [])
        selected = self.cfg.data.setdefault("aipp_selected_models", {})
        if name in models and selected.get(provider) == name:
            return
        if name not in models:               # a model id typed by hand joins the list
            models.append(name)
        selected[provider] = name
        self.cfg.aipp_model = name
        self.cfg.save()
        self._load_models()
        self.changed.emit()


# ---------------------------------------------------------------------------
#   Application
# ---------------------------------------------------------------------------
class AppPage(SettingsPage):
    def __init__(self, cfg, parent: QWidget | None = None):
        super().__init__(cfg, parent)

        g = self.group("Global shortcut")
        cmd = QLabel("<code>bash -c 'voxd --trigger-record'</code>")
        cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.row(g, "Command to bind", cmd,
                 "In your desktop's keyboard settings, add a custom shortcut (e.g. Super+Z) "
                 "that runs this command. It starts and stops recording in every VOXD mode.")

        g = self.group("Startup")
        self.autostart = ToggleBox()
        self.autostart.toggled.connect(lambda state: self._on_autostart(bool(state)))
        self._loaders.append(lambda: self.autostart.setChecked(bool(self.cfg.data.get("autostart", False))))
        self.autostart_row = self.row(g, "Start the tray icon when you log in", self.autostart,
                                      "Enables the voxd-tray user service, or an XDG autostart entry "
                                      "when systemd is unavailable.")
        self.autostart_status = QLabel("")
        self.autostart_status.setProperty("warn", True)
        self.autostart_status.setWordWrap(True)
        self.autostart_status.setVisible(False)
        g.addWidget(self.autostart_status)

        g = self.group("Logging")
        self.toggle(g, "log_enabled", "Keep a session log of transcripts", "")
        self.path(g, "log_location", "Log folder", "Empty: the default data folder.",
                  placeholder="default", dir_only=True)
        self.toggle(g, "verbosity", "Verbose diagnostics",
                    "Writes detailed logs (engine output, GPU selection). Takes effect on restart.")

        g = self.group("Performance metrics")
        self.perf = self.toggle(g, "perf_collect", "Collect timing for every dictation",
                                "Appends recording and transcription times to a CSV in the data folder.")
        self.rating = self.toggle(g, "perf_accuracy_rating_collect", "Ask me to rate accuracy",
                                  "Only while timing collection is on.")
        self.perf.toggled.connect(lambda state: self.rating.setEnabled(bool(state)))
        self.finish()

    def after_reload(self):
        self.rating.setEnabled(self.perf.isChecked())

    def _on_autostart(self, enabled: bool):
        if self._loading or bool(self.cfg.data.get("autostart", False)) == enabled:
            return
        ok, message = apply_autostart(enabled)
        self.cfg.load()  # the autostart handler writes the config itself
        self.autostart_status.setText("" if ok else message)
        self.autostart_status.setVisible(not ok)
        self.reload()
        self.changed.emit()


def apply_autostart(enabled: bool) -> tuple[bool, str]:
    """Enable/disable autostart the way ``voxd --autostart`` does."""
    try:
        from voxd.__main__ import _handle_autostart
        rc = _handle_autostart("true" if enabled else "false")
        return (rc == 0, "" if rc == 0 else "Could not change autostart; run `voxd --autostart "
                f"{'true' if enabled else 'false'}` in a terminal to see why.")
    except Exception as e:  # never let a systemd hiccup break the settings window
        return False, f"Could not change autostart: {e}"


# ---------------------------------------------------------------------------
#   Window
# ---------------------------------------------------------------------------
class SettingsWindow(QDialog):
    """Sidebar + stacked pages. ``cfg`` should be the shared get_config() object."""

    settingsChanged = pyqtSignal()

    PAGES = (("recognition", "Recognition"), ("models", "Models"), ("typing", "Typing"),
             ("audio", "Audio"), ("aipp", "AI processing"), ("app", "Application"))

    def __init__(self, cfg, parent: QWidget | None = None, page: str = "recognition"):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("VOXD Settings")
        self.setStyleSheet(_WINDOW_QSS)
        self.resize(960, 700)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setFixedWidth(170)
        self.stack = QStackedWidget()
        h.addWidget(self.sidebar)
        h.addWidget(self.stack, 1)

        from voxd.core.model_manager import ModelsPage

        self.recognition = RecognitionPage(cfg)
        self.models = ModelsPage()
        self.typing = TypingPage(cfg)
        self.audio = AudioPage(cfg)
        self.aipp = AippPage(cfg)
        self.app = AppPage(cfg)
        self._pages = {"recognition": self.recognition, "models": self.models,
                       "typing": self.typing, "audio": self.audio,
                       "aipp": self.aipp, "app": self.app}

        for name, title in self.PAGES:
            self.sidebar.addItem(QListWidgetItem(title))
            holder = QWidget()
            v = QVBoxLayout(holder)
            v.setContentsMargins(14, 12, 14, 12)
            v.addWidget(self._pages[name])
            self.stack.addWidget(holder)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)

        # keep the pages in step with each other
        self.recognition.open_models.connect(lambda: self.open_page("models"))
        self.recognition.changed.connect(self._on_recognition_changed)
        self.models.changed.connect(self._on_models_changed)
        for p in (self.typing, self.audio, self.aipp, self.app):
            p.changed.connect(self.settingsChanged.emit)

        self.open_page(page)

    def open_page(self, name: str):
        names = [n for n, _ in self.PAGES]
        self.sidebar.setCurrentRow(names.index(name) if name in names else 0)

    def _on_recognition_changed(self):
        self.models.refresh()       # the active model follows the engine
        self.settingsChanged.emit()

    def _on_models_changed(self):
        self.cfg.load()             # the models page writes through a fresh AppConfig
        self.recognition.reload()
        self.settingsChanged.emit()


def show_settings_window(cfg, parent: QWidget | None = None, page: str = "recognition"):
    win = SettingsWindow(cfg, parent, page)
    win.exec()
    return win
