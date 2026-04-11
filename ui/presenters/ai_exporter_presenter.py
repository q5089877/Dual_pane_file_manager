from PyQt6.QtGui import QGuiApplication
from ui.workers.ai_exporter_worker import AIExporterWorker

class AIExporterPresenter:
    """
    Presenter for AI Context Export.
    Coordinates between the AIExporterWorker (background thread) and the View.
    """
    def __init__(self, view, root_path, config, include_contents=True):
        self.view = view
        self.root_path = root_path
        self.config = config
        self.include_contents = include_contents
        self.worker = None

    def start(self):
        """Show view and start background scanning."""
        # Initialize Worker
        self.worker = AIExporterWorker(self.root_path, self.config, self.include_contents)
        
        # Bind Signals and Slots
        self.worker.progress_updated.connect(self.view.update_progress)
        self.worker.export_finished.connect(self.on_export_finished)
        self.worker.error_occurred.connect(self.on_error)
        
        # Allow cancelling from the view
        self.view.set_cancelled_callback(self.worker.cancel)
        
        # Show dialog and start thread
        self.view.show()
        self.worker.start()

    def on_export_finished(self, markdown_content):
        """Called when scanning and MD generation is complete."""
        self.view.close()
        
        # Copy to Clipboard (Smart implementation from user)
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(markdown_content)
        
        # Calculate stats for the success message
        # Counts occurrences of "### File:" to estimate file count
        file_count = markdown_content.count("### File:")
        char_count = len(markdown_content)
        
        self.view.show_success(file_count, char_count)

    def on_error(self, error_msg):
        """Called when an error occurs in the model thread."""
        self.view.close()
        self.view.show_error(error_msg)
