"""
UpdateCheckWorker  — 背景執行緒，檢查 GitHub Releases 是否有新版本。
DownloadUpdateWorker — 背景執行緒，下載新版 zip 並準備更新腳本。

流程：
  1. 啟動時 UpdateCheckWorker 呼叫 GitHub API（輕量，不阻塞 UI）
  2. 若有新版本 → emit update_available(version, url)
  3. 主視窗顯示「立即更新」按鈕
  4. 使用者點擊 → DownloadUpdateWorker 下載 zip 並顯示進度
  5. 下載完成 → 寫入 _update.bat，關閉程式，bat 自動解壓並重啟
"""
import os
import json
import tempfile
import urllib.request
from PyQt6.QtCore import QThread, pyqtSignal


def _parse_version(tag: str) -> tuple:
    """'v1.2.3' 或 '1.2.3' → (1, 2, 3)"""
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except Exception:
        return (0,)


class UpdateCheckWorker(QThread):
    """
    輕量版本檢查執行緒。
    啟動後只做一次 GitHub API 查詢，完成後自動退出。
    """
    update_available = pyqtSignal(str, str)  # (version_tag, download_url)

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr

    def run(self):
        try:
            config = self.config_mgr.load_config()
            repo = config.get("github_repo", "").strip()
            if not repo:
                return

            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": "DualPaneFileManager-Updater"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            latest_tag = data.get("tag_name", "").strip()
            current = self.config_mgr.APP_VERSION

            if _parse_version(latest_tag) <= _parse_version(current):
                return  # 已是最新版

            # 找到 zip asset 下載連結
            for asset in data.get("assets", []):
                if asset["name"].endswith(".zip"):
                    self.update_available.emit(latest_tag, asset["browser_download_url"])
                    return

        except Exception:
            pass  # 網路失敗或 API 限速 → 靜默忽略


class DownloadUpdateWorker(QThread):
    """
    下載新版 zip 並準備更新腳本。
    進度以 0-100 整數回報。
    """
    progress = pyqtSignal(int)        # 0~100
    finished = pyqtSignal(str)        # 下載完成，帶 zip 路徑
    error = pyqtSignal(str)           # 下載失敗訊息

    def __init__(self, download_url: str):
        super().__init__()
        self.download_url = download_url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            zip_path = os.path.join(tempfile.gettempdir(), "DualPaneFileManager_update.zip")

            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "DualPaneFileManager-Updater"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk = 65536  # 64KB
                with open(zip_path, "wb") as f:
                    while True:
                        if self._cancelled:
                            self.error.emit("已取消")
                            return
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        downloaded += len(buf)
                        if total > 0:
                            self.progress.emit(int(downloaded * 100 / total))

            self.progress.emit(100)
            self.finished.emit(zip_path)

        except Exception as e:
            self.error.emit(str(e))


def write_update_script(zip_path: str, install_dir: str, exe_name: str = "DualPaneFileManager.exe") -> str:
    """
    在 temp 目錄寫入 _update.bat。
    腳本會：等待程式關閉 → 解壓覆蓋 → 重啟 exe。
    回傳 bat 路徑。
    """
    bat_path = os.path.join(tempfile.gettempdir(), "_dfe_update.bat")
    exe_path = os.path.join(install_dir, exe_name)

    # PowerShell Expand-Archive 解壓（Windows 10+ 內建）
    script = f"""@echo off
chcp 65001 >nul
echo Updating DualPaneFileManager...
ping -n 3 127.0.0.1 >nul
powershell -Command "Expand-Archive -Path '{zip_path}' -DestinationPath '{install_dir}' -Force"
if exist "{exe_path}" (
    start "" "{exe_path}"
)
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(script)
    return bat_path
