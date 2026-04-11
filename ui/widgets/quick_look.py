import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QApplication, QPlainTextEdit, QStackedWidget,
    QPushButton
)
from PyQt6.QtCore import Qt, QSize, QEvent, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QFont, QKeySequence

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

class QuickLookDialog(QDialog):
    """
    A macOS-style Quick Look dialog that shows a large preview of the selected file.
    Supports: Images, PDF (first page), Text files.
    """
    def __init__(self, file_path, config_mgr=None, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.config_mgr = config_mgr
        self._current_worker = None
        self._dpi_scale = 1.2  # 預設 SD 模式
        self._init_ui()
        self._load_preview()

    def _init_ui(self):
        # Frameless and translucent overlay
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main layout with dark semi-transparent background
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # The actual content container
        self.container = QFrame()
        self.container.setObjectName("QuickLookContainer")
        
        qss = """
            #QuickLookContainer {
                background-color: {{quickLookBg}};
                border-radius: 12px;
                border: 1px solid {{quickLookBorder}};
            }
        """
        if self.config_mgr:
            qss = self.config_mgr.apply_theme_to_text(qss)
        self.container.setStyleSheet(qss)
        
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header (filename + hint + close button)
        header = QHBoxLayout()
        header.setSpacing(15)
        
        self.title_label = QLabel(os.path.basename(self.file_path))
        text_color = "#ffffff"
        if self.config_mgr:
            text_color = self.config_mgr.get_theme_colors().get("text", text_color)
        self.title_label.setStyleSheet(f"color: {text_color}; font-weight: bold; font-size: 16px;")
        header.addWidget(self.title_label)
        
        header.addStretch()
        
        self.close_hint = QLabel("Press Space or Esc to close")
        accent_color = "#3498db"
        if self.config_mgr:
            accent_color = self.config_mgr.get_theme_colors().get("accent", accent_color)
        self.close_hint.setStyleSheet(f"color: {accent_color}; font-size: 13px; font-weight: bold;")
        header.addWidget(self.close_hint)
        
        # Quality Toggle Button (Only for PDF)
        self.quality_btn = QPushButton("SD")
        self.quality_btn.setFixedSize(45, 30)
        self.quality_btn.setToolTip(
            self.config_mgr.get_text("ui_quicklook_quality_tooltip", "切換解析度 (SD / HD)")
            if self.config_mgr else "切換解析度 (SD / HD)"
        )
        self.quality_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quality_btn.setVisible(False)
        self.quality_btn.clicked.connect(self._on_quality_toggle)
        
        quality_qss = """
            QPushButton {
                background-color: {{surfaceSubtle}};
                color: {{accent}};
                border-radius: 15px;
                font-size: 12px;
                font-weight: bold;
                border: 1px solid {{accent}};
            }
            QPushButton:hover {
                background-color: {{headerBg}};
                color: white;
            }
        """
        if self.config_mgr:
            quality_qss = self.config_mgr.apply_theme_to_text(quality_qss)
        self.quality_btn.setStyleSheet(quality_qss)
        header.addWidget(self.quality_btn)

        # Clickable Close Button
        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.accept)
        
        btn_qss = """
            QPushButton {
                background-color: {{surfaceSubtle}};
                color: white;
                border-radius: 15px;
                font-size: 20px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: {{danger}};
            }
        """
        if self.config_mgr:
            btn_qss = self.config_mgr.apply_theme_to_text(btn_qss)
        self.close_btn.setStyleSheet(btn_qss)
        header.addWidget(self.close_btn)
        
        self.container_layout.addLayout(header)
        
        # Content Area - QStackedWidget to show different types
        self.stack = QStackedWidget()
        
        # 1. Image View
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.image_label)
        
        # 2. Text View
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        text_color = "#e0e0e0"
        _font_size = 13
        if self.config_mgr:
            text_color = self.config_mgr.get_theme_colors().get("text", text_color)
            _font_size = self.config_mgr.load_config().get("preview_font_size", 13)
        self.text_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: transparent;
                color: {text_color};
                border: none;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: {_font_size}px;
            }}
        """)
        self.stack.addWidget(self.text_edit)

        # 3. Web View (xlsx / csv / sqlite / pdf / stl / step …)
        if _HAS_WEBENGINE:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWebEngineCore import QWebEngineSettings
            self.web_view = QWebEngineView()
            self.web_view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            self.web_view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            self.stack.addWidget(self.web_view)
        else:
            self.web_view = None

        self.container_layout.addWidget(self.stack)
        self.layout.addWidget(self.container)
        
        # Initial size
        self.resize(QSize(900, 700))
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            int((screen.width() - self.width()) / 2),
            int((screen.height() - self.height()) / 2)
        )

    def _load_preview(self):
        ext = os.path.splitext(self.file_path)[1].lower()
        
        # Show/Hide quality button based on type
        from core.preview_worker import PDF_EXTS
        self.quality_btn.setVisible(ext in PDF_EXTS)

        # 1. Cloud Check: Immediate feedback if it's offline
        try:
            from core.file_ops import FileOps
            if FileOps.is_offline_cloud_file(self.file_path):
                self._show_cloud_placeholder()
                return
        except Exception:
            pass

        # 2. Native Image Loading (Fast if local)
        from core.preview_worker import IMAGE_EXTS
        if ext in IMAGE_EXTS:
            self._stop_current_worker()
            self._load_image_native()
            return

        # 3. Everything else -> Async PreviewWorker
        self._start_async_worker()

    def _show_cloud_placeholder(self):
        if hasattr(self, 'web_view') and self.web_view is not None:
            from core.preview_worker import render_cloud_placeholder
            from PyQt6.QtCore import QUrl
            html = render_cloud_placeholder(self.file_path)
            self.web_view.setContent(html.encode("utf-8"), "text/html", QUrl(""))
            self.stack.setCurrentWidget(self.web_view)
        else:
            self.image_label.setText(
                self.config_mgr.get_text("ui_quicklook_cloud_placeholder", "⛅ 此檔案目前位於雲端 (尚未下載)")
                if self.config_mgr else "⛅ 此檔案目前位於雲端 (尚未下載)"
            )
            self.stack.setCurrentWidget(self.image_label)

    def _load_image_native(self):
        try:
            pix = QPixmap(self.file_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    self.stack.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)
                self.stack.setCurrentWidget(self.image_label)
            else:
                self.image_label.setText(
                    self.config_mgr.get_text("ui_quicklook_image_load_failed", "無法載入圖片預覽")
                    if self.config_mgr else "無法載入圖片預覽"
                )
                self.stack.setCurrentWidget(self.image_label)
        except Exception as e:
            self.image_label.setText(
                self.config_mgr.get_text("ui_quicklook_image_load_error", "圖片載入錯誤: {}").format(e)
                if self.config_mgr else f"圖片載入錯誤: {e}"
            )
            self.stack.setCurrentWidget(self.image_label)

    def _start_async_worker(self):
        self._stop_current_worker()
        
        # Show loading indicator
        if hasattr(self, 'web_view') and self.web_view is not None:
            name = os.path.basename(self.file_path)
            bg = "#1e1e1e"
            muted = "#6c7086"
            if self.config_mgr:
                colors = self.config_mgr.get_theme_colors()
                bg = colors.get("bg", bg)
                muted = colors.get("textMuted", muted)
            loading_text = (
                self.config_mgr.get_text("ui_quicklook_loading", "載入中... {}").format(name)
                if self.config_mgr else f"載入中... {name}"
            )
            loading_html = f"""<body style="background:{bg}; color:{muted}; display:flex; align-items:center; justify-content:center; height:100vh; font-family:sans-serif; margin:0;"><div>{loading_text}</div></body>"""
            self.web_view.setHtml(loading_html)
            self.stack.setCurrentWidget(self.web_view)
        
        from ui.workers.preview_thread import PreviewThread
        _pdf_max = self.config_mgr.load_config().get("pdf_preview_max_pages", 3) if self.config_mgr else 3
        self._current_worker = PreviewThread(self.file_path, pdf_max_pages=_pdf_max, pdf_dpi=self._dpi_scale)
        self._current_worker.html_ready.connect(self._on_preview_ready)
        self._current_worker.error.connect(self._on_preview_error)
        self._current_worker.start()

    def _stop_current_worker(self):
        if self._current_worker and self._current_worker.isRunning():
            self._current_worker.terminate()
            self._current_worker.wait(500)
        self._current_worker = None

    def _on_preview_ready(self, html: str, _base_dir: str, _path: str):
        if hasattr(self, 'web_view') and self.web_view is not None:
            from PyQt6.QtCore import QUrl
            self.web_view.setContent(html.encode("utf-8"), "text/html", QUrl(""))
            self.stack.setCurrentWidget(self.web_view)

    def _on_preview_error(self, msg: str):
        self.title_label.setText(
            self.config_mgr.get_text("ui_quicklook_preview_failed", "預覽讀取失敗: {}").format(msg)
            if self.config_mgr else f"預覽讀取失敗: {msg}"
        )

        # Fallback when WebEngine not installed: plain text for text files
        text_exts = {'.txt', '.py', '.json', '.md', '.ini', '.csv', '.log', '.xml', '.html', '.css', '.js'}
        if ext in text_exts:
            try:
                with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    self.text_edit.setPlainText(f.read(50000))
                self.stack.setCurrentWidget(self.text_edit)
            except Exception as e:
                self.title_label.setText(f"Error loading file: {str(e)}")
            return

        self._load_complex_preview(ext)

    def _load_office_preview(self, ext: str):
        """Render PPTX/DOCX first page via PyMuPDF at high resolution."""
        pix = None
        # 1. Try PyMuPDF — renders Office docs at arbitrary DPI
        try:
            import fitz
            doc = fitz.open(self.file_path)
            if doc.page_count > 0:
                page = doc.load_page(0)
                # Render at 3x zoom for crisp output
                mat = fitz.Matrix(3.0, 3.0)
                fm_pix = page.get_pixmap(matrix=mat, alpha=False)
                img = QImage(
                    fm_pix.samples, fm_pix.width, fm_pix.height,
                    fm_pix.stride, QImage.Format.Format_RGB888
                )
                pix = QPixmap.fromImage(img)
            doc.close()
        except Exception:
            pix = None

        # 2. Fallback: Windows Shell thumbnail at large size
        if pix is None or pix.isNull():
            from ui.workers.thumbnail_manager import _ThumbnailWorker
            worker = _ThumbnailWorker(self.file_path, size=1024)
            pix = worker._generate()

        if pix and not pix.isNull():
            scaled = pix.scaled(
                self.stack.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.stack.setCurrentWidget(self.image_label)
        else:
            self.image_label.setText("No preview available for this file type")
            self.stack.setCurrentWidget(self.image_label)

    def _load_complex_preview(self, ext):
        from ui.workers.thumbnail_manager import _ThumbnailWorker
        worker = _ThumbnailWorker(self.file_path, size=1024)
        pix = worker._generate()
        if pix and not pix.isNull():
            scaled = pix.scaled(
                self.stack.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.stack.setCurrentWidget(self.image_label)
        else:
            self.image_label.setText("No preview available for this file type")
            self.stack.setCurrentWidget(self.image_label)

    def _on_quality_toggle(self):
        """Toggle between SD (1.2) and HD (2.5) and re-render."""
        if self._dpi_scale < 2.0:
            self._dpi_scale = 2.5
            self.quality_btn.setText("HD")
        else:
            self._dpi_scale = 1.2
            self.quality_btn.setText("SD")
        
        self._start_async_worker()

    def closeEvent(self, event):
        self._stop_current_worker()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space or event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)
