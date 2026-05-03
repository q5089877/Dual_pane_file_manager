from abc import ABC, abstractmethod
from typing import List

# ==========================================
# MVP Contract: Explorer (檔案總管合約)
# ==========================================
class IExplorerView(ABC):
    """View 抽象合約：接收路徑狀態與顯示操作，不含業務邏輯判斷"""
    @abstractmethod
    def get_current_path(self) -> str: ...

    @abstractmethod
    def set_display_path(self, path: str) -> None: ...

    @abstractmethod
    def get_selected_paths(self) -> List[str]: ...

    @abstractmethod
    def get_selected_total_size(self) -> int: ...

    @abstractmethod
    def get_selected_count(self) -> int: ...

    @abstractmethod
    def set_back_enabled(self, enabled: bool) -> None: ...

    @abstractmethod
    def set_forward_enabled(self, enabled: bool) -> None:
        pass

    @abstractmethod
    def show_error(self, message: str) -> None:
        pass

    @abstractmethod
    def confirm_action(self, message: str) -> bool:
        pass

    @abstractmethod
    def show_confirm_dialog(self, title: str, message: str) -> bool:
        pass

    @abstractmethod
    def update_status(self, message: str) -> None:
        pass

    @abstractmethod
    def update_disk_usage(self, free_gb: float) -> None:
        pass
        
    @abstractmethod
    def notify_operation_finished(self) -> None:
        pass

    @abstractmethod
    def open_system_file(self, path: str) -> None:
        pass

    @abstractmethod
    def focus_item(self, path: str) -> None:
        pass

    @abstractmethod
    def clipboard_has_urls(self) -> bool:
        pass

    @abstractmethod
    def clipboard_has_image(self) -> bool:
        pass

    @abstractmethod
    def clipboard_has_text(self) -> bool:
        pass

    @abstractmethod
    def get_clipboard_text(self) -> str:
        pass

    @abstractmethod
    def save_clipboard_image(self, path: str) -> bool:
        pass


# ==========================================
# MVP Contract: Search (進階搜尋合約)
# ==========================================
class ISearchView(ABC):
    """View 抽象合約：處理搜尋結果顯示與進度更新"""
    @abstractmethod
    def add_result(self, path: str, mtime: float, size: int, context: str = "") -> None:
        pass

    @abstractmethod
    def show_progress(self, text: str) -> None:
        pass

    @abstractmethod
    def search_finished(self, count: int) -> None:
        pass


# ==========================================
# MVP Contract: MainWindow (主視窗合約)
# ==========================================
class IMainWindowView(ABC):
    """View 抽象合約：主視窗下的分頁操作與加差管理"""
    @abstractmethod
    def get_active_pane_path(self) -> str:
        pass

    @abstractmethod
    def get_opposite_pane_path(self) -> str:
        pass

    @abstractmethod
    def get_active_pane_selected_paths(self) -> list:
        pass

    @abstractmethod
    def navigate_active_pane(self, path: str) -> None:
        pass

    @abstractmethod
    def navigate_opposite_pane(self, path: str) -> None:
        pass

    @abstractmethod
    def copy_selected_to_opposite(self) -> None:
        pass

    @abstractmethod
    def move_selected_to_opposite(self) -> None:
        pass

    @abstractmethod
    def add_tab(self, side: str, path: str) -> None:
        pass

    @abstractmethod
    def close_active_tab(self) -> None:
        pass

    @abstractmethod
    def set_status_msg(self, text: str, style: str) -> None:
        pass

    @abstractmethod
    def save_session(self) -> None:
        pass

    @abstractmethod
    def start_background_scan(self, scan_type: str) -> None:
        """Starts a background scanner (e.g., 'personal' or 'network')."""
        pass

    @abstractmethod
    def stop_background_scan(self, scan_type: str) -> None:
        """Aborts a specific background scanner."""
        pass


# ==========================================
# MVP Contract: AI Exporter (AI 匯出合約)
# ==========================================
class IAIExporterView(ABC):
    """View 抽象合約：處理 AI Context 匯出的進度顯示與結果通知"""
    @abstractmethod
    def show(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def set_range(self, total: int) -> None:
        pass

    @abstractmethod
    def update_progress(self, filename: str, current: int, total: int) -> None:
        pass

    @abstractmethod
    def show_success(self, file_count: int, char_count: int) -> None:
        pass

    @abstractmethod
    def show_error(self, message: str) -> None:
        pass

    @abstractmethod
    def set_cancelled_callback(self, callback) -> None:
        pass

