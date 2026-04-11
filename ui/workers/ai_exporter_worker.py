from PyQt6.QtCore import QThread, pyqtSignal
from core.models.ai_exporter import AIExporterLogic

class AIExporterWorker(QThread):
    """
    UI Layer Worker: Wraps the core AI export logic in a QThread.
    """
    progress_updated = pyqtSignal(str, int, int)  # filename, current, total
    export_finished = pyqtSignal(str)             # resulting markdown string
    error_occurred = pyqtSignal(str)              # error message

    def __init__(self, root_path, config, include_contents=True):
        super().__init__()
        self.logic = AIExporterLogic(root_path, config, include_contents)

    def run(self):
        self.logic.run(
            on_progress=self.progress_updated.emit,
            on_finished=self.export_finished.emit,
            on_error=self.error_occurred.emit
        )

    def cancel(self):
        self.logic.cancel()
