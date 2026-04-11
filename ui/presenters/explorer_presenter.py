import os
from core.interfaces import IExplorerView
from core.file_ops import FileOps

HOME_PATH = "home://"  # 虛擬首頁路徑（磁碟機 + 常用資料夾）

# ==========================================
# MVP Presenter: Explorer (檔案總管調度中心)
# ==========================================
class ExplorerPresenter:
    """中介者：透過 DI 注入 View，處理路徑歷史、檔案刪除與資料夾建立等商務邏輯"""
    def __init__(self, view: IExplorerView, config_model=None):
        self.view = view
        self.config_model = config_model
        self.history = []          # back stack
        self.forward_history = []  # forward stack
        self.is_navigating_history = False

    def navigate_to(self, path: str):
        if path != HOME_PATH and (not path or not os.path.exists(path)):
            return
            
        curr = self.view.get_current_path()
        if not self.is_navigating_history and curr and curr != path:
            self.history.append(curr)
            self.forward_history.clear()  # new navigation clears forward stack
            self.view.set_back_enabled(True)
            self.view.set_forward_enabled(False)
            
        self.view.set_display_path(path)

    def go_back(self):
        if self.history:
            curr = self.view.get_current_path()
            self.is_navigating_history = True
            prev = self.history.pop()
            if curr:
                self.forward_history.append(curr)
            self.navigate_to(prev)
            self.is_navigating_history = False
            self.view.set_back_enabled(len(self.history) > 0)
            self.view.set_forward_enabled(len(self.forward_history) > 0)

    def go_forward(self):
        if self.forward_history:
            curr = self.view.get_current_path()
            self.is_navigating_history = True
            nxt = self.forward_history.pop()
            if curr:
                self.history.append(curr)
            self.navigate_to(nxt)
            self.is_navigating_history = False
            self.view.set_back_enabled(True)
            self.view.set_forward_enabled(len(self.forward_history) > 0)

    def go_up(self):
        curr = self.view.get_current_path()
        if not curr:
            return
        parent = os.path.dirname(curr)
        if os.path.exists(parent) and parent != curr:
            self.navigate_to(parent)

    def handle_delete(self, permanent=False):
        paths = self.view.get_selected_paths()
        if not paths:
            return

        # 邏輯分離：如果是永久刪除，強制彈窗；如果是一般刪除，則視設定決定
        should_prompt = permanent
        if not permanent and self.config_model:
            should_prompt = self.config_model.load_config().get("confirm_before_delete", True)

        if should_prompt:
            if permanent:
                title_key = "ui_explorer_confirm_delete_permanent_title"
                msg_key = "ui_explorer_confirm_delete_permanent_msg"
                title_default = "確認永久刪除"
                msg_default = "確定要將這 {} 個項目永久刪除嗎？"
            else:
                title_key = "ui_explorer_confirm_delete_title"
                msg_key = "ui_explorer_confirm_delete_msg"
                title_default = "確認刪除"
                msg_default = "確定要將這 {} 個項目移至資源回收桶嗎？"
            title = self.config_model.get_text(title_key, title_default) if self.config_model else title_default
            msg = (self.config_model.get_text(msg_key, msg_default) if self.config_model else msg_default).format(len(paths))

            if not self.view.show_confirm_dialog(title, msg):
                return

        res = FileOps.delete_paths(paths, permanent)
        errors = [r[2] for r in res if not r[1]]
        if errors:
            if self.config_model:
                err_msg = self.config_model.get_text("ui_explorer_toast_delete_failed", "刪除失敗: {}").format(errors[0])
            else:
                err_msg = "\n".join(errors)
            self.view.show_error(err_msg)
        self.view.notify_operation_finished()

    def handle_create_folder(self):
        root = self.view.get_current_path()
        if not root or not os.path.exists(root):
            return
            
        base = self.config_model.get_text("ui_explorer_new_folder_base") if self.config_model else "新資料夾"
        path = os.path.join(root, base)
        counter = 2
        while os.path.exists(path): 
            path = os.path.join(root, f"{base} ({counter})")
            counter += 1
            
        try:
            os.makedirs(path)
            # 通知視窗讓該項目被 Focus
            self.view.focus_item(path)
            self.view.notify_operation_finished()
        except Exception as e:
            self.view.show_error(str(e))

    def handle_double_click(self, path: str, is_dir: bool):
        if not path or not os.path.exists(path):
            return

        # 處理 Windows 捷徑 (.lnk) 的底層邏輯
        if path.lower().endswith(".lnk"):
            target = ""
            # 優先用 win32com 取得 TargetPath
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortcut(path)
                target = getattr(shortcut, "TargetPath", "")
            except Exception:
                pass
            # Fallback：用 Qt 內建的捷徑解析
            if not target or not os.path.exists(target):
                from PyQt6.QtCore import QFileInfo
                target = QFileInfo(path).symLinkTarget()
            if target and os.path.exists(target):
                if os.path.isdir(target):
                    self.navigate_to(target)
                    return
                path = target
                is_dir = False
            
        if is_dir: 
            self.navigate_to(path)
        else: 
            self.view.open_system_file(path)

    def handle_paste(self):
        """處理超級貼上：偵測剪貼簿中的圖片或文字，自動生成檔案"""
        # 1. MIME 優先權防禦：如果是檔案路徑 (URLs)，則交由系統處理 (這裡跳過超級貼上)
        if self.view.clipboard_has_urls():
            return

        # 2. 取得目前路徑
        root = self.view.get_current_path()
        if not root or not os.path.exists(root):
            return

        # 3. 取得設定值
        settings = {
            "image_prefix": "剪貼圖",
            "text_prefix": "文字筆記",
            "image_format": "%Y%m%d_%H%M%S",
            "text_format": "%Y%m%d_%H%M%S"
        }
        if self.config_model:
            settings.update(self.config_model.get_paste_settings())

        import datetime
        now = datetime.datetime.now()

        # 4. 偵測圖片
        if self.view.clipboard_has_image():
            filename = f"{settings['image_prefix']}_{now.strftime(settings['image_format'])}.png"
            path = os.path.join(root, filename)
            # 如果還是發生衝突，補一個小小保險 (雖然秒級精度很難發生)
            if os.path.exists(path):
                path = FileOps.get_versioned_name(path)
            
            if self.view.save_clipboard_image(path):
                self.view.focus_item(path)
                self.view.notify_operation_finished()
                return

        # 5. 偵測文字 (加上 UTF-8 編碼防護)
        if self.view.clipboard_has_text():
            text = self.view.get_clipboard_text()
            if text:
                filename = f"{settings['text_prefix']}_{now.strftime(settings['text_format'])}.txt"
                path = os.path.join(root, filename)
                if os.path.exists(path):
                    path = FileOps.get_versioned_name(path)
                
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    self.view.focus_item(path)
                    self.view.notify_operation_finished()
                except Exception as e:
                    self.view.show_error(f"無法儲存文字檔案: {str(e)}")

    def refresh_status(self):
        count = self.view.get_selected_count()
        if count == 0:
            msg = self.config_model.get_text("ui_explorer_status_calculating", "正在計算空間...") if self.config_model else "正在計算空間..."
            self.view.update_status(msg)
            # 這裡我們將 Disk Usage 取得也視為 Presenter 控制的 View 行為
            # 由於 Disk Usage 需要背景非同步，我們將其封裝回 View 或在 Presenter 開 Thread
            # 為不影響現存 QThread 架構，我們呼叫 View 特定的背景更新函式
            self.view.trigger_background_disk_usage()
            return
            
        size = self.view.get_selected_total_size()
        formatted_size = self._format_size(size)
        tpl = self.config_model.get_text("ui_explorer_status_selected_size", "已選取 {} 個項目 ({})") if self.config_model else "已選取 {} 個項目 ({})"
        msg = tpl.format(count, formatted_size)
        self.view.update_status(msg)

    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0: return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
