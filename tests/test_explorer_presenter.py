import unittest
from core.interfaces import IExplorerView
from ui.presenters.explorer_presenter import ExplorerPresenter
import os

class MockExplorerView(IExplorerView):
    """Mock View 實作，完全不依賴 PyQt，用於測試 Presenter 邏輯"""
    def __init__(self, initial_path):
        self.current_path = initial_path
        self.selected_paths = []
        self.back_enabled = False
        self.forward_enabled = False
        self.status = ""
        self.error_messages = []
        self.confirm_returns = True
        
    def get_current_path(self): return self.current_path
    def set_display_path(self, path): self.current_path = path
    def get_selected_paths(self): return self.selected_paths
    def get_selected_total_size(self): return 1024
    def get_selected_count(self): return len(self.selected_paths)
    def set_back_enabled(self, enabled): self.back_enabled = enabled
    def set_forward_enabled(self, enabled): self.forward_enabled = enabled
    def show_error(self, message): self.error_messages.append(message)
    def confirm_action(self, message): return self.confirm_returns
    def show_confirm_dialog(self, title: str, message: str) -> bool: return self.confirm_returns
    def update_status(self, message): self.status = message
    def update_disk_usage(self, free_gb): pass
    def notify_operation_finished(self): pass
    def open_system_file(self, path): pass
    def focus_item(self, path): pass
    def trigger_background_disk_usage(self): pass
    def clipboard_has_urls(self) -> bool: return False
    def clipboard_has_image(self) -> bool: return False
    def clipboard_has_text(self) -> bool: return False
    def get_clipboard_text(self) -> str: return ""
    def save_clipboard_image(self, path: str) -> bool: return False

class TestExplorerPresenter(unittest.TestCase):
    def setUp(self):
        # 建立純 Python 的 Mock View
        self.mock_view = MockExplorerView("C:\\")
        self.presenter = ExplorerPresenter(self.mock_view)

    def test_navigate_and_history(self):
        # 測試導航邏輯 (不啟動 GUI 即可驗證核心導航流程)
        if os.path.exists("C:\\Windows"):
            self.presenter.navigate_to("C:\\Windows")
            
            # 驗證 View 的路徑是否有被更新
            self.assertEqual(self.mock_view.current_path, "C:\\Windows")
            
            # 驗證上一頁記錄
            self.assertTrue(self.mock_view.back_enabled)
            
            # 回上一頁
            self.presenter.go_back()
            self.assertEqual(self.mock_view.current_path, "C:\\")
            self.assertFalse(self.mock_view.back_enabled)

if __name__ == '__main__':
    unittest.main()
