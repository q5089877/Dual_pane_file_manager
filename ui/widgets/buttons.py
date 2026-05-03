from PyQt6.QtWidgets import QPushButton, QToolButton
from PyQt6.QtCore import pyqtSignal, Qt

class PinDropButton(QToolButton):
    """QToolButton that accepts file drag-and-drop to pin items silently."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("pinBtnDrop")
            self._refresh_style()

    def dragLeaveEvent(self, _event):
        self._restore_object_name()
        self._refresh_style()

    def dropEvent(self, event):
        self._restore_object_name()
        self._refresh_style()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        for path in paths:
            if hasattr(self.main_window, "add_pin_silent"):
                self.main_window.add_pin_silent(path)
        event.acceptProposedAction()

    def _restore_object_name(self):
        self.setObjectName("pinBtn")

    def _refresh_style(self):
        self.style().unpolish(self)
        self.style().polish(self)


class HoverButton(QPushButton):
    """Button that emits a signal when hovered."""
    hovered = pyqtSignal(bool)
    
    def enterEvent(self, event):
        super().enterEvent(event)
        self.hovered.emit(True)
        
    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hovered.emit(False)
