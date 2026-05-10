import os
import fnmatch
from core.system_utils import path_exists_fast as _path_exists_fast
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, QPushButton,
    QStackedWidget, QMessageBox, QLabel, QFrame, QTreeView, QAbstractItemView,
    QHeaderView as _QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QDir, QThread, QSortFilterProxyModel, QTimer, QPoint, pyqtSlot, QDateTime, QDate
from PyQt6.QtGui import QFileSystemModel, QIcon, QStandardItemModel, QStandardItem

import shutil
from ui.widgets.file_tree_view import FileTreeView
from ui.widgets.file_list_view import FileListView
from ui.widgets.dialogs import SearchDialog
from ui.widgets.quick_look_delegate import QuickLookDelegate

from core.interfaces import IExplorerView
from ui.presenters.explorer_presenter import ExplorerPresenter, HOME_PATH
from ui.widgets.nav_panel import NavPanel


class DiskUsageWorker(QThread):
    """Background worker to fetch disk usage without blocking UI."""
    finished = pyqtSignal(str, float, float, float)  # path, total, used, free

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            total, used, free = shutil.disk_usage(self.path)
            self.finished.emit(self.path, total, used, free)
        except:
            pass


class _DirScanWorker(QThread):
    """背景掃描指定目錄，統計符合 filter_text 的檔案數量。"""
    result_ready = pyqtSignal(str, int)  # (dir_path, matched_count)

    def __init__(self, dir_path: str, filter_text: str, is_wildcard: bool,
                 max_depth: int = 0, min_bytes: int = 0,
                 date_filter_days: int = 0, parent=None):
        super().__init__(parent)
        self._dir_path = dir_path
        self._filter_text = filter_text.lower()
        self._is_wildcard = is_wildcard
        self._max_depth = max_depth
        self._min_bytes = min_bytes
        self._date_filter_days = date_filter_days
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import time
        from PyQt6.QtCore import QDirIterator, QDir, QDateTime, QDate
        flags = QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        it = QDirIterator(self._dir_path, flags, QDirIterator.IteratorFlag.Subdirectories)
        base_depth = self._dir_path.rstrip("/\\").count(os.sep)
        scanned = 0
        matched_count = 0
        try:
            while it.hasNext() and not self._cancelled:
                it.next()
                scanned += 1
                if scanned % 500 == 0:
                    time.sleep(0.001)
                if scanned > 5000:
                    break
                if self._max_depth > 0:
                    depth = it.filePath().rstrip("/\\").count(os.sep)
                    if depth > base_depth + self._max_depth:
                        continue
                # 名稱比對（只在有文字過濾時才檢查）
                if self._filter_text:
                    name = it.fileName().lower()
                    if self._is_wildcard:
                        if not fnmatch.fnmatch(name, self._filter_text):
                            continue
                    else:
                        if self._filter_text not in name:
                            continue
                # 大小過濾
                fi = it.fileInfo()
                if self._min_bytes > 0 and fi.size() < self._min_bytes:
                    continue
                # 時間過濾
                if self._date_filter_days > 0:
                    last_mod = fi.lastModified()
                    if self._date_filter_days == 1:
                        if last_mod.date() != QDate.currentDate():
                            continue
                    else:
                        if last_mod < QDateTime.currentDateTime().addDays(-self._date_filter_days):
                            continue
                matched_count += 1
        except Exception:
            pass
        if not self._cancelled:
            self.result_ready.emit(self._dir_path, matched_count)


class _FlatScanWorker(QThread):
    """背景遞迴掃描，以分批方式回報符合條件的檔案（Everything 平面列表用）。"""
    batch_ready = pyqtSignal(list)   # list of (name, full_path, size_bytes, date_str, dir_path)
    scan_done   = pyqtSignal(int)    # total_count

    def __init__(self, root: str, filter_text: str, is_wildcard: bool,
                 min_bytes: int = 0, date_filter_days: int = 0, parent=None):
        super().__init__(parent)
        self._root = root
        self._filter_text = filter_text.lower()
        self._is_wildcard = is_wildcard
        self._min_bytes = min_bytes
        self._date_filter_days = date_filter_days
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import time
        from PyQt6.QtCore import QDirIterator, QDir, QDateTime, QDate
        flags = QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        it = QDirIterator(self._root, flags, QDirIterator.IteratorFlag.Subdirectories)
        buffer: list = []
        total = 0
        last_emit = time.monotonic()
        try:
            while it.hasNext() and not self._cancelled:
                it.next()
                if self._filter_text:
                    name = it.fileName().lower()
                    matched = (fnmatch.fnmatch(name, self._filter_text)
                               if self._is_wildcard else self._filter_text in name)
                    if not matched:
                        continue
                fi = it.fileInfo()
                if self._min_bytes > 0 and fi.size() < self._min_bytes:
                    continue
                if self._date_filter_days > 0:
                    lm = fi.lastModified()
                    if self._date_filter_days == 1:
                        if lm.date() != QDate.currentDate():
                            continue
                    else:
                        if lm < QDateTime.currentDateTime().addDays(-self._date_filter_days):
                            continue
                buffer.append((it.fileName(), it.filePath(),
                               fi.size(),
                               fi.lastModified().toString("yyyy-MM-dd HH:mm"),
                               fi.absolutePath()))
                total += 1
                now = time.monotonic()
                if len(buffer) >= 50 or (now - last_emit) >= 0.1:
                    self.batch_ready.emit(list(buffer))
                    buffer.clear()
                    last_emit = now
                    time.sleep(0.001)
        except Exception:
            pass
        if buffer and not self._cancelled:
            self.batch_ready.emit(buffer)
        if not self._cancelled:
            self.scan_done.emit(total)


