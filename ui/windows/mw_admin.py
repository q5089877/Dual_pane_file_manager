from __future__ import annotations


class _MwAdminMixin:
    """Hidden admin panel access via secret keyboard shortcut."""

    def _on_admin_shortcut(self) -> None:
        from PyQt6.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        pwd, ok = QInputDialog.getText(
            self, " ", "進入管理者設定：",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not pwd:
            return
        if pwd != self.config_mgr.get_master_password():
            QMessageBox.warning(self, "驗證失敗", "密碼錯誤。")
            return

        from ui.widgets.admin_config_dialog import AdminConfigDialog
        from PyQt6.QtWidgets import QDialog
        dlg = AdminConfigDialog(self.config_mgr, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._notify_search_panels_reload()
            # Also reload the shared index manager used by explorer panes
            self._reload_shared_index_manager()

    def _notify_search_panels_reload(self) -> None:
        for tw in (self.left_tabs, self.right_tabs):
            for i in range(tw.count()):
                w = tw.widget(i)
                if getattr(w, "_is_search_tab", False) and hasattr(w, "reload_config"):
                    w.reload_config()

    def _reload_shared_index_manager(self) -> None:
        """Rebuild the shared IndexManager so explorer panes get the updated NAS path."""
        try:
            from network_search.engine import IndexManager
            config = self.config_mgr.load_config()
            db_dir = self.config_mgr.get_index_path()
            nas_path = config.get("remote_index_root") or None
            is_master = config.get("is_master_node", False)
            self._shared_index_manager = IndexManager(
                db_dir, nas_folder_path=nas_path, read_only=not is_master
            )
            for tw in (self.left_tabs, self.right_tabs):
                for i in range(tw.count()):
                    w = tw.widget(i)
                    if not getattr(w, "_is_search_tab", False) and hasattr(w, "set_index_manager"):
                        w.set_index_manager(self._shared_index_manager)
        except Exception:
            pass
