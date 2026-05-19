import os, datetime, re, logging

logger = logging.getLogger(__name__)

def _natural_key(s: str) -> list:
    """Split string into text/number chunks for human-friendly sorting."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s or "")]
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox,
    QHeaderView, QCheckBox,
    QMenu, QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem,
    QProgressBar, QStatusBar, QFileIconProvider, QComboBox,
    QWidget,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QFileInfo, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor
from ui.presenters.search_presenter import SearchPresenter
from core.interfaces import ISearchView


class DateSortProxyModel(QSortFilterProxyModel):
    """Custom proxy to support numeric sorting for Date and Size columns."""
    def lessThan(self, left, right):
        # QSortFilterProxyModel.lessThan receives SOURCE indices.
        if not left.isValid() or not right.isValid():
            return super().lessThan(left, right)
            
        col = left.column()
        
        # We always want to compare data based on the source indices provided.
        # UserRole contains the raw values for all columns.
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        
        # Numeric comparison for Date (2) and Size (3)
        if col in (2, 3):
            if left_data is not None and right_data is not None:
                try:
                    return float(left_data) < float(right_data)
                except (TypeError, ValueError):
                    pass
                    
            # Handle None or invalid data by treating them as minimal values
            if left_data is None: return True
            if right_data is None: return False
        
        # Natural sort for Name (1) — "part_2" before "part_10"
        if col == 1:
            l = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole) or ""
            r = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole) or ""
            return _natural_key(l) < _natural_key(r)

        return super().lessThan(left, right)

class SearchDialog(QDialog):
    def __init__(self, root_path, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        # Fallback if config_mgr not passed
        if not self.config_mgr and parent:
            self.config_mgr = getattr(parent, 'config_mgr', None)
            
        title = self.config_mgr.get_text("ui_dialog_search_title", "進階搜尋") if self.config_mgr else "進階搜尋"
        self.setWindowTitle(f"{title} - {os.path.basename(root_path)}")
        self.resize(1000, 700)
        self.root_path = root_path
            
        class _SearchViewAdapter(ISearchView):
            def __init__(self, dlg): self.dlg = dlg
            def add_result(self, path, mtime, size, context=""): self.dlg.add_result(path, mtime, size, context)
            def show_progress(self, text): self.dlg.status_label.setText(text)
            def search_finished(self, count): self.dlg.search_finished(count)

        self.presenter = SearchPresenter(_SearchViewAdapter(self), self.config_mgr)
        self.active_workers = [] # 防止 QThread 被 GC
        self.thread = None
        self.icon_provider = QFileIconProvider()
        
        # 搜尋去抖動 (Debouncing)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.start_search)
        
        self._init_ui()
        self.showMaximized() # 開啟時自動全螢幕，但使用者仍可手動縮小
        
        # Async sync from remote
        QTimer.singleShot(100, self._run_background_sync)

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 5)
        self.main_layout.setSpacing(10)

        # Apply Theme (Attempt to load network search styling)
        if self.presenter.config_mgr:
            qss = self.presenter.config_mgr.load_stylesheet("network_search/styles.qss", "theme.json")
            if qss:
                self.setStyleSheet(qss)

        # --- Header Section (Two Rows) ---
        input_row = QHBoxLayout()
        self.search_input = QLineEdit()
        placeholder = self.config_mgr.get_text("ui_dialog_search_placeholder", "輸入關鍵字搜尋 (例如: .pdf 或 文件名)...") if self.config_mgr else "輸入關鍵字搜尋 (例如: .pdf 或 文件名)..."
        self.search_input.setPlaceholderText(placeholder)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        input_row.addWidget(self.search_input)
        self.main_layout.addLayout(input_row)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)

        # 範圍切換 (Scope Toggles)
        config = self.presenter.config_mgr.load_config()
        monitored = config.get("monitored_paths") or []
        default_root = monitored[0] if monitored else "K:\\"
        
        label_net = self.config_mgr.get_text("ui_dialog_search_network_share", "網路共享 ({})").format(default_root) if self.config_mgr else f"網路共享 ({default_root})"
        self.network_k_cb = QCheckBox(label_net)
        self.network_k_cb.setChecked(True)
        self.network_k_cb.toggled.connect(self.start_search)
        
        label_local = self.config_mgr.get_text("ui_dialog_search_local_global", "本機全域") if self.config_mgr else "本機全域"
        self.local_global_cb = QCheckBox(label_local)
        self.local_global_cb.setChecked(True)
        self.local_global_cb.toggled.connect(self.on_scope_toggled)
        
        control_row.addWidget(self.network_k_cb)
        control_row.addWidget(self.local_global_cb)
        
        self.k_refresh_btn = QToolButton()
        btn_refresh = self.config_mgr.get_text("ui_dialog_search_refresh", "🔄更新") if self.config_mgr else "🔄更新"
        self.k_refresh_btn.setText(btn_refresh)
        tip_refresh = self.config_mgr.get_text("ui_dialog_search_refresh_tooltip", "更新索引 (生產者掃描 / 消費者檢查更新)") if self.config_mgr else "更新索引 (生產者掃描 / 消費者檢查更新)"
        self.k_refresh_btn.setToolTip(tip_refresh)
        self.k_refresh_btn.clicked.connect(self.start_k_scan)
        self.k_refresh_btn.setMinimumWidth(60)

        control_row.addWidget(self.k_refresh_btn)

        self.dup_analysis_btn = QToolButton()
        btn_dup = self.config_mgr.get_text("ui_dup_analysis_btn", "📊 重複分析") if self.config_mgr else "📊 重複分析"
        self.dup_analysis_btn.setText(btn_dup)
        tip_dup = self.config_mgr.get_text("ui_dup_analysis_btn_tip", "分析索引中的重複檔案") if self.config_mgr else "分析索引中的重複檔案"
        self.dup_analysis_btn.setToolTip(tip_dup)
        self.dup_analysis_btn.clicked.connect(self._open_dup_analysis)
        self.dup_analysis_btn.setMinimumWidth(80)
        control_row.addWidget(self.dup_analysis_btn)

        control_row.addStretch()
        self.main_layout.addLayout(control_row)

        # --- Filter Sections (Two Rows) ---
        # 檔案大小過濾初始化 (Size Filter Init)
        self.size_btn_group = QHBoxLayout()
        self.size_btn_group.setSpacing(2)
        self.size_btns = []
        self.current_size_idx = 0
        all_text = self.config_mgr.get_text("search_filter_all", "全部") if self.config_mgr else "全部"
        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {"size_labels": [all_text, "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"]}
        sizes = filters.get("size_labels", [all_text, "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"])
        for i, label in enumerate(sizes):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_size_btn_clicked(idx))
            self.size_btn_group.addWidget(btn)
            self.size_btns.append(btn)

        # 修改日期過濾初始化 (Time Filter Init)
        self.time_btn_group = QHBoxLayout()
        self.time_btn_group.setSpacing(2)
        self.time_btns = []
        self.current_time_idx = 0
        today_text = self.config_mgr.get_text("search_filter_today", "🕒 今日") if self.config_mgr else "🕒 今日"
        week_text = self.config_mgr.get_text("search_filter_week", "📅 本週") if self.config_mgr else "📅 本週"
        month_text = self.config_mgr.get_text("search_filter_month", "本月") if self.config_mgr else "本月"
        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {"time_labels": [all_text, today_text, week_text, month_text]}
        time_labels = filters.get("time_labels", [all_text, today_text, week_text, month_text])
        for i, label in enumerate(time_labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_time_btn_clicked(idx))
            self.time_btn_group.addWidget(btn)
            self.time_btns.append(btn)

        # 1. Size Row
        size_row = QHBoxLayout()
        label_size = self.config_mgr.get_text("ui_dialog_search_size_label", "大小:") if self.config_mgr else "大小:"
        size_row.addWidget(QLabel(label_size))
        size_row.addLayout(self.size_btn_group)
        size_row.addStretch()
        self.main_layout.addLayout(size_row)

        # 2. Time Row
        time_row = QHBoxLayout()
        label_time = self.config_mgr.get_text("ui_dialog_search_time_label", "時間:") if self.config_mgr else "時間:"
        time_row.addWidget(QLabel(label_time))
        time_row.addLayout(self.time_btn_group)
        time_row.addStretch()
        self.main_layout.addLayout(time_row)

        cur_dir_tpl = self.config_mgr.get_text("ui_dialog_search_current_dir", "📁 當前目錄: {}") if self.config_mgr else "📁 當前目錄: {}"
        self.path_display_label = QLabel(cur_dir_tpl.format(self.root_path))
        muted = "#888"
        if self.config_mgr:
            muted = self.config_mgr.get_theme_colors().get("textMuted", muted)
        self.path_display_label.setStyleSheet(f"color: {muted}; font-size: 13px; padding-left: 4px;")

        # 3. Content Search Row
        content_row = QHBoxLayout()
        label_content = self.config_mgr.get_text("ui_dialog_search_content_label", "內容:") if self.config_mgr else "內容:"
        content_row.addWidget(QLabel(label_content))
        self.content_input = QLineEdit()
        content_placeholder = self.config_mgr.get_text("ui_dialog_search_content_placeholder", "搜尋檔案內容（支援 txt/pdf/docx/xlsx）...") if self.config_mgr else "搜尋檔案內容（支援 txt/pdf/docx/xlsx）..."
        self.content_input.setPlaceholderText(content_placeholder)
        self.content_input.setMaximumWidth(480)
        self.content_input.textChanged.connect(self._on_content_changed)
        self.content_input.returnPressed.connect(self.start_search)
        content_row.addWidget(self.content_input)
        self.content_scope_cb = QComboBox()
        scope_cur = self.config_mgr.get_text("ui_dialog_search_scope_current", "當前目錄") if self.config_mgr else "當前目錄"
        scope_global = label_local
        self.content_scope_cb.addItems([scope_cur, scope_global])
        self.content_scope_cb.setFixedWidth(100)
        self.content_scope_cb.currentIndexChanged.connect(
            lambda _: self._on_content_changed(self.content_input.text())
        )
        content_row.addWidget(self.content_scope_cb)
        btn_search_text = self.config_mgr.get_text("ui_dialog_search_btn_search", "搜尋") if self.config_mgr else "搜尋"
        self.content_search_btn = QPushButton(btn_search_text)
        self.content_search_btn.setObjectName("contentSearchBtn")
        self.content_search_btn.setFixedWidth(60)
        self.content_search_btn.clicked.connect(self.start_search)
        content_row.addWidget(self.content_search_btn)
        warn_net_text = self.config_mgr.get_text("ui_dialog_search_warn_network", "⚠ 不支援網路磁碟") if self.config_mgr else "⚠ 不支援網路磁碟"
        self.content_warn_label = QLabel(warn_net_text)
        warn_color = "#e67e22"
        if self.config_mgr:
            warn_color = self.config_mgr.get_theme_colors().get("folder", warn_color) # reuse folder/warning amber
        self.content_warn_label.setStyleSheet(f"color: {warn_color}; font-size: 11px; padding-left: 6px;")
        self.content_warn_label.hide()
        content_row.addWidget(self.content_warn_label)
        content_row.addStretch()
        self.main_layout.addLayout(content_row)

        self.main_layout.addWidget(self.path_display_label)
        self.path_display_label.hide()

        self._update_size_btn_styles()
        self._update_time_btn_styles()

        # Sync/Scan Progress Section
        self.progress_layout = QVBoxLayout()
        status_init_text = self.config_mgr.get_text("ui_dialog_search_status_init", "正在初始化...") if self.config_mgr else "正在初始化..."
        self.sync_status_label = QLabel(status_init_text)
        accent = "#4a9eff"
        if self.config_mgr:
            accent = self.config_mgr.get_theme_colors().get("accent", accent)
        self.sync_status_label.setStyleSheet(f"color: {accent}; font-weight: bold; padding: 2px;")
        
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setFixedHeight(6)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setTextVisible(False)
        
        self.progress_layout.addWidget(self.sync_status_label)
        self.progress_layout.addWidget(self.scan_progress_bar)
        self.main_layout.addLayout(self.progress_layout)
        
        # Determine and show role status immediately
        self._update_role_status_ui()

        # --- Body Section (Results Tree) ---
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
        col_name = self.config_mgr.get_text("ui_dialog_search_col_name", "名稱") if self.config_mgr else "名稱"
        col_date = self.config_mgr.get_text("ui_dialog_search_col_date", "修改日期") if self.config_mgr else "修改日期"
        col_size = self.config_mgr.get_text("ui_dialog_search_col_size", "大小") if self.config_mgr else "大小"
        col_context = self.config_mgr.get_text("ui_dialog_search_col_context", "找到位置") if self.config_mgr else "找到位置"
        col_path = self.config_mgr.get_text("ui_dialog_search_col_path", "完整路徑") if self.config_mgr else "完整路徑"
        self.model.setHorizontalHeaderLabels(["", col_name, col_date, col_size, col_context, col_path])
        
        self.proxy_model = DateSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)
        
        self.tree.setModel(self.proxy_model)
        
        header_view = self.tree.header()
        header_view.setSectionsMovable(True) # 允許欄位左右移動位置
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        
        self.tree.setColumnWidth(0, 42)
        self.tree.setColumnWidth(1, 300)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 200) # 找到位置預設寬度
        self.tree.setColumnWidth(5, 400) # 完整路徑預設寬度
        
        self.main_layout.addWidget(self.tree)
        self.tree.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Action bar — shown when one or more rows are selected
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

        # --- Footer Section (Progress & Status) ---
        self.scan_progress_label = QLabel("")
        _prog_qss = "color: {{success}}; font-size: 11px;"
        if self.config_mgr:
            _prog_qss = self.config_mgr.apply_theme_to_text(_prog_qss)
        self.scan_progress_label.setStyleSheet(_prog_qss)
        self.scan_progress_label.hide()
        self.main_layout.addWidget(self.scan_progress_label)

        self.status_bar = QStatusBar()
        status_ready_text = self.config_mgr.get_text("ui_dialog_search_status_ready", "請輸入關鍵字開始搜尋") if self.config_mgr else "請輸入關鍵字開始搜尋"
        self.status_label = QLabel(status_ready_text)
        self.status_bar.addWidget(self.status_label)
        self.main_layout.addWidget(self.status_bar)

    def _on_content_changed(self, text):
        has_text = bool(text)
        self.content_warn_label.setVisible(has_text)
        is_cur_dir = self.content_scope_cb.currentIndex() == 0
        self.path_display_label.setVisible(has_text and is_cur_dir)
        if text:
            self.network_k_cb.setChecked(False)

    def on_search_text_changed(self, text):
        # 300ms 延遲觸發，避免輸入時過於頻繁
        self.search_timer.start(300)

    def on_scope_toggled(self, checked):
        self.start_search()

    def closeEvent(self, event):
        self.presenter.stop_search()
        
        # 停止所有背景掃描器 (ScannerWorker)
        if hasattr(self, 'scanner') and self.scanner:
            self.scanner.stop()
            self.scanner.wait()
            
        for worker in self.active_workers:
            try:
                worker.stop()
                worker.wait()
            except: pass
        self.active_workers.clear()
            
        super().closeEvent(event)

    def start_search(self):
        keyword = self.search_input.text().strip()
        content_keyword = self.content_input.text().strip()
        if content_keyword:
            import unicodedata
            dw = sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in content_keyword)
            if dw < 2:
                err_content_len = self.config_mgr.get_text("ui_dialog_search_warn_content_len", "⚠ 內容關鍵字至少需輸入 2 個字元（或 1 個中文字）") if self.config_mgr else "⚠ 內容關鍵字至少需輸入 2 個字元（或 1 個中文字）"
                self.status_label.setText(err_content_len)
                return
        if not keyword and not content_keyword and not self.network_k_cb.isChecked():
            err_no_kw = self.config_mgr.get_text("ui_dialog_search_warn_no_keyword", "請輸入關鍵字") if self.config_mgr else "請輸入關鍵字"
            self.status_label.setText(err_no_kw)
            return

        # Disable sorting temporarily during update
        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        status_searching = self.config_mgr.get_text("ui_dialog_search_status_searching", "正在搜尋...") if self.config_mgr else "正在搜尋..."
        self.status_label.setText(status_searching)
        
        # 計算時間過濾基準 (Unix Timestamp)
        min_mtime = 0
        now = datetime.datetime.now()
        if self.current_time_idx == 1: # 今日
            min_mtime = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif self.current_time_idx == 2: # 本週 (以週一為起點)
            monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            min_mtime = monday.timestamp()
        elif self.current_time_idx == 3: # 本月 (以 1 號為起點)
            first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            min_mtime = first_day.timestamp()

        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {}
        size_map = filters.get("size_thresholds", {"0": 0, "1": 1*1024*1024, "2": 10*1024*1024, "3": 100*1024*1024, "4": 1024*1024*1024})
        min_size_val = size_map.get(str(self.current_size_idx), size_map.get(self.current_size_idx, 0))

        # 準備搜尋條件 (簡化為以關鍵字為主)
        use_global_val = self.local_global_cb.isChecked()
        if content_keyword:
            use_global_val = (self.content_scope_cb.currentIndex() == 1)  # 1 = 本機全域
        conditions = {
            'path': self.root_path,
            'pattern': keyword if ('*' in keyword or '?' in keyword) else (f"*{keyword}*" if keyword else "*"),
            'content': content_keyword,
            'use_global': use_global_val,
            'use_k': self.network_k_cb.isChecked(),
            'min_size': min_size_val,
            'min_mtime': min_mtime,
            'limit': 1000
        }
        
        # 如果本機索引不存在，僅顯示提示而不自動啟動掃描 (避免輸入時過於擾民)
        if conditions['use_global'] and not self.presenter.check_personal_db_exists():
             tip_no_local = self.config_mgr.get_text("ui_dialog_search_tip_no_local_db", "提示：本機索引尚未建立，建議點擊「🔄更新」以獲得最佳搜尋速度") if self.config_mgr else "提示：本機索引尚未建立，建議點擊「🔄更新」以獲得最佳搜尋速度"
             self.status_label.setText(tip_no_local)
        
        self.presenter.start_search(conditions)

    def on_size_btn_clicked(self, index):
        self.current_size_idx = index
        self._update_size_btn_styles()
        self.start_search()

    def on_time_btn_clicked(self, index):
        self.current_time_idx = index
        self._update_time_btn_styles()
        self.start_search()

    def _update_size_btn_styles(self):
        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        active_color = tc.get("activeTab", "#2d5a8e")
        accent = tc.get("accent", "#58A6FF")
        dark = tc.get("bg", "#1e2128")

        active_style = f"background-color: {active_color}; color: white; font-weight: bold; border-top: 1px solid {accent}; border-bottom: 2px solid {dark};"
        inactive_style = "background-color: {{surfaceSubtle}}; color: {{textMuted}}; border: 1px solid {{border}};"
        if self.config_mgr:
            inactive_style = self.config_mgr.apply_theme_to_text(inactive_style)

        for i, btn in enumerate(self.size_btns):
            btn.setChecked(i == self.current_size_idx)
            btn.setStyleSheet(active_style if i == self.current_size_idx else inactive_style)

    def _update_time_btn_styles(self):
        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        active_color = tc.get("activeTab", "#2d5a8e")
        accent = tc.get("accent", "#58A6FF")
        dark = tc.get("bg", "#1e2128")

        active_style = f"background-color: {active_color}; color: white; font-weight: bold; border-top: 1px solid {accent}; border-bottom: 2px solid {dark};"
        inactive_style = "background-color: {{surfaceSubtle}}; color: {{textMuted}}; border: 1px solid {{border}};"
        if self.config_mgr:
            inactive_style = self.config_mgr.apply_theme_to_text(inactive_style)

        for i, btn in enumerate(self.time_btns):
            btn.setChecked(i == self.current_time_idx)
            btn.setStyleSheet(active_style if i == self.current_time_idx else inactive_style)

    def add_result(self, path, mtime=None, size=None, context=""):
        name = os.path.basename(path)
        dir_path = os.path.dirname(path)

        # 1. Locate Item
        item_locate = QStandardItem("📂")
        tip_locate = self.config_mgr.get_text("ui_dialog_search_tooltip_locate", "前往路徑 (在主視窗中定位)") if self.config_mgr else "前往路徑 (在主視窗中定位)"
        item_locate.setToolTip(tip_locate)
        item_locate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_locate.setForeground(Qt.GlobalColor.blue)

        # 2. Name Item
        item_name = QStandardItem(name)
        info = QFileInfo(path)
        icon = self.icon_provider.icon(info)
        item_name.setIcon(icon)
        # Store path for opening/context menu
        item_name.setData(path, Qt.ItemDataRole.UserRole)

        # 3. Date Item
        date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
        item_date = QStandardItem(date_str)
        item_date.setData(float(mtime) if mtime else 0.0, Qt.ItemDataRole.UserRole)

        # 4. Size Item
        size_str = self._format_size(size) if size else "0 B"
        item_size = QStandardItem(size_str)
        item_size.setData(float(size) if size else 0.0, Qt.ItemDataRole.UserRole)

        # 5. Context Item
        item_context = QStandardItem(context)
        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        item_context.setForeground(QColor(tc.get("accent", "#58A6FF")))

        # 6. Path Item
        item_path = QStandardItem(dir_path)
        item_path.setForeground(Qt.GlobalColor.gray)
        item_path.setData(dir_path, Qt.ItemDataRole.UserRole)

        self.model.appendRow([item_locate, item_name, item_date, item_size, item_context, item_path])

    def _get_selected_paths(self) -> list[str]:
        paths = []
        for proxy_idx in self.tree.selectionModel().selectedRows():
            src = self.proxy_model.mapToSource(proxy_idx)
            item = self.model.item(src.row(), 1)
            if item:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        return [p for p in paths if p]

    def _on_selection_changed(self):
        count = len(self.tree.selectionModel().selectedRows())
        if count == 0:
            self.action_bar.hide()
            return
        self.action_count_label.setText(f"已選取 {count} 個項目")
        self.action_bar.show()

    def _find_main_window(self):
        p = self.parent()
        while p:
            if hasattr(p, '_get_opposite_pane'):
                return p
            p = p.parent()
        return None

    def _copy_to_pane(self):
        self._do_copy_or_move(move=False)

    def _move_to_pane(self):
        self._do_copy_or_move(move=True)

    def _do_copy_or_move(self, move: bool):
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

    def _copy_paths_to_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        paths = self._get_selected_paths()
        if paths:
            QApplication.clipboard().setText("\n".join(paths))
            self.status_label.setText(f"已複製 {len(paths)} 個路徑")

    def _format_size(self, size):
        if not size: return "0 B"
        s = float(size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if s < 1024.0: return f"{s:.1f} {unit}"
            s /= 1024.0
        return f"{s:.1f} TB"

    def search_finished(self, count):
        status_finished = self.config_mgr.get_text("ui_dialog_search_status_finished", "搜尋完成，共找到 {} 個項目").format(count) if self.config_mgr else f"搜尋完成，共找到 {count} 個項目"
        self.status_label.setText(status_finished)
        
        # Restore sorting on the current column
        header = self.tree.header()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        
        # Force a re-sort on the proxy model
        self.proxy_model.sort(sort_col, sort_order)
        
        # Ensure sorting is enabled on the view
        self.tree.setSortingEnabled(True)
        
        if self.parent() and hasattr(self.parent(), 'statusBar'):
            self.parent().statusBar().showMessage(status_finished, 8000)

    def on_item_clicked(self, index):
        # 僅在單擊第一個欄位 (圖示) 時進行畫面定位
        if index.column() == 0:
            source_index = self.proxy_model.mapToSource(index)
            item = self.model.item(source_index.row(), 1)
            path = item.data(Qt.ItemDataRole.UserRole)
            pane = self.parent() # ExplorerPane
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
                self.accept()
        # 單擊其餘欄位僅為「選擇」，不做開啟動作

    def on_item_double_clicked(self, index):
        # 雙擊 → 開啟檔案，不關閉對話框
        source_index = self.proxy_model.mapToSource(index)
        item = self.model.item(source_index.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(path):
            os.startfile(path)
        else:
            err_title = self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤"
            err_msg = self.config_mgr.get_text("ui_dialog_search_err_file_not_exist", "檔案不存在: {}").format(path) if self.config_mgr else f"檔案不存在: {path}"
            QMessageBox.warning(self, err_title, err_msg)

    def on_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid(): return

        source_index = self.proxy_model.mapToSource(index)
        item = self.model.item(source_index.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)

        selected = self._get_selected_paths()
        if path not in selected:
            selected = [path]

        menu = QMenu(self)
        open_act = jump_act = copy_act = copy_to_act = move_to_act = copy_all_act = None

        if len(selected) <= 1:
            menu_open   = self.config_mgr.get_text("ui_dialog_search_menu_open",      "開啟檔案")       if self.config_mgr else "開啟檔案"
            menu_locate = self.config_mgr.get_text("ui_dialog_search_menu_locate",    "在主視窗中定位") if self.config_mgr else "在主視窗中定位"
            menu_copy   = self.config_mgr.get_text("ui_dialog_search_menu_copy_path", "複製路徑")       if self.config_mgr else "複製路徑"
            open_act  = menu.addAction(menu_open)
            jump_act  = menu.addAction(menu_locate)
            menu.addSeparator()
            copy_act  = menu.addAction(menu_copy)
        else:
            n = len(selected)
            header = menu.addAction(f"已選取 {n} 個項目")
            header.setEnabled(False)
            menu.addSeparator()
            copy_to_act  = menu.addAction(f"複製 {n} 個項目到對面欄")
            move_to_act  = menu.addAction(f"移動 {n} 個項目到對面欄")
            menu.addSeparator()
            copy_all_act = menu.addAction("複製所有路徑")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == open_act:
            os.startfile(path)
        elif action == jump_act:
            pane = self.parent()
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
            self.accept()
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

    def _update_role_status_ui(self):
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")
        
        tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
        _accent = tc.get("accent", "#58A6FF")
        _muted = tc.get("textMuted", "#8B949E")
        _success = tc.get("success", "#57B77F")
        
        tip_refresh_local = self.config_mgr.get_text("ui_dialog_search_refresh_tooltip_local", "手動更新個人本機索引 (C:\\)") if self.config_mgr else "手動更新個人本機索引 (C:\\)"
        
        if is_master:
            role_master = self.config_mgr.get_text("ui_dialog_search_role_master", "🛠️ 生產管理模式") if self.config_mgr else "🛠️ 生產管理模式"
            self.sync_status_label.setText(role_master)
            self.sync_status_label.setStyleSheet(f"color: {_accent}; font-weight: bold;")
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(tip_refresh_local)
        elif not remote_root:
            role_local = self.config_mgr.get_text("ui_dialog_search_role_local", "✅ 本機搜尋模式") if self.config_mgr else "✅ 本機搜尋模式"
            self.sync_status_label.setText(role_local)
            self.sync_status_label.setStyleSheet(f"color: {_muted};")
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(tip_refresh_local)
        else:
            slot = self.presenter.config_mgr.get_active_slot()
            role_consumer = self.config_mgr.get_text("ui_dialog_search_role_consumer", "🌐 消費者模式 (Slot {}): 已偵測到共享索引").format(slot) if self.config_mgr else f"🌐 消費者模式 (Slot {slot}): 已偵測到共享索引"
            self.sync_status_label.setText(role_consumer)
            self.sync_status_label.setStyleSheet(f"color: {_success};")
            
            # 使用者模式也能更新自己的 C 槽索引
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(tip_refresh_local)

    def _update_search_mgr(self):
        """重新加載設定並重新初始化搜尋管理員 (處理模式切換)"""
        self.presenter.reload_config()
        self._update_role_status_ui()

    def _run_background_sync(self):
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")
        
        if not remote_root:
            status_local = self.config_mgr.get_text("ui_dialog_search_status_local_only", "✅ 本機模式") if self.config_mgr else "✅ 本機模式"
            self.sync_status_label.setText(status_local)
            return
            
        if is_master:
            # Master node might still want to check remote availability
            if not os.path.exists(remote_root):
                err_remote = self.config_mgr.get_text("ui_dialog_search_err_remote_failed", "❌ 警告: 共享路徑存取失敗 {}").format(remote_root) if self.config_mgr else f"❌ 警告: 共享路徑存取失敗 {remote_root}"
                self.sync_status_label.setText(err_remote)
            return

        # Consumer node: Just update status, no large downloads needed
        status_connected = self.config_mgr.get_text("ui_dialog_search_status_connected", "✅ 已連接至團隊共享索引 (直接連線模式)") if self.config_mgr else "✅ 已連接至團隊共享索引 (直接連線模式)"
        self.sync_status_label.setText(status_connected)
        self._update_role_status_ui()

    def start_k_scan(self, target_db="local"):
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
                configs_k = [(os.path.normpath(p), network_depth) for p in monitored if os.path.exists(p)]
                if configs_k:
                    has_network_scan = True

            # 1. 執行 C 槽掃描 (Personal)，排除已由 monitored_paths 涵蓋的磁碟
            monitored_drives = {
                (os.path.splitdrive(os.path.normpath(p))[0] + '\\').lower()
                for p in monitored if p
            }
            if local_drives:
                configs_c = [
                    (os.path.normpath(p), 99) for p in local_drives
                    if os.path.exists(p) and os.path.normpath(p).lower() not in monitored_drives
                ]
                if configs_c:
                    status_scanning_local = self.config_mgr.get_text("ui_dialog_search_status_scanning_local", "正在掃描本機全域 (Personal)...") if self.config_mgr else "正在掃描本機全域 (Personal)..."
                    self.sync_status_label.setText(status_scanning_local)
                    sc_c = ScannerWorker(
                        configs_c, 
                        self.presenter.index_mgr, 
                        target_db="personal",
                        exclude_dirs=config.get("exclude_dirs", [])
                    )
                    self.active_workers.append(sc_c)
                    
                    # 加入掃描進度的動態回饋，降低使用者的等待焦慮
                    status_scanning_path_tpl = self.config_mgr.get_text("ui_dialog_search_status_scanning_path", "掃描本機: {}") if self.config_mgr else "掃描本機: {}"
                    sc_c.progress.connect(lambda p: self.sync_status_label.setText(status_scanning_path_tpl.format(p)))
                    
                    status_scanning_count_tpl = self.config_mgr.get_text("ui_dialog_search_status_scanning_count", "本機掃描中... 已索引 {} 個項目") if self.config_mgr else "本機掃描中... 已索引 {} 個項目"
                    sc_c.files_indexed.connect(lambda c: self.sync_status_label.setText(status_scanning_count_tpl.format(c)))
                    
                    sc_c.finished.connect(lambda: self.active_workers.remove(sc_c) if sc_c in self.active_workers else None)
                    if not has_network_scan:
                        sc_c.finished.connect(self.on_k_scan_finished)
                    sc_c.start()
            
            # 2. 執行監控路徑掃描 (Network Master) - 僅生產者模式
            if has_network_scan:
                QTimer.singleShot(1000, lambda: self._run_network_scan(configs_k, remote_dir))
            
            self.k_refresh_btn.setEnabled(False)
            self.scan_progress_bar.setVisible(True)
            self.scan_progress_bar.setRange(0, 0)
            
        except Exception as e:
            err_title = self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤"
            err_msg = self.config_mgr.get_text("ui_dialog_search_err_start_scan", "無法啟動掃描: {}").format(e) if self.config_mgr else f"無法啟動掃描: {e}"
            QMessageBox.critical(self, err_title, err_msg)

    def _run_network_scan(self, configs, remote_dir):
        from network_search.engine import ScannerWorker
        self.planner_scanner = ScannerWorker(
            configs, 
            self.presenter.index_mgr,
            remote_db_dir=remote_dir,
            target_db="local"
        )
        self.active_workers.append(self.planner_scanner)
        status_scanning_k_tpl = self.config_mgr.get_text("ui_dialog_search_status_scanning_k", "掃描 K 槽: {}") if self.config_mgr else "掃描 K 槽: {}"
        self.planner_scanner.progress.connect(lambda p: self.sync_status_label.setText(status_scanning_k_tpl.format(os.path.basename(p))))
        
        status_scanning_k_count_tpl = self.config_mgr.get_text("ui_dialog_search_status_scanning_k_count", "K 槽掃描中... 已發現 {} 個檔案") if self.config_mgr else "K 槽掃描中... 已發現 {} 個檔案"
        self.planner_scanner.files_indexed.connect(lambda c: self.sync_status_label.setText(status_scanning_k_count_tpl.format(c)))
        
        self.planner_scanner.finished.connect(lambda: self.active_workers.remove(self.planner_scanner) if self.planner_scanner in self.active_workers else None)
        self.planner_scanner.finished.connect(self.on_k_scan_finished)
        self.planner_scanner.start()

    def on_k_scan_finished(self, count):
        self.k_refresh_btn.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        status_scan_finished = self.config_mgr.get_text("ui_dialog_search_status_scan_finished", "✅ 掃描完成！共索引 {} 個項目").format(count) if self.config_mgr else f"✅ 掃描完成！共索引 {count} 個項目"
        self.sync_status_label.setText(status_scan_finished)
        _ok_qss = "color: {{text}}; background-color: {{success}}; border-radius: 4px; padding: 4px; font-weight: bold;"
        if self.config_mgr:
            _ok_qss = self.config_mgr.apply_theme_to_text(_ok_qss)
        self.sync_status_label.setStyleSheet(_ok_qss)
        QTimer.singleShot(5000, lambda: self._update_role_status_ui())
        self.start_search()

    def _open_dup_analysis(self):
        main_win = self.parent()
        on_nav = main_win.jump_to_file if (main_win and hasattr(main_win, 'jump_to_file')) else None
        dlg = DuplicateAnalysisDialog(
            self.presenter.index_mgr,
            self.config_mgr,
            on_navigate=on_nav,
            parent=self,
        )
        dlg.show()


class DuplicateAnalysisDialog(QDialog):
    """Non-modal window: DB size candidates → head/tail fingerprint → show only confirmed duplicates."""

    # ── inner worker ──────────────────────────────────────────────────────────
    class _Worker(QThread):
        from PyQt6.QtCore import pyqtSignal
        progress = pyqtSignal(str)
        done     = pyqtSignal(list)   # list[tuple[str, int, list[str]]]

        def __init__(self, index_mgr, parent=None):
            super().__init__(parent)
            self._index_mgr = index_mgr

        def run(self):
            self.progress.emit("查詢資料庫...")
            rows = self._index_mgr.find_duplicates()
            # rows: (name, size, full_path, mtime)

            by_key: dict[tuple[str, int], list[str]] = {}
            for name, size, full_path, _mtime in rows:
                by_key.setdefault((name, int(size)), []).append(full_path)

            groups: list[tuple[str, int, list[str]]] = [
                (name, size, paths)
                for (name, size), paths in sorted(by_key.items(), key=lambda x: x[0][1], reverse=True)
                if len(paths) >= 2
            ]
            logger.info(f"[DupAnalysis] {len(rows)} rows → {len(groups)} duplicate groups")
            self.done.emit(groups)

    # ── dialog ────────────────────────────────────────────────────────────────

    def __init__(self, index_mgr, config_mgr=None, on_navigate=None, parent=None):
        super().__init__(parent)
        self._index_mgr = index_mgr
        self._config_mgr = config_mgr
        self._on_navigate = on_navigate
        self._worker = None
        title = config_mgr.get_text("ui_dup_analysis_title", "重複檔案分析") if config_mgr else "重複檔案分析"
        self.setWindowTitle(title)
        self.resize(900, 600)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()
        QTimer.singleShot(50, self._start_worker)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)

        self._status_label = QLabel(
            self._config_mgr.get_text("ui_dup_analysis_loading", "分析中...") if self._config_mgr else "分析中..."
        )
        layout.addWidget(self._status_label)

        col_path = self._config_mgr.get_text("ui_dup_analysis_col_path", "路徑") if self._config_mgr else "路徑"
        col_size = self._config_mgr.get_text("ui_dup_analysis_col_size", "大小") if self._config_mgr else "大小"
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([col_path, col_size])
        self._tree.setColumnWidth(0, 720)
        self._tree.setColumnWidth(1, 90)
        self._tree.setRootIsDecorated(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.currentItemChanged.connect(self._on_selection_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree, stretch=1)

        btn_row = QHBoxLayout()
        self._del_btn = QPushButton("🗑 移至資源回收筒")
        self._del_btn.setEnabled(False)
        self._del_btn.setToolTip("將選取的檔案移至資源回收筒（可復原）")
        self._del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        nav_text = self._config_mgr.get_text("ui_dup_analysis_navigate", "導航至所選路徑") if self._config_mgr else "導航至所選路徑"
        self._nav_btn = QPushButton(nav_text)
        self._nav_btn.setEnabled(False)
        self._nav_btn.clicked.connect(self._navigate_selected)
        btn_row.addWidget(self._nav_btn)
        close_text = self._config_mgr.get_text("ui_dialog_settings_btn_cancel", "關閉") if self._config_mgr else "關閉"
        close_btn = QPushButton(close_text)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _fmt_size(self, size: int) -> str:
        s = float(size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if s < 1024.0:
                return f"{s:.1f} {unit}"
            s /= 1024.0
        return f"{s:.1f} TB"

    def _start_worker(self):
        self._worker = self._Worker(self._index_mgr, parent=self)
        loading = self._config_mgr.get_text("ui_dup_analysis_loading", "分析中...") if self._config_mgr else "分析中..."
        self._worker.progress.connect(self._status_label.setText)
        self._worker.done.connect(self._populate_tree)
        self._status_label.setText(loading)
        self._worker.start()

    @staticmethod
    def _short_folder(folder: str, depth: int = 3) -> str:
        """Return last `depth` path components for compact display."""
        parts = folder.replace('/', '\\').rstrip('\\').split('\\')
        return '\\'.join(parts[-depth:]) if len(parts) > depth else folder

    def _populate_tree(self, groups: list):
        # groups: list[tuple[str, int, list[str]]]  (name, size, [path, ...])
        self._tree.clear()
        if not groups:
            empty = self._config_mgr.get_text("ui_dup_analysis_empty", "未找到重複檔案") if self._config_mgr else "未找到重複檔案"
            self._status_label.setText(empty)
            return

        # ── Group by folder-pair ───────────────────────────────────────────────
        pair_map: dict[frozenset, list[tuple[str, int, list[str]]]] = {}
        for name, size, paths in groups:
            key = frozenset(os.path.dirname(p) for p in paths)
            pair_map.setdefault(key, []).append((name, size, paths))

        def _pair_waste(file_groups: list) -> int:
            return sum((len(paths) - 1) * size for _, size, paths in file_groups)

        sorted_pairs = sorted(pair_map.items(), key=lambda x: _pair_waste(x[1]), reverse=True)

        total_files = sum(len(paths) for _, _, paths in groups)
        self._status_label.setText(f"找到 {len(sorted_pairs)} 個資料夾對，{len(groups)} 組重複，共 {total_files} 個檔案")

        # ── Build tree ─────────────────────────────────────────────────────────
        for folders, file_groups in sorted_pairs:
            folder_list = sorted(folders)
            short_label = " ↔ ".join(self._short_folder(f) for f in folder_list)
            waste_str   = self._fmt_size(_pair_waste(file_groups))
            pair_item   = QTreeWidgetItem([f"📁 {short_label}   ({len(file_groups)} 組, 浪費 {waste_str})", ""])
            pair_item.setToolTip(0, " ↔ ".join(folder_list))
            pair_item.setExpanded(False)

            for name, size, paths in sorted(file_groups, key=lambda x: x[1], reverse=True):
                size_str  = self._fmt_size(size)
                file_item = QTreeWidgetItem([name, size_str])
                file_item.setExpanded(False)
                for path in paths:
                    child = QTreeWidgetItem([path, size_str])
                    child.setData(0, Qt.ItemDataRole.UserRole, path)
                    file_item.addChild(child)
                pair_item.addChild(file_item)

            self._tree.addTopLevelItem(pair_item)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and self._on_navigate:
            self._do_navigate(path)

    def _navigate_selected(self):
        item = self._tree.currentItem()
        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and self._on_navigate:
                self._do_navigate(path)

    def _do_navigate(self, path: str):
        search_dlg = self.parent()
        if search_dlg:
            search_dlg.close()   # 關掉深度搜尋，分析視窗繼續浮著
        self._on_navigate(path)

    # ── deletion ───────────────────────────────────────────────────────────────

    @staticmethod
    def _item_level(item: QTreeWidgetItem) -> int:
        """0 = folder-pair, 1 = file-group, 2 = leaf file path."""
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return 2
        return 0 if item.parent() is None else 1

    def _on_selection_changed(self, current: QTreeWidgetItem, _prev):
        is_leaf = current is not None and current.data(0, Qt.ItemDataRole.UserRole) is not None
        self._del_btn.setEnabled(is_leaf)
        self._nav_btn.setEnabled(is_leaf)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        level = self._item_level(item)
        menu = QMenu(self)
        if level == 2:
            trash_act = menu.addAction("🗑 移至資源回收筒")
            nav_act   = menu.addAction("📂 導航至此路徑")
            chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if chosen == trash_act:
                self._do_delete(item)
            elif chosen == nav_act:
                path = item.data(0, Qt.ItemDataRole.UserRole)
                if path and self._on_navigate:
                    self._do_navigate(path)
        elif level == 1:
            n = item.childCount()
            del_act = menu.addAction(f"🗑 刪除此群組全部 {n} 個副本")
            chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if chosen == del_act:
                self._do_delete_group(item)
        else:
            total = sum(item.child(j).childCount() for j in range(item.childCount()))
            del_act = menu.addAction(f"🗑 刪除此資料夾對全部 {total} 個檔案")
            chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
            if chosen == del_act:
                self._do_delete_pair(item)

    def _delete_selected(self):
        item = self._tree.currentItem()
        if item and item.data(0, Qt.ItemDataRole.UserRole) is not None:
            self._do_delete(item)

    def _do_delete(self, item: QTreeWidgetItem):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        if not os.path.exists(path):
            # File already gone — just remove from tree silently
            pass
        else:
            try:
                import send2trash
                send2trash.send2trash(path)
            except Exception as e:
                QMessageBox.warning(self, "刪除失敗", f"{os.path.basename(path)}\n\n{e}")
                return

        # Remove leaf from file-group node
        file_item = item.parent()
        if file_item:
            file_item.removeChild(item)
            # If file group has only 1 copy left → no longer duplicate, remove group
            if file_item.childCount() < 2:
                pair_item = file_item.parent()
                if pair_item:
                    pair_item.removeChild(file_item)
                    # If folder pair has no groups left, remove pair
                    if pair_item.childCount() == 0:
                        idx = self._tree.indexOfTopLevelItem(pair_item)
                        self._tree.takeTopLevelItem(idx)
        self._update_summary()

    def _do_delete_group(self, file_item: QTreeWidgetItem):
        """Delete all file copies under a file-group node (level 1)."""
        n = file_item.childCount()
        name = file_item.text(0)
        reply = QMessageBox.question(
            self, "確認刪除群組",
            f"確定要將「{name}」的全部 {n} 個副本移至資源回收筒？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import send2trash
        failed = []
        for i in range(n - 1, -1, -1):
            child = file_item.child(i)
            path = child.data(0, Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                try:
                    send2trash.send2trash(path)
                except Exception as e:
                    failed.append(f"{os.path.basename(path)}: {e}")
        if failed:
            QMessageBox.warning(self, "部分刪除失敗", "\n".join(failed))
        pair_item = file_item.parent()
        if pair_item:
            pair_item.removeChild(file_item)
            if pair_item.childCount() == 0:
                self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(pair_item))
        self._update_summary()

    def _do_delete_pair(self, pair_item: QTreeWidgetItem):
        """Delete every file under a folder-pair node (level 0)."""
        group_count = pair_item.childCount()
        total = sum(pair_item.child(j).childCount() for j in range(group_count))
        reply = QMessageBox.question(
            self, "確認刪除資料夾對",
            f"確定要將此資料夾對的 {group_count} 組、共 {total} 個檔案全部移至資源回收筒？\n\n{pair_item.toolTip(0)}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import send2trash
        failed = []
        for j in range(group_count):
            file_item = pair_item.child(j)
            for k in range(file_item.childCount()):
                path = file_item.child(k).data(0, Qt.ItemDataRole.UserRole)
                if path and os.path.exists(path):
                    try:
                        send2trash.send2trash(path)
                    except Exception as e:
                        failed.append(f"{os.path.basename(path)}: {e}")
        if failed:
            QMessageBox.warning(self, "部分刪除失敗", "\n".join(failed))
        self._tree.takeTopLevelItem(self._tree.indexOfTopLevelItem(pair_item))
        self._update_summary()

    def _update_summary(self):
        pairs  = self._tree.topLevelItemCount()
        groups = sum(self._tree.topLevelItem(i).childCount() for i in range(pairs))
        files  = sum(
            self._tree.topLevelItem(i).child(j).childCount()
            for i in range(pairs)
            for j in range(self._tree.topLevelItem(i).childCount())
        )
        if groups == 0:
            empty = self._config_mgr.get_text("ui_dup_analysis_empty", "未找到重複檔案") if self._config_mgr else "未找到重複檔案"
            self._status_label.setText(empty)
        else:
            self._status_label.setText(f"找到 {pairs} 個資料夾對，{groups} 組重複，共 {files} 個檔案")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)


class BatchRenameDialog(QDialog):
    """批次重新命名對話框。確認後透過 get_op_pairs() 取得 (src, dst) 清單。"""

    _INVALID_RE = re.compile(r'[\\/:*?"<>|]')

    def __init__(self, src_paths: list[str], config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr or (getattr(parent, 'config_mgr', None) if parent else None)
        self._src_paths = src_paths
        self._confirmed_pairs: list[tuple[str, str]] = []
        self._today = datetime.datetime.now().strftime("%Y%m%d")
        self.setWindowTitle(f"批次重新命名 ({len(src_paths)} 個項目)")
        self.resize(700, 450)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._init_ui()
        self._update_preview()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 樣板列
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("樣板:"))
        self._tpl = QLineEdit()
        self._tpl.setPlaceholderText("例如: {date}_{name}  或  report_{n:03d}")
        self._tpl.textChanged.connect(self._update_preview)
        tpl_row.addWidget(self._tpl, 1)

        quick_btn = QToolButton()
        quick_btn.setText("快速樣板 ▼")
        quick_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        qm = QMenu(self)
        for tpl, label in [
            ("{date}_{name}",  "{date}_{name}  (日期_原名)"),
            ("{n:03d}_{name}", "{n:03d}_{name}  (序號_原名)"),
            ("{name}_{date}",  "{name}_{date}  (原名_日期)"),
            ("{n}_{name}",     "{n}_{name}      (序號_原名)"),
        ]:
            qm.addAction(label).triggered.connect(
                lambda checked, t=tpl: self._tpl.setText(t))
        quick_btn.setMenu(qm)
        tpl_row.addWidget(quick_btn)
        layout.addLayout(tpl_row)

        hint = QLabel("佔位符：{name} 原檔名  {ext} 副檔名  {date} 今日日期  {n} 序號  {n:03d} 補零序號")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        # 預覽表格
        self._model = QStandardItemModel(0, 4)
        self._model.setHorizontalHeaderLabels(["#", "原始名稱", "新名稱（預覽）", "狀態"])
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setRootIsDecorated(False)
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree.setSelectionMode(QTreeView.SelectionMode.NoSelection)
        self._tree.setAlternatingRowColors(True)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(0, 36)
        self._tree.setColumnWidth(1, 200)
        self._tree.setColumnWidth(3, 80)
        layout.addWidget(self._tree)

        # 底部按鈕
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("取消", clicked=self.reject))
        btn_row.addStretch()
        self._apply_btn = QPushButton(f"套用重新命名 ({len(self._src_paths)} 個)")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)

    def _apply_template(self, template: str, src_path: str, index: int) -> str:
        name, ext = os.path.splitext(os.path.basename(src_path))
        result = template
        result = result.replace("{name}", name)
        result = result.replace("{ext}",  ext)
        result = result.replace("{date}", self._today)
        result = re.sub(r'\{n:([^}]+)\}', lambda m: format(index + 1, m.group(1)), result)
        result = result.replace("{n}", str(index + 1))
        if "{ext}" not in template.lower() and ext:
            result += ext
        return result

    def _update_preview(self):
        from collections import Counter
        template = self._tpl.text()
        self._model.removeRows(0, self._model.rowCount())
        if not template.strip():
            self._apply_btn.setText("套用重新命名 (0 個)")
            self._apply_btn.setEnabled(False)
            return

        previews = [(s, self._apply_template(template, s, i), os.path.dirname(s))
                    for i, s in enumerate(self._src_paths)]
        dup_counter = Counter((p, n) for (_, n, p) in previews)

        valid = 0
        for i, (src, new_name, parent) in enumerate(previews):
            orig = os.path.basename(src)
            new_path = os.path.join(parent, new_name)
            same = os.path.normcase(new_name) == os.path.normcase(orig)

            if same:
                st, color, ok = "—", QColor("gray"), False
            elif self._INVALID_RE.search(new_name):
                st, color, ok = "✗ 無效", QColor("#e74c3c"), False
            elif dup_counter[(parent, new_name)] > 1:
                st, color, ok = "⚠ 重複", QColor("#e67e22"), False
            elif os.path.normcase(new_path) != os.path.normcase(src) and os.path.exists(new_path):
                st, color, ok = "⚠ 重複", QColor("#e67e22"), False
            else:
                st, color, ok = "✓", QColor("#2ecc71"), True

            if ok:
                valid += 1

            row = [QStandardItem(str(i + 1)), QStandardItem(orig),
                   QStandardItem(new_name),   QStandardItem(st)]
            row[0].setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            row[3].setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            row[3].setForeground(color)
            self._model.appendRow(row)

        self._apply_btn.setText(f"套用重新命名 ({valid} 個)")
        self._apply_btn.setEnabled(valid > 0)

    def _on_apply(self):
        from collections import Counter
        template = self._tpl.text().strip()
        if not template:
            return
        pairs = []
        for i, src in enumerate(self._src_paths):
            new_name = self._apply_template(template, src, i)
            parent   = os.path.dirname(src)
            new_path = os.path.join(parent, new_name)
            if os.path.normcase(os.path.basename(src)) == os.path.normcase(new_name):
                continue
            if self._INVALID_RE.search(new_name):
                continue
            if os.path.normcase(new_path) != os.path.normcase(src) and os.path.exists(new_path):
                continue
            pairs.append((src, new_path))
        dest_count = Counter(os.path.normcase(d) for _, d in pairs)
        pairs = [(s, d) for s, d in pairs if dest_count[os.path.normcase(d)] == 1]
        if not pairs:
            return
        self._confirmed_pairs = pairs
        self.accept()

    def get_op_pairs(self) -> list[tuple[str, str]]:
        return self._confirmed_pairs

