from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QProgressBar, QStatusBar,
    QFileDialog, QDialog, QFormLayout, QMessageBox, QInputDialog,
    QTreeView, QHeaderView, QMenu, QListWidget, QListWidgetItem,
    QCheckBox, QSpinBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QFileInfo, QDateTime, QPoint, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QAction, QFont, QColor
from PyQt6.QtWidgets import QFileIconProvider, QApplication

import os
import datetime
import json
import sys
import logging
from pathlib import Path
from core.system_utils import is_computer_locked

logger = logging.getLogger(__name__)


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
        
        # Numeric comparison for Date (1) and Size (2)
        if col in (1, 2):
            if left_data is not None and right_data is not None:
                try:
                    return float(left_data) < float(right_data)
                except (TypeError, ValueError):
                    pass
                    
            # Handle None or invalid data by treating them as minimal values
            if left_data is None: return True
            if right_data is None: return False
        
        # For Column 0 (Name) and others, if UserRole is set, compare them as strings
        # This prevents falling back to DisplayRole which might include icons/etc.
        if left_data is not None and right_data is not None:
             return left_data < right_data
        
        # Fallback to standard comparison
        return super().lessThan(left, right)

class ThemeConfig:
    """OOP Model for UI Theme Colors."""

    def __init__(self, theme_path="theme.json"):
        self.colors = {}
        self.load_theme(theme_path)

    @staticmethod
    def get_resource_path(path):
        """Helper to find resources in source or bundled build."""
        if getattr(sys, 'frozen', False):
            # PyInstaller onedir/onefile bundle path
            base_path = sys._MEIPASS
        else:
            # Source execution path
            base_path = os.path.dirname(os.path.dirname(__file__))
            
        return os.path.join(base_path, path)

    def load_theme(self, path):
        abs_path = self.get_resource_path(path)
        if not os.path.exists(abs_path):
            return
        try:
            with open(abs_path, 'r', encoding='utf-8') as f:
                self.colors = json.load(f)
        except Exception:
            pass

    def get_color(self, key, default="#888888"):
        return QColor(self.colors.get(key, default))

    def get_qss_vars(self):
        return self.colors


