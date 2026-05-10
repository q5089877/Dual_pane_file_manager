"""
PreviewPanel — persistent file preview widget embedded in the main window.

Renders:
  • images               → _ImageLoader (QThread): file I/O + JPEG decode in background,
                           QPixmap.fromImage() on main thread (near-zero cost)
  • text / source code   → Highlight.js (QWebEngineView)
  • PDF / .ai            → PyMuPDF first page
  • CSV / XLSX / SQLite  → HTML table (first 15 rows)
  • STL                  → Bounding box + volume (trimesh)
  • STEP / STP           → Three.js + occt-import-js WASM
  • SLDPRT / SLDASM      → OLE property table (olefile)

Architecture:
  Images: _ImageLoader (QThread) reads bytes + decodes QImage in background.
          Main thread only does QPixmap.fromImage() + scaled() on the decoded QImage.
          If user navigates away before load completes, stale results are discarded.
  Others: 150 ms debounce timer → PreviewThread (QThread) → QWebEngineView.
  The main thread is never blocked by I/O or JPEG decode.
"""
from __future__ import annotations
import locale
import os
import shutil
import tempfile
import logging

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QPushButton, QPlainTextEdit, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QUrl, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QColor, QPixmap, QImage, QIcon, QKeySequence, QShortcut

from core.preview_worker import TEXT_EXTS

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
    _HAS_WEBENGINE = True
except ImportError as e:
    logger.error(f"WebEngine Import Error: {e}")
    _HAS_WEBENGINE = False

from ui.workers.preview_thread import PreviewThread


# ── custom page to intercept app:// links ──────────────────────────────────────

class _PreviewPage(QWebEnginePage if _HAS_WEBENGINE else object):
    """Intercepts 'app://open' navigation to open files with the system default app."""

    def __init__(self, panel: 'PreviewPanel', parent=None):
        super().__init__(parent)
        self._panel = panel

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() == "app" and url.host() == "open":
            path = self._panel._pending_path or self._panel._current_image_path
            if path and os.path.isfile(path):
                os.startfile(path)
            return False  # block navigation

        if url.scheme() == "app" and url.host() in ("pages-inc", "pages-dec"):
            delta = +1 if url.host() == "pages-inc" else -1
            self._panel._adjust_pdf_pages(delta)
            return False

        # Intercept custom fspath: links (used by cloud placeholder download button)
        if url.scheme() == "fspath":
            path = self._panel._pending_path or self._panel._current_image_path
            if path and os.path.exists(path):
                os.startfile(path)
            return False  # block navigation
            
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif',
               '.tiff', '.tif', '.webp', '.ico', '.svg'}


# ── background image loader ────────────────────────────────────────────────────

class _ImageLoader(QThread):
    """
    Reads the file and decodes it to QImage entirely in a background thread.
    QImage is thread-safe; QPixmap is NOT (must stay on main thread).
    """
    image_ready = pyqtSignal(QImage, str)   # (full-res decoded image, path)

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            with open(self._path, "rb") as f:
                data = f.read()
            img = QImage()
            if img.loadFromData(data) and not img.isNull():
                self.image_ready.emit(img, self._path)
        except Exception:
            pass   # stale/missing file — caller shows placeholder


# ── panel ─────────────────────────────────────────────────────────────────────

