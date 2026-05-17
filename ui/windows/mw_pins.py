from __future__ import annotations
import os
from PyQt6.QtCore import QPoint


class _MwPinsMixin:
    """Pin management: toggle, add silent, set important, edit note, show menu."""

    def toggle_pin(self, path: str):
        """Pin or unpin a path. Called by Ctrl+D and context menus."""
        from ui.widgets.popups import PinNoteDialog
        if self.config_mgr.is_pinned(path):
            self.config_mgr.remove_pin(path)
            msg = self.config_mgr.get_text(
                "ui_main_toast_unpinned", "已解除釘選：{}").format(
                os.path.basename(path) or path)
            self.show_toast(msg, "info")
        else:
            dlg = PinNoteDialog(os.path.basename(path) or path, self)
            if dlg.exec() == PinNoteDialog.DialogCode.Rejected:
                return
            self.config_mgr.add_pin(path, os.path.isdir(path), dlg.note())
            msg = self.config_mgr.get_text(
                "ui_main_toast_pinned", "已釘選：{}").format(
                os.path.basename(path) or path)
            self.show_toast(msg, "success")
        self.refresh_toolbar()

    def add_pin_silent(self, path: str):
        """Pin a path without prompting for a note. Used by drag-and-drop."""
        if self.config_mgr.is_pinned(path):
            msg = self.config_mgr.get_text(
                "ui_main_toast_pinned", "已釘選：{}").format(
                os.path.basename(path) or path)
            self.show_toast(msg, "info")
            return
        self.config_mgr.add_pin(path, os.path.isdir(path))
        msg = self.config_mgr.get_text(
            "ui_main_toast_pinned_with_note", "已釘選：{}（右鍵可加備忘）").format(
            os.path.basename(path) or path)
        self.show_toast(msg, "success")
        self.refresh_toolbar()

    def set_pin_important(self, path: str, important: bool):
        self.config_mgr.set_pin_important(path, important)
        label = (self.config_mgr.get_text("ui_main_pinned_important", "已標為重要（永久保留）")
                 if important
                 else self.config_mgr.get_text("ui_main_pinned_unimportant", "已取消重要標記"))
        self.show_toast(label, "success" if important else "info")
        self.refresh_toolbar()

    def edit_pin_note(self, path: str):
        """Edit the note of an existing pin."""
        from ui.widgets.popups import PinNoteDialog
        pins = self.config_mgr.get_pins()
        current_note = next(
            (p.get("note", "") for p in pins if p["path"] == path), "")
        dlg = PinNoteDialog(os.path.basename(path) or path, self, timeout_sec=0)
        dlg._edit.setText(current_note)
        dlg._edit.selectAll()
        note = dlg.note() if dlg.exec() == PinNoteDialog.DialogCode.Accepted else None
        if note is not None:
            self.config_mgr.update_pin_note(path, note)
            self.refresh_toolbar()

    def _check_stale_pins(self) -> None:
        """啟動後輕量提示：非重要釘選超過 14 天時，在狀態列顯示一行整理建議。"""
        import datetime
        pins = self.config_mgr.get_pins()
        now = datetime.datetime.now()
        stale_count = 0
        for p in pins:
            if p.get("important"):
                continue
            try:
                pinned_dt = datetime.datetime.fromisoformat(p.get("pinned_at", ""))
                if (now - pinned_dt).days >= 14:
                    stale_count += 1
            except (ValueError, TypeError):
                continue
        if stale_count:
            msg = self.config_mgr.get_text(
                "ui_main_stale_pins_hint",
                "💡 您有 {} 個釘選超過兩週了，要整理嗎？（點擊「已釘選」按鈕）"
            ).format(stale_count)
            self.set_status_msg(msg, "tip")

    def _show_pin_menu(self):
        pins = self.config_mgr.get_pins()
        self.pin_popup.populate(pins, self.config_mgr)
        btn = getattr(self, "pin_btn", None)
        if btn:
            pos = btn.mapToGlobal(QPoint(0, btn.height()))
        else:
            pos = self.mapToGlobal(QPoint(0, 40))
        self.pin_popup.move(pos)
        self.pin_popup.show()
