from __future__ import annotations

import numpy as np
from collections import deque

try:
    from PyQt6 import QtWidgets, QtCore, QtGui
except Exception as e:  # pragma: no cover - optional dep guard
    QtWidgets = None  # type: ignore
    QtCore = None  # type: ignore
    QtGui = None  # type: ignore
    _QT_ERR = e

try:
    import pyqtgraph as pg
except Exception as e:  # pragma: no cover - optional dep guard
    pg = None  # type: ignore
    _PG_ERR = e


class FluxGUI(QtWidgets.QWidget):
    def __init__(self, runner):
        super().__init__()
        self.runner = runner
        self.vad = runner.vad
        self.fs = runner.fs
        self.frame_ms = runner.frame_ms
        self.setWindowTitle("VOXD Flux GUI")
        self.setFixedSize(300, 220)

        if pg is None:
            QtWidgets.QMessageBox.critical(self, "pyqtgraph missing", f"pyqtgraph is required for Flux GUI. Error: {_PG_ERR}")
            raise SystemExit(1)

        # Dark theme
        self.setStyleSheet("background-color: #1e1e1e; color: white;")

        # Controls row
        self.btn_toggle = QtWidgets.QPushButton("Listening  ▶")
        self.btn_toggle.setFixedHeight(44)
        self.btn_toggle.setStyleSheet(
            """
            QPushButton { background-color: #FF4500; border-radius: 22px; font-size: 15px; font-weight: bold; color: white; padding: 6px 14px; }
            QPushButton:pressed { background-color: #FF6347; }
            """
        )
        self.btn_toggle.clicked.connect(self._on_toggle)

        self.btn_recalib = QtWidgets.QPushButton("Recalibrate noise (5 s)")
        self.btn_recalib.setStyleSheet("QPushButton { background: #444; color: white; border-radius: 8px; padding: 6px 10px; }")
        self.btn_recalib.clicked.connect(self._on_recalibrate)

        self.chk_ema = QtWidgets.QCheckBox("Noise drift (EMA)")
        self.chk_ema.setChecked(True)
        self.chk_ema.toggled.connect(self._on_ema_toggled)

        self.btn_options = QtWidgets.QPushButton("Options")
        self.btn_options.setStyleSheet("QPushButton { background: #444; color: white; border-radius: 8px; padding: 6px 10px; }")
        self.btn_options.clicked.connect(self._on_options)

        # Only normalized energy in Flux GUI (no absolute toggle)

        # Build a vertical controls column (left panel)
        controls_col = QtWidgets.QVBoxLayout()
        controls_col.setContentsMargins(0, 0, 0, 0)
        controls_col.setSpacing(8)
        controls_col.addWidget(self.btn_toggle)
        controls_col.addWidget(self.btn_recalib)
        controls_col.addWidget(self.chk_ema)
        controls_col.addWidget(self.btn_options)
        controls_col.addStretch(1)

        # Status panel (top row, pill-button color)
        self.status_label = QtWidgets.QLabel("Leave me & go ▶ VOICE-TYPE anywhere.")
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #FF4500; font-size: 12px; font-style: italic;")

        # Energy plot (dBFS)
        self.energy_plot = pg.PlotWidget()
        # Make grid subtly visible (slightly stronger)
        self.energy_plot.showGrid(x=True, y=True, alpha=0.30)
        # Match GUI background and remove axis tick labels/marks (keep axis lines + grid)
        try:
            self.energy_plot.setBackground('#1e1e1e')
        except Exception:
            try:
                self.energy_plot.getPlotItem().getViewBox().setBackgroundColor('#1e1e1e')
            except Exception:
                pass
        self.energy_plot.setLabel('bottom', '')
        self.energy_plot.setLabel('left', '')
        try:
            pi = self.energy_plot.getPlotItem()
            # Ensure axes are visible so the axis lines remain and grid can render
            pi.showAxis('left', True)
            pi.showAxis('bottom', True)
            left_axis = pi.getAxis('left')
            bottom_axis = pi.getAxis('bottom')
            # Hide numeric labels and tick marks while preserving gridlines
            left_axis.setStyle(showValues=False, tickLength=0, tickTextOffset=0)
            bottom_axis.setStyle(showValues=False, tickLength=0, tickTextOffset=0)
            # Make axis lines and gridlines very dark (low contrast)
            dark_pen = pg.mkPen(color=(40, 40, 40))
            try:
                left_axis.setPen(dark_pen)
                bottom_axis.setPen(dark_pen)
            except Exception:
                pass
            # Do not override plot grid via axis.setGrid; rely on showGrid alpha above
        except Exception:
            pass
        # Start in normalized mode [0..1]; when abs-energy checked, switch to dBFS [-60..0]
        self.energy_plot.setYRange(0.0, 1.0)
        # Softer trace line (even dimmer, lower alpha)
        self.energy_curve = self.energy_plot.plot([], [], pen=pg.mkPen(color=(0, 100, 0, 120), width=2))
        # Lines will be positioned per mode on each tick
        self.en_line_start = pg.InfiniteLine(angle=0, pos=0.7, pen=pg.mkPen((120, 180, 255), style=QtCore.Qt.PenStyle.DashLine))
        self.en_line_keep = pg.InfiniteLine(angle=0, pos=0.6, pen=pg.mkPen((80, 140, 220), style=QtCore.Qt.PenStyle.DashLine))
        self.energy_plot.addItem(self.en_line_start)
        self.energy_plot.addItem(self.en_line_keep)
        self.en_text_start = pg.TextItem(color=(120, 180, 255))
        self.en_text_keep = pg.TextItem(color=(80, 140, 220))
        try:
            self.en_text_start.setAnchor((1, 0.5))
            self.en_text_keep.setAnchor((1, 0.5))
        except Exception:
            pass
        self.energy_plot.addItem(self.en_text_start)
        self.energy_plot.addItem(self.en_text_keep)

        # Layout: top status row, then second row with controls(left) + graph(right)
        root = QtWidgets.QVBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        left.addLayout(controls_col)

        second_row = QtWidgets.QHBoxLayout()
        second_row.addLayout(left, 0)
        second_row.addWidget(self.energy_plot, 1)

        # Compose final layout
        root.addWidget(self.status_label)
        # Permanent hotkey hint (second label under status)
        self.hotkey_hint = QtWidgets.QLabel("The HOTKEY toggles listening/pause.")
        self.hotkey_hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setStyleSheet("color: #cccccc; font-size: 11px; font-style: italic;")
        root.addWidget(self.hotkey_hint)
        root.addLayout(second_row)

        # Runtime state
        self.window_sec = float(self.runner.cfg.data.get("flux_monitor_energy_window_s", 10))
        self.buffer_len = int(max(1, self.window_sec * 1000 // self.frame_ms))
        self.y = deque(maxlen=self.buffer_len)  # match tuner behavior
        self.sample_index = 0
        self.frame_sec = self.frame_ms / 1000.0
        # No spectrum in Flux GUI

        self.timer = QtCore.QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()

        # Reflect paused/calibrating state initially
        if getattr(self.runner, "_calibrating", False) or getattr(self.vad, "calibrating", False):
            self.status_label.setText("Quiet, please — background noise calibration —")
            self.btn_toggle.setText("Calibrating...")

    def _on_toggle(self):
        paused = getattr(self.runner, "_paused", False)
        self.runner.set_paused(not paused)
        if not paused:
            self.btn_toggle.setText("Paused  ⏸")
            self.status_label.setText("Paused")
        else:
            self.btn_toggle.setText("Listening  ▶")
            self.status_label.setText("Leave me & go ▶ VOICE-TYPE anywhere.")

    def _on_recalibrate(self):
        self.runner.request_recalibration(5.0)
        self.status_label.setText("Quiet, please — background noise calibration —")

    def _on_ema_toggled(self, state: bool):
        self.runner.set_noise_drift_enabled(bool(state))

    def _on_options(self):
        try:
            from voxd.core.voxd_core import show_options_dialog
            # Allow AIPP in Flux mode per updated requirement
            show_options_dialog(self, self.runner.logger, cfg=self.runner.cfg, modal=True, hide_aipp=False)
        except Exception:
            pass

    def _on_timer(self):
        # Drain a few frames per tick to reduce display lag (like tuner: up to 8)
        frames = []
        try:
            for _ in range(8):
                frames.append(self.runner.mon_q.get_nowait())
        except Exception:
            pass
        if not frames:
            with self.runner._mon_lock:
                if self.runner._mon_frames:
                    frames = [self.runner._mon_frames[-1]]

        for frame in frames:
            # Use the exact tuner scheme: normalized p only
            val = self._prob(frame)
            self.y.append(val)
            self.sample_index += 1

        # Update energy plot
        if len(self.y) > 0:
            y_arr = np.array(self.y)
            n = len(y_arr)
            x_arr = (np.arange(self.sample_index - n, self.sample_index) * self.frame_sec)
            # Normalized 0..1 exactly as tuner
            self.energy_plot.setYRange(0.0, 1.0)
            # self.energy_plot.setLabel('left', 'Normalized energy', '')
            self.energy_curve.setData(x_arr, y_arr)
            start_thr_db, keep_thr_db = self.vad.get_thresholds_db()
            p_start = float(np.clip((start_thr_db + 60.0) / 60.0, 0.0, 1.0))
            p_keep = float(np.clip((keep_thr_db + 60.0) / 60.0, 0.0, 1.0))
            self.en_line_start.setPos(p_start)
            self.en_line_keep.setPos(p_keep)
            self.en_text_start.setText(f"Start p={p_start:.2f}")
            self.en_text_keep.setText(f"Keep p={p_keep:.2f}")
            y_offset = 0.02
            t_end = x_arr[-1]
            t_start = max(0.0, t_end - self.window_sec)
            self.energy_plot.setXRange(t_start, t_end, padding=0.0)
            x_text = t_end - 0.05 * max(0.1, (t_end - t_start))
            self.en_text_start.setPos(max(t_start, x_text), float(self.en_line_start.value()) + y_offset)
            self.en_text_keep.setPos(max(t_start, x_text), float(self.en_line_keep.value()) + y_offset)


        # Status text from calibration/paused
        if self.vad.calibrating or getattr(self.runner, "_calibrating", False):
            self.status_label.setText("Quiet, please — background noise calibration —")
            self.btn_toggle.setText("Calibrating...")
        else:
            if getattr(self.runner, "_paused", False):
                self.status_label.setText("Paused")
                self.btn_toggle.setText("Paused  ⏸")
            else:
                self.status_label.setText("Leave me & go ▶ VOICE-TYPE anywhere.")
                self.btn_toggle.setText("Listening  ▶")

    @staticmethod
    def _dbfs_of(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        return 20.0 * np.log10(rms)

    def _prob(self, frame: np.ndarray) -> float:
        # Match tuner plotting (RMS only, do not advance VAD state here)
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        db = 20.0 * np.log10(rms)
        p = (db + 60.0) / 60.0
        return float(min(1.0, max(0.0, p)))



def show_gui(runner):
    if QtWidgets is None:  # pragma: no cover - guard
        raise RuntimeError(f"PyQt6 not available: {_QT_ERR}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = FluxGUI(runner)
    w.show()
    return app, w


