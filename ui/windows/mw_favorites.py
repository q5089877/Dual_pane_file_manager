from __future__ import annotations
import os
from PyQt6.QtWidgets import QMenu, QFileDialog
from PyQt6.QtCore import QPoint


class _MwFavoritesMixin:
    """Favorites menu, navigation, add/remove, and manager dialog."""

    def _build_favorites_menu(self) -> QMenu:
        menu = QMenu(self)
        favorites = self.config_mgr.get_favorites()
        if favorites:
            for entry in favorites:
                group_name = entry.get("group", "")
                paths = entry.get("paths", [])
                if not paths:
                    continue
                sub = menu.addMenu(f"📁 {group_name}")
                for path in paths:
                    act = sub.addAction(path)
                    act.triggered.connect(
                        lambda checked, p=path: self.on_quick_access_clicked(p))
        else:
            empty_act = menu.addAction(
                self.config_mgr.get_text("ui_favorites_empty", "(尚無常用路徑)"))
            empty_act.setEnabled(False)
        menu.addSeparator()
        add_act = menu.addAction(
            self.config_mgr.get_text("ui_favorites_add_current", "➕ 將目前路徑加入常用..."))
        add_act.triggered.connect(self._add_current_path_to_favorites)
        manage_act = menu.addAction(
            self.config_mgr.get_text("ui_favorites_manage", "✏️ 管理常用路徑..."))
        manage_act.triggered.connect(self._open_favorites_manager)
        return menu

    def _show_favorites_menu_at(self, pos: QPoint) -> None:
        """Slot for pane toolbar star button — shows favorites at the given position."""
        self._build_favorites_menu().exec(pos)

    def _add_path_to_favorites(self, path: str) -> None:
        from PyQt6.QtWidgets import QInputDialog
        if not path or not os.path.isdir(path):
            return
        favorites = self.config_mgr.get_favorites()
        group_names = [e["group"] for e in favorites]
        title = self.config_mgr.get_text(
            "ui_favorites_add_current_title", "加入常用路徑")
        label = self.config_mgr.get_text(
            "ui_favorites_select_group", "選擇或輸入群組名稱：")
        group, ok = QInputDialog.getItem(
            self, title, label, group_names or ["常用"], editable=True)
        if not ok or not group.strip():
            return
        group = group.strip()
        for entry in favorites:
            if entry["group"] == group:
                if path not in entry["paths"]:
                    entry["paths"].append(path)
                self.config_mgr.save_favorites(favorites)
                return
        favorites.append({"group": group, "paths": [path]})
        self.config_mgr.save_favorites(favorites)

    def _add_current_path_to_favorites(self) -> None:
        pane = getattr(self, "active_pane", None)
        if not pane:
            return
        current = getattr(pane, "_current_path", "") or ""
        if not current or current == "home://":
            return
        self._add_path_to_favorites(current)

    def _open_favorites_manager(self) -> None:
        from ui.widgets.favorites_dialog import FavoritesDialog
        dlg = FavoritesDialog(self.config_mgr, self)
        dlg.exec()
        self.refresh_toolbar()

    def on_add_custom_path(self):
        p = QFileDialog.getExistingDirectory(
            self, self.config_mgr.get_text("ui_main_dialog_new_folder", "新增資料夾"))
        if p and p not in self.custom_paths:
            self.custom_paths.append(p)
            self.refresh_toolbar()
            self.save_config()

    def remove_custom_path(self, path):
        if path in self.custom_paths:
            self.custom_paths.remove(path)
            self.refresh_toolbar()
            self.save_config()
            self.path_popup.hide()