class FloatingActionBar(QWidget):
    """
    A semi-transparent, floating action bar overlaid on top of the preview.
    Emits actions to the parent panel.
    """
    action_requested = pyqtSignal(str)  # 'delete', 'duplicate', 'extract'

    def __init__(self, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.setObjectName("FloatingActionBar")
        # 關鍵：讓自訂 Widget 支援 QSS 背景色
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)

        # 1. Glassmorphism Styling - Dynamic processing
        # actionBarBg: 從 glassBg 取 RGB，固定 alpha=0.25（不依賴 theme.json 是否有此 key）
        bar_bg = "rgba(30, 34, 45, 0.25)"
        if self.config_mgr:
            c = QColor(self.config_mgr.get_theme_colors().get("glassBg", "#ffffff"))
            bar_bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, 0.25)"

        qss = f"""
            QWidget#FloatingActionBar {{
                background-color: {bar_bg};
                border: 1px solid {{{{glassBorder}}}};
                border-radius: 20px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {{{{text}}}};
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background-color: {{{{headerBg}}}};
            }}
            QPushButton#btn_delete:hover {{
                background-color: {{{{danger}}}};
                color: white;
            }}
            QPushButton#btn_extract {{
                color: {{{{accent}}}};
            }}
            QPushButton#btn_extract:hover {{
                background-color: {{{{headerBg}}}};
                color: {{{{accent}}}};
            }}
        """
        if self.config_mgr:
            qss = self.config_mgr.apply_theme_to_text(qss)
        self.setStyleSheet(qss)

        # 2. Layout & Buttons
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        # 3. Premium Shadow
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        if self.config_mgr:
            color = QColor(self.config_mgr.get_theme_colors().get("shadow", "#000000"))
        else:
            color = QColor(0, 0, 0, 180)
        shadow.setColor(color)
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        btn_delete = QPushButton(self.config_mgr.get_text("ui_preview_btn_delete", "刪除") if self.config_mgr else "刪除")
        btn_delete.setIcon(QIcon("ui/trash.svg"))
        btn_delete.setObjectName("btn_delete")
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.clicked.connect(
            lambda: self.action_requested.emit('delete'))

        btn_dup = QPushButton(self.config_mgr.get_text("ui_preview_btn_duplicate", "複製到對面") if self.config_mgr else "複製到對面")
        btn_dup.setIcon(QIcon("ui/copy.svg"))
        btn_dup.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_dup.clicked.connect(
            lambda: self.action_requested.emit('duplicate'))

        btn_extract = QPushButton(self.config_mgr.get_text("ui_preview_btn_move", "移動到對面") if self.config_mgr else "移動到對面")
        btn_extract.setIcon(QIcon("ui/extract.svg"))
        btn_extract.setObjectName("btn_extract")
        btn_extract.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_extract.clicked.connect(
            lambda: self.action_requested.emit('extract'))

        layout.addWidget(btn_delete)
        layout.addWidget(btn_dup)
        layout.addWidget(btn_extract)

        # Fix the height so it looks like a pill
        self.setFixedHeight(40)

    def sizeHint(self):
        # 提供準確的 Hint 確保在 resizeEvent 中計算座標正確
        layout_hint = self.layout().sizeHint()
        return QSize(layout_hint.width() + 20, 40)


