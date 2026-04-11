from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QProgressBar, QStatusBar,
    QFileDialog, QDialog, QFormLayout, QMessageBox,
    QTreeView, QHeaderView, QMenu, QListWidget, QListWidgetItem,
    QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QFileInfo, QDateTime
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction, QFont, QColor
from PyQt6.QtWidgets import QFileIconProvider, QApplication

import os
import datetime


class SettingsDialog(QDialog):
    """搜尋模組設定對話框"""

    def __init__(self, config, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.config_mgr = config_mgr
        title = self.config_mgr.get_text("ns_settings_title", "搜尋模組設定") if self.config_mgr else "搜尋模組設定"
        self.setWindowTitle(title)
        self.resize(500, 450)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.default_root_edit = QLineEdit(
            self.config.get("default_scan_root", "C:\\"))
        self.default_root_edit.setPlaceholderText("例如: K:\\, D:\\, E:\\")
        label_root = self.config_mgr.get_text("ns_settings_default_root", "預設自動掃描根目錄:") if self.config_mgr else "預設自動掃描根目錄:"
        form.addRow(label_root, self.default_root_edit)

        self.remote_db_edit = QLineEdit(
            self.config.get("search_db_master", ""))
        self.remote_db_edit.setPlaceholderText("例如: Z:\\Index\\nas_files.db")
        browse_text = self.config_mgr.get_text("ns_settings_browse", "瀏覽") if self.config_mgr else "瀏覽"
        master_btn = QPushButton(browse_text)
        master_btn.clicked.connect(self.on_browse_master)

        master_layout = QHBoxLayout()
        master_layout.addWidget(self.remote_db_edit)
        master_layout.addWidget(master_btn)
        label_net = self.config_mgr.get_text("ns_settings_network_db", "網路母檔路徑:") if self.config_mgr else "網路母檔路徑:"
        form.addRow(label_net, master_layout)
        layout.addLayout(form)

        self.path_list = QListWidget()
        for p in self.config.get("monitored_paths", []):
            self.path_list.addItem(p)
        layout.addWidget(self.path_list)

        btn_layout = QHBoxLayout()
        add_text = self.config_mgr.get_text("ns_settings_add_path", "新增路徑") if self.config_mgr else "新增路徑"
        add_btn = QPushButton(add_text)
        add_btn.clicked.connect(self.on_add_path)
        remove_text = self.config_mgr.get_text("ns_settings_remove_selected", "刪除選取") if self.config_mgr else "刪除選取"
        remove_btn = QPushButton(remove_text)
        remove_btn.clicked.connect(self.on_remove_path)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        layout.addLayout(btn_layout)

        actions = QHBoxLayout()
        save_text = self.config_mgr.get_text("ns_settings_save", "儲存設定") if self.config_mgr else "儲存設定"
        save_btn = QPushButton(save_text)
        save_btn.clicked.connect(self.accept)
        cancel_text = self.config_mgr.get_text("ns_settings_cancel", "取消") if self.config_mgr else "取消"
        cancel_btn = QPushButton(cancel_text)
        cancel_btn.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(save_btn)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def on_browse_master(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self.config_mgr.get_text("ns_settings_browse_title", "選擇網路母檔位置") if self.config_mgr else "選擇網路母檔位置", "", "SQLite DB (*.db)")
        if path:
            self.remote_db_edit.setText(path)

    def on_add_path(self):
        path = QFileDialog.getExistingDirectory(self, self.config_mgr.get_text("ns_settings_add_path_title", "選擇要監測的資料夾") if self.config_mgr else "選擇要監測的資料夾")
        if path:
            self.path_list.addItem(path)

    def on_remove_path(self):
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))

    def get_settings(self):
        paths = [self.path_list.item(i).text()
                 for i in range(self.path_list.count())]
        return {
            "default_scan_root": self.default_root_edit.text(),
            "search_db_master": self.remote_db_edit.text(),
            "monitored_paths": paths
        }


