import os, re
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QMessageBox, QTabBar, QFileDialog, QMenu, QLabel, QDialog,
    QGraphicsOpacityEffect, QToolButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QStandardPaths, QPoint, QTimer, QSize
from PyQt6.QtGui import QAction, QShortcut, QKeySequence, QIcon

from ui.widgets.tabs import CustomTabWidget
from ui.widgets.popups import PathPopup, PinPopup
from ui.widgets.buttons import PinDropButton
from ui.widgets.compare_dialog import CompareDialog
from ui.panes.explorer_pane import ExplorerPane
from core.config_manager import ConfigManager
from core.interfaces import IMainWindowView
from ui.presenters.main_window_presenter import MainWindowPresenter
from core.system_utils import is_computer_locked

from ui.presenters.ai_exporter_presenter import AIExporterPresenter
from ui.widgets.dialogs import AIExporterProgressDialog


class _TrashDropButton(QToolButton):
    """狀態列左側垃圾桶：點擊刪除選取項目，或拖放檔案到此送入回收筒。"""
    def __init__(self, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        icon_path = self.config_mgr.get_ui_resource_path("trash") if self.config_mgr else "ui/trash.svg"
        self.setIcon(QIcon(icon_path))
        self.setIconSize(QSize(18, 18))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setObjectName("trashDropBtn")
        tip = self.config_mgr.get_text("ui_main_trash_tooltip", "點擊刪除選取項目（Del）\n拖放檔案到此處 → 移至回收筒") if self.config_mgr else "點擊刪除選取項目（Del）\n拖放檔案到此處 → 移至回收筒"
        self.setToolTip(tip)
        self.setAcceptDrops(True)
        self.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        """點擊 → 刪除目前 active pane 的選取項目（送回收筒）。"""
        win = self.window()
        pane = getattr(win, 'active_pane', None)
        if pane and hasattr(pane, 'delete_selected'):
            pane.delete_selected(permanent=False)

    def _set_drag_state(self, active: bool) -> None:
        self.setObjectName("trashDropBtnDrag" if active else "trashDropBtn")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._set_drag_state(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event):
        self._set_drag_state(False)

    def dropEvent(self, event):
        self._set_drag_state(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return

        import send2trash
        done, errors = [], []
        for p in paths:
            try:
                send2trash.send2trash(os.path.normpath(p))
                done.append(p)
            except Exception as e:
                errors.append(str(e))

        win = self.window()
        if done:
            if hasattr(win, "register_undo"):
                win.register_undo([(p, None) for p in done], "trash")
            if hasattr(win, "refresh_all_panes"):
                win.refresh_all_panes()
            if hasattr(win, "set_status_msg"):
                msg = self.config_mgr.get_text("ui_main_trash_status_success").format(len(done))
                win.set_status_msg(msg, "success")
        if errors and hasattr(win, "set_status_msg"):
            msg = self.config_mgr.get_text("ui_main_trash_status_error").format(errors[0])
            win.set_status_msg(msg, "error")
        event.acceptProposedAction()


class _MainWindowViewAdapter(IMainWindowView):
    """Pure adapter: bridges MainWindowPresenter to the Qt MainWindow."""
    def __init__(self, window): self.w = window

    def get_active_pane_path(self) -> str:
        p = self.w.active_pane
        return p.path_edit.text() if p else ""

    def get_opposite_pane_path(self) -> str:
        p = self.w.active_pane
        if not p: return ""
        is_left = any(self.w.left_tabs.widget(i) == p for i in range(self.w.left_tabs.count()))
        opp = self.w.right_tabs if is_left else self.w.left_tabs
        pane = opp.currentWidget()
        return pane.path_edit.text() if pane else ""

    def get_active_pane_selected_paths(self) -> list:
        p = self.w.active_pane
        if not p: return []
        return p._get_selected_paths()

    def navigate_active_pane(self, path: str):
        if self.w.active_pane:
            self.w.active_pane.set_path(path)

    def navigate_opposite_pane(self, path: str):
        p = self.w.active_pane
        if not p: return
        is_left = any(self.w.left_tabs.widget(i) == p for i in range(self.w.left_tabs.count()))
        opp = self.w.right_tabs if is_left else self.w.left_tabs
        pane = opp.currentWidget()
        if pane:
            pane.set_path(path)

    def copy_selected_to_opposite(self):
        self.w.copy_selected_to_other_side()

    def move_selected_to_opposite(self):
        self.w.move_selected_to_other_side()

    def add_tab(self, side: str, path: str):
        tw = self.w.left_tabs if side == "left" else self.w.right_tabs
        self.w.add_new_tab(tw, path)

    def close_active_tab(self):
        p = self.w.active_pane
        if not p: return
        for tw in [self.w.left_tabs, self.w.right_tabs]:
            for i in range(tw.count()):
                if tw.widget(i) == p:
                    self.w.close_tab(tw, i)
                    return

    def set_status_msg(self, text: str, style: str):
        self.w.set_status_msg(text, style)

    def save_session(self):
        self.w._internal_save_config()

    def start_background_scan(self, scan_type: str):
        if scan_type == "personal":
            self.w._start_idle_c_scan()
        elif scan_type == "network":
            self.w._start_nightly_k_scan()

    def stop_background_scan(self, scan_type: str):
        if scan_type == "personal":
            self.w._stop_idle_c_scan()
        elif scan_type == "network":
            # Network scan is usually fine to finish or handled similarly
            pass



class MainWindow(QMainWindow):
    """Main application window. Pure View Adapter — all logic delegated to MainWindowPresenter."""
    file_operation_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config_mgr = ConfigManager()
        title = self.config_mgr.get_text("ui_main_window_title", "左右分欄檔案總管 (Dual Pane File Manager)")
        self.setWindowTitle(title)
        self.resize(1200, 800)
        self.showMaximized()

        self.config = self.config_mgr.load_config()
        self.custom_paths = self.config.get("custom_paths", [])

        self.active_pane = None
        self.clipboard = {"paths": [], "op": "copy"}
        self.current_drag_button = Qt.MouseButton.NoButton
        self._undoing = False
        self._preview_source_pane = None
        self._preview_source_view = None
        self._preview_target_pane = None
        self._preview_panels: dict = {}

        # 共享唯讀 IndexManager，必須在 _restore_tabs() 之前初始化
        try:
            from network_search.engine import IndexManager
            import os as _os
            _db_dir = _os.path.join(_os.path.dirname(str(self.config_mgr.config_file)), "indexes")
            self._shared_index_manager = IndexManager(_db_dir, read_only=True)
        except Exception:
            self._shared_index_manager = None

        self._init_ui()
        self._restore_tabs()
        self._init_shortcuts()

        # Presenter wired after UI exists
        self.presenter = MainWindowPresenter(_MainWindowViewAdapter(self), self.config_mgr)
        self.file_operation_finished.connect(self._on_file_op_finished)

        # Undo stack
        from core.undo_stack import UndoStack
        self.undo_stack = UndoStack()

        # 心跳計時器 (P1：確保夜間與維護掃描正常啟動)
        self._system_timer = QTimer(self)
        self._system_timer.timeout.connect(self._on_system_timer_tick)
        self._system_timer.start(60000)

        self.idle_scanner_worker = None
        self.nightly_scanner_worker = None
        self._update_worker = None

        QTimer.singleShot(500, self._cleanup_expired_pins)
        # 啟動 5 秒後進行更新檢查 (非同步)
        QTimer.singleShot(5000, self._start_update_check)

    def _on_file_op_finished(self):
        # Add a 500ms delay before refreshing the UI. 
        # This gives the OS and QFileSystemWatcher enough time to flush metadata (e.g. file size) 
        # to disk and update QFileSystemModel, preventing the "0 byte" ghost file issue.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, self.refresh_all_panes)

    def _init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        from ui.widgets.splitter_bridge import BridgeSplitter
        self.splitter = BridgeSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(32)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.splitterMoved.connect(lambda: self.save_config())
        self.splitter.bridge_clicked.connect(self.on_compare_clicked)

        self.left_tabs = CustomTabWidget()
        self.right_tabs = CustomTabWidget()

        for tw in [self.left_tabs, self.right_tabs]:
            tw.setTabsClosable(True)
            tw.setMovable(True)
            tw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tw.customContextMenuRequested.connect(lambda pos, t=tw: self.on_tab_context(t, pos))
            tw.tabCloseRequested.connect(
                lambda idx, t=tw: self.close_tab(t, idx))
            tw.currentChanged.connect(self.on_tab_changed)
            tw.tabBarClicked.connect(lambda t=tw: self._on_tab_bar_clicked(t))
            tw.tabOverflow.connect(self.flash_tab_hint)
            from PyQt6.QtWidgets import QToolButton
            add_btn = QToolButton()
            add_btn.setText("+")
            add_btn.setObjectName("addTabBtn")
            add_btn.setToolTip(self.config_mgr.get_text("ui_main_action_new_tab", "新增分頁"))
            add_btn.clicked.connect(lambda checked, t=tw: self.add_new_tab(t))
            tw.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)
            self.splitter.addWidget(tw)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        self.layout.addWidget(self.splitter)

        # 兩側同路徑提示條
        from PyQt6.QtWidgets import QLabel
        self.same_path_bar = QLabel(self.config_mgr.get_text("ui_main_same_path_warning", "⚠ 兩側顯示相同資料夾"))
        self.same_path_bar.setObjectName("samePathWarning")
        self.same_path_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.same_path_bar.setFixedHeight(24)
        self.same_path_bar.hide()
        self.layout.addWidget(self.same_path_bar)

        self.create_toolbars()
        self.refresh_toolbar()

    def _restore_tabs(self):
        from core.file_ops import FileOps
        from ui.presenters.explorer_presenter import HOME_PATH
        def_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation)

        if not self.config.get("restore_last_session", True):
            l_paths, r_paths = [def_path], [def_path]
        else:
            l_paths = self.config.get("left_tabs") or [def_path]
            r_paths = self.config.get("right_tabs") or [def_path]

        # 若兩側都只有桌面，以 Quick Access 取代右側，左側改為本機視圖
        both_desktop = (l_paths == [def_path] and r_paths == [def_path])
        if both_desktop:
            qa_paths = FileOps.get_win_quick_access_paths()
            l_paths = [HOME_PATH]
            r_paths = qa_paths[:5] if qa_paths else [def_path]

        for p in l_paths:
            self.add_new_tab(self.left_tabs, p)
        for p in r_paths:
            self.add_new_tab(self.right_tabs, p)
        sizes = self.config.get("splitter_sizes")
        if sizes and len(sizes) == 2 and sum(sizes) > 0:
            self.splitter.setSizes(sizes)

    def _init_shortcuts(self):
        # Tab 鍵：區域循環切換分頁
        tab_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Tab), self)
        tab_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        tab_shortcut.activated.connect(self.cycle_local_tabs)
        switch_shortcut = QShortcut(QKeySequence("`"), self)
        switch_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        switch_shortcut.activated.connect(self.switch_side_focus)

        # 進階導航與功能鍵
        QShortcut(QKeySequence("Alt+Left"),
                  self).activated.connect(self.on_alt_left)
        QShortcut(QKeySequence("Alt+Right"),
                  self).activated.connect(self.on_alt_right)

        # 搜尋與復原
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.on_advanced_search_clicked)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self.undo_last)

    def add_new_tab(self, tab_widget, path=None):
        from ui.presenters.explorer_presenter import HOME_PATH
        if path != HOME_PATH and (not path or not os.path.exists(path)):
            path = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DesktopLocation)
        pane = ExplorerPane(path, self.config_mgr, self)
        if self._shared_index_manager:
            pane.set_index_manager(self._shared_index_manager)
        pane.focused.connect(self.set_active_pane)
        pane.status_updated.connect(self._update_pane_status)
        pane.file_operation_finished.connect(self.file_operation_finished.emit)
        pane.path_edit.textChanged.connect(lambda: self.update_tab_ui())
        pane.close_preview_requested.connect(self.close_inline_preview)
        pane.home_requested.connect(lambda p=pane: p.set_path(HOME_PATH))
        pane.custom_paths_requested.connect(self._show_pane_custom_paths_popup)

        tab_label = self.config_mgr.get_text("ui_pane_label_home", "本機") if path == HOME_PATH else (os.path.basename(path) or path or self.config_mgr.get_text("ui_pane_label_home", "本機"))
        idx = tab_widget.addTab(pane, tab_label)
        tab_widget.setCurrentIndex(idx)
        if not self.active_pane:
            self.set_active_pane(pane)
        tab_widget.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        tab_widget.tabBar().customContextMenuRequested.connect(
            lambda pos, tw=tab_widget: self.show_tab_context(tw, pos))
        self.update_tab_ui()
        self.save_config()

    def show_tab_context(self, tw, pos):
        """分頁右鍵選單處理"""
        idx = tw.tabBar().tabAt(pos)
        if idx == -1: return
        
        pane = tw.widget(idx)
        path = pane.path_edit.text() if pane else ""
        
        menu = QMenu(self)
        close_txt = self.config_mgr.get_text("ui_main_action_close_tab", "關閉分頁") if self.config_mgr else "關閉分頁"
        close_act = menu.addAction(close_txt)
        close_act.setEnabled(tw.count() > 1)
        close_act.triggered.connect(lambda: self.close_tab(tw, idx))
        
        add_txt = self.config_mgr.get_text("ui_main_action_new_tab", "新增分頁") if self.config_mgr else "新增分頁"
        menu.addAction(add_txt).triggered.connect(lambda: self.add_new_tab(tw))
        
        if path and os.path.exists(path):
            menu.addSeparator()
            bookmark_tpl = self.config_mgr.get_text("ui_main_menu_add_bookmark", "將「{}」新增至書籤") if self.config_mgr else "將「{}」新增至書籤"
            menu.addAction(bookmark_tpl.format(os.path.basename(path) or path)).triggered.connect(
                lambda: self.on_quick_add_path(path)
            )
            menu.addSeparator()
            tree_txt = self.config_mgr.get_text("ui_main_menu_gen_tree", "生成目錄結構 (複製到剪貼簿)") if self.config_mgr else "生成目錄結構 (複製到剪貼簿)"
            menu.addAction(tree_txt).triggered.connect(
                lambda: self.on_export_ai_context(path, include_contents=False)
            )
        
        menu.exec(tw.tabBar().mapToGlobal(pos))

    def close_tab(self, tw, idx):
        if tw.count() > 1:
            tw.widget(idx).deleteLater()
            tw.removeTab(idx)
            self.save_config()
            self.update_tab_ui()
        else:
            info_title = self.config_mgr.get_text("ui_dialog_info_title", "資訊") if self.config_mgr else "資訊"
            info_msg = self.config_mgr.get_text("ui_main_msg_keep_one_tab", "至少需保留一個分頁") if self.config_mgr else "至少需保留一個分頁"
            QMessageBox.information(self, info_title, info_msg)

    def update_tab_ui(self):
        from ui.presenters.explorer_presenter import HOME_PATH
        for tw in [self.left_tabs, self.right_tabs]:
            for i in range(tw.count()):
                p = tw.widget(i)
                path = p._current_path
                if path == HOME_PATH or not path:
                    tw.setTabText(i, self.config_mgr.get_text("ui_pane_label_home", "本機"))
                    tw.setTabToolTip(i, self.config_mgr.get_text("ui_pane_tooltip_home_view", "此電腦"))
                else:
                    parts = path.replace("\\", "/").rstrip("/").split("/")
                    label = parts[-1] if parts else path
                    tw.setTabText(i, label)
                    tw.setTabToolTip(i, path)
                btn = tw.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn:
                    btn.setVisible(tw.count() > 1)

        # Same-path warning
        lp = self.left_tabs.currentWidget()._current_path if self.left_tabs.count() else ""
        rp = self.right_tabs.currentWidget()._current_path if self.right_tabs.count() else ""
        self.same_path_bar.setVisible(bool(lp and rp and lp == rp))
        self.save_config()

    def _on_tab_bar_clicked(self, tw):
        """點擊 tab bar（含已選中的分頁）時切換 panel 焦點；預覽中則先關閉預覽。"""
        if self._preview_target_pane is not None:
            self.close_inline_preview()
        w = tw.currentWidget()
        if w:
            self.set_active_pane(w)

    def on_tab_changed(self, idx):
        if self._preview_target_pane is not None:
            self.close_inline_preview()
        tw = self.sender()
        w = tw.widget(idx)
        if w:
            self.set_active_pane(w)
            w.update_status_info()
            # 切換分頁時，強制讓該分頁的檔案列表獲得焦點，避免 Tab 鍵失效
            w.view_stack.currentWidget().setFocus()
        # 更新兩側同路徑警告
        lp = self.left_tabs.currentWidget()._current_path if self.left_tabs.count() else ""
        rp = self.right_tabs.currentWidget()._current_path if self.right_tabs.count() else ""
        self.same_path_bar.setVisible(bool(lp and rp and lp == rp))

    def save_config(self):
        self._internal_save_config()

    def _on_system_timer_tick(self):
        # 這裡可以加入 Windows API 偵測是否鎖屏，目前依建議先傳 False 或使用現有的偵測
        locked = is_computer_locked()
        if hasattr(self, "presenter"):
            self.presenter.on_system_tick(locked)
        


    def _start_idle_c_scan(self):
        if self.idle_scanner_worker and getattr(self.idle_scanner_worker, "isRunning", lambda: False)():
            return
            
        local_drives = self.config_mgr.get_fixed_drives()
        if not local_drives: return
        
        configs_c = [(os.path.normpath(p), 99) for p in local_drives if os.path.exists(p)]
        if not configs_c: return
        
        from network_search.engine import ScannerWorker, IndexManager
        db_dir = os.path.join(os.path.dirname(self.config_mgr.config_file), "indexes")
        
        # 建立專屬的 IndexManager 實例
        idx_mgr = IndexManager(db_dir, read_only=False)
        self.idle_scanner_worker = ScannerWorker(
            configs_c, 
            idx_mgr, 
            target_db="personal",
            exclude_dirs=self.config.get("exclude_dirs", [])
        )
        self.idle_scanner_worker.finished.connect(self._on_idle_scan_finished)
        self.idle_scanner_worker.start()

    def _stop_idle_c_scan(self):
        if self.idle_scanner_worker and getattr(self.idle_scanner_worker, "isRunning", lambda: False)():
            if hasattr(self.idle_scanner_worker, 'stop'):
                self.idle_scanner_worker.stop()
            # 避免卡死 UI，不使用 .wait()，由 GC 回收
            self.idle_scanner_worker = None

    def _on_idle_scan_finished(self):
        self.idle_scanner_worker = None

    def _start_nightly_k_scan(self):
        if hasattr(self, "nightly_scanner_worker") and getattr(self.nightly_scanner_worker, "isRunning", lambda: False)():
            return

        monitored = self.config.get("monitored_paths", [])
        if not monitored: return

        configs_k = [(os.path.normpath(p), self.config.get("max_depth", 7)) for p in monitored if os.path.exists(p)]
        if not configs_k: return

        from network_search.engine import ScannerWorker, IndexManager
        db_dir = os.path.join(os.path.dirname(self.config_mgr.config_file), "indexes")
        remote_dir = self.config.get("remote_index_root")
        
        # 建立獨立的 IndexManager 處理 K 槽更新，隨後會自動拋送(Publish)給所有 Consumer
        idx_mgr = IndexManager(db_dir, read_only=False)
        self.nightly_scanner_worker = ScannerWorker(
            configs_k, 
            idx_mgr,
            remote_db_dir=remote_dir,
            target_db="local" # writes to local master.db, then publishes copy to remote
        )
        self.nightly_scanner_worker.start()

    def _internal_save_config(self):
        l_paths = [self.left_tabs.widget(i).path_edit.text()
                   for i in range(self.left_tabs.count())]
        r_paths = [self.right_tabs.widget(i).path_edit.text()
                   for i in range(self.right_tabs.count())]
        sizes = self.splitter.sizes()
        self.config_mgr.save_config(self.custom_paths, l_paths, r_paths,
                                    splitter_sizes=sizes if sum(sizes) > 0 else None)

    def closeEvent(self, event):
        # 確保所有子視窗與分頁的執行緒都已停止
        for child in self.findChildren((QDialog, ExplorerPane)):
            try:
                child.close()
            except: pass
            
        if hasattr(self, "_system_timer"):
            self._system_timer.stop()
            
        self.presenter.save_session()
        super().closeEvent(event)

    def create_toolbars(self):
        self.tool_bar = self.addToolBar(self.config_mgr.get_text("ui_main_toolbar_label", "工具列"))
        self.tool_bar.actionTriggered.connect(
            lambda: self._preview_target_pane and self.close_inline_preview())
        self.tool_bar.setMovable(False)
        self.tool_bar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.path_popup = PathPopup(self, self)
        self.pin_popup = PinPopup(self, self)

        # 工具列右鍵功能
        self.tool_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tool_bar.customContextMenuRequested.connect(self.on_toolbar_context)

        # 狀態列：左側垃圾桶（拖放送回收筒）
        self.trash_drop_btn = _TrashDropButton(self.config_mgr, self)
        self.statusBar().addWidget(self.trash_drop_btn)

        # 狀態列：左側訊息 label（快捷鍵提示 / 即時操作訊息）
        from PyQt6.QtWidgets import QApplication
        self.msg_label = QLabel()
        self.msg_label.setObjectName("msgLabel")
        self.msg_label.setTextFormat(Qt.TextFormat.RichText)
        self.msg_label.setFont(QApplication.font())
        tip_msg = self.config_mgr.get_text("ui_main_status_tip", "💡 [F2] 改名  [Alt+F2] 時間戳記  [F3/X] 移動  [F4/C] 複製  [F5] 重整  [F6] 副本  [F7] 新資料夾  [Space] 預覽  [Tab] 切換  [`] 切換分欄  [Ctrl+F] 搜尋")
        self.set_status_msg(tip_msg, "tip")
        self.statusBar().addWidget(self.msg_label, 1)

        # 狀態列：右側 pane 資訊 label
        self.pane_status_label = QLabel()
        self.pane_status_label.setObjectName("paneStatusLabel")
        self.statusBar().addPermanentWidget(self.pane_status_label)

        # 狀態列：更新按鈕 (預設隱藏)
        self.update_btn = QToolButton()
        self.update_btn.setObjectName("updateBtn")
        self.update_btn.setStyleSheet("color: #57B77F; font-weight: bold; border: 1px solid #57B77F; border-radius: 4px; padding: 2px 8px;")
        self.update_btn.hide()
        self.statusBar().addPermanentWidget(self.update_btn)

    def refresh_toolbar(self):
        self.tool_bar.clear()

        pins = self.config_mgr.get_pins()
        urgent = sum(1 for p in pins if not p.get("done") and self.config_mgr.get_pin_days_left(p) <= 1)
        done_count = sum(1 for p in pins if p.get("done"))
        active_count = len(pins) - done_count
        
        if urgent:
            tpl = self.config_mgr.get_text("ui_main_pinned_urgent", "已釘選 (⚠️ {})")
            pin_label = tpl.format(urgent)
        elif done_count:
            tpl = self.config_mgr.get_text("ui_main_pinned_active", "已釘選 ({}) | ✓{}")
            pin_label = tpl.format(active_count, done_count)
        elif pins:
            tpl = self.config_mgr.get_text("ui_main_pinned_count", "已釘選 ({})")
            pin_label = tpl.format(active_count)
        else:
            pin_label = self.config_mgr.get_text("ui_main_pinned_label", "釘選項目")

        self.pin_btn = PinDropButton(self)
        self.pin_btn.setText(pin_label)
        from PyQt6.QtGui import QIcon # Local hardened import
        self.pin_btn.setIcon(QIcon(self.config_mgr.get_ui_resource_path("pin")))
        self.pin_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pin_btn.setToolTip(self.config_mgr.get_text("ui_main_pinned_tooltip", "已釘選的檔案 / 資料夾（Ctrl+D 釘選 / 拖曳至此快速釘選）"))
        self.pin_btn.setObjectName("pinBtnUrgent" if urgent else "pinBtn")
        self.pin_btn.clicked.connect(self._show_pin_menu)
        self.tool_bar.addWidget(self.pin_btn)

        self.tool_bar.addSeparator()

        # ── 群組 3：進階功能（低頻）──────────────────────────
        snap_btn = QToolButton()
        snap_btn.setText(self.config_mgr.get_text("ui_main_btn_snapshot", "情境快照"))
        snap_btn.setIcon(QIcon(self.config_mgr.get_ui_resource_path("camera")))
        snap_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        snap_btn.setToolTip(self.config_mgr.get_text("ui_main_btn_snapshot_tooltip", "儲存 / 還原兩欄分頁的情境快照"))
        snap_btn.setObjectName("snapshotBtn")
        snap_btn.clicked.connect(self._show_snapshot_menu)
        self.tool_bar.addWidget(snap_btn)

        self.tool_bar.addSeparator()

        # ── 設定按鈕 ───────────────────────────────────────────
        from PyQt6.QtWidgets import QStyle
        settings_btn = QToolButton()
        settings_btn.setText(self.config_mgr.get_text("ui_main_btn_settings", "設定"))
        settings_icon = QIcon(self.config_mgr.get_ui_resource_path("settings"))
        if settings_icon.isNull():
            settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        settings_btn.setIcon(settings_icon)
        settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings_btn.setToolTip(self.config_mgr.get_text("ui_main_btn_settings_tooltip", "開啟應用程式設定"))
        settings_btn.setObjectName("settingsBtn")
        settings_btn.clicked.connect(self.on_settings_clicked)
        self.tool_bar.addWidget(settings_btn)

    def _show_pane_custom_paths_popup(self, pos: QPoint) -> None:
        self.path_popup.populate(self.custom_paths)
        self.path_popup.move(pos)
        self.path_popup.show()

    def on_settings_clicked(self) -> None:
        from ui.widgets.app_settings_dialog import AppSettingsDialog
        dlg = AppSettingsDialog(self.config_mgr, self)
        dlg.theme_changed.connect(self._reload_stylesheet)
        result = dlg.exec()
        
        # 不管是 Save 還是 Cancel，關閉視窗後強制同步一次當前的 Theme，解決視覺殘留
        self._reload_stylesheet()
        
        if result == QDialog.DialogCode.Accepted:
            self.show_toast(self.config_mgr.get_text("ui_main_toast_settings_saved", "設定已儲存"), "success")

    def _reload_stylesheet(self) -> None:
        from PyQt6.QtWidgets import QApplication
        ss = self.config_mgr.load_stylesheet("styles.qss", "theme.json")
        QApplication.instance().setStyleSheet(ss)
        self.update()

    def on_compare_clicked(self):
        lp = self.left_tabs.currentWidget()
        rp = self.right_tabs.currentWidget()
        if not lp or not rp:
            return
        l_path = lp.model.filePath(lp.proxy_model.mapToSource(lp.tree.rootIndex()))
        r_path = rp.model.filePath(rp.proxy_model.mapToSource(rp.tree.rootIndex()))
        if os.path.isdir(l_path) and os.path.isdir(r_path):
            CompareDialog(l_path, r_path, self).show()
        else:
            QMessageBox.warning(self, self.config_mgr.get_text("ui_main_warn_title", "警告"), self.config_mgr.get_text("ui_main_warn_both_panes_required", "兩側皆需開啟資料夾"))

    def on_advanced_search_clicked(self):
        if self.active_pane:
            self.active_pane.open_advanced_search()
        else:
            QMessageBox.warning(self, self.config_mgr.get_text("ui_main_warn_title", "警告"), self.config_mgr.get_text("ui_main_warn_select_pane", "請先點擊選取一個分頁"))

    def on_quick_access_clicked(self, path):
        if self.active_pane:
            self.active_pane.set_path(path)


    def on_add_custom_path(self):
        p = QFileDialog.getExistingDirectory(self, self.config_mgr.get_text("ui_main_dialog_new_folder", "新增資料夾"))
        if p and p not in self.custom_paths:
            self.custom_paths.append(p)
            self.refresh_toolbar()
            self.save_config()

    def remove_custom_path(self, path):
        if path in self.custom_paths:
            self.custom_paths.remove(path)
            self.refresh_toolbar()
            self.save_config()
            self.path_popup.hide()

    # ── Pin ─────────────────────────────────────────────────────────────────────

    def toggle_pin(self, path: str):
        """Pin or unpin a path. Called by Ctrl+D and context menus."""
        from ui.widgets.popups import PinNoteDialog
        if self.config_mgr.is_pinned(path):
            self.config_mgr.remove_pin(path)
            msg = self.config_mgr.get_text("ui_main_toast_unpinned", "已解除釘選：{}").format(os.path.basename(path) or path)
            self.show_toast(msg, "info")
        else:
            dlg = PinNoteDialog(os.path.basename(path) or path, self)
            if dlg.exec() == PinNoteDialog.DialogCode.Rejected:
                return
            self.config_mgr.add_pin(path, os.path.isdir(path), dlg.note())
            msg = self.config_mgr.get_text("ui_main_toast_pinned", "已釘選：{}").format(os.path.basename(path) or path)
            self.show_toast(msg, "success")
        self.refresh_toolbar()

    def add_pin_silent(self, path: str):
        """Pin a path without prompting for a note. Used by drag-and-drop."""
        if self.config_mgr.is_pinned(path):
            msg = self.config_mgr.get_text("ui_main_toast_pinned", "已釘選：{}").format(os.path.basename(path) or path)
            self.show_toast(msg, "info")
            return
        self.config_mgr.add_pin(path, os.path.isdir(path))
        msg = self.config_mgr.get_text("ui_main_toast_pinned_with_note", "已釘選：{}（右鍵可加備忘）").format(os.path.basename(path) or path)
        self.show_toast(msg, "success")
        self.refresh_toolbar()

    def set_pin_done(self, path: str, done: bool):
        self.config_mgr.set_pin_done(path, done)
        self.refresh_toolbar()

    def set_pin_important(self, path: str, important: bool):
        self.config_mgr.set_pin_important(path, important)
        label = self.config_mgr.get_text("ui_main_pinned_important", "已標為重要（永久保留）") if important else self.config_mgr.get_text("ui_main_pinned_unimportant", "已取消重要標記")
        self.show_toast(label, "success" if important else "info")
        self.refresh_toolbar()

    def edit_pin_note(self, path: str):
        """Edit the note of an existing pin."""
        from ui.widgets.popups import PinNoteDialog
        pins = self.config_mgr.get_pins()
        current_note = next((p.get("note", "") for p in pins if p["path"] == path), "")
        dlg = PinNoteDialog(os.path.basename(path) or path, self, timeout_sec=0)
        dlg._edit.setText(current_note)
        dlg._edit.selectAll()
        note = dlg.note() if dlg.exec() == PinNoteDialog.DialogCode.Accepted else None
        if note is not None:
            self.config_mgr.update_pin_note(path, note)
            self.refresh_toolbar()

    def _show_pin_menu(self):
        pins = self.config_mgr.get_pins()
        self.pin_popup.populate(pins, self.config_mgr)
        btn = getattr(self, "pin_btn", None)
        if btn:
            pos = btn.mapToGlobal(QPoint(0, btn.height()))
        else:
            pos = self.mapToGlobal(QPoint(0, 40))
        self.pin_popup.move(pos)
        self.pin_popup.show()

    def _cleanup_expired_pins(self):
        """Run on startup: remove expired pins and notify user."""
        removed = self.config_mgr.cleanup_expired_pins(ttl_days=7, on_startup=True)
        if removed:
            self.refresh_toolbar()
            names = ", ".join(os.path.basename(p) or p for p in removed[:3])
            suffix = self.config_mgr.get_text("ui_main_toast_and_more", " 等 {} 個").format(len(removed)) if len(removed) > 3 else ""
            msg = self.config_mgr.get_text("ui_main_toast_pinned_expired", "釘選已到期自動移除：{}{}")
            self.show_toast(msg.format(names, suffix), "info")

    def set_active_pane(self, pane):
        self.active_pane = pane
        l_foc = any(self.left_tabs.widget(i) ==
                    pane for i in range(self.left_tabs.count()))
        self.left_tabs.setObjectName(
            "activeTabWidget" if l_foc else "inactiveTabWidget")
        self.right_tabs.setObjectName(
            "activeTabWidget" if not l_foc else "inactiveTabWidget")
        for tw, is_active in [(self.left_tabs, l_foc), (self.right_tabs, not l_foc)]:
            preview_here = (
                self._preview_target_pane is not None and
                any(tw.widget(i) == self._preview_target_pane for i in range(tw.count()))
            )
            if is_active or preview_here:
                tw.setGraphicsEffect(None)
            else:
                effect = QGraphicsOpacityEffect(tw)
                effect.setOpacity(0.55)
                tw.setGraphicsEffect(effect)
            tw.style().unpolish(tw)
            tw.style().polish(tw)
        self._update_pane_styling()

    def _update_pane_styling(self):
        for side in [self.left_tabs, self.right_tabs]:
            for i in range(side.count()):
                p = side.widget(i)
                if p is None:
                    continue
                active = (p == self.active_pane)
                p.setObjectName("activePane" if active else "inactivePane")
                p.tree.setObjectName("active" if active else "")
                p.list_view.setObjectName("active" if active else "")
                for v in [p, p.tree, p.list_view]:
                    v.style().unpolish(v)
                    v.style().polish(v)

    def refresh_all_panes(self):
        for tw in [self.left_tabs, self.right_tabs]:
            for i in range(tw.count()):
                tw.widget(i).refresh()

    def _start_update_check(self):
        """啟動非同步更新檢查執行緒（GitHub Releases）。"""
        from ui.workers.update_manager import UpdateCheckWorker
        self._update_worker = UpdateCheckWorker(self.config_mgr)
        self._update_worker.update_available.connect(self._on_update_available)
        self._update_worker.start()

    def _on_update_available(self, version: str, download_url: str):
        """當 GitHub 有新版本時，在狀態列顯示更新按鈕。"""
        msg = self.config_mgr.get_text("ui_update_found", "🚀 新版本 {v} 已發布！").format(v=version)
        self.set_status_msg(msg, "success")

        btn_text = self.config_mgr.get_text("ui_update_now", "立即更新")
        self.update_btn.setText(btn_text)
        self.update_btn.show()

        try: self.update_btn.clicked.disconnect()
        except: pass
        self.update_btn.clicked.connect(lambda: self._trigger_update(download_url))

    def _trigger_update(self, download_url: str):
        """下載新版 zip，寫入更新腳本後關閉程式。"""
        import sys, subprocess, os
        from ui.workers.update_manager import DownloadUpdateWorker, write_update_script
        from PyQt6.QtWidgets import QProgressDialog, QApplication
        from PyQt6.QtCore import Qt

        self.update_btn.setEnabled(False)
        self.set_status_msg(self.config_mgr.get_text("ui_update_downloading", "正在下載更新…"), "")

        progress_dlg = QProgressDialog(
            self.config_mgr.get_text("ui_update_downloading", "正在下載更新…"),
            self.config_mgr.get_text("ui_cancel", "取消"), 0, 100, self
        )
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.setMinimumDuration(0)
        progress_dlg.show()

        worker = DownloadUpdateWorker(download_url)
        worker.progress.connect(progress_dlg.setValue)
        worker.error.connect(lambda msg: (
            progress_dlg.close(),
            self.set_status_msg(f"下載失敗：{msg}", "error"),
            self.update_btn.setEnabled(True),
        ))

        def on_finished(zip_path: str):
            progress_dlg.close()
            if getattr(sys, 'frozen', False):
                install_dir = os.path.dirname(sys.executable)
            else:
                install_dir = os.path.dirname(os.path.abspath(__file__))

            bat_path = write_update_script(zip_path, install_dir)
            try:
                subprocess.Popen([bat_path], creationflags=0x00000010)  # CREATE_NEW_CONSOLE
                QApplication.quit()
                sys.exit(0)
            except Exception as e:
                self.set_status_msg(f"無法執行更新腳本：{e}", "error")
                self.update_btn.setEnabled(True)

        worker.finished.connect(on_finished)
        progress_dlg.canceled.connect(worker.cancel)
        self._download_worker = worker  # 防止 GC
        worker.start()

    def on_ctrl_left(self): self.presenter.sync_to_left()
    def on_ctrl_right(self): self.presenter.sync_to_right()

    def on_alt_left(self):
        if self.active_pane:
            self.active_pane.go_back()

    def on_alt_right(self):
        if self.active_pane:
            self.active_pane.go_forward()

    def show_drive_selection(self, side):
        """彈出磁碟選單"""
        tabs = self.left_tabs if side == "left" else self.right_tabs
        menu = QMenu(self)
        from PyQt6.QtCore import QDir
        for drive in QDir.drives():
            path = drive.absoluteFilePath()
            tpl = self.config_mgr.get_text("ui_main_menu_disk", "磁碟 {}")
            action = menu.addAction(tpl.format(path))
            action.triggered.connect(
                lambda _, p=path, t=tabs: self.add_new_tab(t, p))

        # 在對應分欄的上方彈出
        pos = tabs.mapToGlobal(QPoint(0, 0))
        menu.exec(pos)

    def copy_selected_to_other_side(self):
        """將選取項目複製到對面分欄"""
        if not self.active_pane:
            return
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        target_tw = self.right_tabs if is_left else self.left_tabs
        target_pane = target_tw.currentWidget()
        if not target_pane:
            return

        dest_dir = target_pane.model.filePath(target_pane.proxy_model.mapToSource(target_pane.tree.rootIndex()))
        view = self.active_pane.view_stack.currentWidget()
        proxy = self.active_pane.list_proxy if view is self.active_pane.list_view else self.active_pane.proxy_model
        idxs = view.selectionModel().selectedRows() if hasattr(
            view, 'selectionModel') else []
        if not idxs and hasattr(view, 'selectionModel'):
            idxs = view.selectionModel().selectedIndexes()

        if not idxs:
            return

        src_paths = list(dict.fromkeys(
            self.active_pane.model.filePath(proxy.mapToSource(idx))
            for idx in idxs
        ))
        src_paths = [p for p in src_paths if p]

        if not src_paths:
            return

        # 這裡調用 view 的 check_and_perform 以顯示進度條並處理衝突
        view.check_and_perform(src_paths, dest_dir, "copy")

    def move_selected_to_other_side(self):
        """將選取項目移動到對面分欄"""
        if not self.active_pane:
            return
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        target_tw = self.right_tabs if is_left else self.left_tabs
        target_pane = target_tw.currentWidget()
        if not target_pane:
            return

        dest_dir = target_pane.model.filePath(target_pane.proxy_model.mapToSource(target_pane.tree.rootIndex()))
        view = self.active_pane.view_stack.currentWidget()
        proxy = self.active_pane.list_proxy if view is self.active_pane.list_view else self.active_pane.proxy_model
        idxs = view.selectionModel().selectedRows() if hasattr(
            view, 'selectionModel') else []
        if not idxs and hasattr(view, 'selectionModel'):
            idxs = view.selectionModel().selectedIndexes()

        src_paths = list(dict.fromkeys(
            self.active_pane.model.filePath(proxy.mapToSource(idx))
            for idx in idxs
        ))
        src_paths = [p for p in src_paths if p]

        if not src_paths:
            return

        # 這裡調用 view 的 check_and_perform 以顯示進度條並處理衝突
        view.check_and_perform(src_paths, dest_dir, "move")

    def cycle_local_tabs(self):
        """在目前側的分欄內循環切換分頁"""
        if self._preview_target_pane is not None:   # 預覽模式下禁止切換分頁
            return
        if not self.active_pane:
            return
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        tw = self.left_tabs if is_left else self.right_tabs

        if tw.count() <= 1:
            return
        idx = tw.indexOf(self.active_pane)
        next_idx = (idx + 1) % tw.count()

        target_pane = tw.widget(next_idx)
        tw.setCurrentIndex(next_idx)
        if target_pane:
            target_pane.view_stack.currentWidget().setFocus()
            self.set_active_pane(target_pane)

    def switch_side_focus(self):
        """切換左右主分欄焦點"""
        if self._preview_target_pane is not None:   # 預覽模式下禁止切換側欄
            return
        if not self.active_pane:
            return
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        tw = self.right_tabs if is_left else self.left_tabs
        pane = tw.currentWidget()
        if pane:
            pane.view_stack.currentWidget().setFocus()
            self.set_active_pane(pane)


    def show_quick_look(self, path):
        """Show the Quick Look preview dialog for the given path."""
        from ui.widgets.quick_look import QuickLookDialog
        dlg = QuickLookDialog(path, self.config_mgr, self)
        dlg.exec()
        is_left = any(self.left_tabs.widget(i) ==
                      self.active_pane for i in range(self.left_tabs.count()))
        target_tw = self.right_tabs if is_left else self.left_tabs

        pane = target_tw.currentWidget()
        if pane:
            pane.view_stack.currentWidget().setFocus()

    def _get_opposite_pane(self):
        if not self.active_pane:
            return None
        is_left = any(self.left_tabs.widget(i) == self.active_pane
                      for i in range(self.left_tabs.count()))
        opp_tabs = self.right_tabs if is_left else self.left_tabs
        return opp_tabs.currentWidget()

    def toggle_inline_preview(self, path: str) -> None:
        if self._preview_target_pane is not None:
            self.close_inline_preview()
            return
        if not path or not os.path.isfile(path):
            return
        target = self._get_opposite_pane()
        if target is None:
            return
        if target not in self._preview_panels:
            from ui.widgets.preview_panel import PreviewPanel
            panel = PreviewPanel(self.config_mgr)
            panel.action_requested.connect(self._on_preview_action)
            
            # 連接 ExplorerPane 上的按鈕與 PreviewPanel 的解析度切換
            if hasattr(target, 'quality_toggle_btn'):
                target.quality_toggle_btn.clicked.connect(panel._toggle_quality)
                panel.quality_changed.connect(target.update_quality_btn)
                
            target.view_stack.addWidget(panel)
            self._preview_panels[target] = panel
        panel = self._preview_panels[target]
        self._preview_source_pane = self.active_pane
        self._preview_target_pane = target
        # Connect directly to the view's currentChanged for instant ↑↓ updates
        self._preview_source_view = self._preview_source_pane.view_stack.currentWidget()
        self._preview_source_view.selectionModel().currentChanged.connect(
            self._on_preview_current_changed)
        self._preview_source_pane.path_changed.connect(self._on_preview_source_path_changed)
        self._preview_source_pane.set_previewing_path(path)
        panel.preview_file(path)
        
        from core.preview_worker import PDF_EXTS
        ext = os.path.splitext(path)[1].lower()
        is_pdf = ext in PDF_EXTS

        # Batch all visual changes into one repaint to prevent opacity/content flash
        self.centralWidget().setUpdatesEnabled(False)
        try:
            target.view_stack.setCurrentWidget(panel)
            target.set_preview_mode(True, is_pdf)
            self.set_active_pane(self.active_pane)
        finally:
            self.centralWidget().setUpdatesEnabled(True)
        self._preview_source_view.setFocus()

    def close_inline_preview(self) -> None:
        if self._preview_target_pane is None:
            return
        if self._preview_source_view is not None:
            try:
                self._preview_source_view.selectionModel().currentChanged.disconnect(
                    self._on_preview_current_changed)
            except RuntimeError:
                pass
            self._preview_source_view = None
        if self._preview_source_pane is not None:
            self._preview_source_pane.set_previewing_path("")
            try:
                self._preview_source_pane.path_changed.disconnect(self._on_preview_source_path_changed)
            except RuntimeError:
                pass
        target = self._preview_target_pane
        if target in self._preview_panels:
            self._preview_panels[target].clear()
        self._preview_source_pane = None
        self._preview_target_pane = None
        # Batch close transition into one repaint to prevent flash
        self.centralWidget().setUpdatesEnabled(False)
        try:
            target.set_preview_mode(False)
            target.set_view_mode(target._current_mode)
            if self.active_pane:
                self.set_active_pane(self.active_pane)  # restore normal dimming
        finally:
            self.centralWidget().setUpdatesEnabled(True)

    def _on_preview_current_changed(self, current, _previous) -> None:
        if not current.isValid() or not self._preview_source_pane:
            return
        view = self._preview_source_view
        if view is None:
            return
        pane = self._preview_source_pane
        if view is pane.flat_view:
            item = pane.flat_model.item(current.row(), 0)
            path = (item.data(Qt.ItemDataRole.UserRole) if item else "") or ""
        else:
            source_idx = view.model().mapToSource(current)
            path = pane.model.filePath(source_idx)
        if path and os.path.isfile(path) and self._preview_target_pane in self._preview_panels:
            self._preview_source_pane.set_previewing_path(path)
            self._preview_panels[self._preview_target_pane].preview_file(path)
            from core.preview_worker import PDF_EXTS
            is_pdf = os.path.splitext(path)[1].lower() in PDF_EXTS
            self._preview_target_pane.set_preview_mode(True, is_pdf)

    def _on_preview_source_path_changed(self, _path: str) -> None:
        self.close_inline_preview()

    def _on_preview_action(self, action: str, path: str) -> None:
        if not path or not os.path.exists(path):
            return
            
        source_pane = self._preview_source_pane
        target_pane = self._preview_target_pane
        if not source_pane or not target_pane:
            return

        is_left = any(self.left_tabs.widget(i) == source_pane for i in range(self.left_tabs.count()))
        
        # [究極 UX 優化]：處理幽靈預覽 (Ghost Preview)
        # 在刪除或提取前，強迫游標跳到下一筆，讓預覽視窗自動更新而不會白屏
        view = source_pane.view_stack.currentWidget()
        sel_mod = view.selectionModel()
        curr_idx = sel_mod.currentIndex()
        if curr_idx.isValid() and action in ('delete', 'extract'):
            from PyQt6.QtCore import QItemSelectionModel
            next_idx = view.model().index(curr_idx.row() + 1, 0, curr_idx.parent())
            if not next_idx.isValid():
                next_idx = view.model().index(curr_idx.row() - 1, 0, curr_idx.parent())
            if next_idx.isValid():
                sel_mod.setCurrentIndex(next_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            else:
                self.close_inline_preview()

        # 執行實際的業務邏輯
        if action == "delete":
            from core.file_ops import FileOps
            res = FileOps.delete_paths([path], permanent=False)
            errors = [r[2] for r in res if not r[1]]
            if errors:
                msg = self.config_mgr.get_text("ui_explorer_toast_delete_failed").format(errors[0])
                self.show_toast(msg, "error")
            else:
                self.register_undo([(path, path)], "trash")
            
        elif action == "extract":
            dest_dir = target_pane.path_edit.text()
            if not dest_dir: return
            dest = os.path.join(dest_dir, os.path.basename(path))
            
            if hasattr(view, "perform_operation"):
                view.perform_operation([(path, dest)], "move")
            else:
                import shutil
                shutil.move(path, dest)
                
        elif action == "duplicate":
            import shutil
            dest_pane = self._preview_target_pane
            # TODO: ExplorerPane 應暴露 public current_path() property 供外部使用
            dest_dir = dest_pane._current_path  # explorer_pane.py:446
            if not dest_dir or not os.path.isdir(dest_dir):
                self.show_toast(self.config_mgr.get_text("ui_main_toast_copy_failed_path"), "error")
                return
            base_name = os.path.basename(path)
            name_part, ext_part = os.path.splitext(base_name)
            new_path = os.path.join(dest_dir, base_name)
            counter = 2
            while os.path.exists(new_path):
                new_path = os.path.join(dest_dir, f"{name_part} ({counter}){ext_part}")
                counter += 1
            try:
                shutil.copy2(path, new_path)
                msg = self.config_mgr.get_text("ui_main_toast_copy_success").format(os.path.basename(new_path))
                self.show_toast(msg, "success")
                dest_pane.refresh()
                # 複製成功後自動推進來源面板到下一個項目（心流體驗）
                if self._preview_source_view:
                    cur = self._preview_source_view.currentIndex()
                    nxt = self._preview_source_view.indexBelow(cur)
                    if nxt.isValid():
                        self._preview_source_view.setCurrentIndex(nxt)
            except Exception as e:
                msg = self.config_mgr.get_text("ui_main_toast_copy_failed").format(e)
                self.show_toast(msg, "error")

    def _sync_side(self, side):
        if not self.active_pane:
            return
        view = self.active_pane.view_stack.currentWidget()
        idx = view.currentIndex()
        path = self.active_pane.model.filePath(
            self.active_pane.proxy_model.mapToSource(idx if idx.isValid() else view.rootIndex()))
        if os.path.isfile(path):
            path = os.path.dirname(path)
        target = self.left_tabs.currentWidget(
        ) if side == "left" else self.right_tabs.currentWidget()
        if target:
            target.set_path(path)

    # ── Snapshot ────────────────────────────────────────────────────────────────

    def _snapshot_auto_name(self) -> str:
        """依左右各分頁名稱產生預設情境名稱，例如 BBB<->CCC"""
        def tab_names(tw):
            return [tw.tabText(i) for i in range(tw.count())]
        left  = " / ".join(tab_names(self.left_tabs))  or "（空）"
        right = " / ".join(tab_names(self.right_tabs)) or "（空）"
        return f"{left}<->{right}"

    def _show_snapshot_menu(self):
        menu = QMenu(self)

        save_act = menu.addAction(self.config_mgr.get_text("ui_main_snapshot_default_name", "＋ 儲存目前情境快照"))
        save_act.triggered.connect(self._save_snapshot)

        snapshots = self.config_mgr.get_snapshots()
        if snapshots:
            menu.addSeparator()
            for i, snap in enumerate(snapshots):
                sub = menu.addMenu(f"📂 {snap['name']}")
                restore_act = sub.addAction(self.config_mgr.get_text("ui_main_snapshot_restore", "還原"))
                restore_act.triggered.connect(lambda checked, s=snap: self._restore_snapshot(s))
                del_act = sub.addAction(self.config_mgr.get_text("ui_main_snapshot_delete", "刪除"))
                del_act.triggered.connect(lambda checked, idx=i: self._delete_snapshot(idx))

        from PyQt6.QtWidgets import QToolButton
        snap_btn = None
        for w in self.tool_bar.findChildren(QToolButton):
            if w.objectName() == "snapshotBtn":
                snap_btn = w
                break
        pos = snap_btn.mapToGlobal(QPoint(0, snap_btn.height())) if snap_btn else self.mapToGlobal(QPoint(0, 40))
        menu.exec(pos)

    def _save_snapshot(self):
        from PyQt6.QtWidgets import QInputDialog
        default_name = self._snapshot_auto_name()
        title = self.config_mgr.get_text("ui_main_snapshot_dialog_title", "儲存情境快照")
        label = self.config_mgr.get_text("ui_main_snapshot_dialog_label", "快照名稱：")
        name, ok = QInputDialog.getText(self, title, label, text=default_name)
        if not ok or not name.strip():
            return
        l_paths = [self.left_tabs.widget(i).path_edit.text()
                   for i in range(self.left_tabs.count())]
        r_paths = [self.right_tabs.widget(i).path_edit.text()
                   for i in range(self.right_tabs.count())]
        sizes = self.splitter.sizes()
        self.config_mgr.add_snapshot(name.strip(), l_paths, r_paths, sizes)
        msg = self.config_mgr.get_text("ui_main_toast_snapshot_saved", "情境快照「{}」已儲存").format(name.strip())
        self.show_toast(msg, "success")

    def _restore_snapshot(self, snap: dict):
        # 清除現有分頁
        for tw in [self.left_tabs, self.right_tabs]:
            while tw.count():
                tw.removeTab(0)
        self.active_pane = None
        # 還原分頁
        for p in snap.get("left_tabs", []):
            self.add_new_tab(self.left_tabs, p)
        for p in snap.get("right_tabs", []):
            self.add_new_tab(self.right_tabs, p)
        # 還原分割比例
        sizes = snap.get("splitter_sizes")
        if sizes and len(sizes) == 2 and sum(sizes) > 0:
            self.splitter.setSizes(sizes)
        msg = self.config_mgr.get_text("ui_main_toast_snapshot_restored", "已還原情境快照「{}」").format(snap['name'])
        self.show_toast(msg, "info")

    def _delete_snapshot(self, index: int):
        self.config_mgr.delete_snapshot(index)

    # ────────────────────────────────────────────────────────────────────────────

    def set_status_msg(self, text, style_type="info"):
        """設定即時訊息內容與樣式，支援 [Key] 鍵帽化顯示。"""
        if style_type == "tip" and "[" in text:
            # 1. 預處理：先將「雙空格 (大群組間距)」與「單空格 (鍵與文字間距)」替換成唯一標記
            text = text.replace("💡", "💡&nbsp;")
            text = text.replace("  ", "{{GAP_L}}").replace(" ", "{{GAP_S}}")
            
            # 2. 定義鍵帽樣式 (VS Code Dark 風格：深灰色背景 + 淡灰色邊框)
            kbd_style = (
                "background-color: #333842; color: #abb2bf; "
                "border: 1px solid #1a1e23; border-radius: 4px; "
                "font-family: 'Consolas', 'Courier New', monospace; "
                "font-size: 11px; padding: 1px 3px;"
            )
            
            # 3. 轉換 [按鍵] 為實體鍵帽 HTML 標籤
            text = re.sub(r'\[([^\]]+)\]', 
                          f'<span style="{kbd_style}">&nbsp;\\1&nbsp;</span>', text)
            
            # 4. 還原標記：GAP_L 為群組間距(4格)，GAP_S 為鍵與字間距(1格)
            text = text.replace("{{GAP_L}}", "&nbsp;" * 4)
            text = text.replace("{{GAP_S}}", "&nbsp;")

        self.msg_label.setText(text)
        self.msg_label.setProperty("type", style_type)
        self.msg_label.style().unpolish(self.msg_label)
        self.msg_label.style().polish(self.msg_label)

    def _update_pane_status(self, text: str):
        """更新狀態列右側的 pane 資訊"""
        self.pane_status_label.setText(text)

    def show_toast(self, message: str, kind: str = "info", duration: int = 3000) -> None:
        """顯示非阻塞 Toast 通知（右下角，自動消失）。"""
        from ui.widgets.toast import show_toast as _show_toast
        _show_toast(self, message, kind, duration)

    def register_undo(self, pairs: list, kind: str) -> None:
        """記錄一筆可復原操作（copy 不記錄）。"""
        if self._undoing or kind == "copy":
            return
        from core.undo_stack import UndoEntry
        self.undo_stack.push(UndoEntry(kind=kind, pairs=list(pairs)))

    def undo_last(self) -> None:
        """Ctrl+Z：復原最後一次 move 或 rename。"""
        entry = self.undo_stack.pop()
        if entry is None:
            self.show_toast(self.config_mgr.get_text("ui_main_undo_nothing", "沒有可復原的操作"), "info")
            return

        self._undoing = True
        try:
            if entry.kind == "move":
                reversed_pairs = [(dst, src) for src, dst in entry.pairs]
                pane = self.active_pane
                if pane:
                    pane._file_view().perform_operation(reversed_pairs, "move")
            elif entry.kind == "rename":
                for old_path, new_path in entry.pairs:
                    try:
                        os.rename(new_path, old_path)
                    except OSError as e:
                        self.show_toast(self.config_mgr.get_text("ui_main_undo_failed", "復原失敗: {}").format(e), "error")
                        return
                self.refresh_all_panes()
                self.show_toast(self.config_mgr.get_text("ui_main_undo_rename_done", "已復原重新命名"), "success")
            elif entry.kind == "trash":
                import winshell
                failed = []
                for original_path, _ in entry.pairs:
                    try:
                        norm_path = os.path.abspath(os.path.normpath(original_path))
                        winshell.undelete(norm_path)
                    except Exception as e:
                        failed.append(f"{os.path.basename(original_path)} ({e})")
                self.refresh_all_panes()
                if failed:
                    self.show_toast(self.config_mgr.get_text("ui_main_undo_trash_partial_fail", "部分還原失敗：{}").format(', '.join(failed)), "error")
                else:
                    self.show_toast(self.config_mgr.get_text("ui_main_undo_trash_done", "已從回收筒還原 {} 個項目").format(len(entry.pairs)), "success")
        finally:
            self._undoing = False

    def flash_tab_hint(self):
        """閃爍顯示分頁切換提示"""
        if hasattr(self, "_flash_timer") and self._flash_timer.isActive():
            return

        original_text = self.msg_label.text()
        self.set_status_msg(self.config_mgr.get_text("ui_main_flash_tab_hint", "[Tab] 切換分頁"), "tip")
        
        self._flash_step = 0
        self._flash_timer = QTimer(self)
        
        def toggle():
            self._flash_step += 1
            # 切換閃爍屬性
            flashing = (self._flash_step % 2 == 1)
            self.msg_label.setProperty("flash", "true" if flashing else "false")
            self.msg_label.style().unpolish(self.msg_label)
            self.msg_label.style().polish(self.msg_label)

            if self._flash_step >= 6: # 閃爍 3 次 (開關各一次為 1 step，0.5s * 6 = 3s)
                self._flash_timer.stop()
                self.msg_label.setProperty("flash", "false")
                self.set_status_msg(original_text, "tip")

        self._flash_timer.timeout.connect(toggle)
        self._flash_timer.start(500)

    def on_toolbar_context(self, pos):
        """工具列右鍵選單"""
        action = self.tool_bar.actionAt(pos)
        menu = QMenu(self)

        if action and action.data():
            path = action.data()
            if os.path.exists(path) or path == "":
                menu.addAction(self.config_mgr.get_text("ui_main_ctx_open_new_tab", "在新分頁開啟")).triggered.connect(
                    lambda: self.add_new_tab(self.left_tabs if self.active_pane in [self.left_tabs.widget(i) for i in range(self.left_tabs.count())] else self.right_tabs, path)
                )

        if not menu.isEmpty():
            menu.exec(self.tool_bar.mapToGlobal(pos))

    def on_tab_context(self, tw, pos):
        """分頁右鍵選單"""
        idx = tw.tabBar().tabAt(pos)
        if idx == -1:
            return

        pane = tw.widget(idx)
        # 取得分頁目前路徑 (ExplorerPane._current_path)
        path = pane._current_path if hasattr(pane, "_current_path") else ""

        menu = QMenu(self)
        menu.addAction(self.config_mgr.get_text("ui_main_action_close_tab", "關閉分頁")).triggered.connect(lambda: self.close_tab(tw, idx))
        if path and os.path.exists(path):
            menu.addAction(self.config_mgr.get_text("ui_main_ctx_open_new_window", "在新視窗開啟")).triggered.connect(lambda: self.open_new_window(path))

        menu.exec(tw.tabBar().mapToGlobal(pos))

    def open_new_window(self, path):
        """用 Windows 檔案總管開啟該路徑"""
        try:
            os.startfile(path)
        except Exception as e:
            self.show_toast(self.config_mgr.get_text("ui_main_ctx_open_window_failed", "無法開啟新視窗: {}").format(e), "error")

    def on_quick_add_path(self, path):
        if path and path not in self.custom_paths:
            self.custom_paths.append(path)
            self.refresh_toolbar()
            self.save_config()

    def on_export_folder_tree(self, path: str) -> None:
        """遞迴產生 ├── 樹狀圖，存成 .txt 後自動開啟。"""
        from core.models.folder_tree import count_items, generate_tree
        import tempfile

        if not path or not os.path.isdir(path):
            QMessageBox.warning(self, self.config_mgr.get_text("ui_main_warn_title", "警告"), self.config_mgr.get_text("ui_main_warn_select_folder", "請選取一個資料夾。"))
            return

        ai_settings = self.config_mgr.get_ai_exporter_settings()
        blacklist = ai_settings.get("blacklist_dirs", [])
        max_depth = ai_settings.get("max_depth", 10)

        total = count_items(path, blacklist=blacklist, max_depth=max_depth)
        if total > 1000:
            reply = QMessageBox.question(
                self, self.config_mgr.get_text("ui_main_warn_too_many_items_title", "項目數量過多"),
                self.config_mgr.get_text("ui_main_warn_too_many_items_msg", "此資料夾共有 {:,} 個項目，產生樹狀圖可能需要一點時間。\n確定繼續？").format(total),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        tree_text = generate_tree(path, blacklist=blacklist, max_depth=max_depth)
        folder_name = os.path.basename(path.rstrip("/\\")) or "tree"
        tmp_path = os.path.join(tempfile.gettempdir(), f"{folder_name}_tree.txt")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(tree_text)
        import subprocess
        subprocess.Popen(["notepad.exe", tmp_path])

    def on_export_ai_context(self, path, include_contents=True):
        """啟動 AI Context 匯出流程"""
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, self.config_mgr.get_text("ui_main_warn_title", "警告"), self.config_mgr.get_text("ui_main_warn_invalid_path", "無效的路徑，無法生成報告。"))
            return
            
        settings = self.config_mgr.get_ai_exporter_settings()
        
        # Instantiate the Qt dialog (IAIExporterView adapter source)
        dialog = AIExporterProgressDialog(self)
        view_adapter = dialog.get_view_adapter()
        
        self._ai_exporter_presenter = AIExporterPresenter(view_adapter, path, settings, include_contents)
        self._ai_exporter_presenter.start()
