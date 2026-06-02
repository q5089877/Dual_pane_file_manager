from __future__ import annotations
import os
from PyQt6.QtWidgets import QMenu, QFileDialog, QInputDialog
from PyQt6.QtCore import QPoint


class _MwFavoritesMixin:
    """Favorites menu, navigation, add/remove, and manager dialog."""

    def _record_recent_folder(self, path: str) -> None:
        if path and path != "home://" and os.path.isdir(path):
            self.config_mgr.add_recent_folder(path)

    def _build_favorites_menu(self) -> QMenu:
        menu = QMenu(self)

        # ── 最近使用 ──────────────────────────────────────────────────────────
        recents = self.config_mgr.get_recent_folders()
        if recents:
            recent_sub = menu.addMenu(
                self.config_mgr.get_text("ui_favorites_recent", "🕐 最近使用"))
            for path in recents:
                label = os.path.basename(path) or path
                act = recent_sub.addAction(label)
                act.setToolTip(path)
                act.triggered.connect(
                    lambda checked, p=path: self.on_quick_access_clicked(p))
            menu.addSeparator()

        favorites = self.config_mgr.get_favorites()
        standalones = [e["path"] for e in favorites if "path" in e]
        groups = [e for e in favorites if "group" in e]

        if not standalones and not groups:
            empty_act = menu.addAction(
                self.config_mgr.get_text("ui_favorites_empty", "(尚無常用路徑)"))
            empty_act.setEnabled(False)
        else:
            for path in standalones:
                label = os.path.basename(path) or path
                act = menu.addAction(f"📌 {label}")
                act.setToolTip(path)
                act.triggered.connect(
                    lambda checked, p=path: self.on_quick_access_clicked(p))

            if standalones and groups:
                menu.addSeparator()

            for entry in groups:
                group_name = entry.get("group", "")
                paths = entry.get("paths", [])
                if not paths:
                    continue
                if len(paths) == 1:
                    act = menu.addAction(f"📁 {group_name}  {paths[0]}")
                    act.triggered.connect(
                        lambda checked, p=paths[0]: self.on_quick_access_clicked(p))
                else:
                    sub = menu.addMenu(f"📁 {group_name}")
                    for path in paths:
                        act = sub.addAction(path)
                        act.triggered.connect(
                            lambda checked, p=path: self.on_quick_access_clicked(p))

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
        if not path or not os.path.isdir(path):
            return
        favorites = self.config_mgr.get_favorites()
        group_names = [e["group"] for e in favorites if "group" in e]

        no_group_label = self.config_mgr.get_text(
            "ui_favorites_no_group", "（直接加入，不分群組）")
        title = self.config_mgr.get_text("ui_favorites_add_current_title", "加入常用路徑")
        label = self.config_mgr.get_text(
            "ui_favorites_select_group", "選擇或輸入群組名稱：")

        options = [no_group_label] + group_names
        choice, ok = QInputDialog.getItem(
            self, title, label, options, editable=True)
        if not ok or not choice.strip():
            return

        norm = os.path.normcase(os.path.normpath(path))
        if choice == no_group_label:
            existing = [os.path.normcase(os.path.normpath(e["path"]))
                        for e in favorites if "path" in e]
            if norm not in existing:
                favorites.append({"path": path})
                self.config_mgr.save_favorites(favorites)
            return

        group = choice.strip()
        for entry in favorites:
            if entry.get("group") == group:
                existing = [os.path.normcase(os.path.normpath(p))
                            for p in entry["paths"]]
                if norm not in existing:
                    entry["paths"].append(path)
                    self.config_mgr.save_favorites(favorites)
                return
        favorites.append({"group": group, "paths": [path]})
        self.config_mgr.save_favorites(favorites)

    def _add_current_path_to_favorites(self) -> None:
        pane = getattr(self, "active_pane", None)
        if not pane:
            self.show_toast(
                self.config_mgr.get_text(
                    "ui_main_warn_select_pane", "請先點擊選取一個分頁"),
                "warning")
            return
        current = getattr(pane, "_current_path", "") or ""
        if not current or current == "home://":
            self.show_toast(
                self.config_mgr.get_text(
                    "ui_favorites_no_valid_path", "目前沒有可加入的有效路徑"),
                "warning")
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
