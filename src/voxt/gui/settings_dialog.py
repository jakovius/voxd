from __future__ import annotations

"""Form-style settings dialog shared by GUI & tray modes.

This replaces the previous table-based ConfigEditorDialog with a
friendlier layout that mirrors the look of the existing "AI
Post-Processing" window.  Only the most common parameters are exposed –
advanced/nested settings can still be edited via the raw YAML editor.
"""

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QPushButton,
    QFileDialog,
    QComboBox,
    QDialogButtonBox,
    QScrollArea,
    QWidget,
    QSizePolicy,
    QAbstractButton,
)

from voxt.core.config import AppConfig


class SettingsDialog(QDialog):
    """Modal dialog to view & edit VOXT configuration."""

    settingsChanged = pyqtSignal()  # emitted after successful save

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.cfg = cfg
        # Let the dialog size adapt naturally to its contents;
        # scroll-area will provide overflow protection.

        # Keep mapping from key → widget for save()
        self._widgets: Dict[str, Any] = {}

        # ---- Layout scaffold ------------------------------------------------
        main_vbox = QVBoxLayout(self)

        # Notice about global shortcut
        hint = QLabel(
            "<b>Global shortcut</b>: <i>Set up a custom keyboard shortcut that runs: </i>"
            "<code>bash -c 'voxt --trigger-record'</code> <i>(e.g. Super+R)</i>."
        )
        hint.setWordWrap(True)
        main_vbox.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scroll.setWidget(inner)

        # ------------------------------------------------------------------
        #  General Section
        # ------------------------------------------------------------------
        form.addRow(self._section_label("General"), QLabel(""))

        self._add_checkbox(form, "simulate_typing", "Simulate typing")
        self._add_spin(form, "typing_delay", "Typing delay (ms)", 0, 1000)
        self._add_doublespin(form, "typing_start_delay", "Start delay (s)", 0, 5, step=0.05)
        self._add_checkbox(form, "ctrl_v_paste", "Use Ctrl+V paste")
        self._add_checkbox(form, "append_trailing_space", "Add trailing space when typing")

        # ------------------------------------------------------------------
        #  Logging & Performance
        # ------------------------------------------------------------------
        form.addRow(self._section_label("Logging / Performance"), QLabel(""))

        self._add_checkbox(form, "log_enabled", "Session logging enabled")
        self._add_filepicker(form, "log_location", "Change", dir_only=True)

        perf_chk = self._add_checkbox(form, "perf_collect", "Collect performance metrics")
        acc_chk = self._add_checkbox(
            form,
            "perf_accuracy_rating_collect",
            "Ask for user accuracy rating",
        )
        # dependent enable state
        acc_chk.setEnabled(perf_chk.isChecked())
        perf_chk.toggled.connect(acc_chk.setEnabled)

        # ------------------------------------------------------------------
        #  Typing / Clipboard behaviour (already part of General)
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        #  AIPP basics (leave advanced to dedicated window)
        # ------------------------------------------------------------------
        form.addRow(self._section_label("AI Post-Processing"), QLabel(""))

        aipp_enabled = self._add_checkbox(form, "aipp_enabled", "Enable AIPP")

        provider_combo = QComboBox()
        providers = ["ollama", "openai", "anthropic", "xai", "llamacpp_server", "llamacpp_direct"]
        provider_combo.addItems(providers)
        provider_combo.setCurrentText(self.cfg.data.get("aipp_provider", "ollama"))
        form.addRow("Provider", provider_combo)
        self._widgets["aipp_provider"] = provider_combo

        model_combo = QComboBox()
        self._populate_models(model_combo, provider_combo.currentText())
        form.addRow("Model", model_combo)
        self._widgets["aipp_selected_model"] = model_combo

        # refresh model list when provider changes
        provider_combo.currentTextChanged.connect(lambda p: self._populate_models(model_combo, p))

        # Disable provider/model combos if AIPP disabled
        def _toggle_aipp_widgets(state: bool):
            provider_combo.setEnabled(state)
            model_combo.setEnabled(state)
        _toggle_aipp_widgets(aipp_enabled.isChecked())
        aipp_enabled.toggled.connect(_toggle_aipp_widgets)

        # ------------------------------------------------------------------
        #  Whisper binary & model path helpers
        # ------------------------------------------------------------------
        form.addRow(self._section_label("Whisper‬ paths"), QLabel(""))

        self._add_filepicker(form, "whisper_binary", "Browse", filter="Executable (*)")
        self._add_filepicker(form, "whisper_model_path", "Browse", filter="*.bin")

        # ------------------------------------------------------------------
        #  Fin
        # ------------------------------------------------------------------
        main_vbox.addWidget(scroll)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        main_vbox.addWidget(btn_box)

        # Finally, adjust size to fit contents (within screen limits)
        # Ensure dialog wide enough so horizontal scroll never appears.
        # Calculate content width (= form widget's sizeHint) and add a small
        # margin plus vertical-scrollbar width (if shown).
        inner_widget = scroll.widget() if scroll.widget() is not None else QWidget()
        content_w = inner_widget.sizeHint().width()  # type: ignore[call-arg]
        vsb = scroll.verticalScrollBar()
        vscroll_w = vsb.sizeHint().width() if vsb is not None else 16  # type: ignore[call-arg]
        self.setMinimumWidth(content_w + vscroll_w + 24)  # 24 px padding

        self.adjustSize()

    # ──────────────────────────────────────────────────────────────────
    #  Helpers to add rows
    # ------------------------------------------------------------------
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(f"<b>{text}</b>")
        return lbl

    def _add_checkbox(self, form: QFormLayout, key: str, label: str) -> QPushButton:
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setChecked(bool(self.cfg.data.get(key, False)))
        btn.setFixedSize(20, 20)
        
        def update_style():
            if btn.isChecked():
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #E03D00;
                        border: 2px solid #777;
                        border-radius: 3px;
                        color: white;
                        font-weight: bold;
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
        
        update_style()
        btn.toggled.connect(lambda: update_style())
        
        form.addRow(label, btn)
        self._widgets[key] = btn
        return btn

    def _add_spin(self, form: QFormLayout, key: str, label: str, mn: int, mx: int) -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(mn, mx)
        sb.setValue(int(self.cfg.data.get(key, 0)))
        form.addRow(label, sb)
        self._widgets[key] = sb
        return sb

    def _add_doublespin(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        mn: float,
        mx: float,
        step: float = 0.1,
    ) -> QDoubleSpinBox:
        dsb = QDoubleSpinBox()
        dsb.setRange(mn, mx)
        dsb.setSingleStep(step)
        dsb.setDecimals(2)
        dsb.setValue(float(self.cfg.data.get(key, 0.0)))
        form.addRow(label, dsb)
        self._widgets[key] = dsb
        return dsb

    def _add_filepicker(
        self,
        form: QFormLayout,
        key: str,
        button_label: str,
        dir_only: bool = False,
        filter: str = "*",
    ) -> QPushButton:
        key_label = key.replace("_", " ").title()
        path_lbl = QLabel(str(self.cfg.data.get(key, "")))
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        btn = QPushButton(button_label)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # First row: label + path string
        form.addRow(key_label, path_lbl)
        # Second row: empty label + browse button (spans editor column)
        form.addRow("", btn)

        def browse():
            current_txt = path_lbl.text().strip()
            start_dir: str
            if current_txt:
                try:
                    p = Path(current_txt).expanduser()
                    if dir_only:
                        start_dir = str(p if p.is_dir() else p.parent)
                    else:
                        start_dir = str(p.parent if p.is_file() else p)
                except Exception:
                    start_dir = str(Path.home())
            else:
                start_dir = str(Path.home())

            if dir_only:
                path = QFileDialog.getExistingDirectory(self, "Select folder", start_dir)
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Select file", start_dir, filter)
            if path:
                path_lbl.setText(path)
        btn.clicked.connect(browse)

        # store tuple (label) for save
        self._widgets[key] = path_lbl
        return btn

    def _populate_models(self, combo: QComboBox, provider: str):
        combo.clear()
        models = self.cfg.get_aipp_models(provider)
        combo.addItems(models)
        current = self.cfg.data.get("aipp_selected_models", {}).get(provider, "")
        if current:
            idx = combo.findText(current)
            combo.setCurrentIndex(max(0, idx))

    # ──────────────────────────────────────────────────────────────────
    #  Save
    # ------------------------------------------------------------------
    def _on_save(self):
        # Iterate over widgets, write back into cfg.data
        for key, widget in self._widgets.items():
            # Any checkable button (covers both QCheckBox and our styled QPushButton)
            if isinstance(widget, QAbstractButton) and widget.isCheckable():
                val = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                val = widget.value()
            elif isinstance(widget, QDoubleSpinBox):
                val = float(widget.value())
            elif isinstance(widget, QLineEdit):
                val = widget.text().strip()
            elif isinstance(widget, QLabel):  # from filepicker
                val = widget.text().strip()
            elif isinstance(widget, QComboBox):
                # handle provider vs model
                if key == "aipp_provider":
                    val = widget.currentText()
                elif key == "aipp_selected_model":
                    val = widget.currentText()
                else:
                    val = widget.currentText()
            else:
                continue

            # Map special keys
            if key == "aipp_selected_model":
                provider = self._widgets["aipp_provider"].currentText()  # type: ignore[index]
                self.cfg.data.setdefault("aipp_selected_models", {})[provider] = val
                self.cfg.aipp_model = val  # type: ignore[attr-defined]
                continue

            self.cfg.data[key] = val
            if hasattr(self.cfg, key):
                setattr(self.cfg, key, val)

        # Save YAML
        try:
            self.cfg.save()
            self.settingsChanged.emit()
            self.accept()
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", f"Could not save config:\n{e}") 