class FolderFilterProxyModel(QSortFilterProxyModel):
    """Custom proxy to ensure current root and ancestors are never filtered out."""
    file_count_changed = pyqtSignal(bool)        # is_scanning

    _MAX_SCAN_WORKERS = 6  # cap concurrent _DirScanWorker threads to avoid UI freeze

    def __init__(self, config_mgr=None, parent=None):
        self.config_mgr = config_mgr
        super().__init__(parent)
        self._current_root_path = ""
        self._filter_text = ""
        self._is_wildcard = False
        self._count_cache: dict[str, int | str] = {}
        self._sql_hits: set[str] = set()        # 全小寫正規化完整路徑
        self._sql_covered_prefix: str = ""       # 已索引的目錄前綴（小寫正規化）
        self._sql_active: bool = False           # SQL 結果是否已就緒
        self._sql_trusted: bool = False          # 路徑是否在 monitored_paths 內（完全信任 SQL）
        self._max_scan_depth: int = 0            # 0 = 無限制；>0 = 限制 QDirIterator 深度
        self._scanning_dirs: set[str] = set()   # 正在背景掃描中的目錄路徑
        self._scan_workers: dict[str, _DirScanWorker] = {}  # 路徑 → Worker
        self._scan_queue: list[str] = []         # pending dirs waiting for a free worker slot
        self._active_scan_count: int = 0         # number of currently running workers
        self._size_filter_bytes: int = 0        # 0 = 不過濾；>0 = 最小位元組數
        self._date_filter_days: int = 0         # 0 = 不過濾；1 = 今日；7 = 本週；30 = 本月

    def set_size_filter(self, min_bytes: int) -> None:
        self._size_filter_bytes = min_bytes
        self.cancel_all_scans()
        self._count_cache.clear()
        self.invalidateFilter()

    def set_date_filter(self, days: int) -> None:
        self._date_filter_days = days
        self.cancel_all_scans()
        self._count_cache.clear()
        self.invalidateFilter()

    def set_root_path(self, path):
        # 強制轉為 Qt 慣用的正斜線，避免與 model.filePath() 比對失敗
        self._current_root_path = os.path.normpath(
            path).replace('\\', '/').lower()
        self.invalidateFilter()

    def setFilterFixedString(self, string):
        self.cancel_all_scans()
        self._filter_text = string
        self._is_wildcard = False
        self._count_cache.clear()
        self.invalidateFilter()  # 避免 modelReset，只發送 layoutChanged 讓 persistent index 存活

    def setFilterWildcard(self, string):
        self.cancel_all_scans()
        self._filter_text = string
        self._is_wildcard = True
        self._count_cache.clear()
        self.invalidateFilter()

    def cancel_all_scans(self) -> None:
        """取消所有進行中的背景掃描 Worker，並重置計數。"""
        for w in self._scan_workers.values():
            try:
                w.result_ready.disconnect(self._on_scan_result)
            except RuntimeError:
                pass  # 已斷開則忽略
            w.cancel()
            # 讓 Qt 在執行緒自然結束後釋放 C++ 物件，避免 "Destroyed while running"
            w.finished.connect(w.deleteLater)
        self._scan_workers.clear()
        self._scanning_dirs.clear()
        self._scan_queue.clear()
        self._active_scan_count = 0

    def _on_scan_result(self, dir_path: str, matched_count: int) -> None:
        """Worker 掃描完成回呼：更新快取、累計計數、條件式重繪。"""
        self._scanning_dirs.discard(dir_path)
        self._scan_workers.pop(dir_path, None)
        self._active_scan_count -= 1
        has_match = matched_count > 0
        cache_key = (f"{dir_path}::{self._filter_text}::{self._is_wildcard}"
                     f"::{self._max_scan_depth}::{self._size_filter_bytes}::{self._date_filter_days}")
        self._count_cache[cache_key] = has_match
        is_scanning = len(self._scanning_dirs) > 0 or bool(self._scan_queue)
        self.file_count_changed.emit(is_scanning)
        # 條件式重繪：只有「樂觀放行」翻盤成「確定無匹配」時才觸發重繪
        # has_match=True 時，資料夾本就顯示中，無需重繪避免閃爍
        if not has_match:
            self.invalidateFilter()
        # Drain the queue: start next pending worker if a slot is now free
        self._drain_scan_queue()

    def set_sql_hits(self, hits: set[str], covered_prefix: str, trusted: bool = False, max_depth: int = 0) -> None:
        self._sql_hits = hits
        self._sql_covered_prefix = os.path.normpath(
            covered_prefix).lower() if covered_prefix else ""
        self._sql_active = bool(hits) or bool(covered_prefix)
        self._sql_trusted = trusted
        self._max_scan_depth = max_depth
        self._count_cache.clear()
        self.invalidateFilter()

    def _drain_scan_queue(self) -> None:
        """Start queued _DirScanWorkers up to _MAX_SCAN_WORKERS at a time."""
        while self._scan_queue and self._active_scan_count < self._MAX_SCAN_WORKERS:
            dir_path = self._scan_queue.pop(0)
            if dir_path not in self._scanning_dirs:
                continue  # was cancelled/cleared while waiting
            self._active_scan_count += 1
            w = _DirScanWorker(dir_path, self._filter_text, self._is_wildcard,
                               self._max_scan_depth, self._size_filter_bytes,
                               self._date_filter_days, parent=self)
            w.result_ready.connect(self._on_scan_result)
            w.finished.connect(w.deleteLater)
            self._scan_workers[dir_path] = w
            w.start()

    def _has_matching_file(self, dir_path: str) -> bool:
        """非同步版：先樂觀放行，背景 Worker 掃完後再 invalidateFilter 修正。"""
        cache_key = (f"{dir_path}::{self._filter_text}::{self._is_wildcard}"
                     f"::{self._max_scan_depth}::{self._size_filter_bytes}::{self._date_filter_days}")
        # 1. 快取命中 → O(1) 直接回傳
        if cache_key in self._count_cache:
            return self._count_cache[cache_key]
        # 2. 正在掃描中或已排隊 → 樂觀放行（保持資料夾可見）
        if dir_path in self._scanning_dirs:
            return True
        # 3. 排入 queue，受 _MAX_SCAN_WORKERS 限制後再啟動
        self._scanning_dirs.add(dir_path)
        self._scan_queue.append(dir_path)
        self._drain_scan_queue()
        return True  # 樂觀放行，掃完後觸發 invalidateFilter 修正

    def filterAcceptsRow(self, source_row, source_parent):
        has_text = bool(self._filter_text)
        has_size = self._size_filter_bytes > 0
        has_date = self._date_filter_days > 0

        if not has_text and not has_size and not has_date:
            return True

        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        is_dir = model.isDir(idx)

        # ── 大小 / 時間過濾：只對檔案生效，資料夾永遠放行 ─────────
        if not is_dir:
            if has_size and model.size(idx) < self._size_filter_bytes:
                return False
            if has_date:
                last_mod = model.fileInfo(idx).lastModified()
                if self._date_filter_days == 1:
                    if last_mod.date() != QDate.currentDate():
                        return False
                else:
                    cutoff = QDateTime.currentDateTime().addDays(-self._date_filter_days)
                    if last_mod < cutoff:
                        return False
        # ────────────────────────────────────────────────────────────

        if not has_text:
            if not is_dir:
                return True  # 檔案已通過屬性檢查
            # 有屬性過濾但無文字 → 資料夾遞迴掃描，行為與文字過濾一致
            if self._current_root_path:
                path = model.filePath(idx).replace('\\', '/').lower()
                if self._current_root_path.startswith(path):
                    return True  # 祖先保護
                if path.startswith(self._current_root_path):
                    return self._has_matching_file(model.filePath(idx))
            return True

        # ── SQL 快速路徑 ──────────────────────────────────────────
        if self._sql_active and self._sql_covered_prefix:
            filepath = os.path.normpath(model.filePath(idx)).lower()
            if filepath.startswith(self._sql_covered_prefix):
                if filepath in self._sql_hits:
                    return True   # SQL Hit: 直接通過
                if self._sql_trusted and not is_dir:
                    return False  # trusted 模式：確定是非命中的檔案，O(1) 拒絕
        # ─────────────────────────────────────────────────────────

        # 取檔名做忽略大小寫比對
        filename = model.fileName(idx)
        name_lower = filename.lower()
        filter_lower = self._filter_text.lower()

        is_match = (
            fnmatch.fnmatch(name_lower, filter_lower)
            if self._is_wildcard else filter_lower in name_lower
        )

        if is_match:
            return True

        # 若檔名不符合，針對資料夾進行額外保護
        if not is_dir:
            return False

        if self._current_root_path:
            # model.filePath() 一律返回正斜線分隔的路徑
            path = model.filePath(idx).replace('\\', '/').lower()

            # 1. 保護祖先資料夾 (防止 TreeView 崩潰)
            if self._current_root_path.startswith(path):
                return True

            # 2. 保護子代資料夾 (確保搜尋時能保留下層目錄結構，以利主動向下展開尋找)
            if path.startswith(self._current_root_path):
                if self._has_matching_file(model.filePath(idx)):
                    return True
                return False

        return False

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            source_index = self.mapToSource(index)
            model = self.sourceModel()
            col = index.column()

            # Column 2 — Type: show clean extension instead of MIME string
            if col == 2:
                fi = model.fileInfo(source_index)
                _mgr = getattr(self, "config_mgr", None)
                if fi.isDir():
                    return _mgr.get_text("ui_pane_type_folder", "資料夾") if _mgr else "資料夾"
                ext = fi.suffix().upper()
                if _mgr:
                    return _mgr.get_text("ui_pane_type_ext_file", "{} 檔案").format(ext) if ext else _mgr.get_text("ui_pane_type_file", "檔案")
                return f"{ext} 檔案" if ext else "檔案"

            # Column 1 — Size: folders will leave blank to avoid synchronous os.scandir UI freeze
            if col == 1:
                fi = model.fileInfo(source_index)
                if fi.isDir():
                    return ""

            # Column 3 — Date: format as yyyy-MM-dd HH:mm
            if col == 3:
                if hasattr(model, 'lastModified'):
                    dt = model.lastModified(source_index)
                    if dt.isValid():
                        return dt.toString("yyyy-MM-dd HH:mm")

        return super().data(index, role)

    def lessThan(self, left, right):
        if not left.isValid() or not right.isValid():
            return super().lessThan(left, right)

        model = self.sourceModel()

        # ── 資料夾優先排序 (Folders First) ──
        # 模擬 Windows 檔案總管：資料夾永遠成組排在最前面
        lp_is_dir = model.isDir(left)
        rp_is_dir = model.isDir(right)

        if lp_is_dir != rp_is_dir:
            # 如果一个是文件夹另一个不是，则依当前排序方向让文件夹排在前面
            if self.sortOrder() == Qt.SortOrder.AscendingOrder:
                return lp_is_dir
            else:
                return rp_is_dir
        # ────────────────────────────────────

        col = left.column()

        if col == 3:
            if hasattr(model, 'lastModified'):
                return model.lastModified(left) < model.lastModified(right)
        elif col == 1:
            if hasattr(model, 'size'):
                return model.size(left) < model.size(right)
        elif col == 2:
            l_ext = model.fileInfo(left).suffix().lower()
            r_ext = model.fileInfo(right).suffix().lower()
            return l_ext < r_ext

        return super().lessThan(left, right)


