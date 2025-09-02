from __future__ import annotations

import numpy as np

try:
    from PyQt6 import QtWidgets, QtCore
except Exception as e:  # pragma: no cover - optional dep guard
    QtWidgets = None  # type: ignore
    QtCore = None  # type: ignore
    _QT_ERR = e

try:
    import pyqtgraph as pg
except Exception as e:  # pragma: no cover - optional dep guard
    pg = None  # type: ignore
    _PG_ERR = e


class FluxMonitorWindow(QtWidgets.QWidget):
    def __init__(self, runner):
        super().__init__()
        self.runner = runner
        self.vad = runner.vad
        self.fs = runner.fs
        self.frame_ms = runner.frame_ms
        self.setWindowTitle("VOXT Flux Monitor")
        self.resize(980, 600)

        if pg is None:
            QtWidgets.QMessageBox.critical(self, "pyqtgraph missing", f"pyqtgraph is required for monitor. Error: {_PG_ERR}")
            raise SystemExit(1)

        # --- Energy plot ---
        self.energy_plot = pg.PlotWidget()
        self.energy_plot.setYRange(0.0, 1.0)
        self.energy_plot.showGrid(x=True, y=True, alpha=0.3)
        self.energy_plot.setLabel('bottom', 'Time', 's')
        self.energy_plot.setLabel('left', 'Normalized energy', '')
        self.energy_curve = self.energy_plot.plot([], [], pen=pg.mkPen(color=(0, 200, 0), width=2))
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

        # --- Spectrum plot ---
        self.spec_plot = pg.PlotWidget()
        self.spec_plot.showGrid(x=True, y=True, alpha=0.3)
        self.spec_plot.setLabel('bottom', 'Frequency', 'Hz')
        self.spec_plot.setLabel('left', 'Magnitude', 'dB')
        self.spec_curve = self.spec_plot.plot([], [], pen=pg.mkPen(color=(230, 160, 60), width=2))
        self.spec_noise_curve = self.spec_plot.plot([], [], pen=pg.mkPen(color=(160, 160, 160), style=QtCore.Qt.PenStyle.DashLine))

        # --- Calibration label ---
        self.calib_label = QtWidgets.QLabel("")
        self.calib_label.setStyleSheet("color: #ddd;")

        # Layout
        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.energy_plot, 1)
        v.addWidget(self.spec_plot, 1)
        v.addWidget(self.calib_label, 0)

        # Runtime state
        self.buffer_len = int(max(1, (self.runner.cfg.data.get("flux_monitor_energy_window_s", 10)) * 1000 // self.frame_ms))
        self.y = []
        self.sample_index = 0
        self.frame_sec = self.frame_ms / 1000.0
        self.spec_floor_db = float(self.runner.cfg.data.get("flux_monitor_spectrum_floor_db", -85.0))

        self.timer = QtCore.QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()

    def _on_timer(self):
        # Drain frames for energy and spectra from runner's buffer
        frames = []
        with self.runner._mon_lock:
            if self.runner._mon_frames:
                frames = self.runner._mon_frames[-min(32, len(self.runner._mon_frames)):]  # take a small batch
        for frame in frames:
            db = self._dbfs_of(frame)
            p = max(0.0, min(1.0, (db + 60.0) / 60.0))
            self.y.append(p)
            if len(self.y) > self.buffer_len:
                self.y = self.y[-self.buffer_len:]
            self.sample_index += 1

        # Update energy plot
        if self.y:
            n = len(self.y)
            x = (np.arange(self.sample_index - n, self.sample_index) * self.frame_sec)
            self.energy_curve.setData(x, np.array(self.y))
            t_end = self.sample_index * self.frame_sec
            t_start = max(0.0, t_end - float(self.runner.cfg.data.get("flux_monitor_energy_window_s", 10)))
            self.energy_plot.setXRange(t_start, t_end, padding=0.0)
            # Threshold guides
            if getattr(self.runner.cfg, "flux_energy_use_absolute", False):
                p_start = float(self.runner.cfg.data.get("flux_energy_start_p", 0.55))
                p_keep = float(self.runner.cfg.data.get("flux_energy_keep_p", 0.50))
                self.en_text_start.setText(f"Start p={p_start:.2f}")
                self.en_text_keep.setText(f"Keep p={p_keep:.2f}")
            else:
                start_thr_db, keep_thr_db = self.vad.get_thresholds_db()
                p_start = max(0.0, min(1.0, (start_thr_db + 60.0) / 60.0))
                p_keep = max(0.0, min(1.0, (keep_thr_db + 60.0) / 60.0))
                self.en_text_start.setText(f"Start ≈ +{(start_thr_db - self.vad.noise_db):.1f} dB over noise")
                self.en_text_keep.setText(f"Keep ≈ +{(keep_thr_db - self.vad.noise_db):.1f} dB over noise")
            self.en_line_start.setPos(p_start)
            self.en_line_keep.setPos(p_keep)
            x_text = t_end - 0.05 * max(0.1, (t_end - t_start))
            self.en_text_start.setPos(max(t_start, x_text), min(1.0, p_start + 0.02))
            self.en_text_keep.setPos(max(t_start, x_text), min(1.0, p_keep + 0.02))

        # Update spectrum plot (use last frame)
        last_frame = frames[-1] if frames else None
        if last_frame is not None and last_frame.size > 0:
            mag = np.abs(np.fft.rfft(last_frame.astype(np.float32))) + 1e-12
            db = 20.0 * np.log10(mag)
            freqs = np.fft.rfftfreq(last_frame.size, 1.0 / max(1, self.fs))
            # Baseline noise spectrum
            try:
                noise_mag = getattr(self.vad, "_noise_spec", None)
                if noise_mag is not None:
                    noise_db = 20.0 * np.log10(np.maximum(noise_mag, 1e-12))
                else:
                    noise_db = None
            except Exception:
                noise_db = None
            # Limit range 40 Hz .. Nyquist (or 20 kHz if lower)
            lo = 40.0
            hi = min(20000.0, self.fs / 2.0)
            m = (freqs >= lo) & (freqs <= hi)
            self.spec_curve.setData(freqs[m], np.maximum(db[m], self.spec_floor_db))
            if noise_db is not None:
                self.spec_noise_curve.setData(freqs[m], np.maximum(noise_db[m], self.spec_floor_db))

        # Calibration label
        if self.vad.calibrating:
            frames_left = max(0, self.vad._calib_frames_target - self.vad._calib_frames_done)
            sec_left = frames_left * (self.frame_ms / 1000.0)
            self.calib_label.setText(f"Calibrating noise baseline… {sec_left:.1f}s left")
        else:
            self.calib_label.setText("")

    @staticmethod
    def _dbfs_of(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-12)
        return 20.0 * np.log10(rms)


def show_monitor(runner):
    if QtWidgets is None:  # pragma: no cover - guard
        raise RuntimeError(f"PyQt6 not available: {_QT_ERR}")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = FluxMonitorWindow(runner)
    w.show()
    return app, w


