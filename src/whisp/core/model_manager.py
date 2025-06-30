"""whisp.core.model_manager - Qt dialog for managing Whisper models.

Usage:
    from whisp.core.model_manager import show_model_manager
    show_model_manager(parent)
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, QPushButton,
    QWidget, QHBoxLayout, QProgressBar, QMessageBox
)

from whisp.core.config import get_config
from whisp import models as mdl

_CFG = get_config()


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
#   Dialog implementation
# ---------------------------------------------------------------------------
class ModelManager(QDialog):
    """Qt dialog that lists all models and allows install / remove / activate."""

    COL_NAME = 0
    COL_SIZE = 1
    COL_STATUS = 2
    COL_ACTION = 3

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Whisper Models")
        self.setMinimumWidth(600)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Size", "Status", "Action"])
        header = self.table.horizontalHeader()
        if header is not None:  # appease static checkers
            header.setStretchLastSection(True)
        layout.addWidget(self.table)

        self._populate()

    # ------------------------------------------------------------------
    def _populate(self):
        self.table.setRowCount(0)
        active_path = Path(_CFG.data.get("model_path", "")).name
        local_set = set(mdl.list_local())

        for key, (size_mb, *_rest) in mdl.CATALOGUE.items():
            row = self.table.rowCount()
            self.table.insertRow(row)

            fname = f"ggml-{key}.bin"
            # Name ----------------------------------------------------
            self.table.setItem(row, self.COL_NAME, QTableWidgetItem(fname))
            # Size ----------------------------------------------------
            self.table.setItem(row, self.COL_SIZE, QTableWidgetItem(f"{size_mb} MB"))

            # Status --------------------------------------------------
            if fname == active_path:
                status = "Active"
            elif fname in local_set:
                status = "Installed"
            else:
                status = "Remote"
            self.table.setItem(row, self.COL_STATUS, QTableWidgetItem(status))

            # Action widget -------------------------------------------
            cell_widget: QWidget
            if status == "Active":
                cell_widget = QWidget()  # empty (could add label)
            elif status == "Installed":
                cell_widget = self._make_installed_actions(key)
            else:  # Remote
                cell_widget = self._make_download_action(key)

            self.table.setCellWidget(row, self.COL_ACTION, cell_widget)

            # Visual tweaks -------------------------------------------
            if status == "Active":
                for col in range(0, 4):
                    item = self.table.item(row, col)
                    if item:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        item.setForeground(Qt.GlobalColor.darkGreen)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)

        self.table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    def _make_installed_actions(self, key: str) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)

        btn_activate = QPushButton("Activate")
        btn_remove = QPushButton("Remove")
        hl.addWidget(btn_activate)
        hl.addWidget(btn_remove)

        btn_activate.clicked.connect(lambda _=False, k=key: self._on_activate(k))
        btn_remove.clicked.connect(lambda _=False, k=key: self._on_remove(k))
        return w

    def _make_download_action(self, key: str) -> QWidget:
        w = QWidget()
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)

        btn_dl = QPushButton("Download")
        hl.addWidget(btn_dl)

        btn_dl.clicked.connect(lambda _=False, k=key: self._start_download(k, w))
        return w

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_activate(self, key: str):
        mdl.set_active(key)
        _CFG.load()  # refresh singleton
        self._populate()

    def _on_remove(self, key: str):
        mdl.remove(key)
        if Path(_CFG.data.get("model_path", "")).name == f"ggml-{key}.bin":
            _CFG.set("model_path", "")
            _CFG.save()
        self._populate()

    def _start_download(self, key: str, cell_widget: QWidget):
        # replace button with progress bar
        pb = QProgressBar()
        pb.setRange(0, 100)
        layout = cell_widget.layout()
        if layout is not None:
            for i in reversed(range(layout.count())):
                item = layout.itemAt(i)
                if item is not None:
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()
            layout.addWidget(pb)

        thread = _DownloadThread(key)
        thread.progress.connect(lambda done, total: pb.setValue(int(done / total * 100)))

        def _done(path: Path):
            thread.deleteLater()
            self._populate()
            QMessageBox.information(self, "Download complete", f"Installed {path.name}")

        def _fail(msg: str):
            thread.deleteLater()
            QMessageBox.warning(self, "Download failed", msg)
            self._populate()

        thread.finished_ok.connect(_done)
        thread.failed.connect(_fail)
        thread.start()


# ---------------------------------------------------------------------------
#   Convenience wrapper
# ---------------------------------------------------------------------------

def show_model_manager(parent: QWidget | None = None):
    dlg = ModelManager(parent)
    dlg.exec()
    return dlg 