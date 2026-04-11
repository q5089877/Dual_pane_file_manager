"""
zip_worker.py — 背景執行緒工具

SizeWorker : 計算 Drop Zone 所有項目的總磁碟大小（遞迴），不阻塞主執行緒。
ZipWorker  : 將 Drop Zone 所有項目壓縮至 %TEMP%，處理 ZIP 內部重名衝突。
"""
from __future__ import annotations
import os
import zipfile
import tempfile
from PyQt6.QtCore import QThread, pyqtSignal


# ── 大小計算（背景） ────────────────────────────────────────────────────────────

class SizeWorker(QThread):
    """背景計算 Drop Zone 所有項目的總磁碟佔用 bytes，避免主執行緒卡死。"""
    size_ready = pyqtSignal(int)  # total bytes

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager

    def run(self) -> None:
        try:
            total = self._manager.get_total_size()
            self.size_ready.emit(total)
        except Exception:
            self.size_ready.emit(0)


# ── ZIP 壓縮（背景） ────────────────────────────────────────────────────────────

class ZipWorker(QThread):
    """背景壓縮 Drop Zone 所有項目至 %TEMP%。
    - 自動處理 ZIP 內部同名檔案（重命名為 _v1, _v2...）
    - 自動處理 ZIP 檔案本身的防撞命名
    """
    finished = pyqtSignal(str)   # 完成後回傳 zip 絕對路徑
    error    = pyqtSignal(str)   # 失敗時回傳錯誤訊息

    def __init__(self, items: list[dict], zip_name: str, parent=None):
        super().__init__(parent)
        self._items    = items
        self._zip_name = zip_name

    def run(self) -> None:
        try:
            tmp_dir  = tempfile.gettempdir()
            zip_path = os.path.join(tmp_dir, self._zip_name)

            # ZIP 檔案本身防撞（避免覆蓋上一次未清理的暫存 ZIP）
            base, ext = os.path.splitext(zip_path)
            v = 1
            while os.path.exists(zip_path):
                zip_path = f"{base}_v{v}{ext}"
                v += 1

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                seen_arcnames: set[str] = set()

                def _safe_arcname(name: str) -> str:
                    """確保 ZIP 內部不重名，避免靜默覆蓋不同來源的同名檔案。"""
                    if name not in seen_arcnames:
                        seen_arcnames.add(name)
                        return name
                    stem, suffix = os.path.splitext(name)
                    i = 1
                    while True:
                        candidate = f"{stem}_v{i}{suffix}"
                        if candidate not in seen_arcnames:
                            seen_arcnames.add(candidate)
                            return candidate
                        i += 1

                for item in self._items:
                    path = item["path"]
                    if os.path.isfile(path):
                        arc = _safe_arcname(os.path.basename(path))
                        zf.write(path, arc)
                    elif os.path.isdir(path):
                        base_dir = os.path.dirname(path)
                        for root, _, files in os.walk(path):
                            for f in files:
                                fp  = os.path.join(root, f)
                                rel = os.path.relpath(fp, base_dir)
                                arc = _safe_arcname(rel)
                                zf.write(fp, arc)

            self.finished.emit(zip_path)
        except Exception as e:
            self.error.emit(str(e))
