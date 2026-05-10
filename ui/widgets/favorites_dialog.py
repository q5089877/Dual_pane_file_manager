from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QInputDialog, QLineEdit,
    QFileDialog, QSplitter, QWidget, QFrame,
)
from PyQt6.QtCore import Qt


class FavoritesDialog(QDialog):
    """管理常用路徑（群組 + 路徑清單）"""

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self._config_mgr = config_mgr
        self._data: list[dict] = [
            {"group": g["group"], "paths": list(g["paths"])}
            for g in config_mgr.get_favorites()
        ]
        title = config_mgr.get_text("ui_favorites_dialog_title", "管理常用路徑")
        self.setWindowTitle(title)
        self.setMinimumSize(600, 380)
        self._build_ui()
        self._refresh_group_list()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        # ── 左欄：群組 ──────────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addWidget(QLabel(
            self._config_mgr.get_text("ui_favorites_label_groups", "群組")))
        self._group_list = QListWidget()
        self._group_list.currentRowChanged.connect(self._on_group_selected)
        lv.addWidget(self._group_list)

        g_btns = QHBoxLayout()
        self._btn_add_group = QPushButton(
            self._config_mgr.get_text("ui_favorites_add_group", "新增群組"))
        self._btn_rename_group = QPushButton(
            self._config_mgr.get_text("ui_favorites_rename_group", "重命名"))
        self._btn_rm_group = QPushButton(
            self._config_mgr.get_text("ui_favorites_remove_group", "移除群組"))
        self._btn_add_group.clicked.connect(self._on_add_group)
        self._btn_rename_group.clicked.connect(self._on_rename_group)
        self._btn_rm_group.clicked.connect(self._on_remove_group)
        g_btns.addWidget(self._btn_add_group)
        g_btns.addWidget(self._btn_rename_group)
        g_btns.addWidget(self._btn_rm_group)
        lv.addLayout(g_btns)
        splitter.addWidget(left)

        # ── 分隔線 ────────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        splitter.addWidget(sep)

        # ── 右欄：路徑 ──────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        self._path_label = QLabel(
            self._config_mgr.get_text("ui_favorites_label_paths", "路徑"))
        rv.addWidget(self._path_label)
        self._path_list = QListWidget()
        rv.addWidget(self._path_list)

        p_btns = QHBoxLayout()
        self._btn_add_path = QPushButton(
            self._config_mgr.get_text("ui_favorites_add_path", "新增路徑"))
        self._btn_rm_path = QPushButton(
            self._config_mgr.get_text("ui_favorites_remove_path", "移除所選"))
        self._btn_add_path.clicked.connect(self._on_add_path)
        self._btn_rm_path.clicked.connect(self._on_remove_path)
        p_btns.addWidget(self._btn_add_path)
        p_btns.addWidget(self._btn_rm_path)
        p_btns.addStretch()
        rv.addLayout(p_btns)
        splitter.addWidget(right)

        splitter.setSizes([220, 4, 360])

        # ── 底部按鈕 ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton(
            self._config_mgr.get_text("ui_dialog_settings_btn_save", "完成並儲存"))
        save_btn.setDefault(True)
        save_btn.setStyleSheet("font-weight: bold; padding: 6px 20px;")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(
            self._config_mgr.get_text("ui_dialog_settings_btn_cancel", "取消"))
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

        self._update_right_state()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _current_group_idx(self) -> int:
        return self._group_list.currentRow()

    def _update_right_state(self) -> None:
        has_group = self._current_group_idx() >= 0
        self._path_list.setEnabled(has_group)
        self._btn_add_path.setEnabled(has_group)
        self._btn_rm_path.setEnabled(has_group)
        self._btn_rename_group.setEnabled(has_group)
        self._btn_rm_group.setEnabled(has_group)

    def _refresh_group_list(self) -> None:
        prev = self._current_group_idx()
        self._group_list.clear()
        for entry in self._data:
            self._group_list.addItem(entry["group"])
        new_row = min(prev, len(self._data) - 1)
        if new_row >= 0:
            self._group_list.setCurrentRow(new_row)
        self._on_group_selected(self._current_group_idx())

    def _refresh_path_list(self, idx: int) -> None:
        self._path_list.clear()
        if 0 <= idx < len(self._data):
            for p in self._data[idx]["paths"]:
                self._path_list.addItem(p)

    # ── group actions ─────────────────────────────────────────────────────────

    def _on_group_selected(self, row: int) -> None:
        self._refresh_path_list(row)
        self._update_right_state()

    def _on_add_group(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            self._config_mgr.get_text("ui_favorites_add_group", "新增群組"),
            self._config_mgr.get_text("ui_favorites_add_group", "群組名稱："))
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(e["group"] == name for e in self._data):
            return
        self._data.append({"group": name, "paths": []})
        self._refresh_group_list()
        self._group_list.setCurrentRow(len(self._data) - 1)

    def _on_rename_group(self) -> None:
        idx = self._current_group_idx()
        if idx < 0:
            return
        old_name = self._data[idx]["group"]
        name, ok = QInputDialog.getText(
            self,
            self._config_mgr.get_text("ui_favorites_rename_group", "重命名"),
            self._config_mgr.get_text("ui_favorites_rename_group", "群組名稱："),
            text=old_name)
        if not ok or not name.strip() or name.strip() == old_name:
            return
        self._data[idx]["group"] = name.strip()
        self._refresh_group_list()
        self._group_list.setCurrentRow(idx)

    def _on_remove_group(self) -> None:
        idx = self._current_group_idx()
        if idx < 0:
            return
        self._data.pop(idx)
        self._refresh_group_list()

    # ── path actions ──────────────────────────────────────────────────────────

    def _on_add_path(self) -> None:
        idx = self._current_group_idx()
        if idx < 0:
            return
        path = QFileDialog.getExistingDirectory(
            self,
            self._config_mgr.get_text("ui_dialog_settings_dlg_select_dir", "選擇資料夾"))
        if not path:
            return
        path = path.replace("/", "\\")
        if path not in self._data[idx]["paths"]:
            self._data[idx]["paths"].append(path)
            self._refresh_path_list(idx)

    def _on_remove_path(self) -> None:
        idx = self._current_group_idx()
        if idx < 0:
            return
        for item in self._path_list.selectedItems():
            p = item.text()
            if p in self._data[idx]["paths"]:
                self._data[idx]["paths"].remove(p)
        self._refresh_path_list(idx)

    # ── accept / reject ───────────────────────────────────────────────────────

    def accept(self) -> None:
        self._config_mgr.save_favorites(self._data)
        super().accept()
