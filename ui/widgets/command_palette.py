from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QKeyEvent


@dataclass
class Command:
    title: str
    action: Callable[[], None]
    shortcut: str = ""
    category: str = ""
    keywords: list[str] = field(default_factory=list)


class CommandPaletteDialog(QDialog):
    """VS Code-style command palette overlay. Ctrl+Shift+P to open."""

    _ITEM_H = 38
    _VISIBLE = 10

    def __init__(self, commands: list[Command], parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._all = commands
        self._build_ui()
        self._populate(commands)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._frame = QFrame()
        self._frame.setObjectName("cmdPaletteFrame")
        vl = QVBoxLayout(self._frame)
        vl.setContentsMargins(8, 8, 8, 8)
        vl.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("cmdPaletteInput")
        self._input.setPlaceholderText(
            "輸入命令名稱…   ↑↓ 選取   Enter 執行   Esc 關閉"
        )
        self._input.textChanged.connect(self._on_filter)
        self._input.installEventFilter(self)
        vl.addWidget(self._input)

        self._list = QListWidget()
        self._list.setObjectName("cmdPaletteList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._list.itemActivated.connect(self._run)
        vl.addWidget(self._list)

        root.addWidget(self._frame)
        self.setFixedWidth(640)

    @staticmethod
    def _row_widget(cmd: Command) -> QWidget:
        w = QWidget()
        w.setObjectName("cmdRow")
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 0, 12, 0)
        h.setSpacing(0)

        if cmd.category:
            cat = QLabel(cmd.category)
            cat.setObjectName("cmdCat")
            cat.setFixedWidth(72)
            h.addWidget(cat)
        else:
            h.addSpacing(72)

        title = QLabel(cmd.title)
        title.setObjectName("cmdTitle")
        h.addWidget(title, 1)

        if cmd.shortcut:
            sc = QLabel(cmd.shortcut)
            sc.setObjectName("cmdSc")
            sc.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            h.addWidget(sc)

        return w

    # ── Data ──────────────────────────────────────────────────────────────────

    def _populate(self, cmds: list[Command]) -> None:
        self._list.clear()
        for cmd in cmds:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cmd)
            item.setSizeHint(QSize(self.width(), self._ITEM_H))
            self._list.addItem(item)
            self._list.setItemWidget(item, self._row_widget(cmd))

        self._list.setFixedHeight(
            min(len(cmds), self._VISIBLE) * self._ITEM_H + 4
        )
        self.adjustSize()
        if self._list.count():
            self._list.setCurrentRow(0)

    def _on_filter(self, text: str) -> None:
        kw = text.lower()
        matched = (
            [
                c for c in self._all
                if kw in c.title.lower()
                or kw in c.category.lower()
                or any(kw in k.lower() for k in c.keywords)
            ]
            if kw else self._all
        )
        self._populate(matched)

    # ── Execute ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        cmd: Command | None = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        if cmd and cmd.action:
            cmd.action()

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._input and isinstance(event, QKeyEvent):
            key = event.key()
            n = self._list.count()
            r = self._list.currentRow()
            if key == Qt.Key.Key_Down and n:
                self._list.setCurrentRow(min(r + 1, n - 1))
                return True
            if key == Qt.Key.Key_Up and n:
                self._list.setCurrentRow(max(r - 1, 0))
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(event)

    # ── Show ──────────────────────────────────────────────────────────────────

    def open_at(self, parent_window) -> None:
        g = parent_window.frameGeometry()
        x = g.x() + (g.width() - self.width()) // 2
        y = g.y() + int(g.height() * 0.18)
        self.move(x, y)
        self.exec()
