"""
ThumbnailDelegate: Custom item delegate for the Gallery/Preview view.
Renders each file as:
  - A thumbnail preview (image or PDF cover) centered in a box.
  - The filename below the thumbnail.
  - Draws a hover highlight and selection frame.
"""
import os
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QFileIconProvider
from PyQt6.QtCore import Qt, QRect, QSize, QFileInfo
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush


class ThumbnailDelegate(QStyledItemDelegate):
    """
    Custom delegate for the gallery view.
    Expects the view to call `set_thumbnail_manager()` so it can request previews.
    """

    THUMB_W = 140
    THUMB_H = 110
    LABEL_H = 36
    PADDING = 8
    CELL_W = THUMB_W + PADDING * 2
    CELL_H = THUMB_H + LABEL_H + PADDING * 2

    def __init__(self, config_mgr=None, parent=None):
        super().__init__(parent)
        self._mgr = None
        self._icon_provider = QFileIconProvider()
        self._config_mgr = config_mgr

    def set_thumbnail_manager(self, mgr):
        """Connect the delegate to a ThumbnailManager instance."""
        self._mgr = mgr
        mgr.thumbnail_ready.connect(self._on_thumbnail_ready)

    def _on_thumbnail_ready(self, path, pixmap):
        """Force repaint of the item whose thumbnail just arrived."""
        # Trigger a repaint of the whole viewport; the view will call paint() again.
        parent = self.parent()
        if parent and hasattr(parent, 'viewport'):
            parent.viewport().update()

    def sizeHint(self, option, index):
        return QSize(self.CELL_W, self.CELL_H)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # --- Background ---
        _tc = self._config_mgr.get_theme_colors() if self._config_mgr else {}
        bg_color = QColor(_tc.get("panelBg", "#23272e"))
        if is_selected:
            bg_color = QColor(88, 166, 255, 60)  # 增亮處理：實一點的背景
        elif is_hovered:
            bg_color = QColor(255, 255, 255, 15)

        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)

        # --- Thumbnail area ---
        thumb_rect = QRect(
            rect.left() + self.PADDING,
            rect.top() + self.PADDING,
            self.THUMB_W,
            self.THUMB_H
        )

        # Get path from model
        model = index.model()
        if hasattr(model, 'sourceModel'):
            src_idx = model.mapToSource(index)
            path = model.sourceModel().filePath(src_idx)
        else:
            path = model.filePath(index)

        drawn = False
        if self._mgr and os.path.isfile(path):
            pixmap = self._mgr.get_thumbnail(path, max(self.THUMB_W, self.THUMB_H))
            if pixmap and not pixmap.isNull():
                # Center pixmap in thumb_rect
                scaled = pixmap.scaled(
                    self.THUMB_W, self.THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                px = thumb_rect.left() + (self.THUMB_W - scaled.width()) // 2
                py = thumb_rect.top() + (self.THUMB_H - scaled.height()) // 2
                painter.drawPixmap(px, py, scaled)
                drawn = True

        if not drawn:
            # Fallback: use the system icon, centered
            icon = self._icon_provider.icon(QFileInfo(path))
            icon_size = QSize(64, 64)
            px = thumb_rect.left() + (self.THUMB_W - icon_size.width()) // 2
            py = thumb_rect.top() + (self.THUMB_H - icon_size.height()) // 2
            icon.paint(painter, px, py, icon_size.width(), icon_size.height())

        # --- Filename label ---
        name = os.path.basename(path) if path else index.data(Qt.ItemDataRole.DisplayRole) or ""
        label_rect = QRect(
            rect.left() + self.PADDING,
            rect.top() + self.PADDING + self.THUMB_H,
            self.THUMB_W,
            self.LABEL_H
        )
        _text_clr = _tc.get("text", "#C9D1D9")
        painter.setPen(QColor(_text_clr))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, name)

        # --- Selection border (增亮處理：極亮藍色邊框) ---
        if is_selected:
            border_pen = QPen(QColor(88, 166, 255, 180), 1.2)  # 超亮的邊框色彩
            
            painter.setPen(border_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)

        painter.restore()