class _ExplorerViewAdapter(IExplorerView):
    """Adapter bridging pure Presenter logic to PyQt specific widgets without QThread/ABC metaclass conflicts."""

    def __init__(self, pane): self.pane = pane

    def get_current_path(self) -> str:
        return self.pane._current_path

    def set_display_path(
        self, path): self.pane._internal_set_display_path(path)

    def get_selected_paths(self): return self.pane._get_selected_paths()
    def get_selected_total_size(self): return self.pane._get_selected_size()
    def get_selected_count(self): return self.pane._get_selected_count()
    def set_back_enabled(self, enabled): self.pane.back_btn.setEnabled(enabled)

    def set_forward_enabled(
        self, enabled): self.pane.forward_btn.setEnabled(enabled)

    def show_error(self, message):
        title = self.pane.config_mgr.get_text("ui_pane_dialog_error", "錯誤") if self.pane.config_mgr else "錯誤"
        QMessageBox.critical(self.pane, title, message)

    def confirm_action(self, message):
        title = self.pane.config_mgr.get_text("ui_pane_dialog_confirm", "確認") if self.pane.config_mgr else "確認"
        return QMessageBox.question(self.pane, title, message) == QMessageBox.StandardButton.Yes

    def show_confirm_dialog(self, title, message):
        return self.pane.show_confirm_dialog(title, message)

    def update_status(self, message): self.pane.status_updated.emit(message)

    def update_disk_usage(self, free_gb):
        tpl = self.pane.config_mgr.get_text("ui_pane_status_disk_usage", "{:.1f} GB 剩餘 / {:.1f} GB 總計") if self.pane.config_mgr else "{:.1f} GB 剩餘 / {:.1f} GB 總計"
        self.pane.status_updated.emit(tpl.format(free_gb, free_gb))

    def notify_operation_finished(
        self): self.pane.file_operation_finished.emit()

    def open_system_file(self, path):
        try:
            cwd = os.path.dirname(path) if os.path.isfile(path) else path
            # 使用 cwd 參數可以確保開啟的程式（如 exe/捷徑）的「工作目錄」正確指向它所在的資料夾，
            # 避免它錯誤地使用雙視窗檔案總管的目錄作為工作目錄。
            import sys
            if sys.version_info >= (3, 10):
                os.startfile(path, "open", cwd=cwd)
            else:
                os.startfile(path, "open")
        except OSError as e:
            # 1223 = user cancelled the UAC/security prompt
            if getattr(e, 'winerror', None) != 1223:
                self.pane.status_updated.emit(f"無法開啟檔案: {e}")

    def focus_item(self, path): self.pane._internal_focus_item(path)
    def trigger_background_disk_usage(self): self.pane._trigger_disk_usage()

    def clipboard_has_urls(self):
        from PyQt6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        return cb.mimeData().hasUrls()

    def clipboard_has_image(self):
        from PyQt6.QtWidgets import QApplication
        return QApplication.clipboard().mimeData().hasImage()

    def clipboard_has_text(self):
        from PyQt6.QtWidgets import QApplication
        return QApplication.clipboard().mimeData().hasText()

    def get_clipboard_text(self):
        from PyQt6.QtWidgets import QApplication
        return QApplication.clipboard().text()

    def save_clipboard_image(self, path):
        from PyQt6.QtWidgets import QApplication
        img = QApplication.clipboard().image()
        if not img.isNull():
            return img.save(path, "PNG")
        return False


