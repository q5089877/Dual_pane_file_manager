import os
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QMessageBox, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QUrl
import struct
from core.file_ops import FileOps
from ui.workers.threads import FileOperationThread

class BaseFileView:
    """Base mixin/class for common functionality between TreeView and ListView."""
    file_operation_finished = pyqtSignal()

    def __init_base__(self):
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_start_pos = event.position().toPoint()
            # 檢查是否點擊在合法項目上
            idx = self.indexAt(event.position().toPoint())
            self._drag_item_clicked = idx.isValid()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Trigger drag based on movement distance rather than a time delay.
        # This matches Windows File Explorer's snappy feel while maintaining precision.
        if event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            if hasattr(self, '_drag_start_pos') and getattr(self, '_drag_item_clicked', False):
                if (event.position().toPoint() - self._drag_start_pos).manhattanLength() >= \
                   QApplication.startDragDistance():
                    # We have sufficient movement to start a drag.
                    supported_actions = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction
                    self.startDrag(supported_actions)
                    return  # Drag has started, no need for default move processing
        super().mouseMoveEvent(event)

    def startDrag(self, supportedActions):
        # Removed the 150ms delay. Now relies on distance threshold in mouseMoveEvent.
        win = self.window()
        if hasattr(win, "current_drag_button"):
            # Record current button to distinguish move vs copy logic later
            win.current_drag_button = QApplication.mouseButtons()
        super().startDrag(supportedActions)

    def handle_drop(self, event, current_root_index):
        index = self.indexAt(event.position().toPoint())
        
        if index.isValid():
            dest_path = self.get_file_path(index)
            if not self.is_dir(index):
                dest_path = os.path.dirname(dest_path)
        else:
            dest_path = self.get_file_path(current_root_index)

        urls = event.mimeData().urls()
        src_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]
        
        if not src_paths or not dest_path:
            return False

        # Determine mode
        win = self.window()
        drag_btn = getattr(win, "current_drag_button", Qt.MouseButton.NoButton)
        mode = None
        if drag_btn == Qt.MouseButton.LeftButton:
            mode = "move"
        elif drag_btn == Qt.MouseButton.RightButton:
            mode = "copy"

        if mode:
            self.check_and_perform(src_paths, dest_path, mode)
        else:
            menu = QMenu(self)
            copy_act = menu.addAction("複製到這裡")
            move_act = menu.addAction("移動到這裡")
            menu.addSeparator()
            menu.addAction("取消")
            action = menu.exec(self.mapToGlobal(event.position().toPoint()))
            
            if action == copy_act:
                self.check_and_perform(src_paths, dest_path, "copy")
            elif action == move_act:
                self.check_and_perform(src_paths, dest_path, "move")
        
        event.acceptProposedAction()
        return True

    def timestamp_rename_selected(self):
        """Append timestamp to selected file names (in-place rename)."""
        idxs = self.selectionModel().selectedRows()
        if not idxs: return
        
        op_pairs = []
        for idx in idxs:
            src_path = self.get_file_path(idx)
            dest_path = FileOps.get_timestamp_suffix_name(src_path)
            if src_path != dest_path:
                op_pairs.append((src_path, dest_path))
        
        if op_pairs:
            self.perform_operation(op_pairs, "move")

    def open_batch_rename_dialog(self):
        """開啟批次重新命名對話框，確認後透過 perform_operation 執行。"""
        idxs = self.selectionModel().selectedRows()
        if not idxs:
            return
        src_paths = [p for p in (self.get_file_path(i) for i in idxs) if p]
        if not src_paths:
            return
        from ui.widgets.dialogs import BatchRenameDialog
        dlg = BatchRenameDialog(src_paths, config_mgr=getattr(self, '_cm', None), parent=self)
        if dlg.exec() == BatchRenameDialog.DialogCode.Accepted:
            op_pairs = dlg.get_op_pairs()
            if op_pairs:
                self.perform_operation(op_pairs, "move")

    def check_and_perform(self, src_paths, dest_path, mode):
        dest_path = os.path.normpath(dest_path)
        src_paths = [os.path.normpath(p) for p in src_paths]
        
        op_pairs = []
        for src in src_paths:
            target = os.path.join(dest_path, os.path.basename(src))
            if mode == "copy" and os.path.normcase(os.path.dirname(src)) == os.path.normcase(dest_path):
                target = FileOps.get_versioned_name(src)
            op_pairs.append((src, target))

        # Overwrite check (only for actual collisions)
        existing = []
        for src, target in op_pairs:
            # If moving to same path, it's a no-op, don't flag as collision
            if src == target:
                continue
            if os.path.exists(target):
                existing.append(os.path.basename(target))

        if existing:
            msg = f"以下項目已存在：\n{', '.join(existing[:5])}{'...' if len(existing)>5 else ''}\n是否覆蓋？"
            if QMessageBox.question(self, "確認覆蓋", msg) == QMessageBox.StandardButton.No:
                return

        self.perform_operation(op_pairs, mode)

    def perform_operation(self, op_pairs, mode):
        from PyQt6.QtWidgets import QProgressDialog
        self.progress_dialog = QProgressDialog("處理中...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("檔案操作")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        
        self.op_thread = FileOperationThread(op_pairs, mode)
        self.op_thread.progress.connect(self.update_progress)
        self.op_thread.finished_signal.connect(self.on_operation_finished)
        self.op_thread.cancelled.connect(self.progress_dialog.close)
        self.op_thread.cancelled.connect(self.file_operation_finished.emit)
        self.progress_dialog.canceled.connect(self.op_thread.stop)
        self.op_thread.start()

    def update_progress(self, val, text):
        self.progress_dialog.setValue(val)
        self.progress_dialog.setLabelText(text)

    def on_operation_finished(self, success, msg):
        self.progress_dialog.close()
        win = self.window()
        if success:
            toast_msg = "操作完成"
            if hasattr(self, "op_thread"):
                mode_dict = {"copy": "複製", "move": "移動", "zip": "壓縮", "extract": "解壓縮"}
                mode_str = mode_dict.get(self.op_thread.mode, self.op_thread.mode)
                count = len(self.op_thread.op_pairs)
                toast_msg = f"成功{mode_str} {count} 個項目"
                if hasattr(win, "register_undo"):
                    win.register_undo(self.op_thread.op_pairs, self.op_thread.mode)
                    
            if hasattr(win, "show_toast"):
                win.show_toast(toast_msg, "success")
        else:
            QMessageBox.critical(self, "錯誤", msg)
        self.file_operation_finished.emit()

    def copy_to_clipboard(self, indexes, cut=False):
        if not indexes: return
        paths = [self.get_file_path(idx) for idx in indexes]
        
        # UI State
        win = self.window()
        if hasattr(win, 'clipboard'):
            win.clipboard = {"paths": paths, "op": "move" if cut else "copy"}
        
        # System Clipboard
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drop_effect = struct.pack("<I", 0x02 if cut else 0x05)
        mime.setData("Preferred DropEffect", drop_effect)
        QApplication.clipboard().setMimeData(mime)
        
        if hasattr(win, "show_toast"):
            win.show_toast(f"已{'剪下' if cut else '複製'} {len(paths)} 個項目", "info")

    def paste_from_clipboard(self, dest_dir):
        win = self.window()
        src_paths = []
        op = "copy"

        # Prioritize system clipboard (handles both internal-synced and external copies)
        mime = QApplication.clipboard().mimeData()
        if mime.hasUrls():
            src_paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
            if mime.hasFormat("Preferred DropEffect"):
                try:
                    effect = struct.unpack("<I", mime.data("Preferred DropEffect"))[0]
                    if effect == 0x02: op = "move"
                except: pass
        
        # Fallback to internal side-channel only if system clipboard has no files
        if not src_paths and hasattr(win, 'clipboard') and win.clipboard.get("paths"):
            src_paths = win.clipboard["paths"]
            op = win.clipboard["op"]

        if not src_paths:
            return

        # Same-folder copy → versioned copy (equivalent to F3)
        dest_norm = os.path.normcase(os.path.normpath(dest_dir))
        if op == "copy" and all(
            os.path.normcase(os.path.normpath(os.path.dirname(p))) == dest_norm
            for p in src_paths
        ):
            file_pairs = [(p, FileOps.get_versioned_name(p)) for p in src_paths if os.path.isfile(p)]
            zip_pairs  = [(p, FileOps.zip_dest_path(p))      for p in src_paths if os.path.isdir(p)]
            if file_pairs: self.perform_operation(file_pairs, "copy")
            if zip_pairs:  self.perform_operation(zip_pairs, "zip")
            return

        self.check_and_perform(src_paths, dest_dir, op)

    def get_file_path(self, index):
        """Helper to get file path, handling proxy models."""
        model = self.model()
        if hasattr(model, 'mapToSource'):
            return model.sourceModel().filePath(model.mapToSource(index))
        return model.filePath(index)

    def is_dir(self, index):
        """Helper to check if index is a directory, handling proxy models."""
        model = self.model()
        if hasattr(model, 'mapToSource'):
            return model.sourceModel().isDir(model.mapToSource(index))
        return model.isDir(index)
