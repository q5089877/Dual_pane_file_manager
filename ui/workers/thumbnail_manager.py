"""
ThumbnailManager: Background async thumbnail generator.
- Images: loaded with QImage (native, no deps).
- PDFs: first page rendered via PyMuPDF (fitz) if available.
- Fallback: standard QFileIconProvider system icon.
Emits thumbnail_ready(path, QPixmap) when done.
"""
import os
import zipfile
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QSize, QFileInfo, Qt
from PyQt6.QtGui import QPixmap, QImage, QColor, QPainter, QFont
from PyQt6.QtWidgets import QFileIconProvider

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp', '.ico', '.svg'}
PDF_EXT = '.pdf'
OFFICE_EXTS = {
    '.docx': ('DOC', '#2980b9'),
    '.doc':  ('DOC', '#2980b9'),
    '.xlsx': ('XLS', '#27ae60'),
    '.xls':  ('XLS', '#27ae60'),
    '.pptx': ('PPT', '#e67e22'),
    '.ppt':  ('PPT', '#e67e22'),
}

THUMB_SIZE = 160  # pixels for the long side


class _ThumbnailWorker(QThread):
    """Background thread that generates one thumbnail."""
    thumbnail_ready = pyqtSignal(str, QPixmap)

    def __init__(self, path: str, size: int, parent=None):
        super().__init__(parent)
        self.path = path
        self.size = size

    def run(self):
        pixmap = self._generate()
        if pixmap and not pixmap.isNull():
            self.thumbnail_ready.emit(self.path, pixmap)

    def _generate(self):
        # 1. Cloud Check: If file is offline/cloud-only, DO NOT trigger I/O.
        # This prevents the UI from freezing while waiting for a download.
        try:
            from core.file_ops import FileOps
            if FileOps.is_offline_cloud_file(self.path):
                # Return None to fallback to generic icon; or handle it specially.
                return None
        except ImportError:
            pass

        # 2. Try Windows Shell thumbnail engine first — covers ALL types Explorer can preview
        px = self._windows_shell_thumb()
        if px and not px.isNull():
            return px

        ext = os.path.splitext(self.path)[1].lower()
        if ext in IMAGE_EXTS:
            return self._image_thumb()
        elif ext == PDF_EXT:
            return self._pdf_thumb()
        elif ext in OFFICE_EXTS:
            return self._office_thumb(ext)
        return None

    def _windows_shell_thumb(self) -> QPixmap | None:
        """
        Call Windows IShellItemImageFactory::GetImage via ctypes (no extra deps).
        Returns the same thumbnail Windows Explorer shows, for ANY file type.
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            from ctypes import (Structure, POINTER, WINFUNCTYPE, byref,
                                c_ulong, c_ushort, c_ubyte, c_uint, c_void_p, HRESULT)

            ole32 = ctypes.windll.ole32
            # Initialize COM for this background thread (STA)
            ole32.CoInitializeEx(None, 0x2)  # COINIT_MULTITHREADED

            # --- GUID helper ---
            class GUID(Structure):
                _fields_ = [("Data1", c_ulong), ("Data2", c_ushort),
                             ("Data3", c_ushort), ("Data4", c_ubyte * 8)]

            # IShellItemImageFactory IID: {BCC18B79-BA16-442F-80C4-8A59C30C463B}
            iid = GUID(0xBCC18B79, 0xBA16, 0x442F,
                       (c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))

            class SIZE(Structure):
                _fields_ = [("cx", wt.LONG), ("cy", wt.LONG)]

            # SHCreateItemFromParsingName
            shell32 = ctypes.windll.shell32
            shell32.SHCreateItemFromParsingName.argtypes = [
                wt.LPCWSTR, c_void_p, POINTER(GUID), POINTER(c_void_p)]
            shell32.SHCreateItemFromParsingName.restype = HRESULT

            ppv = c_void_p()
            hr = shell32.SHCreateItemFromParsingName(self.path, None, byref(iid), byref(ppv))
            if hr != 0 or not ppv.value:
                ole32.CoUninitialize()
                return None

            # Access vtable: [0]=QI, [1]=AddRef, [2]=Release, [3]=GetImage
            vtable = ctypes.cast(
                ctypes.cast(ppv.value, POINTER(c_void_p))[0],
                POINTER(c_void_p))

            # Call GetImage(SIZE, SIIGBF, HBITMAP*)
            GetImageFn = WINFUNCTYPE(HRESULT, c_void_p, SIZE, c_uint, POINTER(wt.HANDLE))
            GetImage = GetImageFn(vtable[3])

            hbm = wt.HANDLE()
            hr = GetImage(ppv, SIZE(self.size, self.size), 0, byref(hbm))  # 0 = SIIGBF_RESIZETOFIT

            # Release the COM interface
            ReleaseFn = WINFUNCTYPE(c_ulong, c_void_p)
            ReleaseFn(vtable[2])(ppv)
            ole32.CoUninitialize()

            if hr != 0 or not hbm.value:
                return None

            # Convert HBITMAP to QPixmap
            try:
                px = QPixmap.fromWinHBITMAP(int(hbm.value))
            except AttributeError:
                # Fallback if fromWinHBITMAP is unavailable: read pixels via GetDIBits
                px = self._hbitmap_to_pixmap(int(hbm.value), self.size)
            finally:
                ctypes.windll.gdi32.DeleteObject(hbm)

            return px if (px and not px.isNull()) else None

        except Exception:
            return None

    def _hbitmap_to_pixmap(self, hbm: int, size: int) -> QPixmap | None:
        """Fallback: convert HBITMAP to QPixmap via GetDIBits (no Qt Windows API needed)."""
        try:
            import ctypes, ctypes.wintypes as wt
            from ctypes import Structure, c_int32, c_uint32, c_ubyte, c_void_p, byref

            class BITMAPINFOHEADER(Structure):
                _fields_ = [
                    ("biSize", c_uint32), ("biWidth", c_int32), ("biHeight", c_int32),
                    ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
                    ("biCompression", c_uint32), ("biSizeImage", c_uint32),
                    ("biXPelsPerMeter", c_int32), ("biYPelsPerMeter", c_int32),
                    ("biClrUsed", c_uint32), ("biClrImportant", c_uint32),
                ]

            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth = size
            bih.biHeight = -size   # negative = top-down
            bih.biPlanes = 1
            bih.biBitCount = 32
            bih.biCompression = 0  # BI_RGB

            buf = (c_ubyte * (size * size * 4))()
            hdc = ctypes.windll.user32.GetDC(None)
            ctypes.windll.gdi32.GetDIBits(hdc, hbm, 0, size, buf, byref(bih), 0)
            ctypes.windll.user32.ReleaseDC(None, hdc)

            # BGRA -> RGBA swap
            data = bytearray(buf)
            for i in range(0, len(data), 4):
                data[i], data[i+2] = data[i+2], data[i]

            img = QImage(bytes(data), size, size, size * 4,
                         QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(img)
        except Exception:
            return None


    def _image_thumb(self):
        try:
            img = QImage(self.path)
            if img.isNull():
                return None
            img = img.scaled(
                self.size, self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            return QPixmap.fromImage(img)
        except Exception:
            return None

    def _pdf_thumb(self):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(self.path)
            if not doc.page_count:
                return None
            page = doc.load_page(0)
            # Render at 2x for sharpness, then downscale
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            doc.close()

            img = QImage(
                pix.samples,
                pix.width, pix.height,
                pix.stride,
                QImage.Format.Format_RGB888
            )
            img = img.scaled(
                self.size, self.size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            return QPixmap.fromImage(img)
        except ImportError:
            return self._pdf_fallback()
        except Exception:
            return None

    def _pdf_fallback(self):
        """Returns a styled PDF badge when fitz is unavailable."""
        return self._draw_badge("PDF", "#c0392b")

    def _office_thumb(self, ext: str) -> QPixmap | None:
        """Try embedded thumbnail first, then text preview for DOCX, then badge fallback."""
        label, color = OFFICE_EXTS.get(ext, ('OFF', '#7f8c8d'))
        try:
            with zipfile.ZipFile(self.path, 'r') as z:
                names = z.namelist()
                # 1. Try embedded thumbnail (works if Word saved with thumbnail enabled)
                for thumb_path in ('docProps/thumbnail.jpeg', 'docProps/thumbnail.jpg',
                                   'docProps/thumbnail.png'):
                    if thumb_path in names:
                        data = z.read(thumb_path)
                        img = QImage.fromData(data)
                        if not img.isNull():
                            img = img.scaled(
                                self.size, self.size,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation
                            )
                            return QPixmap.fromImage(img)

                # 2. For DOCX: parse word/document.xml and render text as page preview
                if ext in ('.docx', '.doc') and 'word/document.xml' in names:
                    import xml.etree.ElementTree as ET
                    xml_data = z.read('word/document.xml')
                    root = ET.fromstring(xml_data)
                    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    lines = []
                    for para in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                        text = ''.join(t.text or '' for t in para.iter(
                            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                        if text.strip():
                            lines.append(text.strip())
                        if len(lines) >= 12:  # enough for a preview
                            break
                    if lines:
                        return self._render_text_page(lines, label, color)
        except Exception:
            pass
        # 3. Final fallback: colour badge
        return self._draw_badge(label, color)

    def _render_text_page(self, lines: list, badge_label: str, badge_color: str) -> QPixmap:
        """Render document text on a white page preview.
        Renders at 3x resolution for sharpness, then downscales.
        """
        SCALE = 3
        W = self.size * SCALE
        H = int(self.size * 1.35 * SCALE)  # A4 aspect ratio

        px = QPixmap(W, H)
        px.fill(QColor("white"))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Border
        painter.setPen(QColor("#dddddd"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, W - 1, H - 1)

        # Badge (top-right corner)
        bw, bh = 36 * SCALE, 14 * SCALE
        bx, by = W - bw - 4 * SCALE, 4 * SCALE
        painter.setBrush(QColor(badge_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bx, by, bw, bh, 4 * SCALE, 4 * SCALE)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 7 * SCALE, QFont.Weight.Bold))
        painter.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, badge_label)

        # Text — fixed small point sizes scaled by SCALE
        margin = 10 * SCALE
        y = margin
        TITLE_PT = 10 * SCALE   # ~10pt title
        BODY_PT  = 8 * SCALE    # ~8pt body
        LINE_H   = BODY_PT + 4 * SCALE

        for i, line in enumerate(lines):
            if y + LINE_H > H - margin:
                break
            if i == 0:
                font = QFont("Segoe UI", TITLE_PT, QFont.Weight.Bold)
                painter.setPen(QColor("#111111"))
                painter.setFont(font)
                fm = painter.fontMetrics()
                y += 2 * SCALE  # extra top margin for title
            else:
                font = QFont("Segoe UI", BODY_PT)
                painter.setPen(QColor("#333333"))
                painter.setFont(font)
                fm = painter.fontMetrics()

            elided = fm.elidedText(line, Qt.TextElideMode.ElideRight, W - margin * 2)
            painter.drawText(margin, y, W - margin * 2, LINE_H,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
            y += LINE_H

        painter.end()
        return px.scaled(self.size, self.size,
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)



    def _draw_badge(self, label: str, bg_color_str: str) -> QPixmap:
        """Draw a clean colored badge with label text (used as fallback)."""
        px = QPixmap(self.size, self.size)
        px.fill(QColor("#1a1a2e"))
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        badge_color = QColor(bg_color_str)
        painter.setBrush(badge_color)
        painter.setPen(Qt.PenStyle.NoPen)
        cx, cy = self.size // 2, self.size // 2
        r = self.size // 3
        painter.drawRoundedRect(cx - r, cy - r, r * 2, r * 2, 10, 10)
        painter.setPen(QColor("white"))
        font = QFont("Arial", r // 2, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(cx - r, cy - r, r * 2, r * 2, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return px



class ThumbnailManager(QObject):
    """
    Central manager that spawns worker threads for thumbnail generation.
    Maintains an in-memory cache.
    """
    thumbnail_ready = pyqtSignal(str, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: dict[str, QPixmap] = {}
        self._in_progress: set[str] = set()
        self._icon_provider = QFileIconProvider()

    def get_thumbnail(self, path: str, size: int = THUMB_SIZE) -> QPixmap | None:
        """
        Returns cached pixmap immediately if available.
        If not, spawns a background worker and returns None (caller should
        connect to thumbnail_ready to refresh the view once it arrives).
        """
        if path in self._cache:
            return self._cache[path]

        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS and ext != PDF_EXT and ext not in OFFICE_EXTS:
            # Not a previewable type — return None, let delegate use system icon
            return None

        if path not in self._in_progress:
            self._in_progress.add(path)
            worker = _ThumbnailWorker(path, size, self)
            worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            worker.finished.connect(lambda p=path: self._in_progress.discard(p))
            worker.start()

        return None  # will call back via thumbnail_ready signal

    def _on_thumbnail_ready(self, path: str, pixmap: QPixmap):
        self._cache[path] = pixmap
        self._in_progress.discard(path)
        self.thumbnail_ready.emit(path, pixmap)

    def invalidate(self, path: str):
        self._cache.pop(path, None)

    def clear(self):
        self._cache.clear()
