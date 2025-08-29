from __future__ import annotations

import sys
import math
import queue
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from PyQt6 import QtWidgets, QtCore

from voxt.core.config import AppConfig
from voxt.utils.libw import verr, verbo
from voxt.flux.flux_main import EnergyVAD  # reuse implementation


try:
    import pyqtgraph as pg
except Exception as e:
    pg = None
    _PG_ERR = e


@dataclass
class TunerState:
    backend: str = "energy"
    sr: int = 16000
    frame_ms: int = 32
    block: int = 512
    sil_start: float = 0.6
    sil_end: float = 0.4
    min_sil_ms: int = 500
    min_sp_ms: int = 200
    en_start_margin: float = 6.0
    en_keep_margin: float = 3.0


class FluxTunerWindow(QtWidgets.QWidget):
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("VOXT Flux Tuner")
        self.resize(900, 520)

        if pg is None:
            QtWidgets.QMessageBox.critical(self, "pyqtgraph missing", f"pyqtgraph is required for tuner. Error: {_PG_ERR}")
            raise SystemExit(1)

        self.state = TunerState(
            backend="energy",
            sr=16000,
            frame_ms=32,
            block=512,
            sil_start=float(cfg.data.get("flux_start_threshold", 0.6)),
            sil_end=float(cfg.data.get("flux_end_threshold", 0.4)),
            min_sil_ms=int(cfg.data.get("flux_min_silence_ms", 500)),
            min_sp_ms=int(cfg.data.get("flux_min_speech_ms", 200)),
            en_start_margin=float(cfg.data.get("flux_energy_start_margin_db", 6.0)),
            en_keep_margin=float(cfg.data.get("flux_energy_keep_margin_db", 3.0)),
        )

        # --- UI ---
        self.plot = pg.PlotWidget()
        self.plot.setYRange(0.0, 1.0)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel('bottom', 'Time', 's')
        self.plot.setLabel('left', 'Normalized energy', '')
        self.curve = self.plot.plot([], [], pen=pg.mkPen(color=(0, 200, 0), width=2))

        # Energy guides
        self.en_line_start = pg.InfiniteLine(angle=0,
                                             pos=0.7,
                                             pen=pg.mkPen((120, 180, 255), style=QtCore.Qt.PenStyle.DashLine))
        self.en_line_keep = pg.InfiniteLine(angle=0,
                                            pos=0.6,
                                            pen=pg.mkPen((80, 140, 220), style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.en_line_start)
        self.plot.addItem(self.en_line_keep)
        self.en_text_start = pg.TextItem(color=(120, 180, 255))
        self.en_text_keep = pg.TextItem(color=(80, 140, 220))
        try:
            self.en_text_start.setAnchor((1, 0.5))
            self.en_text_keep.setAnchor((1, 0.5))
        except Exception:
            pass
        self.plot.addItem(self.en_text_start)
        self.plot.addItem(self.en_text_keep)

        # Fixed backend label
        self.backend_cb = QtWidgets.QComboBox()
        self.backend_cb.addItems(["energy"])  # fixed
        self.backend_cb.setCurrentText("energy")

        self.btn_start = QtWidgets.QPushButton("Start")
        self.btn_stop = QtWidgets.QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_save = QtWidgets.QPushButton("Save to config")

        self.spin_min_sil = QtWidgets.QSpinBox()
        self.spin_min_sil.setRange(50, 3000)
        self.spin_min_sil.setValue(self.state.min_sil_ms)
        self.spin_min_sp = QtWidgets.QSpinBox()
        self.spin_min_sp.setRange(50, 2000)
        self.spin_min_sp.setValue(self.state.min_sp_ms)

        # Energy controls
        self.spin_en_start = QtWidgets.QDoubleSpinBox()
        self.spin_en_start.setRange(0.0, 30.0)
        self.spin_en_start.setDecimals(1)
        self.spin_en_start.setValue(self.state.en_start_margin)
        self.spin_en_keep = QtWidgets.QDoubleSpinBox()
        self.spin_en_keep.setRange(0.0, 30.0)
        self.spin_en_keep.setDecimals(1)
        self.spin_en_keep.setValue(self.state.en_keep_margin)
        # Absolute (normalized) thresholds for Energy
        self.chk_en_abs = QtWidgets.QCheckBox("Use absolute thresholds (normalized)")
        self.chk_en_abs.setChecked(bool(self.cfg.data.get("flux_energy_use_absolute", False)))
        self.spin_en_start_p = QtWidgets.QDoubleSpinBox()
        self.spin_en_start_p.setRange(0.0, 1.0)
        self.spin_en_start_p.setSingleStep(0.01)
        self.spin_en_start_p.setDecimals(2)
        self.spin_en_start_p.setValue(float(self.cfg.data.get("flux_energy_start_p", 0.55)))
        self.spin_en_keep_p = QtWidgets.QDoubleSpinBox()
        self.spin_en_keep_p.setRange(0.0, 1.0)
        self.spin_en_keep_p.setSingleStep(0.01)
        self.spin_en_keep_p.setDecimals(2)
        self.spin_en_keep_p.setValue(float(self.cfg.data.get("flux_energy_keep_p", 0.50)))

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Backend:"), 0, 0)
        grid.addWidget(self.backend_cb, 0, 1)
        grid.addWidget(self.btn_start, 0, 2)
        grid.addWidget(self.btn_stop, 0, 3)
        grid.addWidget(self.btn_save, 0, 4)

        grid.addWidget(QtWidgets.QLabel("min_silence_ms"), 1, 0)
        grid.addWidget(self.spin_min_sil, 1, 1)
        grid.addWidget(QtWidgets.QLabel("min_speech_ms"), 1, 2)
        grid.addWidget(self.spin_min_sp, 1, 3)

        grid.addWidget(QtWidgets.QLabel("Energy start margin (dB)"), 2, 0)
        grid.addWidget(self.spin_en_start, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Energy keep margin (dB)"), 2, 2)
        grid.addWidget(self.spin_en_keep, 2, 3)
        grid.addWidget(self.chk_en_abs, 3, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Energy start p"), 4, 0)
        grid.addWidget(self.spin_en_start_p, 4, 1)
        grid.addWidget(QtWidgets.QLabel("Energy keep p"), 4, 2)
        grid.addWidget(self.spin_en_keep_p, 4, 3)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.plot, 1)
        v.addLayout(grid)

        # --- runtime ---
        self.buffer_len = 10 * 1000 // self.state.frame_ms  # ~10s
        self.y = deque(maxlen=self.buffer_len)
        self.x = np.arange(self.buffer_len)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._on_timer)
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=512)
        self.running = False
        self.vad = None
        self.sample_index = 0
        self.frame_sec = self.state.frame_ms / 1000.0

        # slots
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_save.clicked.connect(self.save_to_config)
        self.backend_cb.currentTextChanged.connect(self._on_backend_change)
        self._on_backend_change(self.backend_cb.currentText())

    def _on_backend_change(self, text: str):
        # Energy only: controls and guides are always enabled
        self.chk_en_abs.setEnabled(True)
        self.spin_en_start_p.setEnabled(self.chk_en_abs.isChecked())
        self.spin_en_keep_p.setEnabled(self.chk_en_abs.isChecked())
        # Clear previous trace
        self.y.clear()
        self.sample_index = 0
        self.curve.setData([], [])

    def start(self):
        if self.running:
            return
        try:
            self.state.sr = int(sd.query_devices(kind='input')['default_samplerate'])
        except Exception:
            self.state.sr = 16000
        self.state.frame_ms = 30
        self.state.block = int(self.state.sr * self.state.frame_ms / 1000)
        self.vad = EnergyVAD(fs=self.state.sr, frame_ms=self.state.frame_ms,
                             start_margin_db=float(self.spin_en_start.value()),
                             keep_margin_db=float(self.spin_en_keep.value()))
        self.y.clear()
        self.sample_index = 0
        self.frame_sec = self.state.frame_ms / 1000.0
        self.running = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.timer.start()

        def callback(indata, frames, t, status):
            if status:
                verbo(f"[tuner] sd status: {status}")
            x = indata[:, 0] if indata.ndim > 1 else indata
            try:
                self.q.put_nowait(x.copy())
            except queue.Full:
                pass

        self.stream = sd.InputStream(samplerate=self.state.sr, channels=1, dtype="float32",
                                     blocksize=self.state.block, callback=callback)
        self.stream.start()

    def stop(self):
        if not self.running:
            return
        self.timer.stop()
        try:
            self.stream.stop(); self.stream.close()
        except Exception:
            pass
        self.running = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _on_timer(self):
        # drain some frames
        for _ in range(8):
            try:
                frame = self.q.get_nowait()
            except queue.Empty:
                break
            p = self._prob(frame)
            self.y.append(p)
            self.sample_index += 1
        # update plot
        if len(self.y) > 0:
            y = np.array(self.y)
            n = len(y)
            x = (np.arange(self.sample_index - n, self.sample_index) * self.frame_sec)
            self.curve.setData(x, y)
            # Keep a ~10s window visible
            t_end = self.sample_index * self.frame_sec
            t_start = max(0.0, t_end - 10.0)
            self.plot.setXRange(t_start, t_end, padding=0.0)
            # Energy guides
            if isinstance(self.vad, EnergyVAD):
                if self.chk_en_abs.isChecked():
                    p_start = float(self.spin_en_start_p.value())
                    p_keep = float(self.spin_en_keep_p.value())
                else:
                    noise_db = float(getattr(self.vad, 'noise_db', -60.0))
                    p_start = (max(noise_db + float(self.spin_en_start.value()), -60.0) + 60.0) / 60.0
                    p_keep = (max(noise_db + float(self.spin_en_keep.value()), -60.0) + 60.0) / 60.0
                p_start = float(min(1.0, max(0.0, p_start)))
                p_keep = float(min(1.0, max(0.0, p_keep)))
                self.en_line_start.setPos(p_start)
                self.en_line_keep.setPos(p_keep)
                x_text = t_end - 0.05 * max(0.1, (t_end - t_start))
                y_off = 0.02 * max(0.1, (self.plot.viewRange()[1][1] - self.plot.viewRange()[1][0]))
                if self.chk_en_abs.isChecked():
                    self.en_text_start.setText(f"Start p={p_start:.2f}")
                    self.en_text_keep.setText(f"Keep p={p_keep:.2f}")
                else:
                    self.en_text_start.setText(f"Start ≈ {float(self.spin_en_start.value()):.1f} dB above noise")
                    self.en_text_keep.setText(f"Keep ≈ {float(self.spin_en_keep.value()):.1f} dB above noise")
                self.en_text_start.setPos(max(t_start, x_text), min(1.0, p_start + y_off))
                self.en_text_keep.setPos(max(t_start, x_text), min(1.0, p_keep + y_off))

    def _prob(self, frame: np.ndarray) -> float:
        try:
            _ = self.vad.is_speech(frame)
        except Exception:
            pass
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        db = 20.0 * np.log10(rms)
        p = (db + 60.0) / 60.0
        return float(min(1.0, max(0.0, p)))

    def save_to_config(self):
        self.cfg.set("flux_min_silence_ms", int(self.spin_min_sil.value()))
        self.cfg.set("flux_min_speech_ms", int(self.spin_min_sp.value()))
        self.cfg.set("flux_energy_start_margin_db", float(self.spin_en_start.value()))
        self.cfg.set("flux_energy_keep_margin_db", float(self.spin_en_keep.value()))
        self.cfg.set("flux_energy_use_absolute", bool(self.chk_en_abs.isChecked()))
        self.cfg.set("flux_energy_start_p", float(self.spin_en_start_p.value()))
        self.cfg.set("flux_energy_keep_p", float(self.spin_en_keep_p.value()))
        self.cfg.save()
        QtWidgets.QMessageBox.information(self, "Saved", "Parameters saved to config.")


def main():
    cfg = AppConfig()
    app = QtWidgets.QApplication(sys.argv)
    w = FluxTunerWindow(cfg)
    w.show()
    sys.exit(app.exec())


