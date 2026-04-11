import os
from core.interfaces import IMainWindowView
from core.config_manager import ConfigManager

# ==========================================
# MVP Presenter: MainWindow (主視窗調度中心)
# ==========================================
class MainWindowPresenter:
    """
    中介者：透過 DI 注入 View 與 ConfigManager。
    接管熱鍵路由 (Ctrl+L/R)、跨欄複製/移動、分頁同步等核心商務邏輯。
    所有方法皆為純 Python，不依賴任何 PyQt 類別。
    """
    def __init__(self, view: IMainWindowView, config_mgr: ConfigManager = None):
        self.view = view
        self.config_mgr = config_mgr or ConfigManager()
        self.locked_minutes = 0
        self.daily_k_scan_done = False

    # ------------------------------------------
    # File Operation Commands
    # ------------------------------------------
    def copy_to_other_side(self):
        """F4: 複製選取項目到對面分欄目錄。"""
        selected = self.view.get_active_pane_selected_paths()
        dest = self.view.get_opposite_pane_path()
        if not selected or not dest:
            return
        if not os.path.isdir(dest):
            return
        # View 負責操作，Presenter 決定目標
        self.view.copy_selected_to_opposite()

    def move_to_other_side(self):
        """F3: 移動選取項目到對面分欄目錄。"""
        selected = self.view.get_active_pane_selected_paths()
        dest = self.view.get_opposite_pane_path()
        if not selected or not dest:
            return
        if not os.path.isdir(dest):
            return
        self.view.move_selected_to_opposite()

    # ------------------------------------------
    # Session Management
    # ------------------------------------------
    def save_session(self):
        """儲存當前分頁清單與設定至 config.json。"""
        self.view.save_session()

    def add_tab(self, side: str, path: str = None):
        """新增分頁到指定側 ('left'/'right')。"""
        if path and not os.path.exists(path):
            path = None
        self.view.add_tab(side, path or "")

    def close_tab(self):
        """關閉當前焦點分頁。"""
        self.view.close_active_tab()

    # ------------------------------------------
    # Maintenance & Background Scanning Logic (MVP: Business Logic)
    # ------------------------------------------
    def on_system_tick(self, is_locked: bool):
        """
        每分鐘觸發一次的維護檢核邏輯。
        負責決定何時啟動本機閒置掃描與夜間網域同步。
        """
        settings = self.config_mgr.get_maintenance_settings()
        cooldown = settings.get("idle_lock_cooldown_min", 2)
        
        # 1. 本機 C 槽閒置掃描控制
        if is_locked:
            self.locked_minutes += 1
            if self.locked_minutes == cooldown:
                self.view.start_background_scan("personal")
        else:
            if self.locked_minutes >= cooldown:
                # 使用者回來了，立即中斷背景掃描以確保操作流暢
                self.view.stop_background_scan("personal")
            self.locked_minutes = 0

        # 2. 網路 K 槽夜間自動更新 (僅 Master Node 負責)
        config = self.config_mgr.load_config()
        if config.get("is_master_node", False):
            import datetime
            now = datetime.datetime.now()
            target_h = settings.get("nightly_scan_hour", 2)
            target_m = settings.get("nightly_scan_minute", 0)
            
            if now.hour == target_h and now.minute == target_m:
                if not self.daily_k_scan_done:
                    self.view.start_background_scan("network")
                    self.daily_k_scan_done = True
            else:
                self.daily_k_scan_done = False
