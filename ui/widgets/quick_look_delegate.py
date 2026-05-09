import os
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QEvent, QPoint, QRectF
from PyQt6.QtGui import QPainter, QFileSystemModel, QColor, QPainterPath
from core.file_ops import FileOps


class QuickLookDelegate(QStyledItemDelegate):
    """
    Delegate for the Name column.
    Draws a 👁️ icon aligned to the right when hovered.
    Clicking the icon emits preview_requested(path).
    """
    preview_requested = pyqtSignal(str)

    def __init__(self, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.icon_margin = 16 # Increase margin for absolute flush right breathing room
        self.active_preview_path = ""

    def _get_icon_rect(self, option_rect):
        width = 24
        height = 24
        return QRect(
            option_rect.right() - width - self.icon_margin,
            option_rect.top() + (option_rect.height() - height) // 2,
            width, height
        )

    def _get_path(self, index) -> str:
        path = index.data(QFileSystemModel.Roles.FilePathRole) or ""
        if not path:
            path = index.data(Qt.ItemDataRole.UserRole) or ""
        return path

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)

        path = self._get_path(index)

        if path and FileOps.is_cloud_only(path):
            r = 4
            x = option.rect.left() + 18
            y = option.rect.top() + option.rect.height() - r - 2
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawEllipse(QPoint(x, y), r + 1, r + 1)
            painter.setBrush(QColor(0, 120, 212))
            painter.drawEllipse(QPoint(x, y), r, r)
            painter.restore()

        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_active = (path == self.active_preview_path) and bool(path)

        if not ((is_hovered or is_active) and path and os.path.isfile(path)):
            return

        rect = self._get_icon_rect(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Pill 背景（固定半透明，不受 actionBarBg 影響）──────────
        if is_active:
            pill_color = QColor(88, 166, 255, 180)   # 藍色：正在預覽
        else:
            pill_color = QColor(80, 84, 100, 100)     # 灰色：hover
        border_color = QColor(255, 255, 255, 50)

        painter.setBrush(pill_color)
        painter.setPen(border_color)
        painter.drawRoundedRect(QRectF(rect), 10, 10)

        # ── 圖示 ───────────────────────────────────────────────────
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)

        if is_active:
            # X 關閉圖示
            from PyQt6.QtGui import QPen
            pen = QPen(QColor(255, 255, 255, 220), 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            d = 4
            painter.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
            painter.drawLine(int(cx - d), int(cy + d), int(cx + d), int(cy - d))
        else:
            # 純線條眼睛（方案 A）
            from PyQt6.QtGui import QPen
            pen = QPen(QColor(255, 255, 255, 210), 1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            eye_w, eye_h = 12, 4
            eye_path = QPainterPath()
            eye_path.moveTo(cx - eye_w / 2, cy)
            eye_path.quadTo(cx, cy - eye_h, cx + eye_w / 2, cy)
            eye_path.quadTo(cx, cy + eye_h, cx - eye_w / 2, cy)
            eye_path.closeSubpath()
            painter.drawPath(eye_path)

            # 瞳孔（實心小圓）
            painter.setBrush(QColor(255, 255, 255, 210))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPoint(int(cx), int(cy)), 2, 2)

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            path = self._get_path(index)
            if path and os.path.isfile(path):
                rect = self._get_icon_rect(option.rect)
                # Handle Qt5/Qt6 event coordinate differences robustly
                pos = getattr(event, "position", event.pos)()
                if rect.contains(pos.toPoint() if hasattr(pos, "toPoint") else pos):
                    self.preview_requested.emit(path)
                    return True  # Stop propagation

        return super().editorEvent(event, model, option, index)