class NetworkSearchWindow(QWidget):
    """Independent search window for network files."""

    def __init__(self, engine_mgr, config_mgr=None):
        super().__init__()
        self.engine = engine_mgr
        self.config_mgr = config_mgr
        self.config = config_mgr.load_config() if config_mgr else {}
        self.scanner = None
        self.icon_provider = QFileIconProvider()

        # 搜尋去抖動 (Debouncing)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)

        self._init_ui()

    def _init_ui(self):
        title = self.config_mgr.get_text("ns_main_title", "網路搜尋") if self.config_mgr else "網路搜尋"
        self.setWindowTitle(title)
        self.resize(1000, 700)

        self.layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        self.search_input = QLineEdit()
        placeholder = self.config_mgr.get_text("ns_main_search_placeholder", "輸入關鍵字搜尋 (例如: .pdf 或 文件名)...") if self.config_mgr else "輸入關鍵字搜尋 (例如: .pdf 或 文件名)..."
        self.search_input.setPlaceholderText(placeholder)
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.setStyleSheet("font-size: 14px; padding: 5px;")

        size_filter_text = self.config_mgr.get_text("ns_main_size_filter", "僅顯示 > 1MB") if self.config_mgr else "僅顯示 > 1MB"
        self.size_filter_cb = QCheckBox(size_filter_text)
        self.size_filter_cb.stateChanged.connect(lambda: self._do_search())

        refresh_text = self.config_mgr.get_text("ns_main_refresh", "開始索引掃描") if self.config_mgr else "開始索引掃描"
        self.refresh_btn = QPushButton(refresh_text)
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        
        settings_text = self.config_mgr.get_text("ns_main_settings", "⚙ 設定") if self.config_mgr else "⚙ 設定"
        self.settings_btn = QPushButton(settings_text)
        self.settings_btn.clicked.connect(self.on_settings_clicked)

        header.addWidget(self.search_input)
        header.addWidget(self.size_filter_cb)
        header.addWidget(self.refresh_btn)
        header.addWidget(self.settings_btn)
        self.layout.addLayout(header)

        # Results TreeView
        self.tree = QTreeView()
        self.tree.setSelectionBehavior(
            QTreeView.SelectionBehavior.SelectRows)  # 整列選取
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.tree.setAllColumnsShowFocus(True)  # 焦點框涵蓋整行
        self.tree.setRootIsDecorated(False)     # 隱藏樹狀層次的展開箭頭
        self.tree.setIndentation(0)             # 移除縮排
        self.tree.setSortingEnabled(True)       # 啟用點擊表頭排序
        self.model = QStandardItemModel(0, 4)
        
        header_labels = [
            self.config_mgr.get_text("ns_header_name", "名稱") if self.config_mgr else "名稱",
            self.config_mgr.get_text("ns_header_date", "修改日期") if self.config_mgr else "修改日期",
            self.config_mgr.get_text("ns_header_size", "大小") if self.config_mgr else "大小",
            self.config_mgr.get_text("ns_header_path", "完整路徑") if self.config_mgr else "完整路徑"
        ]
        self.model.setHorizontalHeaderLabels(header_labels)
        self.tree.setModel(self.model)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        self.tree.doubleClicked.connect(self.on_item_double_clicked)

        header_view = self.tree.header()
        # 設定為 Interactive 讓使用者可手動調整，Stretch 則自動延伸
        header_view.setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive)  # 名稱
        header_view.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive)  # 修改日期
        header_view.setSectionResizeMode(
            2, QHeaderView.ResizeMode.Interactive)  # 大小
        header_view.setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch)      # 完整路徑 (自動填滿)

        # 預設寬度分配 (更符合直覺)
        self.tree.setColumnWidth(0, 250)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 80)

        # 視覺美化 QSS
        self.tree.setStyleSheet("""
            QTreeView {
                alternate-background-color: #f9f9f9;
                selection-background-color: #0078d7;
                selection-color: white;
                border: none;
                outline: 0;  /* 移除單個 Cell 的虛線框 */
            }
            QTreeView::item {
                padding: 5px;
            }
            QTreeView::item:hover {
                background-color: #e5f3ff;
            }
        """)

        self.layout.addWidget(self.tree)

        # Scanner progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # Footer
        self.status_bar = QStatusBar()
        self.layout.addWidget(self.status_bar)
        ready_msg = self.config_mgr.get_text("ns_status_ready", "資料庫準備就緒") if self.config_mgr else "資料庫準備就緒"
        self.status_bar.showMessage(ready_msg)

    def on_settings_clicked(self):
        dialog = SettingsDialog(self.config, config_mgr=self.config_mgr, parent=self)
        if dialog.exec():
            new_settings = dialog.get_settings()
            self.config.update(new_settings)
            if self.config_mgr:
                import json
                try:
                    with open(self.config_mgr.config_file, "w", encoding="utf-8") as f:
                        json.dump(self.config, f, ensure_ascii=False, indent=4)
                except:
                    pass

    def on_search_text_changed(self, text):
        # 重新計時 300ms
        self.search_timer.start(300)

    def _do_search(self):
        text = self.search_input.text()
        if len(text) < 2:
            self.model.removeRows(0, self.model.rowCount())
            return

        min_size = 1024 * 1024 if self.size_filter_cb.isChecked() else 0
        results = self.engine.search(text, min_size=min_size)
        self.model.removeRows(0, self.model.rowCount())

        bold_font = QFont()
        bold_font.setBold(True)
        gray_color = QColor("gray")

        unknown_text = self.config_mgr.get_text("ns_unknown", "未知") if self.config_mgr else "未知"
        invalid_text = self.config_mgr.get_text("ns_invalid", "無效") if self.config_mgr else "無效"
        error_text = self.config_mgr.get_text("ns_error", "錯誤") if self.config_mgr else "錯誤"

        for name, mtime, size, path in results:
            # 1. Name with Icon
            name_item = QStandardItem(name)
            name_item.setFont(bold_font)
            name_item.setIcon(self.icon_provider.icon(QFileInfo(path)))

            # 2. Date - 修復日期顯示問題 (使用 datetime.fromtimestamp)
            date_str = unknown_text
            date_val = 0
            if mtime is not None:
                try:
                    ts = float(mtime)
                    if 0 < ts < 4102444800:
                        dt = datetime.datetime.fromtimestamp(ts)
                        date_str = dt.strftime("%Y-%m-%d %H:%M")
                        date_val = int(ts)
                    else:
                        date_str = f"{invalid_text}:{ts}"
                except:
                    date_str = f"{error_text}:{mtime}"

            date_item = QStandardItem(date_str)
            date_item.setData(date_val, Qt.ItemDataRole.EditRole)

            # 3. Size 格式化
            size_raw = float(size) if size is not None else -1.0
            size_str = self._format_size(size)

            size_item = QStandardItem()
            size_item.setData(size_str, Qt.ItemDataRole.DisplayRole)
            size_item.setData(size_raw, Qt.ItemDataRole.EditRole)
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            # 4. Path
            path_item = QStandardItem(path)
            path_item.setForeground(gray_color)

            self.model.appendRow([name_item, date_item, size_item, path_item])

    def _format_size(self, size):
        unknown_text = self.config_mgr.get_text("ns_unknown", "未知") if self.config_mgr else "未知"
        if size is None or size == "":
            return unknown_text
        try:
            size_num = float(size)
            if size_num < 1024:
                return f"{int(size_num)} B"
            for unit in ['KB', 'MB', 'GB', 'TB']:
                size_num /= 1024
                if size_num < 1024:
                    return f"{size_num:.1f} {unit}"
            return f"{size_num:.1f} PB"
        except Exception as e:
            return f"E:{size}"

    def on_refresh_clicked(self):
        paths = self.config.get("monitored_paths", [])
        if not paths:
            warn_title = self.config_mgr.get_text("ns_warn_title", "警告") if self.config_mgr else "警告"
            warn_msg = self.config_mgr.get_text("ns_warn_add_path", "請先在設定中新增監測路徑") if self.config_mgr else "請先在設定中新增監測路徑"
            QMessageBox.warning(self, warn_title, warn_msg)
            return
        self.start_scan(paths)

    def start_scan(self, paths):
        if self.scanner and self.scanner.isRunning():
            return
        try:
            from .engine import ScannerWorker
        except ImportError:
            from engine import ScannerWorker

        self.scanner = ScannerWorker(paths, self.engine)
        self.scanner.progress.connect(self.on_scanner_progress)
        self.scanner.finished.connect(self.on_scanner_finished)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.refresh_btn.setEnabled(False)
        self.scanner.start()

    def on_scanner_progress(self, msg):
        self.status_bar.showMessage(msg)

    def on_scanner_finished(self, total):
        self.progress_bar.setVisible(False)
        self.refresh_btn.setEnabled(True)
        finished_tpl = self.config_mgr.get_text("ns_status_finished", "掃描完成! 共索引 {} 個檔案") if self.config_mgr else "掃描完成! 共索引 {} 個檔案"
        self.status_bar.showMessage(finished_tpl.format(total))
        self.on_search_text_changed(self.search_input.text())

    def on_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        path = self.model.item(row, 3).text()

        menu = QMenu(self)
        open_text = self.config_mgr.get_text("ns_menu_open", "開啟檔案") if self.config_mgr else "開啟檔案"
        open_loc_text = self.config_mgr.get_text("ns_menu_open_location", "開啟檔案位置") if self.config_mgr else "開啟檔案位置"
        copy_path_text = self.config_mgr.get_text("ns_menu_copy_path", "複製完整路徑") if self.config_mgr else "複製完整路徑"
        
        open_act = menu.addAction(open_text)
        open_loc_act = menu.addAction(open_loc_text)
        copy_path_act = menu.addAction(copy_path_text)

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))

        if action == open_act:
            if os.path.exists(path):
                os.startfile(path)
        elif action == open_loc_act:
            dir_path = os.path.dirname(path)
            if os.path.exists(dir_path):
                os.startfile(dir_path)
        elif action == copy_path_act:
            QApplication.clipboard().setText(path)

    def on_item_double_clicked(self, index):
        row = index.row()
        path = self.model.item(row, 3).text()
        if os.path.exists(path):
            os.startfile(path)
        else:
            err_tpl = self.config_mgr.get_text("ns_error_not_found", "錯誤: 檔案不存在 {}") if self.config_mgr else "錯誤: 檔案不存在 {}"
            self.status_bar.showMessage(err_tpl.format(path))
