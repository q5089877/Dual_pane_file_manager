"""
Preview 快取管理 — 避免重複渲染耗時與記憶體佔用。
"""
import os
import hashlib
import tempfile
from pathlib import Path
from typing import Optional


class PreviewCache:
    def __init__(self, cache_dir: str = ".preview_cache"):
        # 預設將快取存放在系統的暫存資料夾中，避免污染專案目錄
        self.cache_dir = Path(tempfile.gettempdir()) / \
            "DualPaneFileManager" / cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_key(self, file_path: str, params: Optional[dict] = None) -> str:
        """使用檔案路徑 + 修改時間 + 大小 + 渲染參數作為快取鍵，確保檔案或設定變更時快取自動失效"""
        try:
            stat = os.stat(file_path)
            key_str = f"{os.path.abspath(file_path)}_{stat.st_mtime}_{stat.st_size}"
            if params:
                key_str += f"_{str(sorted(params.items()))}"
            return hashlib.md5(key_str.encode()).hexdigest()
        except OSError:
            # 若無法取得 stat (例如檔案被鎖定)，降級僅使用路徑
            return hashlib.md5(os.path.abspath(file_path).encode()).hexdigest()

    def get(self, file_path: str, params: Optional[dict] = None) -> Optional[str]:
        """取得快取 HTML"""
        cache_key = self.get_cache_key(file_path, params)
        cache_file = self.cache_dir / f"{cache_key}.html"

        if cache_file.exists():
            try:
                return cache_file.read_text(encoding='utf-8')
            except Exception:
                pass
        return None

    def set(self, file_path: str, html: str, params: Optional[dict] = None) -> None:
        """儲存快取 HTML"""
        cache_key = self.get_cache_key(file_path, params)
        cache_file = self.cache_dir / f"{cache_key}.html"
        try:
            cache_file.write_text(html, encoding='utf-8')
        except Exception:
            pass

    def clear_old(self, max_age_hours: int = 24) -> None:
        """清理超過指定時間的舊快取檔案"""
        import time
        now = time.time()
        for cache_file in self.cache_dir.glob("*.html"):
            try:
                if now - cache_file.stat().st_mtime > max_age_hours * 3600:
                    cache_file.unlink()
            except OSError:
                pass