class SettingsDialog(QDialog):
    """搜尋模組設定對話框 (全中文)"""

    def __init__(self, config, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.config_mgr = config_mgr
        self.setWindowTitle("搜尋模組設定")
        self.resize(500, 450)
        self._initializing = True
        self._init_ui()
        self._initializing = False

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.remote_db_edit = QLineEdit(
            self.config.get("remote_index_root", ""))
        self.remote_db_edit.setPlaceholderText("選擇 K: 上用來存放索引資料庫的資料夾")
        
        remote_layout = QHBoxLayout()
        remote_layout.addWidget(self.remote_db_edit)
        remote_btn = QPushButton("瀏覽")
        remote_btn.clicked.connect(self.on_browse_remote)
        remote_layout.addWidget(remote_btn)
        form.addRow("共享索引資料庫資料夾:", remote_layout)

        self.limit_edit = QLineEdit(str(self.config.get("search_limit", 1000)))
        self.limit_edit.setPlaceholderText("預設 1000")
        form.addRow("搜尋結果上限:", self.limit_edit)

        # 改用 [ - ] [ 數字 ] [ + ] 組合，設定合理的 1-20 層限制
        self.depth_label = QLabel(str(self.config.get("max_depth", 7)))
        self.depth_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.depth_label.setFixedWidth(40)
        self.depth_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #3498db;")

        depth_layout = QHBoxLayout()
        minus_btn = QPushButton("-")
        minus_btn.setFixedWidth(30)
        minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        minus_btn.clicked.connect(self._on_minus_depth)
        
        plus_btn = QPushButton("+")
        plus_btn.setFixedWidth(30)
        plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plus_btn.clicked.connect(self._on_plus_depth)

        depth_layout.addWidget(minus_btn)
        depth_layout.addWidget(self.depth_label)
        depth_layout.addWidget(plus_btn)
        depth_layout.addStretch()
        
        form.addRow("資料夾搜尋深度 (1-20 層):", depth_layout)

        self.is_master_cb = QCheckBox("啟用生產者模式 (Master Node) - 負責背景掃描與索引發布")
        self.is_master_cb.setChecked(self.config.get("is_master_node", False))
        self.is_master_cb.setToolTip("僅公司一台電腦需要開啟此功能。開啟後，本機會在閒置時掃描磁碟並發布至共享目錄。")
        form.addRow("運行角色:", self.is_master_cb) 

        exclude_exts = self.config.get("exclude_exts", ".tmp, .bak, .log, .cache, .thumbs")
        if isinstance(exclude_exts, list): exclude_exts = ", ".join(exclude_exts)
        self.exclude_exts_edit = QLineEdit(exclude_exts)
        self.exclude_exts_edit.setPlaceholderText("例如: .tmp, .bak, .log")
        form.addRow("排除副檔名 (逗號分隔):", self.exclude_exts_edit)

        exclude_dirs = self.config.get("exclude_dirs", "Archive, Old, Temp")
        if isinstance(exclude_dirs, list): exclude_dirs = ", ".join(exclude_dirs)
        self.exclude_dirs_edit = QLineEdit(exclude_dirs)
        self.exclude_dirs_edit.setPlaceholderText("例如: Archive, Old, Temp")
        form.addRow("排除資料夾關鍵字:", self.exclude_dirs_edit)

        layout.addLayout(form)

        # 角色切換互動: 非 Master 隱藏路徑清單與掃描設定
        self.master_group = QGroupBox("掃描路徑管理 (僅生產者模式需設定)")
        master_group_layout = QVBoxLayout(self.master_group)
        
        self.path_list = QListWidget()
        for p in self.config.get("monitored_paths", []):
            self.path_list.addItem(p)
        master_group_layout.addWidget(self.path_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("新增路徑")
        add_btn.clicked.connect(self.on_add_path)
        remove_btn = QPushButton("刪除選取")
        remove_btn.clicked.connect(self.on_remove_path)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        master_group_layout.addLayout(btn_layout)
        
        layout.addWidget(self.master_group)
        self.is_master_cb.toggled.connect(self._on_role_toggled)
        self._on_role_toggled(self.is_master_cb.isChecked())
        
        # UI Table
        actions = QHBoxLayout()
        save_btn = QPushButton("儲存設定")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(save_btn)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def on_browse_remote(self):
        path = QFileDialog.getExistingDirectory(self, "選擇網路索引暫存目錄")
        if path:
            self.remote_db_edit.setText(path)

    def on_add_path(self):
        path = QFileDialog.getExistingDirectory(self, "選擇要監測的資料夾")
        if path:
            self.path_list.addItem(path)

    def on_remove_path(self):
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))

    def _on_minus_depth(self):
        val = int(self.depth_label.text())
        if val > 1:
            self.depth_label.setText(str(val - 1))

    def _on_plus_depth(self):
        val = int(self.depth_label.text())
        if val < 20: # 設定一個合理的上限防呆 (20層)
            self.depth_label.setText(str(val + 1))

    def _on_role_toggled(self, is_master):
        if is_master and not getattr(self, '_initializing', False):
            # 只有在使用者手動切換為生產者模式時才要求輸入密碼
            text, ok = QInputDialog.getText(
                self, "權限驗證", 
                "開啟生產者模式需輸入管理密碼:", 
                QLineEdit.EchoMode.Password
            )
            
            expected = self.config_mgr.get_master_password() if self.config_mgr else self.config.get("master_node_password", "1235")
            if ok and text == expected:
                self.master_group.setVisible(True)
            else:
                if ok:
                    QMessageBox.warning(self, "錯誤", "密碼不正確處理失敗！")
                
                # 密碼錯誤或取消，回退至消費者模式
                self.is_master_cb.blockSignals(True)
                self.is_master_cb.setChecked(False)
                self.is_master_cb.blockSignals(False)
                self.master_group.setVisible(False)
        else:
            # 關閉生產者模式或正在初始化時，直接切換顯示狀態即可
            self.master_group.setVisible(is_master)

    def get_settings(self):
        paths = [self.path_list.item(i).text()
                 for i in range(self.path_list.count())]
        return {
            "remote_index_root": self.remote_db_edit.text(),
            "monitored_paths": paths,
            "search_limit": int(self.limit_edit.text() or 1000),
            "max_depth": int(self.depth_label.text()),
            "is_master_node": self.is_master_cb.isChecked(),
            "exclude_exts": self.exclude_exts_edit.text(),
            "exclude_dirs": self.exclude_dirs_edit.text()
        }


