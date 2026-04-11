from PyQt6.QtWidgets import QTabWidget
from PyQt6.QtCore import QEvent, pyqtSignal, QTimer, Qt

class CustomTabWidget(QTabWidget):
    """Enhanced QTabWidget that switches tabs when dragging files over headers."""
    tabOverflow = pyqtSignal()
    tabBarClicked = pyqtSignal()  # 任何 tab bar 點擊 → 通知外部切換 panel 焦點

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabBar().setAcceptDrops(True)
        self.tabBar().installEventFilter(self)
        self.tabBar().setUsesScrollButtons(True)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabBar().setExpanding(False) # 重要: 捲動模式下不應自動撐開
        self._last_count = 0

    def tabInserted(self, index):
        super().tabInserted(index)
        # 延時檢查，確保佈局更新後才計算寬度
        QTimer.singleShot(100, self.check_overflow)

    def check_overflow(self):
        tb = self.tabBar()
        if tb.count() > self._last_count:
            # 只有在分頁增加時才檢查提示，避免頻繁觸發
            if tb.sizeHint().width() > tb.width():
                self.tabOverflow.emit()
        self._last_count = tb.count()

    def eventFilter(self, obj, event):
        if obj == self.tabBar():
            if event.type() == QEvent.Type.Wheel:
                return True  # 吃掉滾輪事件，避免誤觸切換分頁
            if event.type() == QEvent.Type.MouseButtonPress:
                self.tabBarClicked.emit()
            if event.type() in [QEvent.Type.DragEnter, QEvent.Type.DragMove]:
                index = self.tabBar().tabAt(event.position().toPoint())
                if index != -1: self.setCurrentIndex(index)
                event.accept(); return True
        return super().eventFilter(obj, event)
