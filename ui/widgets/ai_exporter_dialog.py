from PyQt6.QtWidgets import QProgressDialog, QMessageBox
from PyQt6.QtCore import Qt
from core.interfaces import IAIExporterView


class AIExporterProgressDialog(QProgressDialog):
    """
    Wraps QProgressDialog to provide a visual interface for AI context export.
    Returns an adapter to satisfy the IAIExporterView interface, avoiding PyQt metaclass conflicts.
    """
    def __init__(self, parent=None):
        self.config_mgr = getattr(parent, "config_mgr", None)
        super().__init__(
            self.config_mgr.get_text("ui_dialog_ai_status_scanning", "正在掃描目錄...") if self.config_mgr else "正在掃描目錄...",
            self.config_mgr.get_text("ui_dialog_ai_btn_cancel", "取消") if self.config_mgr else "取消",
            0, 100, parent,
        )
        self.setWindowTitle(self.config_mgr.get_text("ui_dialog_ai_title", "產生 AI Context") if self.config_mgr else "產生 AI Context")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumDuration(0)
        self.setAutoReset(False)
        self.setAutoClose(False)

    def get_view_adapter(self) -> IAIExporterView:
        class _AIExporterViewAdapter(IAIExporterView):
            def __init__(self, dlg): self.dlg = dlg
            def show(self): self.dlg.show()
            def close(self): self.dlg.close()
            def set_range(self, total: int) -> None: self.dlg.setMaximum(total)
            def update_progress(self, filename: str, current: int, total: int) -> None:
                if self.dlg.maximum() != total:
                    self.dlg.setMaximum(total)
                self.dlg.setValue(current)
                _cm = self.dlg.config_mgr
                self.dlg.setLabelText(
                    _cm.get_text("ui_dialog_ai_status_processing", "處理檔案 ({}/{}):\n{}").format(current, total, filename) if _cm else f"處理檔案 ({current}/{total}):\n{filename}"
                )
            def show_success(self, file_count: int, char_count: int) -> None:
                _cm = self.dlg.config_mgr
                _title = _cm.get_text("ui_dialog_ai_success_title", "匯出成功") if _cm else "匯出成功"
                _default_msg = (
                    "✅ AI Context 已成功產生並複製到剪貼簿！\n\n"
                    "• 包含檔案：{} 個\n"
                    "• 總字元數：{} 字\n\n"
                    "提示：現在可以直接在 ChatGPT 或 Claude 中貼上 (Ctrl+V)。"
                )
                _msg = (_cm.get_text("ui_dialog_ai_success_msg", _default_msg) if _cm else _default_msg).format(file_count, f"{char_count:,}")
                QMessageBox.information(self.dlg.parent(), _title, _msg)
            def show_error(self, message: str) -> None:
                _cm = self.dlg.config_mgr
                _title = _cm.get_text("ui_dialog_ai_error_title", "匯出錯誤") if _cm else "匯出錯誤"
                _msg = (_cm.get_text("ui_dialog_ai_error_msg", "發生錯誤：\n{}") if _cm else "發生錯誤：\n{}").format(message)
                QMessageBox.critical(self.dlg.parent(), _title, _msg)
            def set_cancelled_callback(self, callback) -> None:
                self.dlg.canceled.connect(callback)

        return _AIExporterViewAdapter(self)
