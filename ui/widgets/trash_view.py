from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from core.interfaces import ITrashView
from ui.presenters.trash_presenter import TrashPresenter

class _TrashViewAdapter(ITrashView):
    """Pure adapter: bridges Presenter logic to PyQt without inheriting any Qt class."""
    def __init__(self, widget):
        self.widget = widget

    def set_counter(self, count: int):
        self.widget.set_counter_count(count)

    def show_message(self, text: str, style: str):
        self.widget.show_status_message(text, style)

class TrashView(QFrame):
    """
    View for the Temporary Trash.
    Displays a trash icon with a counter badge and handles drag-and-drop.
    """
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedSize(60, 60)
        self.setObjectName("trashWidget")
        self.setToolTip("臨時垃圾桶：拉入此處可暫存 7 天後自動刪除")
        
        # Adapter and Presenter
        self._adapter = _TrashViewAdapter(self)
        self.presenter = TrashPresenter(self._adapter, model)
        
        self._init_ui()
        self.presenter.load()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel("🗑️")
        self.icon_label.setObjectName("trashIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        # Counter Badge
        self.badge_label = QLabel("0")
        self.badge_label.setObjectName("trashBadge")
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setFixedSize(20, 20)
        self.badge_label.setParent(self)
        # Position badge at top-right
        self.badge_label.move(38, 5)
        self.badge_label.hide() # Initially hidden
        
    def set_counter_count(self, count: int):
        """Updates the badge count."""
        self.badge_label.setText(str(count))
        self.badge_label.setVisible(count > 0)

    def show_status_message(self, text: str, style: str):
        """Shows status message."""
        self.setToolTip(text)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("active", "true")
            self._update_style()

    def dragLeaveEvent(self, event):
        self.setProperty("active", "false")
        self._update_style()

    def dropEvent(self, event):
        self.setProperty("active", "false")
        self._update_style()
        urls = event.mimeData().urls()
        paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        if paths:
            self.presenter.add_paths(paths)
            event.acceptProposedAction()
            
            # Show visual feedback
            self.icon_label.setText("♻️")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1000, lambda: self.icon_label.setText("🗑️"))

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        empty_act = menu.addAction("🗑️ 清空臨時垃圾桶 (移至系統回收筒)")
        empty_act.triggered.connect(self.presenter.on_empty_trash)
        
        open_folder_act = menu.addAction("📂 開啟暫存目錄")
        open_folder_act.triggered.connect(self._open_trash_dir)
        
        menu.exec(event.globalPos())
        
    def _open_trash_dir(self):
        import os
        os.startfile(str(self.presenter.model.trash_dir))

    def _update_style(self):
        self.style().unpolish(self)
        self.style().polish(self)
