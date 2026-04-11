from PyQt6.QtCore import QThread, pyqtSignal
from core.preview_worker import generate_preview
import os
import logging

logger = logging.getLogger(__name__)

class PreviewThread(QThread):
    """UI Layer Worker: Wraps the core preview generation in a QThread."""
    html_ready = pyqtSignal(str, str, str)  # (html, base_dir, path)
    error = pyqtSignal(str)

    def __init__(self, path: str, pdf_max_pages: int = 3, font_size: int = 13, pdf_dpi: float = 1.2, parent=None):
        super().__init__(parent)
        self._path = path
        self._pdf_max_pages = pdf_max_pages
        self._font_size = font_size
        self._pdf_dpi = pdf_dpi

    def run(self) -> None:
        try:
            from core.preview_cache import PreviewCache
            cache = PreviewCache()

            # 1. 嘗試從快取讀取
            params = {"pdf_max": self._pdf_max_pages, "font_size": self._font_size, "pdf_dpi": self._pdf_dpi}
            html = cache.get(self._path, params=params)
            base_dir = ""

            if not html:
                # 2. 快取未命中，執行生成
                html, base_dir = generate_preview(
                    self._path, pdf_max_pages=self._pdf_max_pages, font_size=self._font_size, pdf_dpi=self._pdf_dpi
                )
                # 3. 先 emit 讓 UI 顯示，再寫回快取
                self.html_ready.emit(html, base_dir, self._path)
                cache.set(self._path, html, params=params)
            else:
                # Cache Hit
                self.html_ready.emit(html, base_dir, self._path)
        except Exception as e:
            self.error.emit(str(e))