class ExplorerPane(QWidget):
    """A single file explorer pane with a path bar and file view. Refactored into pure View adapter."""
    path_changed = pyqtSignal(str)
    focused = pyqtSignal(object)
    status_updated = pyqtSignal(str)
    file_operation_finished = pyqtSignal()
    # emits single-file path for preview panel
    file_selected = pyqtSignal(str)
    close_preview_requested = pyqtSignal()
    home_requested = pyqtSignal()
    custom_paths_requested = pyqtSignal(QPoint)

    def __init__(self, initial_path=None, config_mgr=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.initial_path = initial_path or QDir.homePath()
        self.config_mgr = config_mgr

        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        self.model.setReadOnly(False)
        self.model.setResolveSymlinks(False)
        self.model.fileRenamed.connect(self._on_file_renamed)

        # 覆寫英文表頭為繁體中文
        self.model.setHeaderData(0, Qt.Orientation.Horizontal, self.config_mgr.get_text("ui_pane_header_name", "名稱") if self.config_mgr else "名稱")
        self.model.setHeaderData(1, Qt.Orientation.Horizontal, self.config_mgr.get_text("ui_pane_header_size", "大小") if self.config_mgr else "大小")
        self.model.setHeaderData(2, Qt.Orientation.Horizontal, self.config_mgr.get_text("ui_pane_header_type", "類型") if self.config_mgr else "類型")
        self.model.setHeaderData(3, Qt.Orientation.Horizontal, self.config_mgr.get_text("ui_pane_header_date", "修改日期") if self.config_mgr else "修改日期")

        self.usage_worker = None

        self.proxy_model = FolderFilterProxyModel(config_mgr=self.config_mgr)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self.proxy_model.setRecursiveFilteringEnabled(True)  # 遞迴過濾子資料夾
        self.proxy_model.setDynamicSortFilter(True)  # 允許排序

        self.list_proxy = FolderFilterProxyModel(config_mgr=self.config_mgr)
        self.list_proxy.setSourceModel(self.model)
        self.list_proxy.setFilterCaseSensitivity(
            Qt.CaseSensitivity.CaseInsensitive)
        self.list_proxy.setDynamicSortFilter(True)

        self._current_path: str = initial_path or ""
        self._current_mode: str = "details"
        self.presenter = ExplorerPresenter(
            _ExplorerViewAdapter(self), self.config_mgr)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(1)

        nav_layout = QHBoxLayout()

        self.back_btn = QToolButton()
        self.back_btn.setObjectName("backBtn")
        self.back_btn.setEnabled(False)
        self.back_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_back", "上一頁") if self.config_mgr else "上一頁")
        self.back_btn.clicked.connect(self.go_back)

        self.forward_btn = QToolButton()
        self.forward_btn.setObjectName("forwardBtn")
        self.forward_btn.setEnabled(False)
        self.forward_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_forward", "下一頁") if self.config_mgr else "下一頁")
        self.forward_btn.clicked.connect(self.go_forward)

        self.up_btn = QToolButton()
        self.up_btn.setObjectName("upBtn")
        self.up_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_up", "上一層") if self.config_mgr else "上一層")
        self.up_btn.clicked.connect(self.go_up)

        self.home_btn = QToolButton()
        self.home_btn.setObjectName("paneHomeBtn")
        self.home_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_home", "回到首頁") if self.config_mgr else "回到首頁")
        self.home_btn.clicked.connect(self.home_requested.emit)

        self.path_edit = QLineEdit(self.initial_path)
        self.path_edit.returnPressed.connect(self.on_path_entered)
        self.path_edit.installEventFilter(self)

        self.custom_paths_btn = QToolButton()
        self.custom_paths_btn.setObjectName("paneCustomPathsBtn")
        self.custom_paths_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_bookmarks", "我的最愛") if self.config_mgr else "我的最愛")
        self.custom_paths_btn.clicked.connect(
            lambda: self.custom_paths_requested.emit(
                self.custom_paths_btn.mapToGlobal(
                    self.custom_paths_btn.rect().bottomLeft())
            )
        )

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("searchEdit")
        self.search_edit.setPlaceholderText(self.config_mgr.get_text("ui_pane_search_placeholder", "搜尋...") if self.config_mgr else "搜尋...")
        self.search_edit.setFixedWidth(150)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.addAction(QIcon(self.config_mgr.get_ui_resource_path(
            "search")), QLineEdit.ActionPosition.LeadingPosition)
        self.search_edit.textChanged.connect(self.on_search_changed)

        self.adv_search_btn = QToolButton()
        self.adv_search_btn.setObjectName("advSearchBtn")
        self.adv_search_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_adv_search", "進階尋找") if self.config_mgr else "進階尋找")
        self.adv_search_btn.setIcon(QIcon(self.config_mgr.get_ui_resource_path("filter")))
        self.adv_search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.adv_search_btn.setCheckable(True)
        self.adv_search_btn.clicked.connect(self._toggle_filter_drawer)

        # 當使用者手動編輯網址列時，也同步清空搜尋列
        self.path_edit.textEdited.connect(self.search_edit.clear)

        self.list_view_btn = QToolButton()
        self.list_view_btn.setObjectName("listViewBtn")
        self.list_view_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_list_view", "詳細列表") if self.config_mgr else "詳細列表")
        self.list_view_btn.clicked.connect(
            lambda: self.set_view_mode("details"))

        self.grid_view_btn = QToolButton()
        self.grid_view_btn.setObjectName("gridViewBtn")
        self.grid_view_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_grid_view", "圖示模式") if self.config_mgr else "圖示模式")
        self.grid_view_btn.clicked.connect(lambda: self.set_view_mode("icons"))

        self.close_preview_btn = QToolButton()
        self.close_preview_btn.setText(self.config_mgr.get_text("ui_pane_btn_close_preview", "✕ 關閉預覽") if self.config_mgr else "✕ 關閉預覽")
        self.close_preview_btn.setObjectName("closePreviewBtn")
        self.close_preview_btn.setVisible(False)
        self.close_preview_btn.clicked.connect(
            self.close_preview_requested.emit)

        self.quality_toggle_btn = QToolButton()
        self.quality_toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.quality_toggle_btn.setObjectName("qualityToggleBtn")
        self.quality_toggle_btn.setToolTip("切換 PDF 預覽畫質 (SD / HD)")
        self.quality_toggle_btn.setVisible(False)
        self.quality_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_quality_btn("SD") # 初始化

        self.quality_separator = QFrame()
        self.quality_separator.setFrameShape(QFrame.Shape.VLine)
        self.quality_separator.setFrameShadow(QFrame.Shadow.Plain)
        self.quality_separator.setObjectName("qualitySeparator")
        self.quality_separator.setVisible(False)

        nav_layout.addWidget(self.back_btn)
        nav_layout.addWidget(self.forward_btn)
        nav_layout.addWidget(self.up_btn)
        nav_layout.addWidget(self.home_btn)
        nav_layout.addWidget(self.custom_paths_btn)
        nav_layout.addWidget(self.path_edit)
        nav_layout.addWidget(self.search_edit)
        nav_layout.addWidget(self.adv_search_btn)
        nav_layout.addWidget(self.list_view_btn)
        nav_layout.addWidget(self.grid_view_btn)
        nav_layout.addWidget(self.quality_toggle_btn)
        nav_layout.addWidget(self.quality_separator)
        nav_layout.addWidget(self.close_preview_btn)

        layout.addLayout(nav_layout)

        # ── 過濾抽屜 (Filter Drawer) ─────────────────────────────
        _SIZE_FILTERS = [("全部", 0), (">1 MB", 1 << 20), (">10 MB", 10 << 20), (">100 MB", 100 << 20)]
        _DATE_FILTERS = [("全部", 0), ("今日", 1), ("本週", 7), ("本月", 30)]

        self._filter_drawer = QFrame()
        self._filter_drawer.setObjectName("filterDrawer")
        self._filter_drawer.setVisible(False)
        _dl = QVBoxLayout(self._filter_drawer)
        _dl.setContentsMargins(6, 4, 6, 4)
        _dl.setSpacing(4)

        _size_row = QHBoxLayout()
        _size_row.setSpacing(4)
        _size_row.addWidget(QLabel("大小:"))
        self._size_btns: list[QPushButton] = []
        self._size_values = [v for _, v in _SIZE_FILTERS]
        for label, val in _SIZE_FILTERS:
            btn = QPushButton(label)
            btn.setObjectName("filterChipBtn")
            btn.setCheckable(True)
            btn.setChecked(val == 0)
            btn.clicked.connect(lambda _, v=val: self._on_size_filter(v))
            self._size_btns.append(btn)
            _size_row.addWidget(btn)
        _size_row.addStretch()
        _dl.addLayout(_size_row)

        _date_row = QHBoxLayout()
        _date_row.setSpacing(4)
        _date_row.addWidget(QLabel("時間:"))
        self._date_btns: list[QPushButton] = []
        self._date_values = [v for _, v in _DATE_FILTERS]
        for label, val in _DATE_FILTERS:
            btn = QPushButton(label)
            btn.setObjectName("filterChipBtn")
            btn.setCheckable(True)
            btn.setChecked(val == 0)
            btn.clicked.connect(lambda _, v=val: self._on_date_filter(v))
            self._date_btns.append(btn)
            _date_row.addWidget(btn)
        _date_row.addStretch()
        _dl.addLayout(_date_row)

        layout.addWidget(self._filter_drawer)
        # ────────────────────────────────────────────────────────

        self._search_status_label = QLabel("")
        self._search_status_label.setObjectName("searchStatusLabel")
        self._search_status_label.setVisible(False)
        self._search_status_label.setWordWrap(True)
        layout.addWidget(self._search_status_label)

        self.view_stack = QStackedWidget()
        self.proxy_model.set_root_path(self.initial_path)
        self.list_proxy.set_root_path(self.initial_path)

        self.tree = FileTreeView(config_mgr=self.config_mgr)
        delegate = QuickLookDelegate(self.config_mgr, self.tree)
        delegate.preview_requested.connect(self.tree._trigger_preview)
        self.tree.setItemDelegateForColumn(0, delegate)
        self.tree.setMouseTracking(True)
        self.tree.setModel(self.proxy_model)
        self.tree.setRootIndex(self.proxy_model.mapFromSource(
            self.model.index(self.initial_path)))
        self.tree._current_path = self.initial_path

        self.list_view = FileListView()
        self.list_view.set_config_mgr(self.config_mgr)
        self.list_view.setModel(self.list_proxy)
        self.list_view.setRootIndex(self.list_proxy.mapFromSource(
            self.model.index(self.initial_path)))
        self.list_view._current_path = self.initial_path

        self.tree.setSortingEnabled(True)
        for v in [self.tree, self.list_view]:
            v.clicked.connect(lambda: self.focused.emit(self))
            v.doubleClicked.connect(self.on_item_double_clicked)
            v.file_operation_finished.connect(
                self.file_operation_finished.emit)
            v.selectionModel().selectionChanged.connect(self.update_status_info)
            v.installEventFilter(self)
            v.viewport().installEventFilter(self)
            self.view_stack.addWidget(v)

        self.home_view = NavPanel(
            on_navigate=lambda path: self.presenter.navigate_to(path),
            config_mgr=self.config_mgr,
        )
        self.home_view.clicked.connect(lambda: self.focused.emit(self))
        self.view_stack.addWidget(self.home_view)

        # ── Everything 平面搜尋結果視圖 ─────────────────────────────
        self.flat_model = QStandardItemModel()
        self.flat_model.setHorizontalHeaderLabels(["名稱", "大小", "修改日期", "所在路徑"])
        self.flat_view = QTreeView()
        self.flat_view.setModel(self.flat_model)
        self.flat_view.setRootIsDecorated(False)
        self.flat_view.setSortingEnabled(True)
        self.flat_view.setObjectName("flatResultView")
        self.flat_view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.flat_view.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.flat_view.setAlternatingRowColors(True)
        self.flat_view.clicked.connect(lambda: self.focused.emit(self))
        self.flat_view.doubleClicked.connect(self._on_flat_double_clicked)
        self.flat_view.header().setStretchLastSection(True)
        self.view_stack.addWidget(self.flat_view)
        self.flat_view.selectionModel().selectionChanged.connect(self.update_status_info)
        self.flat_view.installEventFilter(self)
        self.flat_view.viewport().installEventFilter(self)
        self.flat_view.setMouseTracking(True)
        flat_delegate = QuickLookDelegate(self.config_mgr, self.flat_view)
        flat_delegate.preview_requested.connect(self._flat_trigger_preview)
        self.flat_view.setItemDelegateForColumn(0, flat_delegate)
        QTimer.singleShot(0, lambda: (
            self.flat_view.setColumnWidth(0, 280),
            self.flat_view.setColumnWidth(1, 90),
            self.flat_view.setColumnWidth(2, 150),
        ))
        self._flat_worker: _FlatScanWorker | None = None
        self._current_size_filter: int = 0
        self._current_date_filter: int = 0
        # ────────────────────────────────────────────────────────────

        from PyQt6.QtWidgets import QHeaderView
        header = self.tree.header()
        header.setSectionsMovable(True)  # 允許欄位左右移動位置
        header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)  # 改為可互動調整，不再固定延伸
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)

        self.tree.setColumnWidth(0, 320)  # 設定名稱欄初始寬度
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 100)
        self.tree.setColumnWidth(3, 140)

        # QFileSystemModel 非同步載入子目錄內容時觸發 directoryLoaded，導致 rootIndex 失效
        # 連接此信號以在每次非同步載入完成後還原 rootIndex
        self.model.directoryLoaded.connect(
            lambda _: QTimer.singleShot(0, self._restore_root_from_path))

        # debounce timer：篩選變更後 50ms 還原 rootIndex（處理 layoutChanged）
        self._root_restore_timer = QTimer()
        self._root_restore_timer.setSingleShot(True)
        self._root_restore_timer.timeout.connect(self._restore_root_from_path)

        # SQL 輔助過濾 debounce timer（200ms）
        self._sql_timer = QTimer()
        self._sql_timer.setSingleShot(True)
        self._sql_timer.setInterval(200)
        self._sql_timer.timeout.connect(self._run_sql_filter)
        self._index_manager = None  # 由外部注入

        layout.addWidget(self.view_stack)

        # 確保初始狀態的按鈕文字與顯示模式正確同步
        self.set_view_mode(self._current_mode)

    def set_preview_mode(self, active: bool, is_pdf: bool = False) -> None:
        """Show/hide the [X] close preview button and guard enterEvent focus-steal."""
        self.close_preview_btn.setVisible(active)
        if active and is_pdf:
            self.quality_toggle_btn.setVisible(True)
            self.quality_separator.setVisible(True)
        else:
            self.quality_toggle_btn.setVisible(False)
            self.quality_separator.setVisible(False)
        
        self._in_preview_mode = active

        # UI optimization: Hide general navigation widgets during preview
        self.back_btn.setVisible(not active)
        self.forward_btn.setVisible(not active)
        self.up_btn.setVisible(not active)
        self.home_btn.setVisible(not active)
        self.custom_paths_btn.setVisible(not active)
        self.search_edit.setVisible(not active)
        self.adv_search_btn.setVisible(not active)
        self.list_view_btn.setVisible(not active)
        self.grid_view_btn.setVisible(not active)

        # Center the path edit text to look like a title and disable editing
        if active:
            # We don't overwrite stylesheet permanently, so we'll just set alignment and readonly
            self.path_edit.setReadOnly(True)
            self.path_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            self.path_edit.setReadOnly(False)
            self.path_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)

    def set_previewing_path(self, path: str) -> None:
        """Update the delegate's active preview path state for icon toggling."""
        delegate = self.tree.itemDelegateForColumn(0)
        if hasattr(delegate, 'active_preview_path'):
            delegate.active_preview_path = path

        delegate_list = self.list_view.itemDelegate()
        if hasattr(delegate_list, 'active_preview_path'):
            delegate_list.active_preview_path = path

        flat_delegate = self.flat_view.itemDelegateForColumn(0)
        if hasattr(flat_delegate, 'active_preview_path'):
            flat_delegate.active_preview_path = path

        self.tree.viewport().update()
        self.list_view.viewport().update()
        self.flat_view.viewport().update()

    def _flat_trigger_preview(self, path: str) -> None:
        win = self.window()
        if hasattr(win, "toggle_inline_preview"):
            win.toggle_inline_preview(path)

    def closeEvent(self, event):
        if self.usage_worker and self.usage_worker.isRunning():
            self.usage_worker.terminate()
            self.usage_worker.wait()
        super().closeEvent(event)

    def enterEvent(self, event):
        """Focus follows mouse: automatically activate pane when mouse enters."""
        if getattr(self, '_in_preview_mode', False):
            return
        super().enterEvent(event)
        self.focused.emit(self)

        # 為了讓鍵盤快捷鍵(Del, F2等)能無縫銜接，自動將鍵盤焦點移交給檔案列表
        # 但若使用者正在輸入路徑或搜尋(焦點在 QLineEdit)，則不搶奪焦點
        from PyQt6.QtWidgets import QLineEdit
        focus_widget = self.window().focusWidget()
        if not isinstance(focus_widget, QLineEdit):
            current_view = self.view_stack.currentWidget()
            if current_view:
                current_view.setFocus()

    def mousePressEvent(self, event):
        """Focus the pane on mouse click."""
        self.focused.emit(self)
        current_view = self.view_stack.currentWidget()
        if current_view:
            current_view.setFocus()
        super().mousePressEvent(event)

    def on_path_entered(self):
        self.presenter.navigate_to(self.path_edit.text())

    def set_path(self, path):
        # 對外介面: mainWindow 取用 set_path 來調度
        self.presenter.navigate_to(path)

    @pyqtSlot(str)
    def update_quality_btn(self, quality: str) -> None:
        if quality == "HD":
            self.quality_toggle_btn.setText(" 高畫質 (HD)")
        else:
            self.quality_toggle_btn.setText(" 流暢 (SD)")
        
        self.quality_toggle_btn.setProperty("quality", quality)
        self.quality_toggle_btn.style().unpolish(self.quality_toggle_btn)
        self.quality_toggle_btn.style().polish(self.quality_toggle_btn)

    def _internal_set_display_path(self, path: str) -> None:
        self._current_path = path

        # 導覽時自動清空搜尋列，避免畫面卡在先前的搜尋結果中
        if self.search_edit.text():
            self.search_edit.clear()

        if path == HOME_PATH:
            self.view_stack.setCurrentWidget(self.home_view)
            self.path_edit.setText("")
            self.path_changed.emit(path)
            return

        self.proxy_model.set_root_path(path)
        self.list_proxy.set_root_path(path)
        idx = self.model.index(path)
        self.tree.setRootIndex(self.proxy_model.mapFromSource(idx))
        self.list_view.setRootIndex(self.list_proxy.mapFromSource(idx))
        self.tree._current_path = path
        self.list_view._current_path = path
        if self.view_stack.currentWidget() == self.home_view:
            self.set_view_mode(self._current_mode)
        self.path_edit.setText(path)
        self.path_changed.emit(path)
        # 若屬性過濾仍啟用（無文字但有大小/時間），重新用新路徑觸發掃描
        if not self.search_edit.text() and (self._current_size_filter or self._current_date_filter):
            self._activate_search_mode()

    def go_back(self):
        self.presenter.go_back()

    def go_forward(self):
        self.presenter.go_forward()

    def go_up(self):
        self.presenter.go_up()

    def on_search_changed(self, text):
        if text:
            self._activate_search_mode()
        elif not self._current_size_filter and not self._current_date_filter:
            self._deactivate_search_mode()

    def _restore_root_from_path(self):
        text = self.search_edit.text()
        curr_path = self.path_edit.text()
        if curr_path and _path_exists_fast(curr_path):
            idx = self.model.index(curr_path)
            self.tree.setRootIndex(self.proxy_model.mapFromSource(idx))
            self.list_view.setRootIndex(self.list_proxy.mapFromSource(idx))

            # 根據是否有搜尋條件決定展開或收合樹狀結構
            if text:
                # SQL trusted 模式：filter 已透過祖先路徑處理可見性，跳過展開避免主執行緒阻塞
                # 非 trusted 模式：只展開前 2 層，避免 node_modules 等深層目錄一次 spawn 大量 Worker
                if not self.proxy_model._sql_trusted:
                    self.tree.expandToDepth(1)
                self._was_searching = True
            elif getattr(self, '_was_searching', False):
                self.tree.collapseAll()
                self._was_searching = False

    def set_index_manager(self, mgr) -> None:
        """注入 IndexManager 以啟用 SQL 輔助過濾。"""
        self._index_manager = mgr

    def _run_sql_filter(self) -> None:
        """Debounce 結束後執行 SQL 查詢，將命中路徑集合回寫至 proxy model。"""
        text = self.search_edit.text().strip()
        curr_path = self.path_edit.text().strip()
        if not text or not curr_path or not self._index_manager:
            return
        try:
            # 判定目前路徑是否在 monitored_paths 索引涵蓋範圍內
            config = self.config_mgr.load_config()
            monitored = config.get("monitored_paths", [])
            all_watched = [p for p in monitored if p]
            curr_norm = os.path.normpath(curr_path).lower()
            trusted = any(
                curr_norm.startswith(os.path.normpath(w).lower())
                for w in all_watched if w
            )

            results = self._index_manager.search(
                keyword=text, limit=5000, path_prefix=curr_path,
                use_local=True, use_network=False, use_personal=True
            )
            hits = {os.path.normpath(r[3]).lower() for r in results}
            file_count = len(hits)  # 純檔案數（尚未加入祖先資料夾）

            # 補上所有命中檔案的祖先資料夾，確保 trusted 模式下樹狀圖不全空
            curr_norm_prefix = os.path.normpath(curr_path).lower()
            ancestor_folders: set[str] = set()
            for hit in hits:
                p = hit
                while True:
                    parent = os.path.normpath(os.path.dirname(p))
                    if parent == p or not parent.lower().startswith(curr_norm_prefix):
                        break
                    ancestor_folders.add(parent.lower())
                    p = parent
            hits |= ancestor_folders

            for p in [self.proxy_model, self.list_proxy]:
                p.set_sql_hits(hits, curr_path, trusted=trusted)

            # 更新狀態標籤（SQL 模式：O(1) 純記憶體，不碰磁碟）
            found_tpl = self.config_mgr.get_text("ui_pane_search_found_count", "  找到 {} 個檔案") if self.config_mgr else "  找到 {} 個檔案"
            self._search_status_label.setText(found_tpl.format(file_count))
            self._search_status_label.setVisible(bool(text))
        except Exception:
            self._clear_sql_hits()

    def _count_proxy_files(self, parent=None) -> int:
        """從 proxy model 直接數可見檔案數（主執行緒，同步）。"""
        if parent is None:
            src_root = self.model.index(self._current_path)
            parent = self.proxy_model.mapFromSource(src_root)
            if not parent.isValid():
                return 0
        count = 0
        for row in range(self.proxy_model.rowCount(parent)):
            child = self.proxy_model.index(row, 0, parent)
            src = self.proxy_model.mapToSource(child)
            if self.model.isDir(src):
                count += self._count_proxy_files(child)
            else:
                count += 1
            if count > 9999:  # 防爆保護
                return count
        return count

    def _on_file_count_changed(self, is_scanning: bool) -> None:
        """背景掃描狀態更新 → 更新搜尋欄下方狀態標籤（計數來自 proxy 行數）。"""
        has_text = bool(self.search_edit.text().strip())
        has_attr = (self.proxy_model._size_filter_bytes > 0
                    or self.proxy_model._date_filter_days > 0)
        if not has_text and not has_attr:
            self._search_status_label.setVisible(False)
            return
        count = self._count_proxy_files()
        count_str = f"{count}+" if count > 9999 else str(count)
        is_trusted = getattr(self.proxy_model, '_sql_trusted', False)
        hint = "" if (is_trusted or not has_text) else (
            self.config_mgr.get_text("ui_pane_search_no_index_hint", "⚠️ 未建立索引，建議先使用進階搜尋。")
            if self.config_mgr else "⚠️ 未建立索引，建議先使用進階搜尋。"
        )
        scanning = (
            self.config_mgr.get_text("ui_pane_search_scanning", "（掃描中...）")
            if self.config_mgr else "（掃描中...）"
        ) if is_scanning else ""
        full_tpl = (
            self.config_mgr.get_text("ui_pane_search_status_full", "  {}找到 {} 個檔案{}")
            if self.config_mgr else "  {}找到 {} 個檔案{}"
        )
        self._search_status_label.setText(full_tpl.format(hint, count_str, scanning))
        self._search_status_label.setVisible(True)

    def _clear_sql_hits(self) -> None:
        self._search_status_label.setVisible(False)
        for p in [self.proxy_model, self.list_proxy]:
            p.set_sql_hits(set(), "")

    # ── Everything 平面搜尋模式 ──────────────────────────────────

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if n < 1024:
                return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TiB"

    def _activate_search_mode(self) -> None:
        text = self.search_edit.text().strip()
        is_wildcard = "*" in text or "?" in text

        if self._flat_worker:
            self._flat_worker.cancel()
            try:
                self._flat_worker.batch_ready.disconnect()
                self._flat_worker.scan_done.disconnect()
            except RuntimeError:
                pass
            self._flat_worker.finished.connect(self._flat_worker.deleteLater)
            self._flat_worker = None

        self.flat_model.removeRows(0, self.flat_model.rowCount())
        self.view_stack.setCurrentWidget(self.flat_view)
        self._search_status_label.setText("  掃描中...")
        self._search_status_label.setVisible(True)

        self._flat_worker = _FlatScanWorker(
            self._current_path, text, is_wildcard,
            self._current_size_filter, self._current_date_filter, parent=self
        )
        self._flat_worker.batch_ready.connect(self._on_flat_batch)
        self._flat_worker.scan_done.connect(self._on_flat_done)
        self._flat_worker.finished.connect(self._flat_worker.deleteLater)
        self._flat_worker.start()

    def _deactivate_search_mode(self) -> None:
        if self._flat_worker:
            self._flat_worker.cancel()
            try:
                self._flat_worker.batch_ready.disconnect()
                self._flat_worker.scan_done.disconnect()
            except RuntimeError:
                pass
            self._flat_worker.finished.connect(self._flat_worker.deleteLater)
            self._flat_worker = None
        self.flat_model.removeRows(0, self.flat_model.rowCount())
        self._search_status_label.setVisible(False)
        # 回到原始瀏覽視圖
        if self._current_mode == "icons":
            self.view_stack.setCurrentWidget(self.list_view)
        else:
            self.view_stack.setCurrentWidget(self.tree)

    def _on_flat_batch(self, items: list) -> None:
        for name, full_path, size_bytes, date_str, dir_path in items:
            name_item = QStandardItem(name)
            name_item.setData(full_path, Qt.ItemDataRole.UserRole)
            size_item = QStandardItem(self._fmt_size(size_bytes))
            size_item.setData(size_bytes, Qt.ItemDataRole.UserRole)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            date_item = QStandardItem(date_str)
            loc_item  = QStandardItem(dir_path)
            self.flat_model.appendRow([name_item, size_item, date_item, loc_item])
        count = self.flat_model.rowCount()
        self._search_status_label.setText(f"  找到 {count} 個檔案（掃描中...）")

    def _on_flat_done(self, total: int) -> None:
        self._search_status_label.setText(f"  找到 {total} 個檔案")
        self._flat_worker = None

    def _on_flat_double_clicked(self, index) -> None:
        full_path = self.flat_model.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
        if full_path and os.path.isfile(full_path):
            import subprocess
            try:
                os.startfile(full_path)
            except Exception:
                subprocess.Popen(["explorer", "/select,", full_path])

    # ─────────────────────────────────────────────────────────────

    def _file_view(self):
        """回傳當前實際的檔案視圖（tree、list_view 或 flat_view），home_view 時退回 tree。"""
        w = self.view_stack.currentWidget()
        if w is self.flat_view:
            return self.flat_view
        return self.list_view if w is self.list_view else self.tree

    def _toggle_filter_drawer(self) -> None:
        visible = not self._filter_drawer.isVisible()
        self._filter_drawer.setVisible(visible)
        self.adv_search_btn.setChecked(visible)
        if not visible:
            self._on_size_filter(0)
            self._on_date_filter(0)

    def _on_size_filter(self, val: int) -> None:
        for btn, v in zip(self._size_btns, self._size_values):
            btn.setChecked(v == val)
        self._current_size_filter = val
        self._refresh_search_mode()

    def _on_date_filter(self, val: int) -> None:
        for btn, v in zip(self._date_btns, self._date_values):
            btn.setChecked(v == val)
        self._current_date_filter = val
        self._refresh_search_mode()

    def _refresh_search_mode(self) -> None:
        if self.search_edit.text() or self._current_size_filter or self._current_date_filter:
            self._activate_search_mode()
        else:
            self._deactivate_search_mode()

    def open_advanced_search(self):
        from ui.widgets.dialogs import SearchDialog
        SearchDialog(self.model.rootPath(),
                     self.config_mgr, self).showMaximized()

    def _is_search_active(self) -> bool:
        """判斷目前是否處於搜尋狀態 (包含關鍵字或進階篩選)。"""
        return bool(
            self.search_edit.text()
            or getattr(self, '_current_size_filter', None)
            or getattr(self, '_current_date_filter', None)
        )

    def set_view_mode(self, mode):
        # 1. 永遠記錄使用者的視圖偏好
        self._current_mode = mode

        # 2. 只有在「非搜尋狀態」下，才實際切換底層的視圖元件
        if not self._is_search_active():
            if mode == "details":
                self.view_stack.setCurrentWidget(self.tree)
                self.tree.header().setVisible(True)
                for i in range(1, self.model.columnCount()):
                    self.tree.setColumnHidden(i, False)
            else:  # icons
                self.list_view.set_display_mode("icons")
                self.view_stack.setCurrentWidget(self.list_view)

        # 3. 永遠更新 UI 按鈕的視覺高亮狀態 (即使在搜尋中也要給予回饋)
        self.list_view_btn.setProperty("active", mode == "details")
        self.grid_view_btn.setProperty("active", mode == "icons")
        self.list_view_btn.style().unpolish(self.list_view_btn)
        self.list_view_btn.style().polish(self.list_view_btn)
        self.grid_view_btn.style().unpolish(self.grid_view_btn)
        self.grid_view_btn.style().polish(self.grid_view_btn)

    def on_item_double_clicked(self, index):
        view = self._file_view()
        source_index = view.model().mapToSource(index)
        path = self.model.filePath(source_index)
        is_dir = self.model.isDir(source_index)
        self.presenter.handle_double_click(path, is_dir)

    def jump_to_file(self, file_path):
        if not os.path.exists(file_path):
            return
        dir_path = os.path.dirname(file_path)
        self.presenter.navigate_to(dir_path)
        QTimer.singleShot(300, lambda: self._internal_focus_item(file_path))

    def update_status_info(self):
        self.presenter.refresh_status()
        # Emit single selected file path for the preview panel
        paths = self._get_selected_paths()
        if len(paths) == 1 and os.path.isfile(paths[0]):
            self.file_selected.emit(paths[0])

    def _trigger_disk_usage(self):
        view = self._file_view()
        if view is self.flat_view:
            path = self._current_path or "C:/"
        else:
            path = self.model.filePath(
                view.model().mapToSource(view.rootIndex())) or "C:/"
        if self.usage_worker and self.usage_worker.isRunning():
            self.usage_worker.terminate()
            self.usage_worker.wait()
        self.usage_worker = DiskUsageWorker(path)
        self.usage_worker.finished.connect(self._on_disk_usage_finished)
        self.usage_worker.start()

    def _on_disk_usage_finished(self, path, _total, _used, free):
        current_view = self._file_view()
        if current_view is self.flat_view:
            current_path = self._current_path or ""
        else:
            current_path = self.model.filePath(current_view.model().mapToSource(current_view.rootIndex()))
        if current_path == path:
            free_gb = free / (1024 ** 3)
            total_gb = _total / (1024 ** 3)
            tpl = self.config_mgr.get_text("ui_pane_status_disk_usage", "{:.1f} GB 剩餘 / {:.1f} GB 總計") if self.config_mgr else "{:.1f} GB 剩餘 / {:.1f} GB 總計"
            self.status_updated.emit(tpl.format(free_gb, total_gb))

    def _on_trash_clicked(self) -> None:
        from PyQt6.QtWidgets import QApplication
        permanent = bool(QApplication.keyboardModifiers() &
                         Qt.KeyboardModifier.ShiftModifier)
        self.presenter.handle_delete(permanent)

    def delete_selected(self, permanent=False):
        self.presenter.handle_delete(permanent)

    def show_confirm_dialog(self, title: str, message: str) -> bool:
        reply = QMessageBox.question(
            self, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No  # 預設焦點在「否」，防止誤刪
        )
        return reply == QMessageBox.StandardButton.Yes

    def create_new_folder(self):
        self.presenter.handle_create_folder()

    def refresh(self):
        path = self.path_edit.text()
        if os.path.exists(path):
            self.model.setRootPath("")
            self.model.setRootPath(path)
            idx = self.model.index(path)
            self.tree.setRootIndex(self.proxy_model.mapFromSource(idx))
            self.list_view.setRootIndex(self.list_proxy.mapFromSource(idx))
            self.tree._current_path = path
            self.list_view._current_path = path

    def _on_file_renamed(self, path: str, old_name: str, new_name: str) -> None:
        """QFileSystemModel.fileRenamed → push rename undo entry to main window."""
        if not old_name or not new_name:
            return
        old_path = os.path.join(path, old_name)
        new_path = os.path.join(path, new_name)
        win = self.window()
        if hasattr(win, "register_undo"):
            win.register_undo([(old_path, new_path)], "rename")

    def _get_selected_paths(self):
        view = self._file_view()
        if view is self.flat_view:
            idxs = view.selectionModel().selectedRows()
            paths = []
            for i in idxs:
                item = self.flat_model.item(i.row(), 0)
                if item:
                    p = item.data(Qt.ItemDataRole.UserRole)
                    if p:
                        paths.append(p)
            return paths
        idxs = view.selectionModel().selectedIndexes()
        if not idxs:
            return []
        return list(set(self.model.filePath(view.model().mapToSource(i)) for i in idxs))

    def _get_selected_size(self):
        view = self._file_view()
        if view is self.flat_view:
            idxs = view.selectionModel().selectedRows()
            total = 0
            for i in idxs:
                item = self.flat_model.item(i.row(), 0)
                if item:
                    p = item.data(Qt.ItemDataRole.UserRole)
                    if p and os.path.isfile(p):
                        total += os.path.getsize(p)
            return total
        idxs = view.selectionModel().selectedRows()
        if not idxs:
            return 0
        return sum(self.model.size(view.model().mapToSource(i)) for i in idxs
                   if not self.model.isDir(view.model().mapToSource(i)))

    def _get_selected_count(self):
        view = self._file_view()
        idxs = view.selectionModel().selectedRows()
        return len(idxs) if idxs else 0

    def _internal_focus_item(self, file_path):
        idx = self.model.index(file_path)
        if idx.isValid():
            view = self._file_view()
            proxy_idx = view.model().mapFromSource(idx)
            view.setCurrentIndex(proxy_idx)
            view.scrollTo(proxy_idx)
            view.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == event.Type.MouseButtonPress:
            if obj in [self.tree, self.list_view, self.flat_view,
                       self.tree.viewport(), self.list_view.viewport(),
                       self.flat_view.viewport()]:
                self.focused.emit(self)
        if event.type() == event.Type.FocusIn:
            if obj in [self.tree, self.list_view, self.flat_view,
                       self.path_edit, self.search_edit]:
                self.focused.emit(self)
        if event.type() == event.Type.KeyPress:
            # flat_view Space → 觸發預覽
            if obj in [self.flat_view, self.flat_view.viewport()]:
                if event.key() == Qt.Key.Key_Space:
                    paths = self._get_selected_paths()
                    if len(paths) == 1 and os.path.isfile(paths[0]):
                        win = self.window()
                        if hasattr(win, "toggle_inline_preview"):
                            win.toggle_inline_preview(paths[0])
                    return True
            # 攔截 Ctrl+V
            if event.key() == Qt.Key.Key_V and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                # 只有在視圖區域 (tree 或 list_view) 按下時才觸發超級貼上
                if obj in [self.tree, self.list_view]:
                    # 剪貼簿有檔案路徑 → 交由 keyPressEvent 處理（支援同資料夾複本）
                    from PyQt6.QtWidgets import QApplication
                    if QApplication.clipboard().mimeData().hasUrls():
                        return False
                    self.presenter.handle_paste()
                    return True  # 消耗掉事件
        return super().eventFilter(obj, event)
