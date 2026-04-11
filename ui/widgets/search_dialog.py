import os, datetime
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QCheckBox, QMenu, QToolButton, QTreeView, QProgressBar,
    QStatusBar, QFileIconProvider, QMessageBox, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer, QFileInfo, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem
from core.interfaces import ISearchView
from ui.presenters.search_presenter import SearchPresenter


class DateSortProxyModel(QSortFilterProxyModel):
    """Custom proxy to support numeric sorting for Date and Size columns."""
    def lessThan(self, left, right):
        if not left.isValid() or not right.isValid():
            return super().lessThan(left, right)

        col = left.column()
        left_data = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_data = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)

        if col in (2, 3):
            if left_data is not None and right_data is not None:
                try:
                    return float(left_data) < float(right_data)
                except (TypeError, ValueError):
                    pass
            if left_data is None: return True
            if right_data is None: return False

        return super().lessThan(left, right)


class SearchDialog(QDialog):
    def __init__(self, root_path, parent=None):
        super().__init__(parent)
        self.resize(1000, 700)
        self.root_path = root_path

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)

        config_mgr = getattr(parent, 'config_mgr', None)
        if not config_mgr and parent:
            config_mgr = getattr(parent.parent(), 'config_mgr', None)
        self.config_mgr = config_mgr
        base_title = self.config_mgr.get_text("ui_dialog_search_title", "進階搜尋") if self.config_mgr else "進階搜尋"
        self.setWindowTitle(f"{base_title} - {os.path.basename(root_path)}")

        class _SearchViewAdapter(ISearchView):
            def __init__(self, dlg): self.dlg = dlg
            def add_result(self, path, mtime, size, context=""): self.dlg.add_result(path, mtime, size)
            def show_progress(self, text): self.dlg.status_label.setText(text)
            def search_finished(self, count): self.dlg.search_finished(count)

        self.presenter = SearchPresenter(_SearchViewAdapter(self), config_mgr)
        self.active_workers = []
        self.thread = None
        self.icon_provider = QFileIconProvider()

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.start_search)

        self._init_ui()
        self.showMaximized()

        QTimer.singleShot(100, self._run_background_sync)

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 5)
        self.main_layout.setSpacing(10)

        if self.presenter.config_mgr:
            qss = self.presenter.config_mgr.load_stylesheet("network_search/styles.qss", "theme.json")
            if qss:
                self.setStyleSheet(qss)

        input_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_search_placeholder", "輸入關鍵字搜尋 (例如: .pdf 或 文件名)...")
            if self.config_mgr else "輸入關鍵字搜尋 (例如: .pdf 或 文件名)..."
        )
        self.search_input.textChanged.connect(self.on_search_text_changed)
        input_row.addWidget(self.search_input)
        self.main_layout.addLayout(input_row)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)

        config = self.presenter.config_mgr.load_config()
        default_root = config.get("default_scan_root", "C:\\")

        self.network_k_cb = QCheckBox(self.config_mgr.get_text("ui_dialog_search_network_share", "網路共享 ({})").format(default_root) if self.config_mgr else f"網路共享 ({default_root})")
        self.network_k_cb.setChecked(True)
        self.network_k_cb.toggled.connect(self.start_search)

        self.local_global_cb = QCheckBox(self.config_mgr.get_text("ui_dialog_search_local_global", "本機全域") if self.config_mgr else "本機全域")
        self.local_global_cb.setChecked(True)
        self.local_global_cb.toggled.connect(self.on_scope_toggled)

        control_row.addWidget(self.network_k_cb)
        control_row.addWidget(self.local_global_cb)

        self.k_settings_btn = QToolButton()
        self.k_settings_btn.setText(self.config_mgr.get_text("ui_dialog_search_settings", "⚙設定") if self.config_mgr else "⚙設定")
        self.k_settings_btn.setToolTip(self.config_mgr.get_text("ui_dialog_search_settings_tooltip", "網路索引管理與角色設定") if self.config_mgr else "網路索引管理與角色設定")
        self.k_settings_btn.clicked.connect(self.open_k_settings)
        self.k_settings_btn.setMinimumWidth(60)

        self.k_refresh_btn = QToolButton()
        self.k_refresh_btn.setText(self.config_mgr.get_text("ui_dialog_search_refresh", "🔄更新") if self.config_mgr else "🔄更新")
        self.k_refresh_btn.setToolTip(self.config_mgr.get_text("ui_dialog_search_refresh_tooltip", "更新索引 (生產者掃描 / 消費者檢查更新)") if self.config_mgr else "更新索引 (生產者掃描 / 消費者檢查更新)")
        self.k_refresh_btn.clicked.connect(self.start_k_scan)
        self.k_refresh_btn.setMinimumWidth(60)

        control_row.addWidget(self.k_settings_btn)
        control_row.addWidget(self.k_refresh_btn)
        control_row.addStretch()
        self.main_layout.addLayout(control_row)

        self.size_btn_group = QHBoxLayout()
        self.size_btn_group.setSpacing(2)
        self.size_btns = []
        self.current_size_idx = 0
        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {"size_labels": ["全部", "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"]}
        sizes = filters.get("size_labels", ["全部", "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"])
        for i, label in enumerate(sizes):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_size_btn_clicked(idx))
            self.size_btn_group.addWidget(btn)
            self.size_btns.append(btn)

        self.time_btn_group = QHBoxLayout()
        self.time_btn_group.setSpacing(2)
        self.time_btns = []
        self.current_time_idx = 0
        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {"time_labels": ["全部", "🕒 今日", "📅 本週", "本月"]}
        time_labels = filters.get("time_labels", ["全部", "🕒 今日", "📅 本週", "本月"])
        for i, label in enumerate(time_labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_time_btn_clicked(idx))
            self.time_btn_group.addWidget(btn)
            self.time_btns.append(btn)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel(self.config_mgr.get_text("ui_dialog_search_size_label", "大小:") if self.config_mgr else "大小:"))
        size_row.addLayout(self.size_btn_group)
        size_row.addStretch()
        self.main_layout.addLayout(size_row)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel(self.config_mgr.get_text("ui_dialog_search_time_label", "時間:") if self.config_mgr else "時間:"))
        time_row.addLayout(self.time_btn_group)

        self.path_display_label = QLabel(f"搜尋目錄: {self.root_path}")
        _path_qss = "color: {{textMuted}}; font-size: 11px;"
        if self.presenter.config_mgr:
            _path_qss = self.presenter.config_mgr.apply_theme_to_text(_path_qss)
        self.path_display_label.setStyleSheet(_path_qss)
        time_row.addStretch()
        time_row.addWidget(self.path_display_label)
        self.main_layout.addLayout(time_row)

        self._update_size_btn_styles()
        self._update_time_btn_styles()

        self.progress_layout = QVBoxLayout()
        self.sync_status_label = QLabel(self.config_mgr.get_text("ui_dialog_search_status_init", "正在初始化...") if self.config_mgr else "正在初始化...")
        _status_qss = "color: {{accent}}; font-weight: bold; padding: 2px;"
        if self.presenter.config_mgr:
            _status_qss = self.presenter.config_mgr.apply_theme_to_text(_status_qss)
        self.sync_status_label.setStyleSheet(_status_qss)

        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setFixedHeight(6)
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_bar.setTextVisible(False)

        self.progress_layout.addWidget(self.sync_status_label)
        self.progress_layout.addWidget(self.scan_progress_bar)
        self.main_layout.addLayout(self.progress_layout)

        self._update_role_status_ui()

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

        self.model = QStandardItemModel(0, 5)
        self.model.setHorizontalHeaderLabels([
            "📂",
            self.config_mgr.get_text("ui_dialog_search_col_name", "名稱") if self.config_mgr else "名稱",
            self.config_mgr.get_text("ui_dialog_search_col_date", "修改日期") if self.config_mgr else "修改日期",
            self.config_mgr.get_text("ui_dialog_search_col_size", "大小") if self.config_mgr else "大小",
            self.config_mgr.get_text("ui_dialog_search_col_path", "完整路徑") if self.config_mgr else "完整路徑",
        ])

        self.proxy_model = DateSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)

        self.tree.setModel(self.proxy_model)

        header_view = self.tree.header()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(0, 30)
        self.tree.setColumnWidth(1, 300)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 80)

        self.main_layout.addWidget(self.tree)

        self.scan_progress_label = QLabel("")
        _prog_qss = "color: {{success}}; font-size: 11px;"
        if self.presenter.config_mgr:
            _prog_qss = self.presenter.config_mgr.apply_theme_to_text(_prog_qss)
        self.scan_progress_label.setStyleSheet(_prog_qss)
        self.scan_progress_label.hide()
        self.main_layout.addWidget(self.scan_progress_label)

        self.status_bar = QStatusBar()
        self.status_label = QLabel(self.config_mgr.get_text("ui_dialog_search_status_ready", "請輸入關鍵字開始搜尋") if self.config_mgr else "請輸入關鍵字開始搜尋")
        self.status_bar.addWidget(self.status_label)
        self.main_layout.addWidget(self.status_bar)

    def on_search_text_changed(self, text: str) -> None:
        self.search_timer.start(300)

    def on_scope_toggled(self, checked: bool) -> None:
        is_any_global = self.local_global_cb.isChecked() or self.network_k_cb.isChecked()
        self.path_display_label.setDisabled(is_any_global)
        self.start_search()

    def closeEvent(self, event) -> None:
        self.presenter.stop_search()
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

    def start_search(self) -> None:
        keyword = self.search_input.text().strip()
        if not keyword and not self.network_k_cb.isChecked():
            self.status_label.setText(self.config_mgr.get_text("ui_dialog_search_warn_no_keyword", "請輸入關鍵字") if self.config_mgr else "請輸入關鍵字")
            return

        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        self.status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_searching", "正在搜尋...") if self.config_mgr else "正在搜尋...")

        min_mtime = 0
        now = datetime.datetime.now()
        if self.current_time_idx == 1:
            min_mtime = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        elif self.current_time_idx == 2:
            monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            min_mtime = monday.timestamp()
        elif self.current_time_idx == 3:
            first_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            min_mtime = first_day.timestamp()

        filters = self.presenter.config_mgr.get_search_filters() if self.presenter.config_mgr else {}
        size_map = filters.get("size_thresholds", {"0": 0, "1": 1*1024*1024, "2": 10*1024*1024, "3": 100*1024*1024, "4": 1024*1024*1024})
        min_size_val = size_map.get(str(self.current_size_idx), size_map.get(self.current_size_idx, 0))

        conditions = {
            'path': self.root_path,
            'pattern': f"*{keyword}*" if keyword else "*",
            'use_global': self.local_global_cb.isChecked(),
            'use_k': self.network_k_cb.isChecked(),
            'min_size': min_size_val,
            'min_mtime': min_mtime,
            'limit': 1000
        }

        if conditions['use_global'] and not self.presenter.check_personal_db_exists():
            self.status_label.setText(self.config_mgr.get_text("ui_dialog_search_tip_no_local_db", "提示：本機索引尚未建立，建議點擊「🔄更新」以獲得最佳搜尋速度") if self.config_mgr else "提示：本機索引尚未建立，建議點擊「🔄更新」以獲得最佳搜尋速度")

        self.presenter.start_search(conditions)

    def on_size_btn_clicked(self, index: int) -> None:
        self.current_size_idx = index
        self._update_size_btn_styles()
        self.start_search()

    def on_time_btn_clicked(self, index: int) -> None:
        self.current_time_idx = index
        self._update_time_btn_styles()
        self.start_search()

    def _update_size_btn_styles(self) -> None:
        tc = self.presenter.config_mgr.get_theme_colors() if self.presenter.config_mgr else {}
        active_color = tc.get("activeTab", "#2d5a8e")
        accent = tc.get("accent", "#58A6FF")
        dark = tc.get("bg", "#1e2128")
        active_style = f"background-color: {active_color}; color: white; font-weight: bold; border-top: 1px solid {accent}; border-bottom: 2px solid {dark};"
        inactive_style = "background-color: {{surfaceSubtle}}; color: {{textMuted}}; border: 1px solid {{border}};"
        if self.presenter.config_mgr:
            inactive_style = self.presenter.config_mgr.apply_theme_to_text(inactive_style)
        for i, btn in enumerate(self.size_btns):
            btn.setChecked(i == self.current_size_idx)
            btn.setStyleSheet(active_style if i == self.current_size_idx else inactive_style)

    def _update_time_btn_styles(self) -> None:
        tc = self.presenter.config_mgr.get_theme_colors() if self.presenter.config_mgr else {}
        active_color = tc.get("activeTab", "#2d5a8e")
        accent = tc.get("accent", "#58A6FF")
        dark = tc.get("bg", "#1e2128")
        active_style = f"background-color: {active_color}; color: white; font-weight: bold; border-top: 1px solid {accent}; border-bottom: 2px solid {dark};"
        inactive_style = "background-color: {{surfaceSubtle}}; color: {{textMuted}}; border: 1px solid {{border}};"
        if self.presenter.config_mgr:
            inactive_style = self.presenter.config_mgr.apply_theme_to_text(inactive_style)
        for i, btn in enumerate(self.time_btns):
            btn.setChecked(i == self.current_time_idx)
            btn.setStyleSheet(active_style if i == self.current_time_idx else inactive_style)

    def add_result(self, path: str, mtime: float = None, size: int = None) -> None:
        name = os.path.basename(path)
        dir_path = os.path.dirname(path)

        item_locate = QStandardItem("📂")
        item_locate.setToolTip(self.config_mgr.get_text("ui_dialog_search_tooltip_locate", "前往路徑 (在主視窗中定位)") if self.config_mgr else "前往路徑 (在主視窗中定位)")
        item_locate.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_locate.setForeground(Qt.GlobalColor.blue)

        item_name = QStandardItem(name)
        info = QFileInfo(path)
        icon = self.icon_provider.icon(info)
        item_name.setIcon(icon)
        item_name.setData(path, Qt.ItemDataRole.UserRole)

        date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
        item_date = QStandardItem(date_str)
        item_date.setData(float(mtime) if mtime else 0.0, Qt.ItemDataRole.UserRole)

        size_str = self._format_size(size) if size else "0 B"
        item_size = QStandardItem(size_str)
        item_size.setData(float(size) if size else 0.0, Qt.ItemDataRole.UserRole)

        item_path = QStandardItem(dir_path)
        item_path.setForeground(Qt.GlobalColor.gray)
        item_path.setData(dir_path, Qt.ItemDataRole.UserRole)

        self.model.appendRow([item_locate, item_name, item_date, item_size, item_path])

    def _format_size(self, size: int) -> str:
        if not size: return "0 B"
        s = float(size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if s < 1024.0: return f"{s:.1f} {unit}"
            s /= 1024.0
        return f"{s:.1f} TB"

    def search_finished(self, count: int) -> None:
        self.status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_finished", "搜尋完成，共找到 {} 個項目").format(count) if self.config_mgr else f"搜尋完成，共找到 {count} 個項目")
        header = self.tree.header()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.proxy_model.sort(sort_col, sort_order)
        self.tree.setSortingEnabled(True)
        if self.parent() and hasattr(self.parent(), 'statusBar'):
            self.parent().statusBar().showMessage(self.config_mgr.get_text("ui_dialog_search_status_finished", "搜尋完成，共找到 {} 個項目").format(count) if self.config_mgr else f"搜尋完成，共找到 {count} 個項目", 8000)

    def on_item_clicked(self, index) -> None:
        if index.column() == 0:
            source_index = self.proxy_model.mapToSource(index)
            item = self.model.item(source_index.row(), 1)
            path = item.data(Qt.ItemDataRole.UserRole)
            pane = self.parent()
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
                self.accept()

    def on_item_double_clicked(self, index) -> None:
        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        item = self.model.item(row, 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        if os.path.exists(path):
            os.startfile(path)
            self.accept()
        else:
            QMessageBox.warning(self, self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤", self.config_mgr.get_text("ui_dialog_search_err_file_not_exist", "檔案不存在: {}").format(path) if self.config_mgr else f"檔案不存在: {path}")

    def on_context_menu(self, pos) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid(): return
        source_index = self.proxy_model.mapToSource(index)
        item = self.model.item(source_index.row(), 1)
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        open_act = menu.addAction(self.config_mgr.get_text("ui_dialog_search_menu_open", "開啟檔案") if self.config_mgr else "開啟檔案")
        open_folder_act = menu.addAction("開啟所在資料夾")
        jump_act = menu.addAction(self.config_mgr.get_text("ui_dialog_search_menu_locate", "在主視窗中定位") if self.config_mgr else "在主視窗中定位")
        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action == open_act:
            os.startfile(path)
        elif action == open_folder_act:
            os.startfile(os.path.dirname(path))
        elif action == jump_act:
            pane = self.parent()
            if pane and hasattr(pane, 'jump_to_file'):
                pane.jump_to_file(path)
            self.accept()

    def _update_role_status_ui(self) -> None:
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")
        _tc = self.presenter.config_mgr.get_theme_colors() if self.presenter.config_mgr else {}
        _accent = _tc.get("accent", "#58A6FF")
        _muted = _tc.get("textMuted", "#8B949E")
        _success = _tc.get("success", "#57B77F")
        if is_master:
            self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_role_master", "🛠️ 生產管理模式...") if self.config_mgr else "🛠️ 生產管理模式...")
            self.sync_status_label.setStyleSheet(f"color: {_accent}; font-weight: bold;")
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(self.config_mgr.get_text("ui_dialog_search_refresh_tooltip_local", "手動更新個人本機索引...") if self.config_mgr else "手動更新個人本機索引...")
        elif not remote_root:
            self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_role_local", "✅ 本機搜尋模式") if self.config_mgr else "✅ 本機搜尋模式")
            self.sync_status_label.setStyleSheet(f"color: {_muted};")
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(self.config_mgr.get_text("ui_dialog_search_refresh_tooltip_local", "手動更新個人本機索引...") if self.config_mgr else "手動更新個人本機索引...")
        else:
            slot = self.presenter.config_mgr.get_active_slot()
            self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_role_consumer", "🌐 消費者模式 (Slot {})...").format(slot) if self.config_mgr else f"🌐 消費者模式 (Slot {slot})...")
            self.sync_status_label.setStyleSheet(f"color: {_success};")
            self.k_refresh_btn.setEnabled(True)
            self.k_refresh_btn.setToolTip(self.config_mgr.get_text("ui_dialog_search_refresh_tooltip_local", "手動更新個人本機索引...") if self.config_mgr else "手動更新個人本機索引...")

    def _update_search_mgr(self) -> None:
        self.presenter.reload_config()
        self._update_role_status_ui()

    def _run_background_sync(self) -> None:
        config = self.presenter.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        remote_root = config.get("remote_index_root")
        if not remote_root:
            self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_local_only", "✅ 本機模式") if self.config_mgr else "✅ 本機模式")
            return
        if is_master:
            if not os.path.exists(remote_root):
                self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_err_remote_failed", "❌ 警告: 共享路徑存取失敗 {}").format(remote_root) if self.config_mgr else f"❌ 警告: 共享路徑存取失敗 {remote_root}")
            return
        self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_connected", "✅ 已連接至團隊共享索引...") if self.config_mgr else "✅ 已連接至團隊共享索引...")
        self._update_role_status_ui()

    def open_k_settings(self) -> None:
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
                _share_text = self.config_mgr.get_text("ui_dialog_search_network_share", "網路共享 ({})").format(config.get('default_scan_root', 'K:\\')) if self.config_mgr else f"網路共享 ({config.get('default_scan_root', 'K:\\')})"
                self.network_k_cb.setText(_share_text)
                self._update_search_mgr()
        except Exception as e:
            QMessageBox.critical(self, self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤", self.config_mgr.get_text("ui_dialog_search_err_open_settings", "無法開啟設定: {}").format(e) if self.config_mgr else f"無法開啟設定: {e}")

    def start_k_scan(self, target_db: str = "local") -> None:
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
            if local_drives:
                configs_c = [(os.path.normpath(p), 99) for p in local_drives if os.path.exists(p)]
                if configs_c:
                    self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scanning_local", "正在掃描本機全域 (Personal)...") if self.config_mgr else "正在掃描本機全域 (Personal)...")
                    sc_c = ScannerWorker(
                        configs_c,
                        self.presenter.index_mgr,
                        target_db="personal",
                        exclude_dirs=config.get("exclude_dirs", [])
                    )
                    self.active_workers.append(sc_c)
                    sc_c.progress.connect(lambda p: self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scanning_path", "掃描本機: {}").format(os.path.basename(p)) if self.config_mgr else f"掃描本機: {os.path.basename(p)}"))
                    sc_c.files_indexed.connect(lambda c: self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scanning_count", "本機掃描中... 已索引 {} 個項目").format(c) if self.config_mgr else f"本機掃描中... 已索引 {c} 個項目"))
                    sc_c.finished.connect(lambda: self.active_workers.remove(sc_c) if sc_c in self.active_workers else None)
                    if not has_network_scan:
                        sc_c.finished.connect(self.on_k_scan_finished)
                    sc_c.start()
            if has_network_scan:
                QTimer.singleShot(1000, lambda: self._run_network_scan(configs_k, remote_dir))
            self.k_refresh_btn.setEnabled(False)
            self.scan_progress_bar.setVisible(True)
            self.scan_progress_bar.setRange(0, 0)
        except Exception as e:
            QMessageBox.critical(self, self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤", self.config_mgr.get_text("ui_dialog_search_err_start_scan", "無法啟動掃描: {}").format(e) if self.config_mgr else f"無法啟動掃描: {e}")

    def _run_network_scan(self, configs: list, remote_dir: str) -> None:
        from network_search.engine import ScannerWorker
        self.planner_scanner = ScannerWorker(
            configs,
            self.presenter.index_mgr,
            remote_db_dir=remote_dir,
            target_db="local"
        )
        self.active_workers.append(self.planner_scanner)
        self.planner_scanner.progress.connect(lambda p: self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scanning_k", "掃描 K 槽: {}").format(os.path.basename(p)) if self.config_mgr else f"掃描 K 槽: {os.path.basename(p)}"))
        self.planner_scanner.files_indexed.connect(lambda c: self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scanning_k_count", "K 槽掃描中... 已發現 {} 個檔案").format(c) if self.config_mgr else f"K 槽掃描中... 已發現 {c} 個檔案"))
        self.planner_scanner.finished.connect(lambda: self.active_workers.remove(self.planner_scanner) if self.planner_scanner in self.active_workers else None)
        self.planner_scanner.finished.connect(self.on_k_scan_finished)
        self.planner_scanner.start()

    def on_k_scan_finished(self, count: int) -> None:
        self.k_refresh_btn.setEnabled(True)
        self.scan_progress_bar.setVisible(False)
        self.sync_status_label.setText(self.config_mgr.get_text("ui_dialog_search_status_scan_finished", "✅ 掃描完成！共索引 {} 個項目").format(count) if self.config_mgr else f"✅ 掃描完成！共索引 {count} 個項目")
        _ok_qss = "color: {{text}}; background-color: {{success}}; border-radius: 4px; padding: 4px; font-weight: bold;"
        if self.presenter.config_mgr:
            _ok_qss = self.presenter.config_mgr.apply_theme_to_text(_ok_qss)
        self.sync_status_label.setStyleSheet(_ok_qss)
        QTimer.singleShot(5000, lambda: self._update_role_status_ui())
        self.start_search()
