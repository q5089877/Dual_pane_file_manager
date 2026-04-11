import os
import sys
from PyQt6.QtCore import QThread, pyqtSignal

class UpdateCheckWorker(QThread):
    """
    Background worker to check for updates on the K: drive.
    Uses file modification time comparison for simplicity and reliability.
    """
    update_detected = pyqtSignal(str, str)  # master_exe_path, bat_path

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr
        self._is_running = True

    def run(self):
        if not self._is_running:
            return

        # 1. 取得更新來源路徑 (K 槽)
        source_dir = self.config_mgr.get_update_source_path()
        if not source_dir:
            return

        master_exe = os.path.join(source_dir, "DoubleFileExplorer.exe")
        bat_path = os.path.join(source_dir, "deploy_explorer.bat")

        if not os.path.exists(master_exe) or not os.path.exists(bat_path):
            return

        # 2. 獲取本地執行檔路徑
        import sys
        if getattr(sys, 'frozen', False):
            local_exe = sys.executable
        else:
            # 開發模式下，檢查同目錄是否有打包好的 exe，或者直接略過
            return 

        # 3. 比對修改時間
        # 由於網路磁碟延遲可能造成 os.path.getmtime 阻塞，故在這裡執行是安全的 (背景執行緒)
        master_mtime = self.config_mgr.get_file_mtime(master_exe)
        local_mtime = self.config_mgr.get_file_mtime(local_exe)

        # 容許 2 秒內的誤差（避免檔案系統時間同步誤差）
        if master_mtime > local_mtime + 2:
            self.update_detected.emit(master_exe, bat_path)

    def stop(self):
        self._is_running = False
        self.wait()
