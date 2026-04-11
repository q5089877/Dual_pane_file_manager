from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, QPoint

_ICONS: dict[str, str] = {
    "success": "✓",
    "error": "✕",
    "info": "ℹ",
    "warning": "⚠",
}


class Toast(QFrame):
    """Non-blocking overlay notification; auto-dismisses after *duration* ms."""

    def __init__(self, parent, message: str, kind: str = "info", duration: int = 3000):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("kind", kind)
        self._build_ui(message, kind)
        self._reposition()
        self.show()
        self.raise_()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(duration)

    def _build_ui(self, message: str, kind: str) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        icon_lbl = QLabel(_ICONS.get(kind, "ℹ"))
        icon_lbl.setObjectName("toastIcon")
        layout.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setObjectName("toastMsg")
        msg_lbl.setWordWrap(True)
        msg_lbl.setMaximumWidth(320)
        layout.addWidget(msg_lbl, 1)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("toastClose")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self.adjustSize()

    def _reposition(self) -> None:
        parent = self.parent()
        if parent is None:
            return
        self.adjustSize()
        margin = 16
        # 76px from bottom clears the 60px drop zone + a small gap
        x = parent.width() - self.width() - margin
        y = parent.height() - self.height() - 76
        self.move(QPoint(x, y))


def show_toast(window, message: str, kind: str = "info", duration: int = 3000) -> None:
    """Show a toast on *window*, dismissing any existing toast first."""
    for child in window.findChildren(Toast):
        child._timer.stop()
        child.close()
    Toast(window, message, kind, duration)
