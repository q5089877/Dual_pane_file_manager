from __future__ import annotations
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QInputDialog,
    QFileDialog, QSplitter, QWidget, QFrame, QAbstractItemView,
)
from PyQt6.QtCore import Qt

_STANDALONE_ROW = 0


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class FavoritesDialog(QDialog):
    """管理常用路徑：直屬路徑（無群組）＋ 群組"""

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self._config_mgr = config_mgr
        raw = config_mgr.get_favorites()

        all_standalones = [e["path"] for e in raw if "path" in e]
        all_groups = [
            {"group": e["group"], "paths": list(e["paths"])}
            for e in raw if "group" in e
        ]

        self._standalones, s_removed = self._filter_missing(all_standalones)
        for g in all_groups:
            valid, _ = self._filter_missing(g["paths"])
            g["paths"] = valid
        self._groups = all_groups
        g_removed = sum(
            len(e["paths"]) - len(self._filter_missing(e["paths"])[0])
            for e in all_groups
        )
        self._removed_count = s_removed + g_removed
        self.setWindowTitle(config_mgr.get_text("ui_favorites_dialog_title", "管理常用路徑"))
        self.setMinimumSize(600, 380)
        self._build_ui()
        self._refresh_left_list()
        self._group_list.setCurrentRow(0)
        self._restore_state()
        if self._removed_count:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(300, self._warn_removed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter = splitter
        root.addWidget(splitter, stretch=1)

        # ── 左欄：群組 ────────────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addWidget(QLabel(self._config_mgr.get_text("ui_favorites_label_groups", "群組")))
        self._group_list = QListWidget()
        self._group_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._group_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._group_list.currentRowChanged.connect(self._on_left_selected)
        self._group_list.model().rowsMoved.connect(self._on_groups_reordered)
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

        # ── 右欄：路徑 ────────────────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        self._path_label = QLabel(
            self._config_mgr.get_text("ui_favorites_label_paths", "路徑"))
        rv.addWidget(self._path_label)
        self._path_list = QListWidget()
        self._path_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._path_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._path_list.model().rowsMoved.connect(self._on_paths_reordered)
        self._path_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._path_list.customContextMenuRequested.connect(self._on_path_context_menu)
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

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _filter_missing(paths: list[str]) -> tuple[list[str], int]:
        valid = [p for p in paths if os.path.isdir(p)]
        return valid, len(paths) - len(valid)

    def _warn_removed(self) -> None:
        n = self._removed_count
        msg = self._config_mgr.get_text(
            "ui_favorites_removed_missing",
            f"已自動移除 {n} 個不存在的路徑。")
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            self._config_mgr.get_text("ui_favorites_dialog_title", "管理常用路徑"),
            msg)

    def _restore_state(self) -> None:
        state = self._config_mgr.load_config().get("favorites_dialog_state", {})
        w, h = state.get("width", 640), state.get("height", 420)
        self.resize(w, h)
        sizes = state.get("splitter", [])
        if sizes:
            self._splitter.setSizes(sizes)

    def closeEvent(self, event) -> None:
        self._config_mgr.save_config(
            favorites_dialog_state={
                "width": self.width(),
                "height": self.height(),
                "splitter": self._splitter.sizes(),
            })
        super().closeEvent(event)

    def _is_standalone_row(self) -> bool:
        return self._group_list.currentRow() == _STANDALONE_ROW

    def _group_idx(self) -> int:
        row = self._group_list.currentRow()
        return row - 1 if row > _STANDALONE_ROW else -1

    def _refresh_left_list(self) -> None:
        prev = self._group_list.currentRow()
        self._group_list.clear()
        label = self._config_mgr.get_text("ui_favorites_standalone", "📌 直屬路徑")
        suffix = f"  ({len(self._standalones)})" if self._standalones else ""
        standalone_item = QListWidgetItem(f"{label}{suffix}")
        standalone_item.setFlags(
            standalone_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
        self._group_list.addItem(standalone_item)
        for entry in self._groups:
            self._group_list.addItem(entry["group"])
        self._group_list.setCurrentRow(
            max(0, min(prev, self._group_list.count() - 1)))

    def _refresh_path_list(self) -> None:
        self._path_list.clear()
        if self._is_standalone_row():
            for p in self._standalones:
                self._path_list.addItem(p)
        else:
            idx = self._group_idx()
            if 0 <= idx < len(self._groups):
                for p in self._groups[idx]["paths"]:
                    self._path_list.addItem(p)

    def _update_button_states(self) -> None:
        has_group = self._group_idx() >= 0
        self._btn_rename_group.setEnabled(has_group)
        self._btn_rm_group.setEnabled(has_group)

    # ── left list ─────────────────────────────────────────────────────────────

    def _on_left_selected(self, _row: int) -> None:
        self._refresh_path_list()
        self._update_button_states()

    def _on_groups_reordered(self) -> None:
        name_to_group = {g["group"]: g for g in self._groups}
        self._groups = [
            name_to_group[self._group_list.item(r).text()]
            for r in range(1, self._group_list.count())
            if self._group_list.item(r) and
            self._group_list.item(r).text() in name_to_group
        ]

    def _on_paths_reordered(self) -> None:
        new_order = [
            self._path_list.item(r).text()
            for r in range(self._path_list.count())
        ]
        if self._is_standalone_row():
            self._standalones = new_order
        else:
            idx = self._group_idx()
            if 0 <= idx < len(self._groups):
                self._groups[idx]["paths"] = new_order

    def _on_path_context_menu(self, pos) -> None:
        selected = [item.text() for item in self._path_list.selectedItems()]
        if not selected:
            return
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        move_label = self._config_mgr.get_text("ui_favorites_move_to_group", "移至群組…")
        move_menu = menu.addMenu(move_label)

        # 直屬路徑 option
        standalone_label = self._config_mgr.get_text("ui_favorites_standalone", "📌 直屬路徑")
        if not self._is_standalone_row():
            act = move_menu.addAction(standalone_label)
            act.triggered.connect(lambda: self._move_paths_to(selected, None))

        for g in self._groups:
            if self._is_standalone_row() or g["group"] != self._groups[self._group_idx()]["group"]:
                act = move_menu.addAction(f"📁 {g['group']}")
                act.triggered.connect(
                    lambda checked, name=g["group"]: self._move_paths_to(selected, name))

        menu.exec(self._path_list.viewport().mapToGlobal(pos))

    def _move_paths_to(self, paths: list[str], target_group: str | None) -> None:
        # Remove from source
        if self._is_standalone_row():
            for p in paths:
                if p in self._standalones:
                    self._standalones.remove(p)
        else:
            idx = self._group_idx()
            if 0 <= idx < len(self._groups):
                for p in paths:
                    if p in self._groups[idx]["paths"]:
                        self._groups[idx]["paths"].remove(p)

        # Add to target
        if target_group is None:
            for p in paths:
                if _norm(p) not in [_norm(x) for x in self._standalones]:
                    self._standalones.append(p)
        else:
            for g in self._groups:
                if g["group"] == target_group:
                    for p in paths:
                        if _norm(p) not in [_norm(x) for x in g["paths"]]:
                            g["paths"].append(p)
                    break

        self._refresh_left_list()
        self._refresh_path_list()

    def _on_add_group(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            self._config_mgr.get_text("ui_favorites_add_group", "新增群組"),
            self._config_mgr.get_text("ui_favorites_add_group", "群組名稱："))
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(e["group"] == name for e in self._groups):
            return
        self._groups.append({"group": name, "paths": []})
        self._refresh_left_list()
        self._group_list.setCurrentRow(len(self._groups))

    def _on_rename_group(self) -> None:
        idx = self._group_idx()
        if idx < 0:
            return
        old = self._groups[idx]["group"]
        name, ok = QInputDialog.getText(
            self,
            self._config_mgr.get_text("ui_favorites_rename_group", "重命名"),
            self._config_mgr.get_text("ui_favorites_rename_group", "群組名稱："),
            text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        self._groups[idx]["group"] = name.strip()
        prev_row = self._group_list.currentRow()
        self._refresh_left_list()
        self._group_list.setCurrentRow(prev_row)

    def _on_remove_group(self) -> None:
        idx = self._group_idx()
        if idx < 0:
            return
        self._groups.pop(idx)
        self._refresh_left_list()

    # ── path actions ──────────────────────────────────────────────────────────

    def _on_add_path(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            self._config_mgr.get_text("ui_dialog_settings_dlg_select_dir", "選擇資料夾"))
        if not path:
            return
        path = path.replace("/", "\\")
        if self._is_standalone_row():
            if _norm(path) not in [_norm(p) for p in self._standalones]:
                self._standalones.append(path)
                self._refresh_left_list()
                self._refresh_path_list()
        else:
            idx = self._group_idx()
            if 0 <= idx < len(self._groups):
                existing = [_norm(p) for p in self._groups[idx]["paths"]]
                if _norm(path) not in existing:
                    self._groups[idx]["paths"].append(path)
                    self._refresh_path_list()

    def _on_remove_path(self) -> None:
        selected = [item.text() for item in self._path_list.selectedItems()]
        if self._is_standalone_row():
            for p in selected:
                if p in self._standalones:
                    self._standalones.remove(p)
            self._refresh_left_list()
            self._refresh_path_list()
        else:
            idx = self._group_idx()
            if 0 <= idx < len(self._groups):
                for p in selected:
                    if p in self._groups[idx]["paths"]:
                        self._groups[idx]["paths"].remove(p)
                self._refresh_path_list()

    # ── accept ────────────────────────────────────────────────────────────────

    def accept(self) -> None:
        full = [{"path": p} for p in self._standalones] + self._groups
        self._config_mgr.save_favorites(full)
        super().accept()