class NetworkSearchWindow(QWidget):
    """Independent search window for network files."""

    def __init__(self, engine_mgr, config_mgr=None):
        super().__init__()
        self.engine = engine_mgr
        self.index_mgr = engine_mgr # Ensure compatibility with scanner calls
        self.config_mgr = config_mgr
        self.config = config_mgr.load_config() if config_mgr else {}
        self.theme = ThemeConfig()
        self.scanner = None
        self.icon_provider = QFileIconProvider()

        # 搜尋去抖動 (Debouncing)
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)

        # 背景掃描相關狀態
        self.is_master = self.config.get("is_master_node", False)
        self.active_workers = [] # 防止被 GC
        # 初始化時先執行一次檢查，避免啟動時因為 False->True 觸發誤判
        self.was_locked_last_check = is_computer_locked() 
        self.lock_check_timer = QTimer(self)
        self.lock_check_timer.timeout.connect(self.check_lock_state)
        
        if self.is_master:
            self.lock_check_timer.start(60000) # 每 60 秒檢查一次系統狀態
        
        # Pillar 1 Sync: On start, sync from remote
        self._sync_on_start()
        self.update_status_bar()
        self.refresh_scan_status_from_db() # New: show previous status
        self._init_ui()

    def update_status_bar(self):
        remote_root = self.config.get("remote_index_root")
        is_master = self.config.get("is_master_node", False)
        
        if is_master:
            self.search_status_label.setText("🛠️ 生產者模式 (Master) - 負責索引維護")
            self.search_status_label.setStyleSheet("color: #3498db; font-weight: bold;")
        elif not remote_root:
            self.search_status_label.setText("✅ 本機模式 (尚未設定共享路徑)")
            self.search_status_label.setStyleSheet("color: #888;")
        elif not os.path.exists(remote_root):
            self.search_status_label.setText(f"⚠️ 共享路徑存取失敗: {remote_root}")
            self.search_status_label.setStyleSheet("color: #ff4d4d; font-weight: bold;")
        else:
            slot = "未知"
            if hasattr(self.config_mgr, 'get_active_slot'):
                slot = self.config_mgr.get_active_slot()
            self.search_status_label.setText(f"🌐 消費者模式 (Slot {slot}): {remote_root}")
            self.search_status_label.setStyleSheet("color: #4CAF50;")
            
        # 消費者模式下，隱藏手動掃描按鈕
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setVisible(is_master)

    def _sync_on_start(self):
        is_master = self.config.get("is_master_node", False)
        if is_master:
            # Master node might still want to sync existing remote if it just took over,
            # but usually it pushes. For now, only pull for consumers.
            # However, if it's a consumer, we rely on direct network access via get_index_path()
            # so we don't NEED to sync_from_remote here anymore.
            pass
        
        # Legacy sync logic for single-DB mode (fallback)
        # In AB mode, if it's consumer, IndexManager already points to the UNC path.
        # So we skip active syncing to save startup time.
        self.search_status_label.setText("已連線至共享索引")

    def _do_sync(self, remote_root):
        try:
            self.engine.sync_from_remote(remote_root)
            self.search_status_label.setText(f"同步完成")
        except Exception as e:
            self.search_status_label.setText(f"同步失敗: {e}")

    def refresh_scan_status_from_db(self):
        """從資料庫讀取最後一次掃描的成果狀態"""
        # 假設以主要的掃描根目錄來顯示狀態
        monitored = self.config.get("monitored_paths", [])
        if monitored:
            root = monitored[0]
            if hasattr(self.engine, 'get_scan_status'):
                status_info = self.engine.get_scan_status(root)
            if status_info:
                status, last_finished, total = status_info
                if status == 'FINISHED' and last_finished:
                    dt = datetime.datetime.fromtimestamp(last_finished)
                    self.search_status_label.setText(f" ✅ 索引已於 {dt.strftime('%H:%M')} 完整建立 (共 {total} 檔案) ")
                    self.search_status_label.setStyleSheet("background-color: #27ae60; color: #ffffff; padding: 4px 12px; border-radius: 4px; font-weight: bold;")
                elif status == 'INTERRUPTED':
                    self.search_status_label.setText(f" 🛑 上次掃描已中斷 (已索引 {total} 檔案) ")
                    self.search_status_label.setStyleSheet("background-color: #7f8c8d; color: #ffffff; padding: 4px 12px; border-radius: 4px; font-weight: bold;")

    def check_lock_state(self):
        """偵測電腦鎖定狀態並決定是否啟動背景掃描"""
        currently_locked = is_computer_locked()
        
        # 1. 剛被鎖定 -> 啟動背景掃描 (偷偷執行)
        if currently_locked and not self.was_locked_last_check:
            logger.info("🕒 [背景] 偵測到電腦已鎖定，準備啟動背景掃描...")
            self.on_refresh_clicked(is_background=True)
            
        # 2. 剛被解鎖 -> 使用者回來了，立即煞車！
        elif not currently_locked and self.was_locked_last_check:
            if self.scanner and self.scanner.isRunning():
                logger.info("👁️ [背景] 偵測到使用者回來了！正在中止背景掃描以維持流暢度...")
                self.scanner.cancel()
            
        self.was_locked_last_check = currently_locked

    def _init_ui(self):
        self.setWindowTitle("網路搜尋獨立模組 (Network Search)")
        self.resize(1000, 700)

        self.layout = QVBoxLayout(self)

        # Apply Theme Stylesheet
        if self.config_mgr:
            qss = self.config_mgr.load_stylesheet("network_search/styles.qss", "theme.json")
            if qss:
                self.setStyleSheet(qss)

        # Header (Split into two rows for responsiveness)
        top_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("輸入關鍵字 / 萬用字元 (例如: *.pdf, a*.bmp, abc.*) ...")
        self.search_input.textChanged.connect(self.on_search_text_changed)

        self.refresh_btn = QPushButton("開始索引掃描")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        self.settings_btn = QPushButton("⚙ 設定")
        self.settings_btn.clicked.connect(self.on_settings_clicked)

        top_row.addWidget(self.search_input)
        top_row.addWidget(self.refresh_btn)
        top_row.addWidget(self.settings_btn)
        self.layout.addLayout(top_row)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 5, 0, 5)
        
        # 搜尋來源勾選 (Search Source)
        self.search_local_cb = QCheckBox("本機")
        self.search_local_cb.setChecked(True)
        self.search_local_cb.stateChanged.connect(lambda: self.search_timer.start(300))
        
        self.search_network_cb = QCheckBox("網路")
        self.search_network_cb.setChecked(True)
        self.search_network_cb.stateChanged.connect(lambda: self.search_timer.start(300))
        
        filter_row.addWidget(QLabel("來源:"))
        filter_row.addWidget(self.search_local_cb)
        filter_row.addWidget(self.search_network_cb)
        filter_row.addSpacing(20)
        # 檔案大小過濾 (Segmented Buttons)
        self.size_btn_group = QHBoxLayout()
        self.size_btn_group.setSpacing(2)
        self.size_btns = []
        self.current_size_idx = 0
        filters = self.config_mgr.get_search_filters() if hasattr(self, 'config_mgr') and self.config_mgr else {"size_labels": ["全部", "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"]}
        sizes = filters.get("size_labels", ["全部", "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"])
        for i, label in enumerate(sizes):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_size_btn_clicked(idx))
            self.size_btn_group.addWidget(btn)
            self.size_btns.append(btn)

        # 修改日期過濾 (Time Filter Buttons)
        self.time_btn_group = QHBoxLayout()
        self.time_btn_group.setSpacing(2)
        self.time_btns = []
        self.current_time_idx = 0
        filters = self.config_mgr.get_search_filters() if hasattr(self, 'config_mgr') and self.config_mgr else {"time_labels": ["全部", "🕒 今日", "📅 本週", "本月"]}
        time_labels = filters.get("time_labels", ["全部", "🕒 今日", "📅 本週", "本月"])
        for i, label in enumerate(time_labels):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedWidth(70)
            btn.clicked.connect(lambda checked, idx=i: self.on_time_btn_clicked(idx))
            self.time_btn_group.addWidget(btn)
            self.time_btns.append(btn)

        filter_row.addWidget(QLabel("大小:"))
        filter_row.addLayout(self.size_btn_group)
        filter_row.addSpacing(20)
        filter_row.addWidget(QLabel("時間:"))
        filter_row.addLayout(self.time_btn_group)
        filter_row.addStretch()
        
        self.layout.addLayout(filter_row)
        
        self._update_size_btn_styles()
        self._update_time_btn_styles()

        # Results TreeView
        self.tree = QTreeView()
        self.tree.setSelectionBehavior(
            QTreeView.SelectionBehavior.SelectRows)  # 整列選取
        self.tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self.tree.setAllColumnsShowFocus(True)  # 焦點框涵蓋整行
        self.tree.setRootIsDecorated(False)     # 隱藏樹狀層次的展開箭頭
        self.tree.setIndentation(0)             # 移除縮排
        self.model = QStandardItemModel(0, 4)
        self.model.setHorizontalHeaderLabels(["名稱", "修改日期", "大小", "完整路徑"])
        
        self.proxy_model = DateSortProxyModel()
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setDynamicSortFilter(True)
        # self.proxy_model.setSortRole(Qt.ItemDataRole.UserRole) # Removed to avoid global override
        
        self.tree.setModel(self.proxy_model)
        self.tree.setSortingEnabled(True)
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

        # 視覺美化移至 styles.qss
        # self.tree.setStyleSheet(...)

        self.layout.addWidget(self.tree)

        # Scanner progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.layout.addWidget(self.progress_bar)

        # Footer
        self.status_bar = QStatusBar()
        self.search_status_label = QLabel("資料庫準備就緒")
        self.status_bar.addWidget(self.search_status_label)
        self.layout.addWidget(self.status_bar)

    def on_settings_clicked(self):
        dialog = SettingsDialog(self.config, self.config_mgr)
        if dialog.exec():
            new_settings = dialog.get_settings()
            self.config.update(new_settings)
            if self.config_mgr:
                self.config_mgr.save_config(
                    self.config.get("custom_paths", []),
                    self.config.get("left_tabs", []),
                    self.config.get("right_tabs", []),
                    remote_index_root=self.config.get("remote_index_root"),
                    watchlist=self.config.get("monitored_paths"),
                    max_depth=self.config.get("max_depth", 999),
                    search_limit=self.config.get("search_limit"),
                    is_master_node=self.config.get("is_master_node")
                )
            
            # 同步更新引擎的網路路徑
            new_nas_path = self.config.get("remote_index_root")
            if self.engine.nas_folder_path != new_nas_path:
                self.engine.nas_folder_path = new_nas_path
                self.engine.current_shared_slot = None # 重置連線，強制下次搜尋重連
                
            self.is_master = self.config.get("is_master_node", False)
            if self.is_master:
                if not self.lock_check_timer.isActive():
                    self.lock_check_timer.start(60000)
            else:
                self.lock_check_timer.stop()
                
            self.update_status_bar()

    def on_search_text_changed(self, text):
        # 重新計時 300ms
        self.search_timer.start(300)

    def _do_search(self):
        text = self.search_input.text()
        if len(text) < 2:
            self.model.removeRows(0, self.model.rowCount())
            return

        filters = self.config_mgr.get_search_filters() if hasattr(self, 'config_mgr') and self.config_mgr else {}
        size_map = filters.get("size_thresholds", {"0": 0, "1": 1*1024*1024, "2": 10*1024*1024, "3": 100*1024*1024, "4": 1024*1024*1024})
        # Handle string keys from JSON
        min_size = size_map.get(str(self.current_size_idx), size_map.get(self.current_size_idx, 0))
        
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
            
        limit = self.config.get("search_limit", 1000)
        use_local = self.search_local_cb.isChecked()
        use_network = self.search_network_cb.isChecked()
        
        results = self.engine.search(
            text, 
            limit=limit, 
            min_size=min_size, 
            min_mtime=min_mtime, 
            use_local=use_local, 
            use_network=use_network
        )
        
        # Disable sorting temporarily during update
        self.tree.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())

        # 更新狀態列訊息 (強化配色對比)
        if len(results) >= limit:
            msg = f" ⚠️ 僅顯示前 {limit} 筆結果 (請縮小搜尋範圍) "
            self.search_status_label.setText(msg)
            self.search_status_label.setStyleSheet(
                "background-color: #f1c40f; color: #000000; padding: 4px 12px; "
                "border-radius: 4px; font-weight: bold; border: 1px solid #d4ac0d;"
            )
        else:
            self.search_status_label.setText(f"找到 {len(results)} 筆結果")
            self.search_status_label.setStyleSheet(
                "color: #ffffff; background-color: #2c3e50; padding: 2px 8px; "
                "border-radius: 4px; font-size: 12px;"
            )

        # 清除過時的 showMessage
        self.status_bar.clearMessage()

        muted_color = self.theme.get_color("textMuted", "gray")

        # 依照 SQL 回傳順序：name, mtime, size, path
        for name, mtime, size, path in results:
            # 1. Name with Icon
            name_item = QStandardItem(name)
            name_item.setData(name, Qt.ItemDataRole.UserRole)
            name_item.setIcon(self.icon_provider.icon(QFileInfo(path)))

            # 2. Date - 改用更穩定的 datetime.fromtimestamp
            date_str = "未知"
            date_val = 0
            if mtime is not None:
                try:
                    ts = float(mtime)
                    if 0 < ts < 4102444800:  # 1970 ~ 2100
                        dt = datetime.datetime.fromtimestamp(ts)
                        date_str = dt.strftime("%Y-%m-%d %H:%M")
                        date_val = int(ts)
                    else:
                        date_str = f"無效:{ts}"
                except Exception as e:
                    date_str = f"錯誤:{e}"
            
            # DEBUG
            logger.debug(f"UI V2: name={name}, date_str={date_str}")

            date_item = QStandardItem()
            date_item.setText(date_str)
            date_item.setData(date_val, Qt.ItemDataRole.UserRole)

            # 3. Size
            size_raw = float(size) if size is not None else -1.0
            size_str = self._format_size(size)

            size_item = QStandardItem()
            size_item.setText(size_str)
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            size_item.setData(size_raw, Qt.ItemDataRole.UserRole)

            # 4. Path
            path_item = QStandardItem(path)
            path_item.setData(path, Qt.ItemDataRole.UserRole)
            path_item.setForeground(muted_color)

            self.model.appendRow([name_item, date_item, size_item, path_item])

        # Restore sorting on the current column
        header = self.tree.header()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        
        # Force a re-sort on the proxy model
        self.proxy_model.sort(sort_col, sort_order)
        
        # Ensure sorting is enabled on the view
        self.tree.setSortingEnabled(True)

    def _format_size(self, size):
        if size is None:
            return "未知"
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def on_size_btn_clicked(self, index):
        self.current_size_idx = index
        self._update_size_btn_styles()
        self._do_search()

    def on_time_btn_clicked(self, index):
        self.current_time_idx = index
        self._update_time_btn_styles()
        self._do_search()

    def _update_size_btn_styles(self):
        active_style = "background-color: #1F6F99; color: white; font-weight: bold; border-top: 1px solid #2980b9; border-bottom: 2px solid #1a5276;"
        inactive_style = "background-color: #333; color: #888; border: 1px solid #444;"
        for i, btn in enumerate(self.size_btns):
            btn.setChecked(i == self.current_size_idx)
            btn.setStyleSheet(active_style if i == self.current_size_idx else inactive_style)

    def _update_time_btn_styles(self):
        active_style = "background-color: #1F6F99; color: white; font-weight: bold; border-top: 1px solid #2980b9; border-bottom: 2px solid #1a5276;"
        inactive_style = "background-color: #333; color: #888; border: 1px solid #444;"
        for i, btn in enumerate(self.time_btns):
            btn.setChecked(i == self.current_time_idx)
            btn.setStyleSheet(active_style if i == self.current_time_idx else inactive_style)

    def on_refresh_clicked(self, is_background=False):
        is_master = self.config.get("is_master_node", False)
        monitored = self.config.get("monitored_paths", [])
        local_drives = self.config_mgr.get_fixed_drives()
        
        # 分流邏輯：
        # 1. 掃描本機固定硬碟 (如 C:\) -> 永遠存入 personal.db
        if local_drives:
            self.start_scan(local_drives, is_background=is_background, target_db="personal")
            
        # 2. 掃描監控路徑 (如 K:\) -> 僅在生產者模式下存入 network_master.db 並發布
        if is_master and monitored:
            # 如果背景掃描且 personal 正在跑，這會被 queue 住或是 skip (依 start_scan 邏輯)
            # 這裡我們稍微等一下或是連續觸發
            QTimer.singleShot(500, lambda: self.start_scan(monitored, is_background=is_background, target_db="local"))

    def start_scan(self, paths, is_background=False, force_rescan=False, target_db="local"):
        if self.scanner and self.scanner.isRunning():
            return
        try:
            from .engine import ScannerWorker
        except ImportError:
            from engine import ScannerWorker

        # 定義路徑特定的深度 (Path-specific depths)
        max_depth = self.config.get("max_depth", 7)
        
        def get_depth(p):
            # 判斷是否為本機硬碟 (如 C:\, D:\)
            if len(p) <= 3 and p.endswith(':\\'): return 99
            return max_depth

        root_configs = [(p, get_depth(p)) for p in paths]
        
        self.scanner = ScannerWorker(
            root_configs, 
            self.index_mgr,
            remote_db_dir=self.config.get("remote_index_root") if target_db == "local" else None,
            force_rescan=force_rescan, 
            exclude_exts=self.config.get("exclude_exts"),
            exclude_dirs=self.config.get("exclude_dirs"),
            target_db=target_db
        )
        self.active_workers.append(self.scanner)
        self.scanner.progress.connect(self.on_scanner_progress)
        self.scanner.files_indexed.connect(self.on_scanner_files_indexed)
        self.scanner.finished.connect(lambda: self.active_workers.remove(self.scanner) if self.scanner in self.active_workers else None)
        self.scanner.finished.connect(self.on_scanner_finished)
        self.scanner.cancelled.connect(self.on_scanner_cancelled)
        
        if not is_background:
            self.progress_bar.setVisible(True)
            self.progress_bar.setRange(0, 0)
            self.refresh_btn.setEnabled(False)
        else:
            self.search_status_label.setText("🌱 正在背景掃描 (電腦鎖定中)...")
            
        self.scanner.start()

    def on_scanner_progress(self, msg):
        # 僅在左側狀態列顯示進度詳情
        self.status_bar.showMessage(msg)

    def on_scanner_files_indexed(self, count):
        # 在右側標籤同步顯示掃描計數 (強化對比)
        self.search_status_label.setText(f" 正在掃描... 已發現 {count} 個檔案 ")
        self.search_status_label.setStyleSheet(
            "background-color: #3498db; color: #ffffff; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )

    def on_scanner_finished(self, total):
        self.progress_bar.setVisible(False)
        self.refresh_btn.setEnabled(True)
        self.search_status_label.setText(f" ✅ 掃描完成! 共索引 {total} 檔案 ")
        self.search_status_label.setStyleSheet(
            "background-color: #27ae60; color: #ffffff; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self.on_search_text_changed(self.search_input.text())

    def on_scanner_cancelled(self, total):
        self.progress_bar.setVisible(False)
        self.refresh_btn.setEnabled(True)
        self.search_status_label.setText(f" 🛑 掃描已依使用者操作中止 (已索引 {total} 檔案) ")
        self.search_status_label.setStyleSheet(
            "background-color: #7f8c8d; color: #ffffff; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )

    def on_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        # Retrieve path from source model using proxy mapping
        source_index = self.proxy_model.mapToSource(index)
        # Use model.index().data() for safer access to other columns
        path = self.model.index(source_index.row(), 3).data()

        menu = QMenu(self)
        open_act = menu.addAction("開啟檔案")
        open_loc_act = menu.addAction("開啟檔案位置")
        copy_path_act = menu.addAction("複製完整路徑")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))

        if action == open_act:
            os.startfile(path)
        elif action == open_loc_act:
            os.startfile(os.path.dirname(path))
        elif action == copy_path_act:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(path)

    def on_item_double_clicked(self, index):
        source_index = self.proxy_model.mapToSource(index)
        path = self.model.index(source_index.row(), 3).data()
        if os.path.exists(path):
            os.startfile(path)
        else:
            self.status_bar.showMessage(f"錯誤: 檔案不存在 {path}")
