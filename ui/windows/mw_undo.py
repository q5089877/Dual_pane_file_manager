from __future__ import annotations
import os


class _MwUndoMixin:
    """Undo/redo stack operations."""

    def register_undo(self, pairs: list, kind: str) -> None:
        """記錄一筆可復原操作（copy 不記錄）。"""
        if self._undoing or kind == "copy":
            return
        from core.undo_stack import UndoEntry
        self.undo_stack.push(UndoEntry(kind=kind, pairs=list(pairs)))

    def undo_last(self) -> None:
        """Ctrl+Z：復原最後一次 move 或 rename。"""
        entry = self.undo_stack.pop()
        if entry is None:
            self.show_toast(self.config_mgr.get_text(
                "ui_main_undo_nothing", "沒有可復原的操作"), "info")
            return

        self._undoing = True
        try:
            if entry.kind == "move":
                reversed_pairs = [(dst, src) for src, dst in entry.pairs]
                pane = self.active_pane
                if pane:
                    pane._file_view().perform_operation(reversed_pairs, "move")
            elif entry.kind == "rename":
                for old_path, new_path in entry.pairs:
                    try:
                        os.rename(new_path, old_path)
                    except OSError as e:
                        self.show_toast(self.config_mgr.get_text(
                            "ui_main_undo_failed", "復原失敗: {}").format(e), "error")
                        return
                self.refresh_all_panes()
                self.show_toast(self.config_mgr.get_text(
                    "ui_main_undo_rename_done", "已復原重新命名"), "success")
            elif entry.kind == "trash":
                import winshell
                failed = []
                for original_path, _ in entry.pairs:
                    try:
                        norm_path = os.path.abspath(
                            os.path.normpath(original_path))
                        winshell.undelete(norm_path)
                    except Exception as e:
                        failed.append(
                            f"{os.path.basename(original_path)} ({e})")
                self.refresh_all_panes()
                if failed:
                    self.show_toast(self.config_mgr.get_text(
                        "ui_main_undo_trash_partial_fail", "部分還原失敗：{}").format(', '.join(failed)), "error")
                else:
                    self.show_toast(self.config_mgr.get_text(
                        "ui_main_undo_trash_done", "已從回收筒還原 {} 個項目").format(len(entry.pairs)), "success")
        finally:
            self._undoing = False
