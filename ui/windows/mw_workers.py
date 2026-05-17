from __future__ import annotations
import os
from core.system_utils import get_user_idle_time_ms


class _MwWorkersMixin:
    """Background scan workers, update checker, and system timer tick."""

    def _on_system_timer_tick(self):
        idle_ms = get_user_idle_time_ms()
        idle_minutes = idle_ms // 60000
        if hasattr(self, "presenter"):
            self.presenter.on_system_tick(idle_minutes)

    def _start_idle_c_scan(self):
        if self.idle_scanner_worker and getattr(
                self.idle_scanner_worker, "isRunning", lambda: False)():
            return

        local_drives = self.config_mgr.get_fixed_drives()
        if not local_drives:
            return

        configs_c = [(os.path.normpath(p), 99)
                     for p in local_drives if os.path.exists(p)]
        if not configs_c:
            return

        from network_search.engine import ScannerWorker, IndexManager
        db_dir = os.path.join(
            os.path.dirname(self.config_mgr.config_file), "indexes")

        idx_mgr = IndexManager(db_dir, read_only=False)
        self.idle_scanner_worker = ScannerWorker(
            configs_c,
            idx_mgr,
            target_db="personal",
            exclude_dirs=self.config.get("exclude_dirs", [])
        )
        self.idle_scanner_worker.finished.connect(self._on_idle_scan_finished)
        self.idle_scanner_worker.start()

    def _stop_idle_c_scan(self):
        if self.idle_scanner_worker and getattr(
                self.idle_scanner_worker, "isRunning", lambda: False)():
            if hasattr(self.idle_scanner_worker, 'stop'):
                self.idle_scanner_worker.stop()
            self.idle_scanner_worker = None

    def _on_idle_scan_finished(self):
        self.idle_scanner_worker = None

    def _start_nightly_k_scan(self):
        if hasattr(self, "nightly_scanner_worker") and getattr(
                self.nightly_scanner_worker, "isRunning", lambda: False)():
            return

        monitored = self.config.get("monitored_paths", [])
        if not monitored:
            return

        configs_k = [(os.path.normpath(p), self.config.get("max_depth", 7))
                     for p in monitored if os.path.exists(p)]
        if not configs_k:
            return

        from network_search.engine import ScannerWorker, IndexManager
        db_dir = os.path.join(
            os.path.dirname(self.config_mgr.config_file), "indexes")
        remote_dir = self.config.get("remote_index_root")

        idx_mgr = IndexManager(db_dir, read_only=False)
        self.nightly_scanner_worker = ScannerWorker(
            configs_k,
            idx_mgr,
            remote_db_dir=remote_dir,
            target_db="local"
        )
        self.nightly_scanner_worker.start()

    def _start_update_check(self):
        """啟動非同步更新檢查執行緒（GitHub Releases）。"""
        from ui.workers.update_manager import UpdateCheckWorker
        self._update_worker = UpdateCheckWorker(self.config_mgr)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_worker.start()

    def _on_update_available(self, version: str, download_url: str):
        """當 GitHub 有新版本時，在狀態列顯示更新按鈕。"""
        msg = self.config_mgr.get_text(
            "ui_update_found", "🚀 新版本 {v} 已發布！").format(v=version)
        self.set_status_msg(msg, "success")

        btn_text = self.config_mgr.get_text("ui_update_now", "立即更新")
        self.update_btn.setText(btn_text)
        self.update_btn.show()

        try:
            self.update_btn.clicked.disconnect()
        except Exception:
            pass
        self.update_btn.clicked.connect(
            lambda: self._trigger_update(download_url))

    def _trigger_update(self, download_url: str):
        """下載新版 zip，寫入更新腳本後關閉程式。"""
        import sys
        import subprocess
        from ui.workers.update_manager import DownloadUpdateWorker, write_update_script
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        from PyQt6.QtCore import Qt

        self.update_btn.setEnabled(False)
        self.set_status_msg(self.config_mgr.get_text(
            "ui_update_downloading", "正在下載更新…"), "")

        progress_dlg = QProgressDialog(
            self.config_mgr.get_text("ui_update_downloading", "正在下載更新…"),
            self.config_mgr.get_text("ui_cancel", "取消"), 0, 100, self
        )
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.show()

        worker = DownloadUpdateWorker(download_url)
        worker.progress.connect(progress_dlg.setValue)
        worker.error.connect(lambda msg: (
            progress_dlg.close(),
            self.set_status_msg(f"下載失敗：{msg}", "error"),
            self.update_btn.setEnabled(True),
        ))

        def on_finished(zip_path: str):
            progress_dlg.close()
            if getattr(sys, 'frozen', False):
                install_dir = os.path.dirname(sys.executable)
            else:
                install_dir = os.path.dirname(os.path.abspath(__file__))

            bat_path = write_update_script(zip_path, install_dir)
            try:
                subprocess.Popen([bat_path], creationflags=0x00000010)
                QApplication.quit()
                sys.exit(0)
            except Exception as e:
                self.set_status_msg(f"無法執行更新腳本：{e}", "error")
                self.update_btn.setEnabled(True)

        worker.finished.connect(on_finished)
        progress_dlg.canceled.connect(worker.cancel)
        self._download_worker = worker
        worker.start()
