import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter,
    QMessageBox, QTabBar, QMenu, QLabel, QDialog,
    QGraphicsOpacityEffect, QToolButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QStandardPaths, QTimer, QSize, QThread
from PyQt6.QtGui import QShortcut, QKeySequence, QIcon

from ui.widgets.tabs import CustomTabWidget
from ui.widgets.popups import PathPopup, PinPopup
from ui.widgets.buttons import PinDropButton
from ui.panes.explorer_pane import ExplorerPane
from core.config_manager import ConfigManager
from core.interfaces import IMainWindowView
from ui.presenters.main_window_presenter import MainWindowPresenter
from core.system_utils import path_exists_fast as _path_exists_fast

from ui.windows.mw_status import _MwStatusMixin
from ui.windows.mw_undo import _MwUndoMixin
from ui.windows.mw_pins import _MwPinsMixin
from ui.windows.mw_favorites import _MwFavoritesMixin
from ui.windows.mw_workers import _MwWorkersMixin
from ui.windows.mw_file_ops import _MwFileOpsMixin
from ui.windows.mw_admin import _MwAdminMixin


class _TrashDropButton(QToolButton):
    """狀態列左側垃圾桶：點擊刪除選取項目，或拖放檔案到此送入回收筒。"""

    def __init__(self, config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        icon_path = self.config_mgr.get_ui_resource_path(
            "trash") if self.config_mgr else "ui/trash.svg"
        self.setIcon(QIcon(icon_path))
        self.setIconSize(QSize(18, 18))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setObjectName("trashDropBtn")
        tip = self.config_mgr.get_text(
            "ui_main_trash_tooltip", "點擊刪除選取項目（Del）\n拖放檔案到此處 → 移至回收筒") if self.config_mgr else "點擊刪除選取項目（Del）\n拖放檔案到此處 → 移至回收筒"
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
        paths = [u.toLocalFile()
                 for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return

        from core.file_ops import FileOps
        results = FileOps.delete_paths(paths)
        done = [p for p, ok, _ in results if ok]
        errors = [e for _, ok, e in results if not ok]

        win = self.window()
        if done:
            if hasattr(win, "register_undo"):
                win.register_undo([(p, None) for p in done], "trash")
            if hasattr(win, "refresh_all_panes"):
                win.refresh_all_panes()
            if hasattr(win, "set_status_msg"):
                msg = self.config_mgr.get_text(
                    "ui_main_trash_status_success").format(len(done))
                win.set_status_msg(msg, "success")
        if errors and hasattr(win, "set_status_msg"):
            msg = self.config_mgr.get_text(
                "ui_main_trash_status_error").format(errors[0])
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
        if not p:
            return ""
        is_left = any(self.w.left_tabs.widget(i) ==
                      p for i in range(self.w.left_tabs.count()))
        opp = self.w.right_tabs if is_left else self.w.left_tabs
        pane = opp.currentWidget()
        return pane.path_edit.text() if pane else ""

    def get_active_pane_selected_paths(self) -> list:
        p = self.w.active_pane
        if not p:
            return []
        return p._get_selected_paths()

    def navigate_active_pane(self, path: str):
        if self.w.active_pane:
            self.w.active_pane.set_path(path)

    def navigate_opposite_pane(self, path: str):
        p = self.w.active_pane
        if not p:
            return
        is_left = any(self.w.left_tabs.widget(i) ==
                      p for i in range(self.w.left_tabs.count()))
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
        if not p:
            return
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


class _QuickAccessWorker(QThread):
    """Fetches Windows Quick Access paths in a background thread to avoid blocking UI startup."""
    paths_ready = pyqtSignal(list)

    def run(self) -> None:
        from core.file_ops import FileOps
        paths = FileOps.get_win_quick_access_paths()
        self.paths_ready.emit(paths[:5] if paths else [])


class MainWindow(
    _MwAdminMixin,
    _MwWorkersMixin,
    _MwUndoMixin,
    _MwPinsMixin,
    _MwFavoritesMixin,
    _MwFileOpsMixin,
    _MwStatusMixin,
    QMainWindow,
):
    """Main application window. Pure View Adapter — all logic delegated to MainWindowPresenter."""
    file_operation_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.config_mgr = ConfigManager()
        title = self.config_mgr.get_text(
            "ui_main_window_title", "左右分欄檔案總管 (Dual Pane File Manager)")
        self.setWindowTitle(title)
        self.resize(1200, 800)
        self.showMaximized()

        self.config = self.config_mgr.load_config()
        self.custom_paths = self.config.get("custom_paths", [])

        self.active_pane = None
        self._active_side = "left"   # tracks active side even when search tab is current
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
            _db_dir = _os.path.join(_os.path.dirname(
                str(self.config_mgr.config_file)), "indexes")
            self._shared_index_manager = IndexManager(_db_dir, read_only=True)
        except Exception:
            self._shared_index_manager = None

        self._init_ui()
        QTimer.singleShot(0, self._restore_tabs)
        self._init_shortcuts()

        # Presenter wired after UI exists
        self.presenter = MainWindowPresenter(
            _MainWindowViewAdapter(self), self.config_mgr)
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

        # 啟動 10 秒後進行更新檢查 (非同步，讓 UI 充分渲染後才連網)
        QTimer.singleShot(10000, self._start_update_check)
        # 啟動 2 秒後檢查過期釘選（UI 穩定後再顯示提示）
        QTimer.singleShot(2000, self._check_stale_pins)

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

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.splitterMoved.connect(lambda: self.save_config())

        self.left_tabs = CustomTabWidget()
        self.right_tabs = CustomTabWidget()

        for tw in [self.left_tabs, self.right_tabs]:
            tw.setTabsClosable(True)
            tw.setMovable(True)
            tw.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            tw.customContextMenuRequested.connect(
                lambda pos, t=tw: self.on_tab_context(t, pos))
            tw.tabCloseRequested.connect(
                lambda idx, t=tw: self.close_tab(t, idx))
            tw.currentChanged.connect(self.on_tab_changed)
            tw.tabBarClicked.connect(lambda t=tw: self._on_tab_bar_clicked(t))
            tw.tabOverflow.connect(self.flash_tab_hint)
            from PyQt6.QtWidgets import QToolButton
            add_btn = QToolButton()
            add_btn.setText("+")
            add_btn.setObjectName("addTabBtn")
            add_btn.setToolTip(self.config_mgr.get_text(
                "ui_main_action_new_tab", "新增分頁"))
            add_btn.clicked.connect(lambda checked, t=tw: self.add_new_tab(t))
            tw.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)
            self.splitter.addWidget(tw)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)

        self.layout.addWidget(self.splitter)

        # 兩側同路徑提示條
        from PyQt6.QtWidgets import QLabel
        self.same_path_bar = QLabel(self.config_mgr.get_text(
            "ui_main_same_path_warning", "⚠ 兩側顯示相同資料夾"))
        self.same_path_bar.setObjectName("samePathWarning")
        self.same_path_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.same_path_bar.setFixedHeight(24)
        self.same_path_bar.hide()
        self.layout.addWidget(self.same_path_bar)

        self.create_toolbars()
        self.refresh_toolbar()

    def _restore_tabs(self):
        from ui.presenters.explorer_presenter import HOME_PATH
        def_path = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation)

        if not self.config.get("restore_last_session", True):
            l_paths, r_paths = [def_path], [def_path]
        else:
            l_paths = self.config.get("left_tabs") or [def_path]
            r_paths = self.config.get("right_tabs") or [def_path]

        # 若兩側都只有桌面，左側改本機視圖，右側先顯示桌面，待背景 worker 取回 Quick Access 後替換
        both_desktop = (l_paths == [def_path] and r_paths == [def_path])
        if both_desktop:
            l_paths = [HOME_PATH]
            r_paths = [def_path]

        for p in l_paths:
            self.add_new_tab(self.left_tabs, p)
        for p in r_paths:
            self.add_new_tab(self.right_tabs, p)
        sizes = self.config.get("splitter_sizes")
        if sizes and len(sizes) == 2 and sum(sizes) > 0:
            self.splitter.setSizes(sizes)

        if both_desktop:
            self._qa_worker = _QuickAccessWorker()
            self._qa_worker.paths_ready.connect(self._on_quick_access_ready)
            self._qa_worker.start()

    def _on_quick_access_ready(self, qa_paths: list[str]) -> None:
        if not qa_paths:
            return
        while self.right_tabs.count() > 0:
            widget = self.right_tabs.widget(0)
            self.right_tabs.removeTab(0)
            if widget:
                widget.deleteLater()
        for p in qa_paths:
            self.add_new_tab(self.right_tabs, p)

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
        QShortcut(QKeySequence("Ctrl+F"),
                  self).activated.connect(self.on_advanced_search_clicked)
        QShortcut(QKeySequence("Ctrl+Z"),
                  self).activated.connect(self.undo_last)

        # 隱藏管理者後門 — 不顯示於任何選單或工具列
        _admin_sc = QShortcut(QKeySequence("Ctrl+Shift+Alt+A"), self)
        _admin_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        _admin_sc.activated.connect(self._on_admin_shortcut)

    _MAX_TABS = 5

    def add_new_tab(self, tab_widget, path=None):
        if tab_widget.count() >= self._MAX_TABS:
            self.show_toast(self.config_mgr.get_text(
                "ui_main_toast_tab_limit", "最多 5 個分頁"), "warning")
            return
        from ui.presenters.explorer_presenter import HOME_PATH
        if path != HOME_PATH and (not path or not _path_exists_fast(path)):
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
        pane.custom_paths_requested.connect(self._show_favorites_menu_at)
        pane.path_changed.connect(self._record_recent_folder)

        tab_label = self.config_mgr.get_text("ui_pane_label_home", "本機") if path == HOME_PATH else (
            os.path.basename(path) or path or self.config_mgr.get_text("ui_pane_label_home", "本機"))
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
        if idx == -1:
            return

        pane = tw.widget(idx)
        path = pane.path_edit.text() if pane else ""

        menu = QMenu(self)
        close_txt = self.config_mgr.get_text(
            "ui_main_action_close_tab", "關閉分頁") if self.config_mgr else "關閉分頁"
        close_act = menu.addAction(close_txt)
        close_act.setEnabled(tw.count() > 1)
        close_act.triggered.connect(lambda: self.close_tab(tw, idx))

        add_txt = self.config_mgr.get_text(
            "ui_main_action_new_tab", "新增分頁") if self.config_mgr else "新增分頁"
        menu.addAction(add_txt).triggered.connect(lambda: self.add_new_tab(tw))

        if path and os.path.exists(path):
            menu.addSeparator()
            fav_tpl = self.config_mgr.get_text(
                "ui_main_menu_add_bookmark", "將「{}」加入我的最愛...") if self.config_mgr else "將「{}」加入我的最愛..."
            menu.addAction(fav_tpl.format(os.path.basename(path) or path)).triggered.connect(
                lambda: self._add_path_to_favorites(path)
            )
            menu.addSeparator()
            tree_txt = self.config_mgr.get_text(
                "ui_ctx_export_tree", "輸出資料夾樹狀圖") if self.config_mgr else "輸出資料夾樹狀圖"
            menu.addAction(tree_txt).triggered.connect(
                lambda: self.on_export_folder_tree(path)
            )

        menu.exec(tw.tabBar().mapToGlobal(pos))

    def close_tab(self, tw, idx):
        if tw.count() > 1:
            w = tw.widget(idx)
            if hasattr(w, 'cleanup'):
                w.cleanup()
            w.deleteLater()
            tw.removeTab(idx)
            self.save_config()
            self.update_tab_ui()
        else:
            info_title = self.config_mgr.get_text(
                "ui_dialog_info_title", "資訊") if self.config_mgr else "資訊"
            info_msg = self.config_mgr.get_text(
                "ui_main_msg_keep_one_tab", "至少需保留一個分頁") if self.config_mgr else "至少需保留一個分頁"
            QMessageBox.information(self, info_title, info_msg)

    def update_tab_ui(self):
        from ui.presenters.explorer_presenter import HOME_PATH
        for tw in [self.left_tabs, self.right_tabs]:
            for i in range(tw.count()):
                p = tw.widget(i)
                if getattr(p, '_is_search_tab', False):
                    btn = tw.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                    if btn:
                        btn.setVisible(True)
                    continue
                path = p._current_path
                if path == HOME_PATH or not path:
                    tw.setTabText(i, self.config_mgr.get_text(
                        "ui_pane_label_home", "本機"))
                    tw.setTabToolTip(i, self.config_mgr.get_text(
                        "ui_pane_tooltip_home_view", "此電腦"))
                else:
                    parts = path.replace("\\", "/").rstrip("/").split("/")
                    label = parts[-1] if parts else path
                    tw.setTabText(i, label)
                    tw.setTabToolTip(i, path)
                btn = tw.tabBar().tabButton(i, QTabBar.ButtonPosition.RightSide)
                if btn:
                    btn.setVisible(tw.count() > 1)

        # Same-path warning (skip search tabs)
        lw = self.left_tabs.currentWidget()
        rw = self.right_tabs.currentWidget()
        lp = getattr(lw, '_current_path', '') if lw else ""
        rp = getattr(rw, '_current_path', '') if rw else ""
        self.same_path_bar.setVisible(bool(lp and rp and lp == rp))
        self.save_config()

    def add_search_tab(self, source_pane) -> None:
        tw = next(
            (t for t in [self.left_tabs, self.right_tabs]
             for i in range(t.count()) if t.widget(i) is source_pane),
            None)
        if tw is None:
            return
        if tw.count() >= self._MAX_TABS:
            self.show_toast(self.config_mgr.get_text(
                "ui_main_toast_tab_limit", "最多 5 個分頁"), "warning")
            return
        from ui.widgets.search_panel import SearchPanel
        panel = SearchPanel(source_pane._current_path or source_pane.model.rootPath(), self.config_mgr, self)
        idx = tw.addTab(panel, "🔍 搜尋")
        tw.setCurrentIndex(idx)
        panel.close_requested.connect(lambda: self._close_search_tab(tw, panel))
        panel.focus_search()
        self.update_tab_ui()

    def _close_search_tab(self, tw, panel) -> None:
        panel.cleanup()
        idx = tw.indexOf(panel)
        if idx >= 0:
            tw.widget(idx).deleteLater()
            tw.removeTab(idx)
            self.update_tab_ui()

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
            if getattr(w, '_is_search_tab', False):
                w.focus_search()
            else:
                w.update_status_info()
                w.view_stack.currentWidget().setFocus()
        lw = self.left_tabs.currentWidget()
        rw = self.right_tabs.currentWidget()
        lp = getattr(lw, '_current_path', '') if lw else ""
        rp = getattr(rw, '_current_path', '') if rw else ""
        self.same_path_bar.setVisible(bool(lp and rp and lp == rp))

    def save_config(self):
        self._internal_save_config()

    def _internal_save_config(self):
        l_paths = [self.left_tabs.widget(i).path_edit.text()
                   for i in range(self.left_tabs.count())
                   if not getattr(self.left_tabs.widget(i), '_is_search_tab', False)]
        r_paths = [self.right_tabs.widget(i).path_edit.text()
                   for i in range(self.right_tabs.count())
                   if not getattr(self.right_tabs.widget(i), '_is_search_tab', False)]
        sizes = self.splitter.sizes()
        self.config_mgr.save_config(self.custom_paths, l_paths, r_paths,
                                    splitter_sizes=sizes if sum(sizes) > 0 else None)

    def closeEvent(self, event):
        # 確保所有子視窗與分頁的執行緒都已停止
        for child in self.findChildren((QDialog, ExplorerPane)):
            try:
                child.close()
            except:
                pass

        if hasattr(self, "_system_timer"):
            self._system_timer.stop()

        self.presenter.save_session()
        super().closeEvent(event)

    def create_toolbars(self):
        self.tool_bar = self.addToolBar(
            self.config_mgr.get_text("ui_main_toolbar_label", "工具列"))
        self.tool_bar.actionTriggered.connect(
            lambda: self._preview_target_pane and self.close_inline_preview())
        self.tool_bar.setMovable(False)
        self.tool_bar.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.path_popup = PathPopup(self, self)
        self.pin_popup = PinPopup(self, self)

        # 工具列右鍵功能
        self.tool_bar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tool_bar.customContextMenuRequested.connect(
            self.on_toolbar_context)

        # 狀態列：左側垃圾桶（拖放送回收筒）
        self.trash_drop_btn = _TrashDropButton(self.config_mgr, self)
        self.statusBar().addWidget(self.trash_drop_btn)

        # 狀態列：左側訊息 label（快捷鍵提示 / 即時操作訊息）
        from PyQt6.QtWidgets import QApplication
        self.msg_label = QLabel()
        self.msg_label.setObjectName("msgLabel")
        self.msg_label.setTextFormat(Qt.TextFormat.RichText)
        self.msg_label.setFont(QApplication.font())
        tip_msg = self.config_mgr.get_text(
            "ui_main_status_tip", "💡 [F2] 改名  [Alt+F2] 時間戳記  [F3/X] 移動  [F4/C] 複製  [F5] 重整  [F6] 副本  [F7] 新資料夾  [Space] 預覽  [Tab] 切換  [`] 切換分欄  [Ctrl+F] 搜尋")
        self.set_status_msg(tip_msg, "tip")
        self.statusBar().addWidget(self.msg_label, 1)

        # 狀態列：右側 pane 資訊 label
        self.pane_status_label = QLabel()
        self.pane_status_label.setObjectName("paneStatusLabel")
        self.statusBar().addPermanentWidget(self.pane_status_label)

        # 狀態列：更新按鈕 (預設隱藏)
        self.update_btn = QToolButton()
        self.update_btn.setObjectName("updateBtn")
        self.update_btn.setStyleSheet(
            "color: #57B77F; font-weight: bold; border: 1px solid #57B77F; border-radius: 4px; padding: 2px 8px;")
        self.update_btn.hide()
        self.statusBar().addPermanentWidget(self.update_btn)

    def refresh_toolbar(self):
        self.tool_bar.clear()

        pins = self.config_mgr.get_pins()
        if pins:
            tpl = self.config_mgr.get_text("ui_main_pinned_count", "已釘選 ({})")
            pin_label = tpl.format(len(pins))
        else:
            pin_label = self.config_mgr.get_text(
                "ui_main_pinned_label", "釘選項目")

        self.pin_btn = PinDropButton(self)
        self.pin_btn.setText(pin_label)
        from PyQt6.QtGui import QIcon  # Local hardened import
        self.pin_btn.setIcon(
            QIcon(self.config_mgr.get_ui_resource_path("pin")))
        self.pin_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pin_btn.setToolTip(self.config_mgr.get_text(
            "ui_main_pinned_tooltip", "已釘選的檔案 / 資料夾（Ctrl+D 釘選 / 拖曳至此快速釘選）"))
        self.pin_btn.setObjectName("pinBtn")
        self.pin_btn.clicked.connect(self._show_pin_menu)
        self.tool_bar.addWidget(self.pin_btn)

        self.tool_bar.addSeparator()

        deep_btn = QToolButton()
        deep_btn.setText(self.config_mgr.get_text("ui_pane_btn_deep_search", "深度搜尋"))
        deep_btn.setIcon(QIcon(self.config_mgr.get_ui_resource_path("search")))
        deep_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        deep_btn.setToolTip(self.config_mgr.get_text("ui_pane_tooltip_deep_search", "深度搜尋（索引 / 內容）"))
        deep_btn.setObjectName("deepSearchBtn")
        deep_btn.clicked.connect(self._open_deep_search)
        self.tool_bar.addWidget(deep_btn)

        self.tool_bar.addSeparator()

        # ── 設定按鈕 ───────────────────────────────────────────
        from PyQt6.QtWidgets import QStyle
        settings_btn = QToolButton()
        settings_btn.setText(self.config_mgr.get_text(
            "ui_main_btn_settings", "設定"))
        settings_icon = QIcon(self.config_mgr.get_ui_resource_path("settings"))
        if settings_icon.isNull():
            settings_icon = self.style().standardIcon(
                QStyle.StandardPixmap.SP_FileDialogDetailedView)
        settings_btn.setIcon(settings_icon)
        settings_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        settings_btn.setToolTip(self.config_mgr.get_text(
            "ui_main_btn_settings_tooltip", "開啟應用程式設定"))
        settings_btn.setObjectName("settingsBtn")
        settings_btn.clicked.connect(self.on_settings_clicked)
        self.tool_bar.addWidget(settings_btn)

    def on_settings_clicked(self) -> None:
        from ui.widgets.app_settings_dialog import AppSettingsDialog
        dlg = AppSettingsDialog(self.config_mgr, self)
        dlg.theme_changed.connect(self._reload_stylesheet)
        result = dlg.exec()

        # 不管是 Save 還是 Cancel，關閉視窗後強制同步一次當前的 Theme，解決視覺殘留
        self._reload_stylesheet()

        if result == QDialog.DialogCode.Accepted:
            self.show_toast(self.config_mgr.get_text(
                "ui_main_toast_settings_saved", "設定已儲存"), "success")

    def _reload_stylesheet(self) -> None:
        from PyQt6.QtWidgets import QApplication
        ss = self.config_mgr.load_stylesheet("styles.qss", "theme.json")
        QApplication.instance().setStyleSheet(ss)
        self.update()

    def set_active_pane(self, pane):
        if not getattr(pane, '_is_search_tab', False):
            self.active_pane = pane
        l_foc = any(self.left_tabs.widget(i) ==
                    pane for i in range(self.left_tabs.count()))
        self._active_side = "left" if l_foc else "right"
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
        for tw_side, side in [("left", self.left_tabs), ("right", self.right_tabs)]:
            is_active_side = (tw_side == self._active_side)
            for i in range(side.count()):
                p = side.widget(i)
                if p is None:
                    continue
                if getattr(p, '_is_search_tab', False):
                    active = is_active_side and (side.currentWidget() == p)
                    p.setObjectName("activePane" if active else "inactivePane")
                    tc = self.config_mgr.get_theme_colors() if self.config_mgr else {}
                    if active:
                        color = tc.get("activeBorder", "#D97706")
                        p.setStyleSheet(
                            f"SearchPanel {{ border: 1.5px solid {color};"
                            f" border-radius: 8px; }}")
                    else:
                        border = tc.get("border", "#3e4451")
                        p.setStyleSheet(
                            f"SearchPanel {{ border: 2px solid {border};"
                            f" border-radius: 8px; }}")
                else:
                    active = (p == self.active_pane) and is_active_side
                    p.setObjectName("activePane" if active else "inactivePane")
                    p.tree.setObjectName("active" if active else "")
                    p.list_view.setObjectName("active" if active else "")
                    for v in [p, p.tree, p.list_view]:
                        v.style().unpolish(v)
                        v.style().polish(v)

    def refresh_all_panes(self):
        for tw in [self.left_tabs, self.right_tabs]:
            for i in range(tw.count()):
                w = tw.widget(i)
                if not getattr(w, '_is_search_tab', False):
                    w.refresh()

    def on_ctrl_left(self): self.presenter.sync_to_left()
    def on_ctrl_right(self): self.presenter.sync_to_right()

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
            if getattr(target_pane, '_is_search_tab', False):
                target_pane.focus_search()
            else:
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
            if getattr(pane, '_is_search_tab', False):
                pane.focus_search()
            else:
                pane.view_stack.currentWidget().setFocus()
            self.set_active_pane(pane)

    def _get_opposite_pane(self):
        opp_tabs = self.right_tabs if self._active_side == "left" else self.left_tabs
        target = opp_tabs.currentWidget()
        if target and getattr(target, '_is_search_tab', False):
            for i in range(opp_tabs.count()):
                w = opp_tabs.widget(i)
                if not getattr(w, '_is_search_tab', False):
                    return w
            return None
        return target

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
            target.view_stack.addWidget(panel)
            self._preview_panels[target] = panel
        panel = self._preview_panels[target]
        self._preview_source_pane = self.active_pane
        self._preview_target_pane = target
        # Connect source-view tracking only for explorer panes (search tabs handle their own updates)
        if self._preview_source_pane and hasattr(self._preview_source_pane, 'view_stack'):
            self._preview_source_view = self._preview_source_pane.view_stack.currentWidget()
            self._preview_source_view.selectionModel().currentChanged.connect(
                self._on_preview_current_changed)
            self._preview_source_pane.path_changed.connect(
                self._on_preview_source_path_changed)
            self._preview_source_pane.set_previewing_path(path)
        panel.preview_file(path)

        # Batch all visual changes into one repaint to prevent opacity/content flash
        self.centralWidget().setUpdatesEnabled(False)
        try:
            target.view_stack.setCurrentWidget(panel)
            target.set_preview_mode(True)
            # Use _active_side to dim correctly when source may be a search tab
            src_tabs = self.left_tabs if self._active_side == "left" else self.right_tabs
            self.set_active_pane(src_tabs.currentWidget())
        finally:
            self.centralWidget().setUpdatesEnabled(True)
        if self._preview_source_view:
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
            if hasattr(self._preview_source_pane, 'set_previewing_path'):
                self._preview_source_pane.set_previewing_path("")
            if hasattr(self._preview_source_pane, 'path_changed'):
                try:
                    self._preview_source_pane.path_changed.disconnect(
                        self._on_preview_source_path_changed)
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
                # restore normal dimming
                self.set_active_pane(self.active_pane)
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
            self._preview_target_pane.set_preview_mode(True)

    def _on_preview_source_path_changed(self, _path: str) -> None:
        self.close_inline_preview()

    def _on_preview_action(self, action: str, path: str) -> None:
        if not path or not os.path.exists(path):
            return

        source_pane = self._preview_source_pane
        target_pane = self._preview_target_pane
        if not source_pane or not target_pane:
            return

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
                sel_mod.setCurrentIndex(
                    next_idx, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
            else:
                self.close_inline_preview()

        # 執行實際的業務邏輯
        if action == "delete":
            from core.file_ops import FileOps
            res = FileOps.delete_paths([path], permanent=False)
            errors = [r[2] for r in res if not r[1]]
            if errors:
                msg = self.config_mgr.get_text(
                    "ui_explorer_toast_delete_failed").format(errors[0])
                self.show_toast(msg, "error")
            else:
                self.register_undo([(path, path)], "trash")

        elif action == "extract":
            dest_dir = target_pane.path_edit.text()
            if not dest_dir:
                return
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
                self.show_toast(self.config_mgr.get_text(
                    "ui_main_toast_copy_failed_path"), "error")
                return
            base_name = os.path.basename(path)
            name_part, ext_part = os.path.splitext(base_name)
            new_path = os.path.join(dest_dir, base_name)
            counter = 2
            while os.path.exists(new_path):
                new_path = os.path.join(
                    dest_dir, f"{name_part} ({counter}){ext_part}")
                counter += 1
            try:
                shutil.copy2(path, new_path)
                msg = self.config_mgr.get_text(
                    "ui_main_toast_copy_success").format(os.path.basename(new_path))
                self.show_toast(msg, "success")
                dest_pane.refresh()
                # 複製成功後自動推進來源面板到下一個項目（心流體驗）
                if self._preview_source_view:
                    cur = self._preview_source_view.currentIndex()
                    nxt = self._preview_source_view.indexBelow(cur)
                    if nxt.isValid():
                        self._preview_source_view.setCurrentIndex(nxt)
            except Exception as e:
                msg = self.config_mgr.get_text(
                    "ui_main_toast_copy_failed").format(e)
                self.show_toast(msg, "error")

    def on_toolbar_context(self, pos):
        """工具列右鍵選單"""
        action = self.tool_bar.actionAt(pos)
        menu = QMenu(self)

        if action and action.data():
            path = action.data()
            if os.path.exists(path) or path == "":
                menu.addAction(self.config_mgr.get_text("ui_main_ctx_open_new_tab", "在新分頁開啟")).triggered.connect(
                    lambda: self.add_new_tab(self.left_tabs if self.active_pane in [self.left_tabs.widget(
                        i) for i in range(self.left_tabs.count())] else self.right_tabs, path)
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
        menu.addAction(self.config_mgr.get_text("ui_main_action_close_tab",
                       "關閉分頁")).triggered.connect(lambda: self.close_tab(tw, idx))
        if path and os.path.exists(path):
            menu.addAction(self.config_mgr.get_text("ui_main_ctx_open_new_window",
                           "在新視窗開啟")).triggered.connect(lambda: self.open_new_window(path))

        menu.exec(tw.tabBar().mapToGlobal(pos))

