from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QFileDialog, QMessageBox

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
        clipboard.copy(tscript)
        if self.cfg.simulate_typing and tscript:
            self.status_changed.emit("Typing")
            typer.type(tscript)
        self.finished.emit(tscript)

def show_options_dialog(parent, logger):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Options")
    dialog.setStyleSheet("background-color: #2e2e2e; color: white;")
    layout = QVBoxLayout()

    def show_log():
        logger.show()
        if QMessageBox.question(dialog, "Save log?", "Save session log to file?") == QMessageBox.StandardButton.Yes:
            path, _ = QFileDialog.getSaveFileName(dialog, "Save Log", "", "Text Files (*.txt)")
            if path:
                logger.save(path)

    def edit_config():
        import subprocess
        subprocess.run(["xdg-open", "config.yaml"])
        QMessageBox.information(dialog, "Settings", "Changes apply after restart.")

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
    dialog.exec()