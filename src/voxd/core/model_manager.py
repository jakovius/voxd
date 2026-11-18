"""voxd.core.model_manager - Qt page + dialog for managing speech models.

``ModelsPage`` is a plain QWidget so it can be embedded in a settings window;
``ModelManager`` / ``show_model_manager`` wrap it in a dialog.

Layout:
  • "On this computer" – every model on disk with engine, size, Use / Delete,
    and the total space taken;
  • "Available to download" – the catalogue minus what is installed, with an
    engine filter, a search box and one "Download and use" action.

Usage:
    from voxd.core.model_manager import show_model_manager
    show_model_manager(parent)
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QWidget, QHBoxLayout, QProgressBar, QMessageBox, QLabel, QComboBox,
    QLineEdit, QHeaderView, QAbstractItemView,
)

from voxd.core.config import get_config
from voxd import models as mdl

ENGINE_LABEL = {"whisper": "Whisper", "parakeet": "Parakeet"}


def activate_model(path: Path):
    """Make *path* the active model (also switches asr_engine) and refresh the
    shared config so running components pick it up."""
    mdl.set_active(str(path))
    get_config().load()


# ---------------------------------------------------------------------------
#   Background downloader thread
# ---------------------------------------------------------------------------
class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)  # downloaded, total
    finished_ok = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, key: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._key = key

    def run(self):
        try:
            def _cb(done: int, total: int):
                self.progress.emit(done, total)

            path = mdl.ensure(self._key, quiet=True, progress_cb=_cb)
            self.finished_ok.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
#   Page
# ---------------------------------------------------------------------------
class ModelsPage(QWidget):
    """Lists installed and downloadable models; activate / download / delete."""

    changed = pyqtSignal()  # active model or the set of installed models changed

    # installed table
    I_NAME, I_ENGINE, I_SIZE, I_ACTION = range(4)
    # catalogue table
    C_NAME, C_ENGINE, C_SIZE, C_ABOUT, C_ACTION = range(5)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._downloads: dict[str, _DownloadThread] = {}
        self._progress: dict[str, int] = {}

        layout = QVBoxLayout(self)

        # ── On this computer ────────────────────────────────────────────
        head = QHBoxLayout()
        title = QLabel("On this computer")
        title.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.total_label = QLabel("")
        rescan = QPushButton("Rescan")
        rescan.setToolTip("Look again for model files added outside VOXD")
        rescan.clicked.connect(self.refresh)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.total_label)
        head.addWidget(rescan)
        layout.addLayout(head)

        self.installed = self._make_table(["Model", "Engine", "Size", ""])
        layout.addWidget(self.installed, 2)
        self.empty_label = QLabel("No models yet. Pick one below: it downloads, then VOXD uses it.")
        self.empty_label.setStyleSheet("color: #aaa;")
        layout.addWidget(self.empty_label)

        # ── Available to download ───────────────────────────────────────
        head2 = QHBoxLayout()
        title2 = QLabel("Available to download")
        title2.setStyleSheet("font-weight: bold; font-size: 11pt;")
        self.engine_filter = QComboBox()
        self.engine_filter.addItem("All engines", "")
        for eng, label in ENGINE_LABEL.items():
            self.engine_filter.addItem(label, eng)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models…")
        self.search.setClearButtonEnabled(True)
        self.engine_filter.currentIndexChanged.connect(lambda _=0: self._populate_catalogue())
        self.search.textChanged.connect(lambda _="": self._populate_catalogue())
        head2.addWidget(title2)
        head2.addStretch(1)
        head2.addWidget(self.engine_filter)
        head2.addWidget(self.search)
        layout.addLayout(head2)

        self.catalogue = self._make_table(["Model", "Engine", "Size", "About", ""], stretch=self.C_ABOUT)
        layout.addWidget(self.catalogue, 3)

        self.refresh()

    # ------------------------------------------------------------------
    def _make_table(self, headers: list[str], stretch: int = 0) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        vh = t.verticalHeader()
        if vh is not None:
            vh.setVisible(False)
        hh = t.horizontalHeader()
        if hh is not None:
            hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
            # ResizeToContents ignores cell widgets, so the button column is
            # sized by hand in _fit_action_column().
            hh.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Fixed)
        return t

    @staticmethod
    def _fit_action_column(t: QTableWidget):
        """Make the last column and the rows big enough for their buttons —
        button size depends on the desktop style (Breeze pads more than Fusion)."""
        col = t.columnCount() - 1
        width = 0
        for row in range(t.rowCount()):
            w = t.cellWidget(row, col)
            if w is None:
                continue
            hint = w.sizeHint()
            width = max(width, hint.width())
            t.setRowHeight(row, max(t.rowHeight(row), hint.height() + 6))
        if width:
            t.setColumnWidth(col, width + 12)

    def refresh(self):
        self._populate_installed()
        self._populate_catalogue()

    # ------------------------------------------------------------------
    def _populate_installed(self):
        models = mdl.installed_models()
        active = mdl.active_model_path(get_config().data)
        t = self.installed
        t.setRowCount(0)
        for m in models:
            row = t.rowCount()
            t.insertRow(row)
            is_active = active is not None and m.path == active
            name = QTableWidgetItem(m.name)
            name.setToolTip(f"{m.path}\n{mdl.describe(m.name)}")
            cells = [name, QTableWidgetItem(ENGINE_LABEL[m.engine]),
                     QTableWidgetItem(mdl.human_size(m.size_bytes))]
            for col, item in enumerate(cells):
                if is_active:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(Qt.GlobalColor.green)
                t.setItem(row, col, item)
            t.setCellWidget(row, self.I_ACTION, self._installed_actions(m, is_active))

        total = sum(m.size_bytes for m in models)
        self.total_label.setText(
            f"{len(models)} model{'s' if len(models) != 1 else ''} · {mdl.human_size(total)}"
            if models else "")
        self.empty_label.setVisible(not models)
        t.setVisible(bool(models))
        self._fit_action_column(t)

    def _installed_actions(self, m: mdl.InstalledModel, is_active: bool) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(4, 0, 4, 0)
        if is_active:
            lbl = QLabel("✓ In use")
            lbl.setStyleSheet("color: #4caf50; font-weight: bold;")
            hl.addWidget(lbl)
        else:
            use = QPushButton("Use")
            use.clicked.connect(lambda _=False, mm=m: self.activate(mm))
            hl.addWidget(use)
        delete = QPushButton("Delete")
        delete.clicked.connect(lambda _=False, mm=m: self.delete(mm))
        hl.addWidget(delete)
        return w

    # ------------------------------------------------------------------
    def _catalogue_keys(self) -> list[str]:
        """Catalogue keys not on disk that pass the engine filter and search."""
        have = {m.name for m in mdl.installed_models()}
        engine = self.engine_filter.currentData() or ""
        words = self.search.text().lower().split()
        keys = []
        for key in mdl.CATALOGUE:
            fname = mdl._pretty_name(key)
            if fname in have:
                continue
            eng = "parakeet" if mdl.is_parakeet_model(fname) else "whisper"
            if engine and eng != engine:
                continue
            hay = f"{key} {fname} {eng} {mdl.describe(key)}".lower()
            if all(w in hay for w in words):
                keys.append(key)
        return keys

    def _populate_catalogue(self):
        t = self.catalogue
        t.setRowCount(0)
        for key in self._catalogue_keys():
            size_mb = mdl.CATALOGUE[key][0]
            fname = mdl._pretty_name(key)
            eng = "parakeet" if mdl.is_parakeet_model(fname) else "whisper"
            row = t.rowCount()
            t.insertRow(row)
            t.setItem(row, self.C_NAME, QTableWidgetItem(key))
            t.setItem(row, self.C_ENGINE, QTableWidgetItem(ENGINE_LABEL[eng]))
            t.setItem(row, self.C_SIZE, QTableWidgetItem(mdl.human_size(size_mb * 1024 * 1024)))
            t.setItem(row, self.C_ABOUT, QTableWidgetItem(mdl.describe(key)))
            t.setCellWidget(row, self.C_ACTION, self._catalogue_action(key))
        self._fit_action_column(t)

    def _catalogue_action(self, key: str) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(4, 0, 4, 0)
        if key in self._downloads:
            pb = QProgressBar()
            pb.setRange(0, 100)
            pb.setValue(self._progress.get(key, 0))
            pb.setObjectName(f"pb:{key}")
            hl.addWidget(pb)
        else:
            btn = QPushButton("Download and use")
            btn.clicked.connect(lambda _=False, k=key: self.download(k))
            hl.addWidget(btn)
        return w

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def activate(self, m: mdl.InstalledModel):
        if not m.path.exists():
            QMessageBox.warning(self, "Activate failed", f"File not found:\n{m.path}")
        else:
            activate_model(m.path)
            self.changed.emit()
        self.refresh()

    def delete(self, m: mdl.InstalledModel):
        models = mdl.installed_models()
        is_active = mdl.active_model_path(get_config().data) == m.path
        successor = mdl.replacement_for(m, models) if is_active else None
        text = f"Delete {m.name}? It frees {mdl.human_size(m.size_bytes)}."
        if is_active and successor:
            text += f"\n\nIt is the model in use. VOXD will switch to {successor.name}."
        elif is_active:
            text += "\n\nIt is the model in use. VOXD can't transcribe until you pick another."
        answer = QMessageBox.question(
            self, "Delete model", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            mdl.remove_file(m.path)
        except OSError as e:
            QMessageBox.warning(self, "Delete failed", str(e))
            return
        if is_active:
            if successor:
                activate_model(successor.path)
            else:
                self._forget_path(m.path)
        self.changed.emit()
        self.refresh()

    def _forget_path(self, path: Path):
        """Clear config keys that still point at a deleted model."""
        cfg = get_config()
        changed = False
        for key in ("whisper_model_path", "parakeet_model_path"):
            cur = cfg.data.get(key) or ""
            if cur and Path(cur).name == path.name:
                cfg.set(key, "")
                changed = True
        if changed:
            cfg.save()

    def download(self, key: str):
        if key in self._downloads:
            return
        thread = _DownloadThread(key, self)
        self._downloads[key] = thread
        self._progress[key] = 0

        def _progress(done: int, total: int, k=key):
            self._progress[k] = int(done / total * 100) if total else 0
            pb = self.catalogue.findChild(QProgressBar, f"pb:{k}")
            if pb is not None:
                pb.setValue(self._progress[k])

        def _finish(k=key):
            self._downloads.pop(k, None)
            self._progress.pop(k, None)
            thread.deleteLater()

        def _done(path: Path):
            _finish()
            activate_model(path)  # "Download and use"
            self.changed.emit()
            self.refresh()

        def _fail(msg: str):
            _finish()
            self.refresh()
            QMessageBox.warning(self, "Download failed", msg)

        thread.progress.connect(_progress)
        thread.finished_ok.connect(_done)
        thread.failed.connect(_fail)
        thread.start()
        self._populate_catalogue()  # swap the button for a progress bar


# ---------------------------------------------------------------------------
#   Dialog wrapper
# ---------------------------------------------------------------------------
class ModelManager(QDialog):
    """Dialog hosting :class:`ModelsPage`."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Speech Models")
        self.resize(760, 620)
        from voxd.core.voxd_core import DARK_DIALOG_QSS
        self.setStyleSheet(DARK_DIALOG_QSS + """
            QTableWidget { background-color: #1e1e1e; color: white; gridline-color: #444; }
            QHeaderView::section { background-color: #3a3a3a; color: white; border: 1px solid #555; padding: 4px; }
            QLineEdit, QComboBox { background-color: #1e1e1e; color: white; border: 1px solid #555; padding: 3px; }
        """)
        layout = QVBoxLayout(self)
        self.page = ModelsPage(self)
        layout.addWidget(self.page)


def show_model_manager(parent: QWidget | None = None):
    dlg = ModelManager(parent)
    dlg.exec()
    return dlg