class PreviewPanel(QWidget):
    """Side preview panel — call ``preview_file(path)`` on selection."""

    # Forward the action request to the outside world
    action_requested = pyqtSignal(str, str)  # action, current_path
    quality_changed = pyqtSignal(str)

    DEBOUNCE_MS = 150
    # kill worker if it hangs > 20 s (e.g. PyMuPDF on bad PDF)
    WORKER_TIMEOUT_MS = 20_000

    def __init__(self, config_mgr=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.setObjectName("previewPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        self._pending_path: str = ""
        self._current_image_path: str = ""   # path of the image currently loading/shown
        # full-res decoded image (for resize re-scale)
        self._image_qimg: QImage | None = None
        self._image_loader: _ImageLoader | None = None
        self._current_worker: PreviewThread | None = None
        self._dpi_scale = 1.2  # 預設 SD 模式

        # ── edit mode state ──────────────────────────────────────────────────
        self._is_editing: bool = False
        self._editing_path: str = ""
        self._original_content: str = ""
        self._editing_encoding: str = "utf-8"

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DEBOUNCE_MS)
        self._timer.timeout.connect(self._start_worker)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(self.WORKER_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_worker_timeout)

        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Ignored policy prevents pixmap size from leaking into
        # the layout's minimum-size calculation.
        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg_color = "#1e1e2e"
        if self.config_mgr:
            bg_color = self.config_mgr.get_theme_colors().get("bg", bg_color)
        self._image_label.setStyleSheet(f"background: {bg_color};")
        self._image_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Ignored)
        self._image_label.setMinimumSize(0, 0)
        self._image_label.setVisible(False)
        layout.addWidget(self._image_label)

        # ── edit action bar (floating overlay at top, text files only) ───────
        # NOT in layout — positioned via resizeEvent like floating_bar
        self._edit_bar = QWidget(self)
        self._edit_bar.setObjectName("previewEditBar")
        eb = QHBoxLayout(self._edit_bar)
        eb.setContentsMargins(8, 3, 8, 3)
        eb.setSpacing(6)
        eb.addStretch()

        _btn_txt = lambda key, fb: (
            self.config_mgr.get_text(key, fb) if self.config_mgr else fb)

        self._btn_edit = QPushButton(_btn_txt("ui_preview_btn_edit", "✏️ 編輯"))
        self._btn_save = QPushButton(_btn_txt("ui_preview_btn_save_edit", "💾 儲存"))
        self._btn_discard = QPushButton(_btn_txt("ui_preview_btn_discard", "✕ 放棄"))

        self._btn_save.setObjectName("editSaveBtn")
        self._btn_discard.setObjectName("editDiscardBtn")

        self._btn_edit.clicked.connect(self._enter_edit_mode)
        self._btn_save.clicked.connect(self._save_edit)
        self._btn_discard.clicked.connect(self._discard_edit)

        self._btn_save.setVisible(False)
        self._btn_discard.setVisible(False)

        eb.addWidget(self._btn_edit)
        eb.addWidget(self._btn_save)
        eb.addWidget(self._btn_discard)
        self._edit_bar.setVisible(False)

        # ── plain text editor (floating overlay, edit mode only) ──────────
        # NOT in layout — covers _web area via resizeEvent
        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setObjectName("previewTextEdit")
        font_size = 13
        if self.config_mgr:
            font_size = self.config_mgr.load_config().get("preview_font_size", 13)
        bg = "#1e1e2e"
        fg = "#c9d1d9"
        if self.config_mgr:
            c = self.config_mgr.get_theme_colors()
            bg = c.get("panelBg", bg)
            fg = c.get("text", fg)
        self._text_edit.setStyleSheet(
            f"QPlainTextEdit {{ background:{bg}; color:{fg}; "
            f"font-family:'Consolas','Courier New',monospace; font-size:{font_size}pt; "
            f"border:none; }}")
        self._text_edit.setVisible(False)

        # Ctrl+S saves while in edit mode
        shortcut = QShortcut(QKeySequence("Ctrl+S"), self._text_edit)
        shortcut.activated.connect(self._save_edit)

        if _HAS_WEBENGINE:
            self._web = QWebEngineView(self)
            # Custom page to intercept app:// links
            custom_page = _PreviewPage(self, self._web)
            self._web.setPage(custom_page)
            settings = self._web.settings()
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
            # Prevent white flash before first HTML render
            bg_color = QColor("#1e1e2e")
            if self.config_mgr:
                bg_color = QColor(self.config_mgr.get_theme_colors().get("bg", "#1e1e2e"))
            self._web.page().setBackgroundColor(bg_color)
            self._web.setHtml(self._placeholder_html())
            layout.addWidget(self._web)
        else:
            _missing_text = self.config_mgr.get_text(
                "ui_preview_missing_webengine",
                "預覽功能需要 PyQt6-WebEngine\n請執行: pip install PyQt6-WebEngine"
            ) if self.config_mgr else "預覽功能需要 PyQt6-WebEngine\n請執行: pip install PyQt6-WebEngine"
            lbl = QLabel(_missing_text, self)
            lbl.setObjectName("previewFallbackLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        # ── Floating Action Bar ─────────────────────────────────────────────
        self.floating_bar = FloatingActionBar(self.config_mgr, self)
        self.floating_bar.hide()
        # Connect internal FAB signal to external panel signal
        self.floating_bar.action_requested.connect(
            lambda action: self.action_requested.emit(
                action, self._pending_path or self._current_image_path)
        )

    def _adjust_pdf_pages(self, delta: int) -> None:
        if not self.config_mgr:
            return
        cfg = self.config_mgr.load_config()
        current = cfg.get("pdf_preview_max_pages", 3)
        new_val = max(1, min(20, current + delta))
        if new_val == current:
            return
        self.config_mgr.save_config(pdf_preview_max_pages=new_val)
        if self._pending_path:
            self._start_worker()

    @pyqtSlot()
    def _toggle_quality(self) -> None:
        if self._dpi_scale < 2.0:
            self._dpi_scale = 2.5
            self.quality_changed.emit("HD")
        else:
            self._dpi_scale = 1.2
            self.quality_changed.emit("SD")
            
        if self._pending_path:
            self._start_worker()

    # ── public API ────────────────────────────────────────────────────────────

    def preview_file(self, path: str) -> None:
        """
        Switch to a new file.  Images start an async _ImageLoader immediately
        (no debounce — I/O is in the background so there is no main-thread cost).
        Other file types use the 150 ms debounce → PreviewThread pipeline.
        """
        if not path or not os.path.isfile(path):
            self._show_placeholder()
            return

        # ── guard: ask to save if switching away while editing ────────────
        if self._is_editing and path != self._editing_path:
            if self._text_edit.toPlainText() != self._original_content:
                title = (self.config_mgr.get_text("ui_preview_edit_unsaved_title", "未儲存的變更")
                         if self.config_mgr else "未儲存的變更")
                msg = (self.config_mgr.get_text("ui_preview_edit_unsaved_msg",
                                                "目前的編輯尚未儲存，要儲存嗎？")
                       if self.config_mgr else "目前的編輯尚未儲存，要儲存嗎？")
                btn = QMessageBox.question(
                    self, title, msg,
                    QMessageBox.StandardButton.Save |
                    QMessageBox.StandardButton.Discard |
                    QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save)
                if btn == QMessageBox.StandardButton.Cancel:
                    return
                if btn == QMessageBox.StandardButton.Save:
                    self._save_edit()
                    return
            self._exit_edit_mode()

        ext = os.path.splitext(path)[1].lower()

        # show / hide edit bar based on file type
        is_text = ext in TEXT_EXTS
        self._edit_bar.setVisible(is_text)
        if not is_text:
            self._btn_edit.setVisible(True)
            self._btn_save.setVisible(False)
            self._btn_discard.setVisible(False)

        if ext in _IMAGE_EXTS:
            self._timer.stop()
            self._stop_worker()
            self._load_image_async(path)
        else:
            self._stop_image_loader()
            self._pending_path = path
            self._timer.start()

        self.floating_bar.show()
        self.floating_bar.raise_()

    # ── edit mode ─────────────────────────────────────────────────────────────

    @staticmethod
    def _read_file_text(path: str) -> tuple[str, str]:
        """Return (content, encoding). Tries UTF-8 BOM → UTF-8 → system → latin-1."""
        for enc in ("utf-8-sig", "utf-8", locale.getpreferredencoding(False), "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    return f.read(), enc
            except (UnicodeDecodeError, LookupError):
                continue
        return "", "utf-8"

    def _enter_edit_mode(self) -> None:
        path = self._pending_path
        if not path or not os.path.isfile(path):
            return
        content, enc = self._read_file_text(path)
        self._editing_path = path
        self._original_content = content
        self._editing_encoding = enc
        self._is_editing = True

        self._timer.stop()
        self._stop_worker()
        self._image_label.setVisible(False)
        if _HAS_WEBENGINE:
            self._web.setVisible(False)

        self._text_edit.setPlainText(content)
        self._text_edit.setVisible(True)
        self._text_edit.setFocus()

        self._btn_edit.setVisible(False)
        self._btn_save.setVisible(True)
        self._btn_discard.setVisible(True)
        self._reposition_overlays()

    def _save_edit(self) -> None:
        if not self._is_editing:
            return
        content = self._text_edit.toPlainText()
        try:
            enc = self._editing_encoding if self._editing_encoding != "utf-8-sig" else "utf-8"
            with open(self._editing_path, "w", encoding=enc,
                      newline="") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.warning(
                self,
                self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤",
                str(e))
            return
        saved_path = self._editing_path
        self._exit_edit_mode()
        self._pending_path = saved_path
        self._timer.start()

    def _discard_edit(self) -> None:
        if not self._is_editing:
            return
        if self._text_edit.toPlainText() != self._original_content:
            title = (self.config_mgr.get_text("ui_preview_edit_unsaved_title", "未儲存的變更")
                     if self.config_mgr else "未儲存的變更")
            msg = (self.config_mgr.get_text("ui_preview_edit_discard_msg", "放棄所有編輯內容？")
                   if self.config_mgr else "放棄所有編輯內容？")
            if QMessageBox.question(self, title, msg) != QMessageBox.StandardButton.Yes:
                return
        path = self._editing_path
        self._exit_edit_mode()
        self._pending_path = path
        self._timer.start()

    def _exit_edit_mode(self) -> None:
        self._is_editing = False
        self._editing_path = ""
        self._original_content = ""
        self._text_edit.setVisible(False)
        if _HAS_WEBENGINE:
            self._web.setVisible(True)
        self._btn_edit.setVisible(True)
        self._btn_save.setVisible(False)
        self._btn_discard.setVisible(False)
        self._reposition_overlays()

    def clear(self) -> None:
        """Reset to placeholder."""
        self._timer.stop()
        self._pending_path = ""
        self._current_image_path = ""
        self._image_qimg = None
        self._stop_image_loader()
        self._stop_worker()
        if self._is_editing:
            self._exit_edit_mode()
        self._edit_bar.setVisible(False)
        self._show_placeholder()
        self.floating_bar.hide()

    # ── image path (async) ────────────────────────────────────────────────────

    def _load_image_async(self, path: str) -> None:
        self._stop_image_loader()
        self._current_image_path = path
        # Keep the previous image on screen while the new one loads —
        # avoids a blank flash during fast ↑↓ navigation.
        loader = _ImageLoader(path, self)
        loader.image_ready.connect(self._on_image_ready)
        self._image_loader = loader
        loader.start()

    def _stop_image_loader(self) -> None:
        loader = self._image_loader
        self._image_loader = None
        if loader is None:
            return
        try:
            loader.image_ready.disconnect()
        except RuntimeError:
            pass
        if loader.isRunning():
            loader.terminate()
            loader.wait(300)

    @pyqtSlot(QImage, str)
    def _on_image_ready(self, img: QImage, path: str) -> None:
        """Received on the main thread after background decode."""
        if path != self._current_image_path:
            return   # user already moved to a different file — discard
        self._image_qimg = img
        self._image_label.setVisible(True)
        if _HAS_WEBENGINE:
            self._web.setVisible(False)
        # Defer rendering to next event loop tick so the layout has time to
        # assign the correct size to _image_label before we scale the pixmap.
        QTimer.singleShot(0, self._render_image_to_label)

    def _render_image_to_label(self) -> None:
        """Scale the stored full-res QImage to fit the label, then convert to QPixmap."""
        if self._image_qimg is None:
            return
        size = self._image_label.size()
        if size.width() <= 1 or size.height() <= 1:
            return
        scaled_img = self._image_qimg.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(QPixmap.fromImage(scaled_img))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_image_to_label()
        self._reposition_overlays()

    def _reposition_overlays(self) -> None:
        w, h = self.width(), self.height()

        # Edit bar: full-width strip pinned to the top
        if self._edit_bar.isVisible():
            self._edit_bar.adjustSize()
            eb_h = max(self._edit_bar.sizeHint().height(), 28)
            self._edit_bar.setGeometry(0, 0, w, eb_h)
            self._edit_bar.raise_()
        else:
            eb_h = 0

        # Text editor: fills the area below the edit bar
        if self._text_edit.isVisible():
            self._text_edit.setGeometry(0, eb_h, w, h - eb_h)
            self._text_edit.raise_()

        # Floating action bar: bottom center (unchanged)
        self.floating_bar.adjustSize()
        bar_w = self.floating_bar.width()
        bar_h = self.floating_bar.height()
        x = (w - bar_w) // 2
        y = h - bar_h - 20
        self.floating_bar.setGeometry(x, y, bar_w, bar_h)
        self.floating_bar.raise_()

    # ── WebEngine path ────────────────────────────────────────────────────────

    def _start_worker(self) -> None:
        if not self._pending_path:
            return
        self._stop_worker()
        self._image_qimg = None
        self._image_label.setVisible(False)
        if _HAS_WEBENGINE:
            self._web.setVisible(True)

        # Skip heavy loading placeholder for PDF to avoid WebEngine race conditions
        ext = os.path.splitext(self._pending_path)[1].lower()
        if ext not in {".pdf", ".ai"}:
            self._show_loading()
        _cfg = self.config_mgr.load_config() if self.config_mgr else {}
        _pdf_max = _cfg.get("pdf_preview_max_pages", 3)
        _font_size = _cfg.get("preview_font_size", 13)
        self._current_worker = PreviewThread(
            self._pending_path, pdf_max_pages=_pdf_max, font_size=_font_size, pdf_dpi=self._dpi_scale, parent=self)
        self._current_worker.html_ready.connect(self._on_html_ready)
        self._current_worker.error.connect(self._on_error)
        self._current_worker.finished.connect(self._on_worker_finished)
        self._current_worker.start()
        self._timeout_timer.start()   # watchdog: kill if worker hangs

    def _stop_worker(self) -> None:
        self._timeout_timer.stop()
        w = self._current_worker
        self._current_worker = None
        if w is None:
            return
        try:
            w.html_ready.disconnect()
            w.error.disconnect()
            w.finished.disconnect()
        except RuntimeError:
            pass
        if w.isRunning():
            w.terminate()
            w.wait(500)

    def _on_worker_timeout(self) -> None:
        """Worker has been running too long (e.g. PyMuPDF hanging on a bad PDF)."""
        self._stop_worker()
        if _HAS_WEBENGINE:
            name = os.path.basename(self._pending_path)
            bg = "#1e1e2e"
            text = "#f38ba8"
            muted = "#6c7086"
            if self.config_mgr:
                colors = self.config_mgr.get_theme_colors()
                bg = colors.get("bg", bg)
                text = colors.get("danger", text)
                muted = colors.get("textMuted", muted)

            timeout_tpl = self.config_mgr.get_text("ui_preview_timeout", "預覽逾時：{}") if self.config_mgr else "預覽逾時：{}"
            err_detail = self.config_mgr.get_text("ui_preview_encrypted_or_invalid", "此檔案可能已加密或格式異常") if self.config_mgr else "此檔案可能已加密或格式異常"

            self._web.setHtml(
                f"""<!DOCTYPE html><html><body style="background:{bg};color:{text};
        font-family:system-ui;padding:20px;display:flex;align-items:center;
        justify-content:center;height:100vh;margin:0;flex-direction:column;gap:8px">
        <span style="font-size:24px">⏱</span>
        <span>{timeout_tpl.format(name)}</span>
        <span style="font-size:11px;color:{muted}">{err_detail}</span>
        </body></html>"""
            )


    @pyqtSlot(str, str, str)
    def _on_html_ready(self, html: str, _base_dir: str, _path: str) -> None:
        if not _HAS_WEBENGINE:
            return

        if _path != self._pending_path:
            return

        # Use temporary file loading for stability with large HTML/Base64 payloads
        try:
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, "double_explorer_preview.html")
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(html)

            from PyQt6.QtCore import QUrl
            logger.debug(f"[UI Ready] Loading via temp file: {temp_file}")
            self._web.setUrl(QUrl.fromLocalFile(temp_file))
            self._web.update()
        except Exception as e:
            logger.error(f"Failed to write temp preview file: {e}")
            # Fallback to direct setHtml if file writing fails
            self._web.setHtml(html)

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        bg = "#1e1e2e"
        text = "#f38ba8"
        if self.config_mgr:
            colors = self.config_mgr.get_theme_colors()
            bg = colors.get("bg", bg)
            text = colors.get("danger", text)

        if _HAS_WEBENGINE:
            err_tpl = self.config_mgr.get_text("ui_preview_load_failed", "載入失敗: {}") if self.config_mgr else "載入失敗: {}"
            err_html = f"""<!DOCTYPE html><html><body style="background:{bg};color:{text};
font-family:system-ui;padding:20px">{err_tpl.format(msg)}</body></html>"""
            self._web.setHtml(err_html)

    @pyqtSlot()
    def _on_worker_finished(self) -> None:
        self._timeout_timer.stop()
        self._current_worker = None

    def _show_placeholder(self) -> None:
        self._image_qimg = None
        self._image_label.setVisible(False)
        if _HAS_WEBENGINE:
            self._web.setVisible(True)
            self._web.setHtml(self._placeholder_html())

    def _show_loading(self) -> None:
        if _HAS_WEBENGINE:
            name = os.path.basename(self._pending_path)
            bg = "#1e1e2e"
            muted = "#6c7086"
            if self.config_mgr:
                colors = self.config_mgr.get_theme_colors()
                bg = colors.get("bg", bg)
                muted = colors.get("textMuted", muted)

            loading_tpl = self.config_mgr.get_text("ui_preview_loading", "載入中… {}") if self.config_mgr else "載入中… {}"
            html = f"""<!DOCTYPE html><html>
<body style="background:{bg};color:{muted};font-family:system-ui;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<span>{loading_tpl.format(name)}</span>
</body></html>"""
            self._web.setHtml(html)

    def _placeholder_html(self) -> str:
        bg = "#1e1e2e"
        muted = "#45475a"
        if self.config_mgr:
            colors = self.config_mgr.get_theme_colors()
            bg = colors.get("bg", bg)
            muted = colors.get("textMuted", muted)

        select_text = self.config_mgr.get_text("ui_preview_select_file", "選擇檔案以預覽") if self.config_mgr else "選擇檔案以預覽"
        return f"""<!DOCTYPE html><html>
<body style="background:{bg};color:{muted};font-family:system-ui;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
flex-direction:column;gap:8px">
<span style="font-size:32px">👁</span>
<span>{select_text}</span>
</body></html>"""

    # ── cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        self._stop_image_loader()
        self._stop_worker()
        super().closeEvent(event)
