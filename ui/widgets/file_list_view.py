import os
from PyQt6.QtWidgets import QListView, QMenu, QAbstractItemView, QApplication, QStyledItemDelegate
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from ui.widgets.base_view import BaseFileView
from core.file_ops import FileOps
from ui.workers.thumbnail_manager import ThumbnailManager
from ui.widgets.thumbnail_delegate import ThumbnailDelegate

_ICON_CELL_W = 96
_ICON_CELL_H = 96

class FileListView(BaseFileView, QListView):
    """Refactored QListView using BaseFileView for common logic."""
    file_operation_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.__init_base__()
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setSelectionRectVisible(True)
        # Prevent rename from starting on double-click (same as FileTreeView)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)

        # Thumbnail delegate (used in icons mode)
        self._thumb_mgr = ThumbnailManager(self)
        self._delegate = ThumbnailDelegate(config_mgr=None, parent=self)
        self._delegate.set_thumbnail_manager(self._thumb_mgr)
        self._default_delegate = QStyledItemDelegate(self)

        # Default: icons mode
        self.set_display_mode("icons")

    def set_config_mgr(self, config_mgr) -> None:
        """注入 ConfigManager，讓 ThumbnailDelegate 能使用 theme 顏色。"""
        self._cm = config_mgr
        self._delegate._config_mgr = config_mgr

    def _t(self, key: str, fallback: str) -> str:
        cm = getattr(self, '_cm', None)
        return cm.get_text(key, fallback) if cm else fallback

    def set_display_mode(self, mode: str):
        """Switch between 'list' (compact rows) and 'icons' (medium thumbnail grid)."""
        if mode == "list":
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setItemDelegate(self._default_delegate)
            self.setIconSize(QSize(16, 16))
            self.setGridSize(QSize())
            self.setSpacing(0)
            self.setWordWrap(False)
        else:  # icons
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setItemDelegate(self._delegate)
            from ui.widgets.thumbnail_delegate import ThumbnailDelegate as _TD
            self.setIconSize(QSize(_TD.THUMB_W, _TD.THUMB_H))
            self.setGridSize(QSize(_TD.CELL_W + 8, _TD.CELL_H + 8))
            self.setSpacing(4)
            self.setWordWrap(True)


    def dropEvent(self, event):
        self.handle_drop(event, self.rootIndex())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            idx = self.indexAt(event.position().toPoint())
            if idx.isValid() and not self.selectionModel().isSelected(idx):
                if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                    return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()
        
        if key == Qt.Key.Key_Delete:
            permanent = bool(mod & Qt.KeyboardModifier.ShiftModifier)
            self.parent().parent().delete_selected(permanent=permanent)
        elif key == Qt.Key.Key_F2 and (mod & Qt.KeyboardModifier.AltModifier):
            self.timestamp_rename_selected()
        elif key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            if self.state() == QAbstractItemView.State.EditingState:
                super().keyPressEvent(event)
            else:
                idx = self.currentIndex()
                if idx.isValid(): self.doubleClicked.emit(idx)
        elif key == Qt.Key.Key_F2:
            idxs = self.selectionModel().selectedIndexes()
            if idxs: self.edit(idxs[0])
        elif key == Qt.Key.Key_Backspace:
            self.parent().parent().go_up()
        elif key == Qt.Key.Key_F3:
            self.window().move_selected_to_other_side()
        elif key == Qt.Key.Key_F4:
            self.window().copy_selected_to_other_side()
        elif key == Qt.Key.Key_F5:
            self.parent().parent().refresh()
        elif key == Qt.Key.Key_F6:
            self.version_selected()
        elif key == Qt.Key.Key_F7:
            self.parent().parent().create_new_folder()
        elif mod & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_C: self.copy_to_clipboard(self.selectionModel().selectedIndexes(), False)
            elif key == Qt.Key.Key_X: self.copy_to_clipboard(self.selectionModel().selectedIndexes(), True)
            elif key == Qt.Key.Key_V:
                dest = getattr(self, '_current_path', None) or self.get_file_path(self.rootIndex())
                self.paste_from_clipboard(dest)
            elif key == Qt.Key.Key_D:
                idxs = self.selectionModel().selectedIndexes()
                if idxs:
                    path = self.get_file_path(idxs[0])
                    win = self.window()
                    if hasattr(win, "toggle_pin"):
                        win.toggle_pin(path)
            elif key == Qt.Key.Key_A:
                self.selectAll()
                event.accept()
        elif key == Qt.Key.Key_Space:
            idx = self.currentIndex()
            if idx.isValid():
                path = self.get_file_path(idx)
                if os.path.isfile(path):
                    win = self.window()
                    if hasattr(win, "toggle_inline_preview"):
                        win.toggle_inline_preview(path)
                    else:
                        win.show_quick_look(path)
        elif key == Qt.Key.Key_Escape:
            win = self.window()
            if hasattr(win, "close_inline_preview") and getattr(win, "_preview_target_pane", None):
                win.close_inline_preview()
                return
            super().keyPressEvent(event)
        elif not mod and self.state() == QAbstractItemView.State.NoState and \
                key == Qt.Key.Key_X:
            self.window().move_selected_to_other_side()
            event.accept()
        elif not mod and self.state() == QAbstractItemView.State.NoState and \
                key == Qt.Key.Key_C:
            self.window().copy_selected_to_other_side()
            event.accept()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        idxs = self.selectionModel().selectedIndexes()
        root_path = getattr(self, '_current_path', None) or self.get_file_path(self.rootIndex())
        win = self.window()
        has_paste = (hasattr(win, 'clipboard') and win.clipboard.get("paths")) or \
                    QApplication.clipboard().mimeData().hasUrls()

        if len(idxs) == 1:
            idx = idxs[0]; path = self.get_file_path(idx)
            is_folder = self.is_dir(idx)

            if not is_folder:
                menu.addAction(self._t("ui_ctx_preview", "👁️ 預覽 (Space)")).triggered.connect(lambda: self._trigger_preview(path))
                menu.addSeparator()
                menu.addAction(self._t("ui_ctx_open_with", "以其它程式開啟...")).triggered.connect(lambda: FileOps.open_with(path))
                if FileOps.is_archive(path):
                    menu.addAction(self._t("ui_ctx_smart_extract", "📦 智慧解壓縮到此 (Smart Extract)")).triggered.connect(lambda: self._extract_selected(path))
                menu.addSeparator()

            menu.addAction(self._t("ui_main_action_copy", "複製") + " (Ctrl+C)").triggered.connect(lambda: self.copy_to_clipboard(idxs, False))
            menu.addAction(self._t("ui_main_action_cut", "剪下") + " (Ctrl+X)").triggered.connect(lambda: self.copy_to_clipboard(idxs, True))
            if has_paste:
                menu.addAction(self._t("ui_main_action_paste", "貼上") + " (Ctrl+V)").triggered.connect(lambda: self.paste_from_clipboard(root_path))
            menu.addSeparator()
            menu.addAction(self._t("ui_main_action_delete", "刪除") + " → 回收筒 (Del)").triggered.connect(lambda: self.parent().parent().delete_selected())
            menu.addAction(self._t("ui_main_action_rename", "重新命名") + " (F2)").triggered.connect(lambda: self.edit(idx))
            menu.addAction(self._t("ui_ctx_timestamp_rename", "時間戳記改名 (Alt+F2)")).triggered.connect(self.timestamp_rename_selected)
            menu.addAction(self._t("ui_ctx_batch_rename", "批次重新命名...")).triggered.connect(self.open_batch_rename_dialog)
            menu.addAction(self._t("ui_ctx_duplicate", "製作副本 (F6)")).triggered.connect(self.version_selected)
            menu.addSeparator()
            menu.addAction(self._t("ui_ctx_copy_to_other", "複製到對面 (F4)")).triggered.connect(lambda: self.window().copy_selected_to_other_side())
            menu.addAction(self._t("ui_ctx_move_to_other", "移動到對面 (F3)")).triggered.connect(lambda: self.window().move_selected_to_other_side())
            menu.addSeparator()
            menu.addAction(self._t("ui_dialog_search_menu_copy_path", "複製路徑")).triggered.connect(lambda: QApplication.clipboard().setText(path))
            if is_folder:
                menu.addAction(self._t("ui_ctx_export_tree", "輸出資料夾樹狀圖")).triggered.connect(
                    lambda: win.on_export_folder_tree(path))
            if hasattr(win, "toggle_pin"):
                already = hasattr(win, "config_mgr") and win.config_mgr.is_pinned(path)
                pin_key = "ui_ctx_unpin" if already else "ui_ctx_pin"
                pin_fb = "解除釘選 (Ctrl+D)" if already else "📌 釘選 (Ctrl+D)"
                menu.addAction(self._t(pin_key, pin_fb)).triggered.connect(lambda: win.toggle_pin(path))
            menu.addSeparator()
            menu.addAction(self._t("ui_ctx_properties", "內容")).triggered.connect(lambda: FileOps.show_properties(path))

        elif idxs:
            menu.addAction(self._t("ui_main_action_copy", "複製") + " (Ctrl+C)").triggered.connect(lambda: self.copy_to_clipboard(idxs, False))
            menu.addAction(self._t("ui_main_action_cut", "剪下") + " (Ctrl+X)").triggered.connect(lambda: self.copy_to_clipboard(idxs, True))
            if has_paste:
                menu.addAction(self._t("ui_main_action_paste", "貼上") + " (Ctrl+V)").triggered.connect(lambda: self.paste_from_clipboard(root_path))
            menu.addSeparator()
            menu.addAction(self._t("ui_main_action_delete", "刪除") + " → 回收筒 (Del)").triggered.connect(lambda: self.parent().parent().delete_selected())
            menu.addAction(self._t("ui_ctx_timestamp_rename", "時間戳記改名 (Alt+F2)")).triggered.connect(self.timestamp_rename_selected)
            menu.addAction(self._t("ui_ctx_batch_rename", "批次重新命名...")).triggered.connect(self.open_batch_rename_dialog)
            menu.addAction(self._t("ui_ctx_duplicate", "製作副本 (F6)")).triggered.connect(self.version_selected)
            menu.addSeparator()
            menu.addAction(self._t("ui_ctx_copy_to_other", "複製到對面 (F4)")).triggered.connect(lambda: self.window().copy_selected_to_other_side())
            menu.addAction(self._t("ui_ctx_move_to_other", "移動到對面 (F3)")).triggered.connect(lambda: self.window().move_selected_to_other_side())

        else:
            menu.addAction(self._t("ui_main_dialog_new_folder", "新增資料夾") + " (F7)").triggered.connect(lambda: self.parent().parent().create_new_folder())
            menu.addAction(self._t("ui_ctx_new_text_file", "新增文字檔")).triggered.connect(lambda: self.parent().parent().create_new_text_file())
            menu.addAction(self._t("ui_main_action_refresh", "重新整理") + " (F5)").triggered.connect(lambda: self.parent().parent().refresh())
            if has_paste:
                menu.addSeparator()
                menu.addAction(self._t("ui_main_action_paste", "貼上") + " (Ctrl+V)").triggered.connect(lambda: self.paste_from_clipboard(root_path))
            menu.addSeparator()
            menu.addAction(self._t("ui_ctx_open_terminal", "在此處開啟終端機")).triggered.connect(lambda: os.system(f'start cmd /K "cd /d {root_path}"'))
            menu.addSeparator()
            menu.addAction(self._t("ui_ctx_properties", "內容")).triggered.connect(lambda: FileOps.show_properties(root_path))

        menu.exec(event.globalPos())




    def version_selected(self):
        idxs = self.selectionModel().selectedIndexes()
        if not idxs: return
        file_pairs, zip_pairs = [], []
        for idx in idxs:
            path = self.get_file_path(idx)
            if self.is_dir(idx):
                zip_pairs.append((path, FileOps.zip_dest_path(path)))
            else:
                file_pairs.append((path, FileOps.get_versioned_name(path)))
        if file_pairs:
            self.perform_operation(file_pairs, "copy")
        if zip_pairs:
            self.perform_operation(zip_pairs, "zip")

    def _extract_selected(self, path: str) -> None:
        dest = FileOps.archive_dest_folder(path)
        self.perform_operation([(path, dest)], "extract")

    def _trigger_preview(self, path: str) -> None:
        win = self.window()
        if hasattr(win, "toggle_inline_preview"):
            win.toggle_inline_preview(path)
        else:
            win.show_quick_look(path)
