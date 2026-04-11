from PyQt6.QtWidgets import QSplitter, QSplitterHandle, QPushButton
from PyQt6.QtCore import pyqtSignal, Qt


class BridgeHandle(QSplitterHandle):
    bridge_clicked = pyqtSignal()

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._btn = QPushButton(self)
        self._btn.setToolTip("同步路徑 / 資料夾比對")
        self._btn.setObjectName("splitterBridgeBtn")
        self._btn.setFixedSize(28, 28)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self.bridge_clicked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        bw, bh = self._btn.width(), self._btn.height()
        x = (self.width() - bw) // 2
        y = (self.height() - bh) // 2
        self._btn.move(x, y)


class BridgeSplitter(QSplitter):
    bridge_clicked = pyqtSignal()

    def createHandle(self):
        h = BridgeHandle(self.orientation(), self)
        h.bridge_clicked.connect(self.bridge_clicked)
        return h
