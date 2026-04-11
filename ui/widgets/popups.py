import os
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMenu, QCheckBox,
    QDialog, QLineEdit, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon


class PinNoteDialog(QDialog):
    """Input dialog for pin note that auto-accepts after `timeout_sec` seconds."""

    def __init__(self, filename: str, parent=None, timeout_sec: int = 5):
        super().__init__(parent)
        self.config_mgr = getattr(parent, "config_mgr", None) if parent else None
        title = self.config_mgr.get_text("ui_popup_pin_note_title", "釘選備忘（可空白）") if self.config_mgr else "釘選備忘（可空白）"
        self.setWindowTitle(title)
        self._timeout = timeout_sec
        self._remaining = timeout_sec

        layout = QVBoxLayout(self)
        label_text = self.config_mgr.get_text("ui_popup_pin_note_label", "為「{}」加上備忘：").format(filename) if self.config_mgr else f"為「{filename}」加上備忘："
        layout.addWidget(QLabel(label_text))

        self._edit = QLineEdit()
        self._edit.textChanged.connect(self._on_typing)
        layout.addWidget(self._edit)

        hint_text = self.config_mgr.get_text("ui_popup_pin_note_hint", "{} 秒後自動確認...").format(self._remaining) if self.config_mgr else f"{self._remaining} 秒後自動確認..."
        self._hint = QLabel(hint_text)
        self._hint.setObjectName("pinNoteLabel")
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        if timeout_sec > 0:
            self._timer.start()
        else:
            self._hint.hide()

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
        else:
            self._hint.setText(f"{self._remaining} 秒後自動確認...")

    def _on_typing(self):
        """Stop countdown once user starts typing."""
        self._timer.stop()
        self._hint.setText("")

    def note(self) -> str:
        return self._edit.text().strip()

