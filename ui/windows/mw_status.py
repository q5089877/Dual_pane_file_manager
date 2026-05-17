from __future__ import annotations
import re
from PyQt6.QtCore import QTimer


class _MwStatusMixin:
    """Status bar messages, toast notifications, and pane status label."""

    def set_status_msg(self, text, style_type="info"):
        """設定即時訊息內容與樣式，支援 [Key] 鍵帽化顯示。"""
        if style_type == "tip" and "[" in text:
            text = text.replace("💡", "💡&nbsp;")
            text = text.replace("  ", "{{GAP_L}}").replace(" ", "{{GAP_S}}")

            kbd_style = (
                "background-color: #333842; color: #abb2bf; "
                "border: 1px solid #1a1e23; border-radius: 4px; "
                "font-family: 'Consolas', 'Courier New', monospace; "
                "font-size: 11px; padding: 1px 3px;"
            )

            text = re.sub(r'\[([^\]]+)\]',
                          f'<span style="{kbd_style}">&nbsp;\\1&nbsp;</span>', text)

            text = text.replace("{{GAP_L}}", "&nbsp;" * 4)
            text = text.replace("{{GAP_S}}", "&nbsp;")

        self.msg_label.setText(text)
        self.msg_label.setProperty("type", style_type)
        self.msg_label.style().unpolish(self.msg_label)
        self.msg_label.style().polish(self.msg_label)

    def _update_pane_status(self, text: str):
        """更新狀態列右側的 pane 資訊"""
        self.pane_status_label.setText(text)

    def show_toast(self, message: str, kind: str = "info", duration: int = 3000) -> None:
        """顯示非阻塞 Toast 通知（右下角，自動消失）。"""
        from ui.widgets.toast import show_toast as _show_toast
        _show_toast(self, message, kind, duration)

    def flash_tab_hint(self):
        """閃爍顯示分頁切換提示"""
        if hasattr(self, "_flash_timer") and self._flash_timer.isActive():
            return

        original_text = self.msg_label.text()
        self.set_status_msg(self.config_mgr.get_text(
            "ui_main_flash_tab_hint", "[Tab] 切換分頁"), "tip")

        self._flash_step = 0
        self._flash_timer = QTimer(self)

        def toggle():
            self._flash_step += 1
            flashing = (self._flash_step % 2 == 1)
            self.msg_label.setProperty(
                "flash", "true" if flashing else "false")
            self.msg_label.style().unpolish(self.msg_label)
            self.msg_label.style().polish(self.msg_label)

            if self._flash_step >= 6:
                self._flash_timer.stop()
                self.msg_label.setProperty("flash", "false")
                self.set_status_msg(original_text, "tip")

        self._flash_timer.timeout.connect(toggle)
        self._flash_timer.start(500)
