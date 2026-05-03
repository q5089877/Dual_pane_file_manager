import os, datetime, re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox, QListWidget, QInputDialog,
    QHeaderView, QCheckBox,
    QMenu, QToolButton, QTreeView, QProgressBar, QStatusBar, QFileIconProvider, QComboBox,
    QTabWidget, QWidget, QFormLayout, QSpinBox, QFileDialog, QProgressDialog,
)
from PyQt6.QtCore import Qt, QTimer, QFileInfo, QSortFilterProxyModel, pyqtSignal, QThread
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor
from ui.presenters.search_presenter import SearchPresenter
from core.interfaces import ISearchView, IAIExporterView


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
        
        # Fallback to standard comparison for Name (1), Path (4), etc.
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
        default_root = config.get("default_scan_root", "C:\\")
        
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
        
        # 管理按鈕 (Management Buttons) - 放到前面確保可見
        self.k_settings_btn = QToolButton()
        btn_settings = self.config_mgr.get_text("ui_dialog_search_settings", "⚙設定") if self.config_mgr else "⚙設定"
        self.k_settings_btn.setText(btn_settings) 
        tip_settings = self.config_mgr.get_text("ui_dialog_search_settings_tooltip", "網路索引管理與角色設定") if self.config_mgr else "網路索引管理與角色設定"
        self.k_settings_btn.setToolTip(tip_settings)
        self.k_settings_btn.clicked.connect(self.open_k_settings)
        self.k_settings_btn.setMinimumWidth(60)

        self.k_refresh_btn = QToolButton()
        btn_refresh = self.config_mgr.get_text("ui_dialog_search_refresh", "🔄更新") if self.config_mgr else "🔄更新"
        self.k_refresh_btn.setText(btn_refresh)
        tip_refresh = self.config_mgr.get_text("ui_dialog_search_refresh_tooltip", "更新索引 (生產者掃描 / 消費者檢查更新)") if self.config_mgr else "更新索引 (生產者掃描 / 消費者檢查更新)"
        self.k_refresh_btn.setToolTip(tip_refresh)
        self.k_refresh_btn.clicked.connect(self.start_k_scan)
        self.k_refresh_btn.setMinimumWidth(60)

        control_row.addWidget(self.k_settings_btn)
        control_row.addWidget(self.k_refresh_btn)
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
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
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
        
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(1, 300)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)
        self.tree.setColumnWidth(4, 200) # 找到位置預設寬度
        self.tree.setColumnWidth(5, 400) # 完整路徑預設寬度
        
        self.main_layout.addWidget(self.tree)

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
        
        # 從第二欄 (名稱) 獲取 UserRole 儲存的完整路徑
        source_index = self.proxy_model.mapToSource(index)
        item = self.model.item(source_index.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        
        menu = QMenu(self)
        menu_open = self.config_mgr.get_text("ui_dialog_search_menu_open", "開啟檔案") if self.config_mgr else "開啟檔案"
        menu_locate = self.config_mgr.get_text("ui_dialog_search_menu_locate", "在主視窗中定位") if self.config_mgr else "在主視窗中定位"
        menu_copy = self.config_mgr.get_text("ui_dialog_search_menu_copy_path", "複製路徑") if self.config_mgr else "複製路徑"
        
        open_act    = menu.addAction(menu_open)
        jump_act    = menu.addAction(menu_locate)
        menu.addSeparator()
        copy_act    = menu.addAction(menu_copy)

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
            role_master = self.config_mgr.get_text("ui_dialog_search_role_master", "🛠️ 生產管理模式 (Master) - 掃描本機並發布至區域路徑") if self.config_mgr else "🛠️ 生產管理模式 (Master) - 掃描本機並發布至區域路徑"
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

    def open_k_settings(self):
        try:
            from network_search.ui import SettingsDialog
            config = self.presenter.config_mgr.load_config()
            config_mgr = self.presenter.config_mgr
            
            dialog = SettingsDialog(config, config_mgr=config_mgr, parent=self)
            if dialog.exec():
                new_settings = dialog.get_settings()
                is_m = new_settings.get("is_master_node", False)
                config.update(new_settings)
                
                config_mgr.save_config(
                    config.get("custom_paths", []),
                    config.get("left_tabs", []),
                    config.get("right_tabs", []),
                    remote_index_root=config.get("remote_index_root"),
                    watchlist=config.get("monitored_paths"),
                    default_scan_root=config.get("default_scan_root"),
                    max_depth=config.get("max_depth"),
                    search_limit=config.get("search_limit"),
                    is_master_node=is_m
                )
                label_net_prefix = self.config_mgr.get_text("ui_dialog_search_network_share", "網路共享 ({})") if self.config_mgr else "網路共享 ({})"
                self.network_k_cb.setText(label_net_prefix.format(config.get('default_scan_root', 'K:\\')))
                self._update_search_mgr()
        except Exception as e:
            err_title = self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤"
            err_msg = self.config_mgr.get_text("ui_dialog_search_err_open_settings", "無法開啟設定: {}").format(e) if self.config_mgr else f"無法開啟設定: {e}"
            QMessageBox.critical(self, err_title, err_msg)

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
                configs_k = [(os.path.normpath(p), max_depth) for p in monitored if os.path.exists(p)]
                if configs_k:
                    has_network_scan = True

            # 1. 執行 C 槽掃描 (Personal)
            if local_drives:
                configs_c = [(os.path.normpath(p), 99) for p in local_drives if os.path.exists(p)]
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



from core.interfaces import IAIExporterView
from PyQt6.QtWidgets import QProgressDialog, QMessageBox
from PyQt6.QtCore import Qt

class AIExporterProgressDialog(QProgressDialog):
    """
    Wraps QProgressDialog to provide a visual interface for AI context export.
    Returns an adapter to satisfy the IAIExporterView interface, avoiding PyQt metaclass conflicts.
    """
    def __init__(self, parent=None):
        self.config_mgr = getattr(parent, 'config_mgr', None) if parent else None
        
        label_scanning = self.config_mgr.get_text("ui_dialog_ai_status_scanning", "正在掃描目錄...") if self.config_mgr else "正在掃描目錄..."
        btn_cancel = self.config_mgr.get_text("ui_dialog_ai_btn_cancel", "取消") if self.config_mgr else "取消"
        super().__init__(label_scanning, btn_cancel, 0, 100, parent)
        
        title = self.config_mgr.get_text("ui_dialog_ai_title", "產生 AI Context") if self.config_mgr else "產生 AI Context"
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumDuration(0)
        self.setAutoReset(False)
        self.setAutoClose(False)
        
    def get_view_adapter(self) -> IAIExporterView:
        class _AIExporterViewAdapter(IAIExporterView):
            def __init__(self, dlg): self.dlg = dlg
            def show(self): self.dlg.show()
            def close(self): self.dlg.close()
            def set_range(self, total): self.dlg.setMaximum(total)
            def update_progress(self, filename, current, total):
                if self.dlg.maximum() != total:
                    self.dlg.setMaximum(total)
                self.dlg.setValue(current)
                
                tpl = self.dlg.config_mgr.get_text("ui_dialog_ai_status_processing", "處理檔案 ({}/{}):\n{}") if self.dlg.config_mgr else "處理檔案 ({}/{}):\n{}"
                self.dlg.setLabelText(tpl.format(current, total, filename))
                
            def show_success(self, file_count, char_count):
                title = self.dlg.config_mgr.get_text("ui_dialog_ai_success_title", "匯出成功") if self.dlg.config_mgr else "匯出成功"
                msg_tpl = self.dlg.config_mgr.get_text("ui_dialog_ai_success_msg", "✅ AI Context 已成功產生並複製到剪貼簿！\n\n• 包含檔案：{} 個\n• 總字元數：{:,} 字\n\n提示：現在可以直接在 ChatGPT 或 Claude 中貼上 (Ctrl+V)。") if self.dlg.config_mgr else "✅ AI Context 已成功產生並複製到剪貼簿！\n\n• 包含檔案：{} 個\n• 總字元數：{:,} 字\n\n提示：現在可以直接在 ChatGPT 或 Claude 中貼上 (Ctrl+V)。"
                
                QMessageBox.information(
                    self.dlg.parent(),
                    title,
                    msg_tpl.format(file_count, char_count)
                )
            def show_error(self, message):
                title = self.dlg.config_mgr.get_text("ui_dialog_ai_error_title", "匯出錯誤") if self.dlg.config_mgr else "匯出錯誤"
                msg_tpl = self.dlg.config_mgr.get_text("ui_dialog_ai_error_msg", "發生錯誤：\n{}") if self.dlg.config_mgr else "發生錯誤：\n{}"
                QMessageBox.critical(self.dlg.parent(), title, msg_tpl.format(message))
            def set_cancelled_callback(self, callback):
                self.dlg.canceled.connect(callback)
                
        return _AIExporterViewAdapter(self)


# ── Background Workers ──────────────────────────────────────────────────────────

class PathDiscoveryWorker(QThread):
    """非同步智慧路徑偵測 Worker"""
    finished = pyqtSignal(str) # 回傳偵測到的路徑，若無則回空字串

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr

    def run(self):
        # 呼叫 ConfigManager 的核心偵測邏輯 (可能涉及網路硬碟掛載點遍歷，耗時)
        path = self.config_mgr.auto_discover_remote_root()
        self.finished.emit(path or "")

# ── App-wide Settings Dialog ────────────────────────────────────────────────────

class AppSettingsDialog(QDialog):
    """集中式設定對話框：外觀 / 語言 / 搜尋K槽 / 排程 / 預覽與檔案"""

    theme_changed = pyqtSignal()  # 主題切換時發送，通知 MainWindow reload stylesheet

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._config_mgr = config_mgr # backwards compat for internal refs
        s = config_mgr.get_app_settings()
        self._backup_theme = s["theme_name"]   # Cancel 時還原用
        self._backup_lang = s.get("language", "zh_TW")  # Cancel 時還原用
        self._block_theme_signal = False
        
        title = self.config_mgr.get_text("ui_dialog_settings_title", "設定") if self.config_mgr else "設定"
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self._build_ui(s)

    def _build_ui(self, s: dict) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 12)

        tabs = QTabWidget()
        root.addWidget(tabs)

        tab_appearance = self.config_mgr.get_text("ui_dialog_settings_tab_appearance", "🎨 外觀") if self.config_mgr else "🎨 外觀"
        tab_search = self.config_mgr.get_text("ui_dialog_settings_tab_search", "🔍 搜尋 / 排程") if self.config_mgr else "🔍 搜尋 / 排程"
        tab_monitored = self.config_mgr.get_text("ui_dialog_settings_tab_monitored", "🛰 監控路徑") if self.config_mgr else "🛰 監控路徑"
        tab_preview = self.config_mgr.get_text("ui_dialog_settings_tab_preview", "📄 預覽與檔案") if self.config_mgr else "📄 預覽與檔案"
        tab_paste = self.config_mgr.get_text("ui_dialog_settings_tab_paste", "📋 貼上設定") if self.config_mgr else "📋 貼上設定"

        tabs.addTab(self._tab_appearance(s),   tab_appearance)
        tabs.addTab(self._tab_search(s),       tab_search)
        tabs.addTab(self._tab_monitored(s),    tab_monitored)
        tabs.addTab(self._tab_preview(s),      tab_preview)
        tabs.addTab(self._tab_paste(s),        tab_paste)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 0)
        btn_row.addStretch()
        
        btn_save_text = self.config_mgr.get_text("ui_dialog_settings_btn_save", "完成並儲存") if self.config_mgr else "完成並儲存"
        save_btn = QPushButton(btn_save_text)
        save_btn.setStyleSheet("font-weight: bold; padding: 6px 20px;")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        
        btn_cancel_text = self.config_mgr.get_text("ui_dialog_settings_btn_cancel", "取消") if self.config_mgr else "取消"
        cancel_btn = QPushButton(btn_cancel_text)
        cancel_btn.clicked.connect(self.reject)
        
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _form_widget(self) -> tuple:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(16, 12, 16, 12)
        f.setSpacing(10)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        return w, f

    # ── Tab 1: 外觀 ────────────────────────────────────────────────────────────

    def _tab_appearance(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        self._theme_combo = QComboBox()
        
        t1 = self.config_mgr.get_text("theme_name_eye_care", "調光護眼 (預設)") if self.config_mgr else "調光護眼 (預設)"
        t2 = self.config_mgr.get_text("theme_name_dracula", "深色 Dracula") if self.config_mgr else "深色 Dracula"
        t3 = self.config_mgr.get_text("theme_name_light", "亮色清爽") if self.config_mgr else "亮色清爽"
        
        self._theme_map = {
            t1: "調光護眼 (預設)",
            t2: "深色 Dracula",
            t3: "亮色清爽"
        }
        
        themes = [t1, t2, t3]
        self._theme_combo.addItems(themes)
        
        cur = s["theme_name"]
        # Find display name for internal theme name
        for disp, internal in self._theme_map.items():
            if internal == cur:
                self._theme_combo.setCurrentText(disp)
                break
                
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        
        label_theme = self.config_mgr.get_text("ui_dialog_settings_label_theme", "主題：") if self.config_mgr else "主題："
        f.addRow(label_theme, self._theme_combo)

        self._lang_combo = QComboBox()
        
        l_zh = self.config_mgr.get_text("ui_lang_zh_TW", "繁體中文") if self.config_mgr else "繁體中文"
        l_en = self.config_mgr.get_text("ui_lang_en_US", "English") if self.config_mgr else "English"
        
        self._lang_options = [(l_zh, "zh_TW"), (l_en, "en_US")]
        self._lang_combo.addItems([name for name, _ in self._lang_options])
        cur_lang = s.get("language", "zh_TW")
        for i, (_, code) in enumerate(self._lang_options):
            if code == cur_lang:
                self._lang_combo.setCurrentIndex(i)
                break
        
        label_lang = self.config_mgr.get_text("ui_dialog_settings_label_lang", "語言：") if self.config_mgr else "語言："
        f.addRow(label_lang, self._lang_combo)

        chk_restore_text = self.config_mgr.get_text("ui_dialog_settings_restore_session", "啟動時還原上一次的分頁") if self.config_mgr else "啟動時還原上一次的分頁"
        self._restore_session_chk = QCheckBox(chk_restore_text)
        self._restore_session_chk.setChecked(s.get("restore_last_session", True))
        
        label_startup = self.config_mgr.get_text("ui_dialog_settings_label_startup", "啟動行為：") if self.config_mgr else "啟動行為："
        f.addRow(label_startup, self._restore_session_chk)

        return w

    def _on_theme_changed(self, display_name: str) -> None:
        if self._block_theme_signal:
            return
        internal_name = self._theme_map.get(display_name, display_name)
        self._config_mgr.apply_theme_preset(internal_name)
        self.theme_changed.emit()


    # ── Tab 3: 搜尋 / K槽 ─────────────────────────────────────────────────────

    def _tab_search(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        chk_master_text = self.config_mgr.get_text("ui_dialog_settings_master_mode", "啟用生產者模式 (Master Node)") if self.config_mgr else "啟用生產者模式 (Master Node)"
        self._is_master_chk = QCheckBox(chk_master_text)
        self._is_master_chk.setChecked(s.get("is_master_node", False))
        
        tip_master = self.config_mgr.get_text("ui_dialog_settings_master_mode_tip", "僅公司主機需要開啟。開啟後負責執行背景掃描並發布索引。") if self.config_mgr else "僅公司主機需要開啟。開啟後負責執行背景掃描並發布索引。"
        self._is_master_chk.setToolTip(tip_master)
        self._is_master_chk.toggled.connect(self._on_master_toggled)
        
        label_role = self.config_mgr.get_text("ui_dialog_settings_label_role", "運行角色：") if self.config_mgr else "運行角色："
        f.addRow(label_role, self._is_master_chk)

        self._remote_root_edit = QLineEdit(s.get("remote_index_root", ""))
        placeholder_remote = self.config_mgr.get_text("ui_dialog_settings_remote_root_placeholder", "K:\\... 資料庫存放路徑") if self.config_mgr else "K:\\... 資料庫存放路徑"
        self._remote_root_edit.setPlaceholderText(placeholder_remote)
        
        self._discover_btn = QToolButton()
        self._discover_btn.setText("🪄")
        tip_discover = self.config_mgr.get_text("ui_dialog_settings_remote_root_tooltip", "智慧偵測網路索引位置") if self.config_mgr else "智慧偵測網路索引位置"
        self._discover_btn.setToolTip(tip_discover)
        self._discover_btn.clicked.connect(self._on_discover_clicked)
        
        browse1 = QPushButton("📂")
        browse1.setFixedWidth(32)
        browse1.clicked.connect(lambda: self._browse_dir(self._remote_root_edit))
        
        row1 = QHBoxLayout()
        row1.addWidget(self._remote_root_edit)
        row1.addWidget(self._discover_btn)
        row1.addWidget(browse1)
        
        label_remote = self.config_mgr.get_text("ui_dialog_settings_label_remote_root", "團隊索引存放路徑：") if self.config_mgr else "團隊索引存放路徑："
        f.addRow(label_remote, row1)

        self._scan_root_edit = QLineEdit(s.get("default_scan_root", ""))
        placeholder_scan = self.config_mgr.get_text("ui_dialog_settings_scan_root_placeholder", "K:  或其他磁碟根目錄") if self.config_mgr else "K:  或其他磁碟根目錄"
        self._scan_root_edit.setPlaceholderText(placeholder_scan)
        browse2 = QPushButton("📂")
        browse2.setFixedWidth(32)
        browse2.clicked.connect(lambda: self._browse_dir(self._scan_root_edit))
        row2 = QHBoxLayout()
        row2.addWidget(self._scan_root_edit)
        row2.addWidget(browse2)
        
        label_scan = self.config_mgr.get_text("ui_dialog_settings_label_scan_root", "預設搜尋根目錄：") if self.config_mgr else "預設搜尋根目錄："
        f.addRow(label_scan, row2)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(100, 50000)
        self._limit_spin.setSingleStep(100)
        self._limit_spin.setValue(s.get("search_limit", 1000))
        
        label_limit = self.config_mgr.get_text("ui_dialog_settings_label_limit", "搜尋結果上限：") if self.config_mgr else "搜尋結果上限："
        f.addRow(label_limit, self._limit_spin)

        from PyQt6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        f.addRow(sep)

        note_nightly = self.config_mgr.get_text("ui_dialog_settings_nightly_note", "夜間自動掃描索引的執行時間（24小時制）") if self.config_mgr else "夜間自動掃描索引的執行時間（24小時制）"
        scan_note = QLabel(note_nightly)
        _note_qss = "color: {{textMuted}}; font-size: 11px;"
        if self._config_mgr:
            _note_qss = self._config_mgr.apply_theme_to_text(_note_qss)
        scan_note.setStyleSheet(_note_qss)
        f.addRow(scan_note)

        self._hour_spin = QSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setValue(s.get("nightly_scan_hour", 2))
        suffix_hour = self.config_mgr.get_text("ui_dialog_settings_hour_suffix", " 時") if self.config_mgr else " 時"
        self._hour_spin.setSuffix(suffix_hour)
        
        label_hour = self.config_mgr.get_text("ui_dialog_settings_label_nightly_hour", "夜間掃描時間：") if self.config_mgr else "夜間掃描時間："
        f.addRow(label_hour, self._hour_spin)

        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 59)
        self._min_spin.setValue(s.get("nightly_scan_minute", 0))
        suffix_min = self.config_mgr.get_text("ui_dialog_settings_min_suffix", " 分") if self.config_mgr else " 分"
        self._min_spin.setSuffix(suffix_min)
        
        label_min = self.config_mgr.get_text("ui_dialog_settings_label_nightly_minute", "分鐘：") if self.config_mgr else "分鐘："
        f.addRow(label_min, self._min_spin)

        return w

    def _tab_monitored(self, s: dict) -> QWidget:
        """移植原本獨立設定視窗的路徑管理清單"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 12, 16, 12)
        
        note_monitored = self.config_mgr.get_text("ui_dialog_settings_monitored_note", "設定 Master Node 掃描的來源資料夾（如 C:\\, K:\\Project）") if self.config_mgr else "設定 Master Node 掃描的來源資料夾（如 C:\\, K:\\Project）"
        note = QLabel(note_monitored)
        _note2_qss = "color: {{textMuted}}; font-size: 11px;"
        if self._config_mgr:
            _note2_qss = self._config_mgr.apply_theme_to_text(_note2_qss)
        note.setStyleSheet(_note2_qss)
        layout.addWidget(note)

        self._path_list = QListWidget()
        for p in s.get("monitored_paths", []):
            self._path_list.addItem(p)
        layout.addWidget(self._path_list)

        btn_row = QHBoxLayout()
        
        btn_add_text = self.config_mgr.get_text("ui_dialog_settings_btn_add_path", "新增路徑") if self.config_mgr else "新增路徑"
        add_btn = QPushButton(btn_add_text)
        add_btn.clicked.connect(self._on_add_monitored_path)
        
        btn_remove_text = self.config_mgr.get_text("ui_dialog_settings_btn_remove_path", "移除所選") if self.config_mgr else "移除所選"
        remove_btn = QPushButton(btn_remove_text)
        remove_btn.clicked.connect(self._on_remove_monitored_path)
        
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _on_add_monitored_path(self):
        title = self.config_mgr.get_text("ui_dialog_settings_dlg_select_dir", "選擇要監測的資料夾") if self.config_mgr else "選擇要監測的資料夾"
        path = QFileDialog.getExistingDirectory(self, title)
        if path:
            # 避免重複
            for i in range(self._path_list.count()):
                if self._path_list.item(i).text() == path: return
            self._path_list.addItem(path)

    def _on_remove_monitored_path(self):
        for item in self._path_list.selectedItems():
            self._path_list.takeItem(self._path_list.row(item))

    def _on_master_toggled(self, checked):
        if checked:
            title = self.config_mgr.get_text("ui_dialog_settings_auth_title", "權限驗證") if self.config_mgr else "權限驗證"
            msg = self.config_mgr.get_text("ui_dialog_settings_auth_msg", "開啟生產者模式請輸入密碼:") if self.config_mgr else "開啟生產者模式請輸入密碼:"
            txt, ok = QInputDialog.getText(self, title, msg, QLineEdit.EchoMode.Password)
            if not ok or txt != "1235":
                if ok: 
                    err_title = self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤"
                    err_auth = self.config_mgr.get_text("ui_dialog_settings_auth_err", "密碼不正確") if self.config_mgr else "密碼不正確"
                    QMessageBox.warning(self, err_title, err_auth)
                self._is_master_chk.setChecked(False)

    def _on_discover_clicked(self):
        self._discover_btn.setEnabled(False)
        detecting_text = self.config_mgr.get_text("ui_dialog_settings_detecting", "正在智慧偵測中...") if self.config_mgr else "正在智慧偵測中..."
        self._remote_root_edit.setPlaceholderText(detecting_text)
        
        # 💡 使用者建議：實位生命週期宣告，避免 GC 回收
        self._discovery_worker = PathDiscoveryWorker(self._config_mgr)
        self._discovery_worker.finished.connect(self._on_discovery_finished)
        self._discovery_worker.start()

    def _on_discovery_finished(self, path):
        self._discover_btn.setEnabled(True)
        if path:
            self._remote_root_edit.setText(path)
            # 綠色閃爍視覺回饋
            _ok_qss = "background-color: {{success}}; color: {{text}};"
            self._remote_root_edit.setStyleSheet(self._config_mgr.apply_theme_to_text(_ok_qss) if self._config_mgr else _ok_qss)
            QTimer.singleShot(1000, lambda: self._remote_root_edit.setStyleSheet(""))
            
            title = self.config_mgr.get_text("ui_dialog_settings_detect_success_title", "偵測成功") if self.config_mgr else "偵測成功"
            msg = self.config_mgr.get_text("ui_dialog_settings_detect_success_msg", "已尋獲索引存放區：\n{}").format(path) if self.config_mgr else f"已尋獲索引存放區：\n{path}"
            QMessageBox.information(self, title, msg)
        else:
            detect_fail = self.config_mgr.get_text("ui_dialog_settings_detect_fail", "偵測失敗，請手動指定") if self.config_mgr else "偵測失敗，請手動指定"
            self._remote_root_edit.setPlaceholderText(detect_fail)
            
            title = self.config_mgr.get_text("ui_dialog_settings_detect_fail_title", "偵測失敗") if self.config_mgr else "偵測失敗"
            msg = self.config_mgr.get_text("ui_dialog_settings_detect_fail_msg", "無法自動定位網路索引，請手動選擇資料夾。") if self.config_mgr else "無法自動定位網路索引，請手動選擇資料夾。"
            QMessageBox.warning(self, title, msg)

    def _browse_dir(self, edit: QLineEdit) -> None:
        title = self.config_mgr.get_text("ui_dialog_settings_dlg_select_dir_general", "選擇資料夾") if self.config_mgr else "選擇資料夾"
        path = QFileDialog.getExistingDirectory(self, title, edit.text() or "")
        if path:
            edit.setText(path)

    # ── Tab 4: 預覽與檔案 ──────────────────────────────────────────────────────

    def _tab_preview(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        self._preview_font_spin = QSpinBox()
        self._preview_font_spin.setRange(9, 24)
        self._preview_font_spin.setValue(s.get("preview_font_size", 13))
        self._preview_font_spin.setSuffix(" px")
        
        label_font = self.config_mgr.get_text("ui_dialog_settings_label_preview_font", "預覽字體大小：") if self.config_mgr else "預覽字體大小："
        f.addRow(label_font, self._preview_font_spin)

        chk_confirm_delete = self.config_mgr.get_text("ui_dialog_settings_confirm_delete", "刪除檔案前顯示確認視窗") if self.config_mgr else "刪除檔案前顯示確認視窗"
        self._confirm_delete_chk = QCheckBox(chk_confirm_delete)
        self._confirm_delete_chk.setChecked(s.get("confirm_before_delete", True))
        
        label_del = self.config_mgr.get_text("ui_dialog_settings_label_delete", "刪除防呆：") if self.config_mgr else "刪除防呆："
        f.addRow(label_del, self._confirm_delete_chk)

        ai_s = self._config_mgr.get_ai_exporter_settings()
        self._ai_exclude_edit = QLineEdit(", ".join(ai_s.get("blacklist_dirs", [])))
        placeholder_ai = self.config_mgr.get_text("ui_dialog_settings_ai_exclude_placeholder", "例如: node_modules, .git") if self.config_mgr else "例如: node_modules, .git"
        self._ai_exclude_edit.setPlaceholderText(placeholder_ai)
        
        label_ai = self.config_mgr.get_text("ui_dialog_settings_label_ai_exclude", "AI 匯出排除目錄：") if self.config_mgr else "AI 匯出排除目錄："
        f.addRow(label_ai, self._ai_exclude_edit)

        return w

    # ── Tab 5: 貼上設定 ────────────────────────────────────────────────────────

    def _tab_paste(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        note_paste = self.config_mgr.get_text("ui_dialog_settings_paste_note", "「貼上為檔案」功能的命名規則（支援 strftime 格式）") if self.config_mgr else "「貼上為檔案」功能的命名規則（支援 strftime 格式）"
        note = QLabel(note_paste)
        _paste_note_qss = "color: {{textMuted}}; font-size: 11px;"
        if self._config_mgr:
            _paste_note_qss = self._config_mgr.apply_theme_to_text(_paste_note_qss)
        note.setStyleSheet(_paste_note_qss)
        note.setWordWrap(True)
        f.addRow(note)

        default_img_prefix = self.config_mgr.get_text("paste_prefix_image", "剪貼圖") if self.config_mgr else "剪貼圖"
        self._img_prefix_edit = QLineEdit(s.get("image_prefix", default_img_prefix))
        label_img_p = self.config_mgr.get_text("ui_dialog_settings_label_img_prefix", "圖片前綴：") if self.config_mgr else "圖片前綴："
        f.addRow(label_img_p, self._img_prefix_edit)

        self._img_format_edit = QLineEdit(s.get("image_format", "%Y%m%d_%H%M%S"))
        self._img_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._img_format_edit.textChanged.connect(self._update_format_preview)
        label_img_f = self.config_mgr.get_text("ui_dialog_settings_label_img_format", "圖片日期格式：") if self.config_mgr else "圖片日期格式："
        f.addRow(label_img_f, self._img_format_edit)

        default_txt_prefix = self.config_mgr.get_text("paste_prefix_text", "文字筆記") if self.config_mgr else "文字筆記"
        self._txt_prefix_edit = QLineEdit(s.get("text_prefix", default_txt_prefix))
        label_txt_p = self.config_mgr.get_text("ui_dialog_settings_label_txt_prefix", "文字前綴：") if self.config_mgr else "文字前綴："
        f.addRow(label_txt_p, self._txt_prefix_edit)

        self._txt_format_edit = QLineEdit(s.get("text_format", "%Y%m%d_%H%M%S"))
        self._txt_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._txt_format_edit.textChanged.connect(self._update_format_preview)
        label_txt_f = self.config_mgr.get_text("ui_dialog_settings_label_txt_format", "文字日期格式：") if self.config_mgr else "文字日期格式："
        f.addRow(label_txt_f, self._txt_format_edit)

        self._format_preview_label = QLabel()
        _preview_qss = "color: {{accent}}; font-size: 11px; font-weight: bold;"
        if self._config_mgr:
            _preview_qss = self._config_mgr.apply_theme_to_text(_preview_qss)
        self._format_preview_label.setStyleSheet(_preview_qss)
        
        label_preview = self.config_mgr.get_text("ui_dialog_settings_label_preview", "💡 預覽：") if self.config_mgr else "💡 預覽："
        f.addRow(label_preview, self._format_preview_label)
        
        self._update_format_preview()
        return w

    def _update_format_preview(self):
        """實作雙層防護網 (Item 2)"""
        fmt_img = self._img_format_edit.text().strip()
        fmt_txt = self._txt_format_edit.text().strip()
        
        try:
            # 1. 測試 strftime 有效性
            ts = datetime.datetime.now()
            out_img = ts.strftime(fmt_img)
            out_txt = ts.strftime(fmt_txt)
            
            # 2. Regex 校驗：不可包含 Windows 禁用的檔名符號
            invalid_chars = r'[\\/:*?"<>|]'
            if re.search(invalid_chars, out_img) or re.search(invalid_chars, out_txt):
                err_invalid = self.config_mgr.get_text("ui_dialog_settings_err_format_invalid", r"包含非法檔名字元 (如 : / \ * 等)") if self.config_mgr else r"包含非法檔名字元 (如 : / \ * 等)"
                raise ValueError(err_invalid)
                
            self._format_preview_label.setText(f"圖：{self._img_prefix_edit.text()}{out_img}.png\n文：{self._txt_prefix_edit.text()}{out_txt}.txt")
            _ok = "color: {{accent}};"
            self._format_preview_label.setStyleSheet(self._config_mgr.apply_theme_to_text(_ok) if self._config_mgr else _ok)

            # Enable save button (find it in root layout)
            self._set_save_enabled(True)

        except Exception as e:
            err_tpl = self.config_mgr.get_text("ui_dialog_settings_err_format", "⚠️ 格式錯誤: {}") if self.config_mgr else "⚠️ 格式錯誤: {}"
            self._format_preview_label.setText(err_tpl.format(str(e)))
            _err = "color: {{danger}};"
            self._format_preview_label.setStyleSheet(self._config_mgr.apply_theme_to_text(_err) if self._config_mgr else _err)
            self._set_save_enabled(False)

    def _set_save_enabled(self, enabled):
        # 遍歷尋找儲存按鈕並設定狀態
        btn_save_text = self.config_mgr.get_text("ui_dialog_settings_btn_save", "完成並儲存") if self.config_mgr else "完成並儲存"
        for btn in self.findChildren(QPushButton):
            if btn.text() == btn_save_text:
                btn.setEnabled(enabled)
                break

    # ── Accept / Reject ────────────────────────────────────────────────────────

    def accept(self) -> None:
        internal_theme = self._theme_map.get(self._theme_combo.currentText(), self._theme_combo.currentText())
        self._config_mgr.apply_theme_preset(internal_theme)
        
        # 整理路徑清單
        m_paths = [self._path_list.item(i).text() for i in range(self._path_list.count())]
        
        self._config_mgr.save_app_settings({
            "restore_last_session":  self._restore_session_chk.isChecked(),
            "remote_index_root":     self._remote_root_edit.text().strip(),
            "default_scan_root":     self._scan_root_edit.text().strip(),
            "search_limit":          self._limit_spin.value(),
            "nightly_scan_hour":     self._hour_spin.value(),
            "nightly_scan_minute":   self._min_spin.value(),
            "preview_font_size":     self._preview_font_spin.value(),
            "confirm_before_delete": self._confirm_delete_chk.isChecked(),
            "image_prefix":          self._img_prefix_edit.text().strip(),
            "text_prefix":           self._txt_prefix_edit.text().strip(),
            "image_format":          self._img_format_edit.text().strip(),
            "text_format":           self._txt_format_edit.text().strip(),
            "is_master_node":        self._is_master_chk.isChecked(),
            "monitored_paths":       m_paths,
            "ai_blacklist_dirs":     [d.strip() for d in self._ai_exclude_edit.text().split(",") if d.strip()],
            "language":              self._lang_options[self._lang_combo.currentIndex()][1],
        })
        self.theme_changed.emit()

        new_lang = self._lang_options[self._lang_combo.currentIndex()][1]
        if new_lang != self._backup_lang:
            title = self.config_mgr.get_text("ui_dialog_settings_lang_changed_title", "語言已變更") if self.config_mgr else "語言已變更"
            msg = self.config_mgr.get_text("ui_dialog_settings_lang_changed_msg", "語言設定已儲存，重新啟動應用程式後生效。") if self.config_mgr else "語言設定已儲存，重新啟動應用程式後生效。"
            QMessageBox.information(self, title, msg)

        super().accept()

    def reject(self) -> None:
        self._block_theme_signal = True
        self._config_mgr.apply_theme_preset(self._backup_theme)
        self._block_theme_signal = False
        self.theme_changed.emit()
        super().reject()
