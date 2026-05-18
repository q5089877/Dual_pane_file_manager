from __future__ import annotations
import os
import datetime
import logging

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox,
    QHeaderView, QCheckBox, QFrame,
    QMenu, QToolButton, QTreeView,
    QProgressBar, QStatusBar, QFileIconProvider, QComboBox,
)
from PyQt6.QtCore import Qt, QTimer, QFileInfo, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QKeySequence, QShortcut
from ui.presenters.search_presenter import SearchPresenter
from core.interfaces import ISearchView
from ui.widgets.dialogs import DateSortProxyModel


class SearchPanel(QWidget):
    """深度搜尋面板 — 嵌入 ExplorerPane 的 view_stack，取代獨立彈出的 SearchDialog。"""

    close_requested = pyqtSignal()

    def __init__(self, root_path: str, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.root_path = root_path

        class _Adapter(ISearchView):
            def __init__(self, p): self.p = p
            def add_result(self, path, mtime, size, context=""): self.p.add_result(path, mtime, size, context)
            def show_progress(self, text): self.p.status_label.setText(text)
            def search_finished(self, count): self.p.search_finished(count)

        self._is_search_tab = True  # tab system skips _current_path lookup for this widget
        self.presenter = SearchPresenter(_Adapter(self), self.config_mgr)
        self.active_workers: list = []
        self.thread = None
        self.icon_provider = QFileIconProvider()

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.start_search)

        self._init_ui()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
            self.close_requested.emit)
        QTimer.singleShot(100, self._run_background_sync)

    # ── UI Construction ────────────────────────────────────────────────────────

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(6, 6, 6, 4)
        self.main_layout.setSpacing(4)

        if self.presenter.config_mgr:
            qss = self.presenter.config_mgr.load_stylesheet(
                "network_search/styles.qss", "theme.json")
            if qss:
                self.setStyleSheet(qss)

        # ── Row 1: keyword input | sync status | ✕ ───────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self._t(
            "ui_dialog_search_placeholder",
            "輸入關鍵字搜尋 (例如: .pdf 或 文件名)..."))
        self.search_input.textChanged.connect(self.on_search_text_changed)
        row1.addWidget(self.search_input, 1)

        accent = "#4a9eff"
        if self.config_mgr:
            accent = self.config_mgr.get_theme_colors().get("accent", accent)

        self.sync_status_label = QLabel(self._t(
            "ui_dialog_search_status_init", "正在初始化..."))
        self.sync_status_label.setStyleSheet(
            f"color: {accent}; font-weight: bold; padding: 2px;")
        row1.addWidget(self.sync_status_label)

        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("關閉搜尋 (Esc)")
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.clicked.connect(self.close_requested.emit)
        row1.addWidget(self.close_btn)

        self.main_layout.addLayout(row1)

        # ── Row 2: scope + tools | size combo | time combo | stretch | 進階▾ ──
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        config = self.presenter.config_mgr.load_config()
        monitored = config.get("monitored_paths") or []
        default_root = monitored[0] if monitored else "K:\\"

        label_local = self._t("ui_dialog_search_local_global", "本機全域")

        self.network_k_cb = QCheckBox(
            self._t("ui_dialog_search_network_share",
                    "網路共享 ({})").format(default_root))
        self.network_k_cb.setChecked(True)
        self.network_k_cb.toggled.connect(self.start_search)
        row2.addWidget(self.network_k_cb)

        self.local_global_cb = QCheckBox(label_local)
        self.local_global_cb.setChecked(True)
        self.local_global_cb.toggled.connect(self.on_scope_toggled)
        row2.addWidget(self.local_global_cb)

        row2.addWidget(self._vline())

        self.k_refresh_btn = QToolButton()
        self.k_refresh_btn.setText(self._t("ui_dialog_search_refresh", "🔄更新"))
        self.k_refresh_btn.setToolTip(self._t(
            "ui_dialog_search_refresh_tooltip",
            "更新索引 (生產者掃描 / 消費者檢查更新)"))
        self.k_refresh_btn.clicked.connect(self.start_k_scan)
        self.k_refresh_btn.setMinimumWidth(56)
        row2.addWidget(self.k_refresh_btn)

        self.dup_analysis_btn = QToolButton()
        self.dup_analysis_btn.setText(self._t("ui_dup_analysis_btn", "📊 重複分析"))
        self.dup_analysis_btn.setToolTip(self._t(
            "ui_dup_analysis_btn_tip", "分析索引中的重複檔案"))
        self.dup_analysis_btn.clicked.connect(self._open_dup_analysis)
        self.dup_analysis_btn.setMinimumWidth(76)
        row2.addWidget(self.dup_analysis_btn)

        row2.addWidget(self._vline())

        filters = (self.presenter.config_mgr.get_search_filters()
                   if self.presenter.config_mgr else {})
        all_text = self._t("search_filter_all", "全部")

        size_labels = filters.get("size_labels",
                                  [all_text, "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"])
        self.size_combo = QComboBox()
        self.size_combo.addItems(size_labels)
        self.size_combo.setFixedWidth(90)
        self.current_size_idx = 0
        self.size_combo.currentIndexChanged.connect(self._on_size_combo_changed)
        row2.addWidget(self.size_combo)

        time_labels = filters.get("time_labels", [
            all_text,
            self._t("search_filter_today", "🕒 今日"),
            self._t("search_filter_week", "📅 本週"),
            self._t("search_filter_month", "本月"),
        ])
        self.time_combo = QComboBox()
        self.time_combo.addItems(time_labels)
        self.time_combo.setFixedWidth(90)
        self.current_time_idx = 0
        self.time_combo.currentIndexChanged.connect(self._on_time_combo_changed)
        row2.addWidget(self.time_combo)

        row2.addStretch()

        self._adv_toggle_btn = QToolButton()
        self._adv_toggle_btn.setText("進階 ▾")
        self._adv_toggle_btn.setCheckable(True)
        self._adv_toggle_btn.setFixedWidth(66)
        self._adv_toggle_btn.toggled.connect(self._on_adv_toggled)
        row2.addWidget(self._adv_toggle_btn)

        self.main_layout.addLayout(row2)

        # Pill-button compatibility shims (no actual widgets created)
        self.size_btns: list = []
        self.time_btns: list = []

        # ── Row 3 (collapsible): content search ───────────────────────────────
        self._content_row_widget = QWidget()
        cr = QHBoxLayout(self._content_row_widget)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(4)
        cr.addWidget(QLabel(self._t("ui_dialog_search_content_label", "內容:")))

        self.content_input = QLineEdit()
        self.content_input.setPlaceholderText(self._t(
            "ui_dialog_search_content_placeholder",
            "搜尋檔案內容（支援 txt/pdf/docx/xlsx）..."))
        self.content_input.textChanged.connect(self._on_content_changed)
        self.content_input.returnPressed.connect(self.start_search)
        cr.addWidget(self.content_input, 1)

        self.content_scope_cb = QComboBox()
        self.content_scope_cb.addItems([
            self._t("ui_dialog_search_scope_current", "當前目錄"),
            label_local,
        ])
        self.content_scope_cb.setFixedWidth(100)
        self.content_scope_cb.currentIndexChanged.connect(
            lambda _: self._on_content_changed(self.content_input.text()))
        cr.addWidget(self.content_scope_cb)

        self.content_search_btn = QPushButton(
            self._t("ui_dialog_search_btn_search", "搜尋"))
        self.content_search_btn.setObjectName("contentSearchBtn")
        self.content_search_btn.setFixedWidth(60)
        self.content_search_btn.clicked.connect(self.start_search)
        cr.addWidget(self.content_search_btn)

        warn_color = "#e67e22"
        if self.config_mgr:
            warn_color = self.config_mgr.get_theme_colors().get("folder", warn_color)
        self.content_warn_label = QLabel(
            self._t("ui_dialog_search_warn_network", "⚠ 不支援網路磁碟"))
        self.content_warn_label.setStyleSheet(
            f"color: {warn_color}; font-size: 11px; padding-left: 6px;")
        self.content_warn_label.hide()
        cr.addWidget(self.content_warn_label)
        cr.addStretch()

        self._content_row_widget.setVisible(False)
        self.main_layout.addWidget(self._content_row_widget)

        # Current-dir hint (shown during content search in current-dir mode)
        muted = "#888"
        if self.config_mgr:
            muted = self.config_mgr.get_theme_colors().get("textMuted", muted)
        self.path_display_label = QLabel(
            self._t("ui_dialog_search_current_dir",
                    "📁 當前目錄: {}").format(self.root_path))
        self.path_display_label.setStyleSheet(
            f"color: {muted}; font-size: 13px; padding-left: 4px;")
        self.path_display_label.hide()
        self.main_layout.addWidget(self.path_display_label)

        # Thin progress bar for scan progress
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setFixedHeight(6)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setTextVisible(False)
        self.main_layout.addWidget(self.scan_progress_bar)

        # ── Results tree ──────────────────────────────────────────────────────
        self.tree = QTreeView()
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        self.tree.clicked.connect(self.on_item_clicked)
        self.tree.doubleClicked.connect(self.on_item_double_clicked)

        self.model = QStandardItemModel(0, 6)
        self.model.setHorizontalHeaderLabels([
            "",
            self._t("ui_dialog_search_col_name", "名稱"),
            self._t("ui_dialog_search_col_date", "修改日期"),
            self._t("ui_dialog_search_col_size", "大小"),
            self._t("ui_dialog_search_col_context", "找到位置"),
            self._t("ui_dialog_search_col_path", "完整路徑"),
        ])

        self.proxy_model = DateSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)
        self.tree.setModel(self.proxy_model)

        hdr = self.tree.header()
        hdr.setSectionsMovable(True)
        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 42)
        self.tree.setColumnWidth(1, 300)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 200)
        self.tree.setColumnWidth(5, 400)

        self.main_layout.addWidget(self.tree, 1)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # ── Action bar (shown on selection) ───────────────────────────────────
        self.action_bar = QWidget()
        self.action_bar.setObjectName("searchActionBar")
        self.action_bar.hide()
        _ab = QHBoxLayout(self.action_bar)
        _ab.setContentsMargins(8, 4, 8, 4)
        _ab.setSpacing(6)
        self.action_count_label = QLabel("")
        _ab.addWidget(self.action_count_label)
        _ab.addStretch()
        self.action_copy_btn = QPushButton("複製到對面欄")
        self.action_copy_btn.clicked.connect(self._copy_to_pane)
        _ab.addWidget(self.action_copy_btn)
        self.action_move_btn = QPushButton("移動到對面欄")
        self.action_move_btn.clicked.connect(self._move_to_pane)
        _ab.addWidget(self.action_move_btn)
        self.action_copy_path_btn = QPushButton("複製路徑")
        self.action_copy_path_btn.clicked.connect(self._copy_paths_to_clipboard)
        _ab.addWidget(self.action_copy_path_btn)
        self.main_layout.addWidget(self.action_bar)

        # ── Footer ────────────────────────────────────────────────────────────
        self.scan_progress_label = QLabel("")
        _prog_qss = "color: {{success}}; font-size: 11px;"
        if self.config_mgr:
            _prog_qss = self.config_mgr.apply_theme_to_text(_prog_qss)
        self.scan_progress_label.setStyleSheet(_prog_qss)
        self.scan_progress_label.hide()
        self.main_layout.addWidget(self.scan_progress_label)

        self.status_bar = QStatusBar()
        self.status_label = QLabel(
            self._t("ui_dialog_search_status_ready", "請輸入關鍵字開始搜尋"))
        self.status_bar.addWidget(self.status_label)
        self.main_layout.addWidget(self.status_bar)

        self._update_role_status_ui()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _t(self, key: str, default: str) -> str:
        return self.config_mgr.get_text(key, default) if self.config_mgr else default

    @staticmethod
    def _vline() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_root(self, path: str) -> None:
        self.root_path = path
        self.path_display_label.setText(
            self._t("ui_dialog_search_current_dir",
                    "📁 當前目錄: {}").format(path))

    def focus_search(self) -> None:
        self.search_input.setFocus()
        self.search_input.selectAll()

    def cleanup(self) -> None:
        self.presenter.stop_search()
        if hasattr(self, 'scanner') and self.scanner:
            self.scanner.stop()
            self.scanner.wait()
        for worker in list(self.active_workers):
            try:
                worker.stop()
                worker.wait()
            except Exception:
                pass
        self.active_workers.clear()

    def closeEvent(self, event):
        self.close_requested.emit()
        event.ignore()

    # ── Slot: advanced row toggle ──────────────────────────────────────────────

    def _on_adv_toggled(self, checked: bool) -> None:
        self._content_row_widget.setVisible(checked)
        self._adv_toggle_btn.setText("進階 ▲" if checked else "進階 ▾")

    # ── Slots: combo-based filter ──────────────────────────────────────────────

    def _on_size_combo_changed(self, index: int) -> None:
        self.current_size_idx = index
        self.start_search()

    def _on_time_combo_changed(self, index: int) -> None:
        self.current_time_idx = index
        self.start_search()

    def _update_size_btn_styles(self) -> None:
        pass

    def _update_time_btn_styles(self) -> None:
        pass

    def on_size_btn_clicked(self, index: int) -> None:
        self.size_combo.setCurrentIndex(index)

    def on_time_btn_clicked(self, index: int) -> None:
        self.time_combo.setCurrentIndex(index)

    # ── Search logic (ported from SearchDialog) ────────────────────────────────

    def _on_content_changed(self, text: str) -> None:
        has_text = bool(text)
        self.content_warn_label.setVisible(has_text)
        is_cur_dir = self.content_scope_cb.currentIndex() == 0
        self.path_display_label.setVisible(has_text and is_cur_dir)
        if text:
            self.network_k_cb.setChecked(False)

    def on_search_text_changed(self, _text: str) -> None:
        self.search_timer.start(300)

    def on_scope_toggled(self, _checked: bool) -> None:
        self.start_search()

    def start_search(self) -> None:
        keyword = self.search_input.text().strip()
        content_keyword = self.content_input.text().strip()
        if content_keyword:
            import unicodedata
            dw = sum(
                2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
                for c in content_keyword)
            if dw < 2:
                self.status_label.setText(self._t(
                    "ui_dialog_search_warn_content_len",
                    "⚠ 內容關鍵字至少需輸入 2 個字元（或 1 個中文字）"))
                return
        if not keyword and not content_keyword and not self.network_k_cb.isChecked():
            self.status_label.setText(
                self._t("ui_dialog_search_warn_no_keyword", "請輸入關鍵字"))
            return

        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        self.status_label.setText(
            self._t("ui_dialog_search_status_searching", "正在搜尋..."))

        min_mtime = 0
        now = datetime.datetime.now()
        if self.current_time_idx == 1:
            min_mtime = now.replace(
                hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif self.current_time_idx == 2:
            monday = (now - datetime.timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0)
            min_mtime = monday.timestamp()
        elif self.current_time_idx == 3:
            min_mtime = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

        filters = (self.presenter.config_mgr.get_search_filters()
                   if self.presenter.config_mgr else {})
        size_map = filters.get("size_thresholds", {
            "0": 0, "1": 1*1024*1024, "2": 10*1024*1024,
            "3": 100*1024*1024, "4": 1024*1024*1024,
        })
        min_size_val = size_map.get(str(self.current_size_idx),
                                    size_map.get(self.current_size_idx, 0))

        use_global_val = self.local_global_cb.isChecked()
        if content_keyword:
            use_global_val = (self.content_scope_cb.currentIndex() == 1)

        conditions = {
            'path': self.root_path,
            'pattern': (keyword if ('*' in keyword or '?' in keyword)
                        else (f"*{keyword}*" if keyword else "*")),
            'content': content_keyword,
            'use_global': use_global_val,
            'use_k': self.network_k_cb.isChecked(),
            'min_size': min_size_val,
            'min_mtime': min_mtime,
            'limit': 1000,
        }

        if (conditions['use_global']
                and not self.presenter.check_personal_db_exists()):
            self.status_label.setText(self._t(
                "ui_dialog_search_tip_no_local_db",
                "提示：本機索引尚未建立，建議點擊「🔄更新」以獲得最佳搜尋速度"))

        self.presenter.start_search(conditions)

    def add_result(self, path: str, mtime=None, size=None, context: str = "") -> None:
        name = os.path.basename(path)
        dir_path = os.path.dirname(path)

        item_locate = QStandardItem("📂")
        item_locate.setToolTip(self._t(
            "ui_dialog_search_tooltip_locate", "前往路徑 (在主視窗中定位)"))
        item_locate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_locate.setForeground(Qt.GlobalColor.blue)

        item_name = QStandardItem(name)
        info = QFileInfo(path)
        item_name.setIcon(self.icon_provider.icon(info))
        item_name.setData(path, Qt.ItemDataRole.UserRole)

        date_str = (datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    if mtime else "")
        item_date = QStandardItem(date_str)
        item_date.setData(float(mtime) if mtime else 0.0, Qt.ItemDataRole.UserRole)

        size_str = self._format_size(size) if size else "0 B"
        item_size = QStandardItem(size_str)
        item_size.setData(float(size) if size else 0.0, Qt.ItemDataRole.UserRole)

        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        item_context = QStandardItem(context)
        item_context.setForeground(QColor(tc.get("accent", "#58A6FF")))

        item_path = QStandardItem(dir_path)
        item_path.setForeground(Qt.GlobalColor.gray)
        item_path.setData(dir_path, Qt.ItemDataRole.UserRole)

        self.model.appendRow(
            [item_locate, item_name, item_date, item_size, item_context, item_path])

    def search_finished(self, count: int) -> None:
        msg = self._t("ui_dialog_search_status_finished",
                      "搜尋完成，共找到 {} 個項目").format(count)
        self.status_label.setText(msg)
        hdr = self.tree.header()
        self.proxy_model.sort(hdr.sortIndicatorSection(),
                              hdr.sortIndicatorOrder())
        self.tree.setSortingEnabled(True)

    def _get_explorer_pane(self):
        """Return the active ExplorerPane for jump_to_file navigation."""
        mw = self._find_main_window()
        if mw and getattr(mw, 'active_pane', None):
            return mw.active_pane
        return None

    def on_item_clicked(self, index) -> None:
        if index.column() == 0:
            src = self.proxy_model.mapToSource(index)
            item = self.model.item(src.row(), 1)
            path = item.data(Qt.ItemDataRole.UserRole)
            pane = self._get_explorer_pane()
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
                self.close_requested.emit()

    def on_item_double_clicked(self, index) -> None:
        src = self.proxy_model.mapToSource(index)
        item = self.model.item(src.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(
                self,
                self._t("ui_dialog_common_error", "錯誤"),
                self._t("ui_dialog_search_err_file_not_exist",
                        "檔案不存在: {}").format(path))

    def on_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        src = self.proxy_model.mapToSource(index)
        item = self.model.item(src.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        selected = self._get_selected_paths()
        if path not in selected:
            selected = [path]

        menu = QMenu(self)
        open_act = jump_act = copy_act = copy_to_act = move_to_act = copy_all_act = None

        if len(selected) <= 1:
            open_act = menu.addAction(
                self._t("ui_dialog_search_menu_open", "開啟檔案"))
            jump_act = menu.addAction(
                self._t("ui_dialog_search_menu_locate", "在主視窗中定位"))
            menu.addSeparator()
            copy_act = menu.addAction(
                self._t("ui_dialog_search_menu_copy_path", "複製路徑"))
        else:
            n = len(selected)
            hdr = menu.addAction(f"已選取 {n} 個項目")
            hdr.setEnabled(False)
            menu.addSeparator()
            copy_to_act = menu.addAction(f"複製 {n} 個項目到對面欄")
            move_to_act = menu.addAction(f"移動 {n} 個項目到對面欄")
            menu.addSeparator()
            copy_all_act = menu.addAction("複製所有路徑")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == open_act:
            os.startfile(path)
        elif action == jump_act:
            pane = self._get_explorer_pane()
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
            self.close_requested.emit()
        elif action == copy_act:
            from PyQt6.QtWidgets import QApplication
            from PyQt6.QtCore import QMimeData, QUrl
            mime = QMimeData()
            mime.setText(path)
            mime.setUrls([QUrl.fromLocalFile(path)])
            QApplication.clipboard().setMimeData(mime)
        elif action == copy_to_act:
            self._do_copy_or_move(move=False)
        elif action == move_to_act:
            self._do_copy_or_move(move=True)
        elif action == copy_all_act:
            self._copy_paths_to_clipboard()

    # ── K-scan logic ──────────────────────────────────────────────────────────

    def start_k_scan(self, _target_db: str = "local") -> None:
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        monitored = config.get("monitored_paths", [])
        local_drives = self.presenter.config_mgr.get_fixed_drives()

        try:
            from network_search.engine import ScannerWorker
            max_depth = config.get("max_depth", 7)
            remote_dir = config.get("remote_index_root")

            has_network_scan = False
            configs_k = []
            if is_master and monitored:
                network_depth = config.get("network_scan_depth", max(max_depth, 7))
                configs_k = [
                    (os.path.normpath(p), network_depth)
                    for p in monitored if os.path.exists(p)
                ]
                if configs_k:
                    has_network_scan = True

            monitored_drives = {
                (os.path.splitdrive(os.path.normpath(p))[0] + '\\').lower()
                for p in monitored if p
            }
            if local_drives:
                configs_c = [
                    (os.path.normpath(p), 99) for p in local_drives
                    if os.path.exists(p)
                    and os.path.normpath(p).lower() not in monitored_drives
                ]
                if configs_c:
                    self.sync_status_label.setText(self._t(
                        "ui_dialog_search_status_scanning_local",
                        "正在掃描本機全域 (Personal)..."))
                    sc_c = ScannerWorker(
                        configs_c,
                        self.presenter.index_mgr,
                        target_db="personal",
                        exclude_dirs=config.get("exclude_dirs", []),
                    )
                    self.active_workers.append(sc_c)

                    tpl_path = self._t("ui_dialog_search_status_scanning_path",
                                       "掃描本機: {}")
                    tpl_count = self._t("ui_dialog_search_status_scanning_count",
                                        "本機掃描中... 已索引 {} 個項目")
                    sc_c.progress.connect(
                        lambda p: self.sync_status_label.setText(tpl_path.format(p)))
                    sc_c.files_indexed.connect(
                        lambda c: self.sync_status_label.setText(tpl_count.format(c)))
                    sc_c.finished.connect(
                        lambda: self.active_workers.remove(sc_c)
                        if sc_c in self.active_workers else None)
                    if not has_network_scan:
                        sc_c.finished.connect(self.on_k_scan_finished)
                    sc_c.start()

            if has_network_scan:
                QTimer.singleShot(1000,
                                  lambda: self._run_network_scan(configs_k, remote_dir))

            self.k_refresh_btn.setEnabled(False)
            self.scan_progress_bar.setVisible(True)
            self.scan_progress_bar.setRange(0, 0)

        except Exception as e:
            QMessageBox.critical(
                self,
                self._t("ui_dialog_common_error", "錯誤"),
                self._t("ui_dialog_search_err_start_scan",
                        "無法啟動掃描: {}").format(e))

    def _run_network_scan(self, configs: list, remote_dir: str) -> None:
        from network_search.engine import ScannerWorker
        self.planner_scanner = ScannerWorker(
            configs,
            self.presenter.index_mgr,
            remote_db_dir=remote_dir,
            target_db="local",
        )
        self.active_workers.append(self.planner_scanner)
        tpl_path = self._t("ui_dialog_search_status_scanning_k", "掃描 K 槽: {}")
        tpl_count = self._t("ui_dialog_search_status_scanning_k_count",
                             "K 槽掃描中... 已發現 {} 個檔案")
        self.planner_scanner.progress.connect(
            lambda p: self.sync_status_label.setText(
                tpl_path.format(os.path.basename(p))))
        self.planner_scanner.files_indexed.connect(
            lambda c: self.sync_status_label.setText(tpl_count.format(c)))
        self.planner_scanner.finished.connect(
            lambda: self.active_workers.remove(self.planner_scanner)
            if self.planner_scanner in self.active_workers else None)
        self.planner_scanner.finished.connect(self.on_k_scan_finished)
        self.planner_scanner.start()

    def on_k_scan_finished(self, count: int) -> None:
        self.k_refresh_btn.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        self.sync_status_label.setText(self._t(
            "ui_dialog_search_status_scan_finished",
            "✅ 掃描完成！共索引 {} 個項目").format(count))
        _qss = "color: {{text}}; background-color: {{success}}; border-radius: 4px; padding: 4px; font-weight: bold;"
        if self.config_mgr:
            _qss = self.config_mgr.apply_theme_to_text(_qss)
        self.sync_status_label.setStyleSheet(_qss)
        QTimer.singleShot(5000, self._update_role_status_ui)
        self.start_search()

    # ── Role / sync status ────────────────────────────────────────────────────

    def _update_role_status_ui(self) -> None:
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")
        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        _accent = tc.get("accent", "#58A6FF")
        _muted = tc.get("textMuted", "#8B949E")
        _success = tc.get("success", "#57B77F")
        tip_local = self._t("ui_dialog_search_refresh_tooltip_local",
                             "手動更新個人本機索引 (C:\\)")

        if is_master:
            self.sync_status_label.setText(self._t(
                "ui_dialog_search_role_master",
                "🛠️ 生產管理模式 (Master) - 掃描本機並發布至區域路徑"))
            self.sync_status_label.setStyleSheet(
                f"color: {_accent}; font-weight: bold;")
        elif not remote_root:
            self.sync_status_label.setText(
                self._t("ui_dialog_search_role_local", "✅ 本機搜尋模式"))
            self.sync_status_label.setStyleSheet(f"color: {_muted};")
        else:
            slot = self.presenter.config_mgr.get_active_slot()
            self.sync_status_label.setText(self._t(
                "ui_dialog_search_role_consumer",
                "🌐 消費者模式 (Slot {}): 已偵測到共享索引").format(slot))
            self.sync_status_label.setStyleSheet(f"color: {_success};")

        self.k_refresh_btn.setEnabled(True)
        self.k_refresh_btn.setToolTip(tip_local)

    def _run_background_sync(self) -> None:
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")

        if not remote_root:
            self.sync_status_label.setText(
                self._t("ui_dialog_search_status_local_only", "✅ 本機模式"))
            return
        if is_master:
            if not os.path.exists(remote_root):
                self.sync_status_label.setText(self._t(
                    "ui_dialog_search_err_remote_failed",
                    "❌ 警告: 共享路徑存取失敗 {}").format(remote_root))
            return

        self.sync_status_label.setText(self._t(
            "ui_dialog_search_status_connected",
            "✅ 已連接至團隊共享索引 (直接連線模式)"))
        self._update_role_status_ui()

    # ── Duplicate analysis ────────────────────────────────────────────────────

    def _open_dup_analysis(self) -> None:
        from ui.widgets.dialogs import DuplicateAnalysisDialog
        pane = self.parent()
        on_nav = pane.jump_to_file if (pane and hasattr(pane, 'jump_to_file')) else None
        dlg = DuplicateAnalysisDialog(
            self.presenter.index_mgr,
            self.config_mgr,
            on_navigate=on_nav,
            parent=self,
        )
        dlg.show()

    # ── Copy / move helpers ───────────────────────────────────────────────────

    def _find_main_window(self):
        p = self.parent()
        while p:
            if hasattr(p, '_get_opposite_pane'):
                return p
            p = p.parent()
        return None

    def _get_selected_paths(self) -> list[str]:
        paths = []
        for proxy_idx in self.tree.selectionModel().selectedRows():
            src = self.proxy_model.mapToSource(proxy_idx)
            item = self.model.item(src.row(), 1)
            if item:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        return [p for p in paths if p]

    def _on_selection_changed(self) -> None:
        count = len(self.tree.selectionModel().selectedRows())
        if count == 0:
            self.action_bar.hide()
            return
        self.action_count_label.setText(f"已選取 {count} 個項目")
        self.action_bar.show()

    def _copy_to_pane(self) -> None:
        self._do_copy_or_move(move=False)

    def _move_to_pane(self) -> None:
        self._do_copy_or_move(move=True)

    def _do_copy_or_move(self, move: bool) -> None:
        import shutil
        paths = self._get_selected_paths()
        if not paths:
            return
        main_win = self._find_main_window()
        if not main_win:
            return
        opp = main_win._get_opposite_pane()
        if not opp:
            return
        dest_dir = opp.path_edit.text()
        if not dest_dir or not os.path.isdir(dest_dir):
            return
        errors = []
        for src in paths:
            dest = os.path.join(dest_dir, os.path.basename(src))
            try:
                if move:
                    shutil.move(src, dest)
                else:
                    if os.path.isdir(src):
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")
        opp.refresh()
        verb = "移動" if move else "複製"
        done = len(paths) - len(errors)
        msg = f"{verb}完成：{done} 個項目"
        if errors:
            msg += f"，{len(errors)} 個失敗"
        self.status_label.setText(msg)

    def _copy_paths_to_clipboard(self) -> None:
        from PyQt6.QtWidgets import QApplication
        paths = self._get_selected_paths()
        if paths:
            QApplication.clipboard().setText("\n".join(paths))
            self.status_label.setText(f"已複製 {len(paths)} 個路徑")

    @staticmethod
    def _format_size(size) -> str:
        if not size:
            return "0 B"
        s = float(size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if s < 1024.0:
                return f"{s:.1f} {unit}"
            s /= 1024.0
        return f"{s:.1f} TB"