class PathPopup(QFrame):
    """Popup window for custom paths/quick access."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.main_window = main_window; self.setObjectName("PathPopup")
        self.layout = QVBoxLayout(self); self.layout.setContentsMargins(5, 5, 5, 5); self.layout.setSpacing(2)
        self.hide_timer = QTimer(self); self.hide_timer.setSingleShot(True); self.hide_timer.setInterval(2000)
        self.hide_timer.timeout.connect(self.hide)

    def populate(self, paths):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        for p in paths:
            if os.path.exists(p):
                btn = QPushButton(os.path.basename(p) or p); btn.setIcon(QIcon.fromTheme("folder")); btn.setToolTip(p)
                btn.clicked.connect(lambda checked, path=p: self._on_clicked(path))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(lambda pos, path=p, b=btn: self._show_context(pos, path, b))
                self.layout.addWidget(btn)

        add_text = self.main_window.config_mgr.get_text("ui_popup_bookmark_add", "+ 加入書籤") if hasattr(self.main_window, "config_mgr") else "+ 加入書籤"
        add_btn = QPushButton(add_text)
        _add_qss = "color: {{accent}}; font-weight: bold;"
        _cm = getattr(self.main_window, 'config_mgr', None)
        if _cm:
            _add_qss = _cm.apply_theme_to_text(_add_qss)
        add_btn.setStyleSheet(_add_qss)
        add_btn.clicked.connect(self.main_window.on_add_custom_path); self.layout.addWidget(add_btn)

    def _on_clicked(self, path):
        self.hide(); self.main_window.on_quick_access_clicked(path)

    def _show_context(self, pos, path, button):
        del_text = self.main_window.config_mgr.get_text("ui_popup_bookmark_remove", "移除書籤") if hasattr(self.main_window, "config_mgr") else "移除書籤"
        menu = QMenu(self); del_act = QAction(del_text, self)
        del_act.triggered.connect(lambda: self.main_window.remove_custom_path(path))
        menu.addAction(del_act); menu.exec(button.mapToGlobal(pos))

    def enterEvent(self, event): self.hide_timer.stop(); super().enterEvent(event)
    def leaveEvent(self, event): self.hide_timer.start(); super().leaveEvent(event)


class PinPopup(QFrame):
    """Popup showing pinned items with TTL countdown dots."""

    _DOT_FRESH  = "pinDotFresh"
    _DOT_WARN   = "pinDotWarn"
    _DOT_URGENT = "pinDotUrgent"

    def __init__(self, main_window, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.main_window = main_window
        self._config_mgr = None
        self.setObjectName("PinPopup")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(2)

    def _refresh(self):
        if self._config_mgr:
            self.populate(self._config_mgr.get_pins(), self._config_mgr)
            self.main_window.refresh_toolbar()

    def populate(self, pins: list, config_mgr):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._config_mgr = config_mgr

        if not pins:
            empty_text = self._config_mgr.get_text("ui_popup_pin_empty", "（無釘選項目）") if self._config_mgr else "（無釘選項目）"
            lbl = QLabel(empty_text)
            lbl.setObjectName("pinEmptyLabel")
            self.layout.addWidget(lbl)
            return

        # Sort: important first, then by days_left asc, done last
        def _sort_key(p):
            if p.get("done"):
                return (2, 0)
            if p.get("important"):
                return (0, 0)
            return (1, config_mgr.get_pin_days_left(p))

        for pin in sorted(pins, key=_sort_key):
            days_left = config_mgr.get_pin_days_left(pin)
            path = pin["path"]
            name = os.path.basename(path) or path
            note = pin.get("note", "").strip()
            is_important = pin.get("important", False)
            is_done = pin.get("done", False)

            cell = QFrame()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 1, 2, 1)
            cell_layout.setSpacing(0)

            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            # ✓ 完成勾選框
            chk = QCheckBox()
            chk.setChecked(is_done)
            chk.setObjectName("pinDoneCheck")
            done_tip = self._config_mgr.get_text("ui_popup_pin_done_tooltip", "標為完成（24 小時後自動清除）") if self._config_mgr else "標為完成（24 小時後自動清除）"
            chk.setToolTip(done_tip)
            def _on_done(checked, p=path):
                self.main_window.config_mgr.set_pin_done(p, checked)
                self._refresh()
            chk.clicked.connect(_on_done)

            # 主按鈕
            icon = "📁 " if pin.get("is_dir") else "📄 "
            btn = QPushButton(icon + name)
            btn.setToolTip(path)
            btn.setFlat(True)
            btn.setObjectName("pinItemBtnDone" if is_done else "pinItemBtn")
            btn.clicked.connect(lambda checked, p=path: self._on_clicked(p))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, p=path, b=btn: self._show_context(pos, p, b))

            # ⭐ 重要切換
            star_btn = QPushButton("⭐" if is_important else "☆")
            star_btn.setFixedWidth(24)
            star_btn.setFlat(True)
            star_btn.setObjectName("pinStarActive" if is_important else "pinStar")
            imp_tip = self._config_mgr.get_text("ui_popup_pin_important_tooltip", "永久釘選（30 天未使用自動降級）") if self._config_mgr else "永久釘選（30 天未使用自動降級）"
            not_imp_tip = self._config_mgr.get_text("ui_popup_pin_not_important_tooltip", "標為重要（永久保留）") if self._config_mgr else "標為重要（永久保留）"
            star_btn.setToolTip(imp_tip if is_important else not_imp_tip)
            def _on_star(_checked, p=path, imp=is_important):
                self.main_window.config_mgr.set_pin_important(p, not imp)
                self._refresh()
            star_btn.clicked.connect(_on_star)

            # TTL 圓點（重要釘選不顯示）
            if not is_important and not is_done:
                dot = QLabel()
                dot.setFixedSize(10, 10)
                if days_left <= 1:
                    dot.setObjectName(self._DOT_URGENT)
                    dot.setToolTip(self._config_mgr.get_text("ui_popup_pin_expiry_today", "今天到期") if self._config_mgr else "今天到期")
                elif days_left <= 3:
                    dot.setObjectName(self._DOT_WARN)
                    dot.setToolTip(self._config_mgr.get_text("ui_popup_pin_expiry_days", "剩 {} 天").format(days_left) if self._config_mgr else f"剩 {days_left} 天")
                else:
                    dot.setObjectName(self._DOT_FRESH)
                    dot.setToolTip(self._config_mgr.get_text("ui_popup_pin_expiry_days", "剩 {} 天").format(days_left) if self._config_mgr else f"剩 {days_left} 天")
            else:
                dot = None

            row_layout.addWidget(chk, 0)
            row_layout.addWidget(btn, 1)
            row_layout.addWidget(star_btn, 0)
            if dot:
                row_layout.addWidget(dot, 0)
            cell_layout.addWidget(row)

            if note:
                note_lbl = QLabel(note)
                note_lbl.setObjectName("pinNoteLabel")
                note_lbl.setWordWrap(True)
                cell_layout.addWidget(note_lbl)

            self.layout.addWidget(cell)

    def _on_clicked(self, path: str):
        self.hide()
        if hasattr(self.main_window, "config_mgr"):
            self.main_window.config_mgr.touch_pin(path)
        norm = os.path.normpath(path)
        if os.path.isdir(norm):
            self.main_window.on_quick_access_clicked(norm)
        else:
            try:
                os.startfile(norm)
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self.main_window, "無法開啟",
                                    f"找不到或無法開啟：\n{norm}\n\n{e}")

    def _show_context(self, pos, path: str, button):
        self.hide()
        menu = QMenu(self.main_window)
        edit_text = self.main_window.config_mgr.get_text("ui_popup_pin_edit_note", "編輯備忘") if hasattr(self.main_window, "config_mgr") else "編輯備忘"
        edit_act = QAction(edit_text, self.main_window)
        edit_act.triggered.connect(lambda: self.main_window.edit_pin_note(path))
        menu.addAction(edit_act)
        menu.addSeparator()
        unpin_text = self.main_window.config_mgr.get_text("ui_popup_pin_unpin", "解除釘選") if hasattr(self.main_window, "config_mgr") else "解除釘選"
        unpin_act = QAction(unpin_text, self.main_window)
        unpin_act.triggered.connect(lambda: self.main_window.toggle_pin(path))
        menu.addAction(unpin_act)
        menu.exec(button.mapToGlobal(pos))
