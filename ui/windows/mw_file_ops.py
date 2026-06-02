from __future__ import annotations
import os
from PyQt6.QtWidgets import QMenu, QMessageBox
from PyQt6.QtCore import QPoint


class _MwFileOpsMixin:
    """Copy/move between panes, navigation shortcuts, drive selection,
    quick look, folder tree export, and misc. one-liner actions."""

    _TREE_BLACKLIST = [
        ".git", ".svn", "__pycache__", "venv", ".venv", "node_modules",
        "build", "dist", "out", "target", "logs", "log", "temp", "tmp",
    ]
    _TREE_MAX_DEPTH = 10

    def on_alt_left(self):
        if self.active_pane:
            self.active_pane.go_back()

    def on_alt_right(self):
        if self.active_pane:
            self.active_pane.go_forward()

    def on_advanced_search_clicked(self):
        if self.active_pane:
            self.active_pane.open_advanced_search()
        else:
            QMessageBox.warning(
                self,
                self.config_mgr.get_text("ui_main_warn_title", "警告"),
                self.config_mgr.get_text("ui_main_warn_select_pane", "請先點擊選取一個分頁"),
            )

    def on_quick_access_clicked(self, path):
        if not self.active_pane:
            return
        if not os.path.isdir(path):
            self.show_toast(
                self.config_mgr.get_text(
                    "ui_favorites_path_not_found",
                    f"路徑不存在：{path}"),
                "error")
            return
        self.active_pane.set_path(path)

    def show_drive_selection(self, side):
        """彈出磁碟選單"""
        tabs = self.left_tabs if side == "left" else self.right_tabs
        menu = QMenu(self)
        from PyQt6.QtCore import QDir
        for drive in QDir.drives():
            path = drive.absoluteFilePath()
            tpl = self.config_mgr.get_text("ui_main_menu_disk", "磁碟 {}")
            action = menu.addAction(tpl.format(path))
            action.triggered.connect(
                lambda _, p=path, t=tabs: self.add_new_tab(t, p))
        pos = tabs.mapToGlobal(QPoint(0, 0))
        menu.exec(pos)

    def _transfer_to_other_side(self, operation: str) -> None:
        """複製或移動選取項目到對面分欄（operation: 'copy' | 'move'）"""
        if not self.active_pane:
            return
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        target_pane = (self.right_tabs if is_left else self.left_tabs).currentWidget()
        if not target_pane:
            return

        dest_dir = target_pane.model.filePath(
            target_pane.proxy_model.mapToSource(target_pane.tree.rootIndex()))
        view = self.active_pane.view_stack.currentWidget()
        proxy = (self.active_pane.list_proxy
                 if view is self.active_pane.list_view
                 else self.active_pane.proxy_model)
        idxs = view.selectionModel().selectedRows() if hasattr(
            view, 'selectionModel') else []
        if not idxs and hasattr(view, 'selectionModel'):
            idxs = view.selectionModel().selectedIndexes()
        if not idxs:
            return

        src_paths = [p for p in dict.fromkeys(
            self.active_pane.model.filePath(proxy.mapToSource(idx))
            for idx in idxs
        ) if p]
        if not src_paths:
            return

        view.check_and_perform(src_paths, dest_dir, operation)

    def copy_selected_to_other_side(self):
        self._transfer_to_other_side("copy")

    def move_selected_to_other_side(self):
        self._transfer_to_other_side("move")

    def _sync_side(self, side):
        if not self.active_pane:
            return
        view = self.active_pane.view_stack.currentWidget()
        idx = view.currentIndex()
        path = self.active_pane.model.filePath(
            self.active_pane.proxy_model.mapToSource(
                idx if idx.isValid() else view.rootIndex()))
        if os.path.isfile(path):
            path = os.path.dirname(path)
        target = (self.left_tabs.currentWidget()
                  if side == "left"
                  else self.right_tabs.currentWidget())
        if target:
            target.set_path(path)

    def show_quick_look(self, path):
        """Show the Quick Look preview dialog for the given path."""
        from ui.widgets.quick_look import QuickLookDialog
        dlg = QuickLookDialog(path, self.config_mgr, self)
        dlg.exec()
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        target_tw = self.right_tabs if is_left else self.left_tabs
        pane = target_tw.currentWidget()
        if pane:
            pane.view_stack.currentWidget().setFocus()

    def _open_deep_search(self) -> None:
        pane = self.active_pane
        if pane and hasattr(pane, 'open_advanced_search'):
            pane.open_advanced_search()

    def open_new_window(self, path):
        """用 Windows 檔案總管開啟該路徑"""
        try:
            os.startfile(path)
        except Exception as e:
            self.show_toast(self.config_mgr.get_text(
                "ui_main_ctx_open_window_failed", "無法開啟新視窗: {}").format(e), "error")

    def on_export_folder_tree(self, path: str) -> None:
        """遞迴產生 ├── 樹狀圖，存成 .txt 後自動開啟。"""
        from core.models.folder_tree import count_items, generate_tree
        import tempfile
        import subprocess

        if not path or not os.path.isdir(path):
            QMessageBox.warning(
                self,
                self.config_mgr.get_text("ui_main_warn_title", "警告"),
                self.config_mgr.get_text("ui_main_warn_select_folder", "請選取一個資料夾。"),
            )
            return

        total = count_items(path, blacklist=self._TREE_BLACKLIST, max_depth=self._TREE_MAX_DEPTH)
        if not self._confirm_large_tree(total):
            return

        tree_text = generate_tree(path, blacklist=self._TREE_BLACKLIST, max_depth=self._TREE_MAX_DEPTH)
        folder_name = os.path.basename(path.rstrip("/\\")) or "tree"
        tmp_path = os.path.join(tempfile.gettempdir(), f"{folder_name}_tree.txt")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(tree_text)
        subprocess.Popen(["notepad.exe", tmp_path])

    def _confirm_large_tree(self, total: int) -> bool:
        if total <= 1000:
            return True
        reply = QMessageBox.question(
            self,
            self.config_mgr.get_text("ui_main_warn_too_many_items_title", "項目數量過多"),
            self.config_mgr.get_text(
                "ui_main_warn_too_many_items_msg",
                "此資料夾共有 {:,} 個項目，產生樹狀圖可能需要一點時間。\n確定繼續？",
            ).format(total),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes
