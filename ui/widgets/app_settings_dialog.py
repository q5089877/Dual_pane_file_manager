import datetime, re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox, QListWidget, QInputDialog, QCheckBox,
    QToolButton, QTabWidget, QWidget, QFormLayout, QSpinBox, QFileDialog, QFrame,
    QComboBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread


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
        self._theme_combo.addItems(self.config_mgr.get_theme_names())
        self._theme_combo.setCurrentText(s["theme_name"])

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

    def _on_theme_changed(self, theme_name: str) -> None:
        if self._block_theme_signal:
            return
        self._config_mgr.apply_theme_preset(theme_name)
        self.theme_changed.emit()


    # ── Tab 2: 搜尋 / K槽 ─────────────────────────────────────────────────────

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
            if not ok or txt != self.config_mgr.get_master_password():
                if ok:
                    err_title = self.config_mgr.get_text("ui_dialog_common_error", "錯誤") if self.config_mgr else "錯誤"
                    err_auth = self.config_mgr.get_text("ui_dialog_settings_auth_err", "密碼不正確") if self.config_mgr else "密碼不正確"
                    QMessageBox.warning(self, err_title, err_auth)
                self._is_master_chk.setChecked(False)

    def _on_discover_clicked(self):
        self._discover_btn.setEnabled(False)
        detecting_text = self.config_mgr.get_text("ui_dialog_settings_detecting", "正在智慧偵測中...") if self.config_mgr else "正在智慧偵測中..."
        self._remote_root_edit.setPlaceholderText(detecting_text)

        self._discovery_worker = PathDiscoveryWorker(self._config_mgr)
        self._discovery_worker.finished.connect(self._on_discovery_finished)
        self._discovery_worker.start()

    def _on_discovery_finished(self, path):
        self._discover_btn.setEnabled(True)
        if path:
            self._remote_root_edit.setText(path)
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
        fmt_img = self._img_format_edit.text().strip()
        fmt_txt = self._txt_format_edit.text().strip()

        try:
            ts = datetime.datetime.now()
            out_img = ts.strftime(fmt_img)
            out_txt = ts.strftime(fmt_txt)

            invalid_chars = r'[\\/:*?"<>|]'
            if re.search(invalid_chars, out_img) or re.search(invalid_chars, out_txt):
                err_invalid = self.config_mgr.get_text("ui_dialog_settings_err_format_invalid", r"包含非法檔名字元 (如 : / \ * 等)") if self.config_mgr else r"包含非法檔名字元 (如 : / \ * 等)"
                raise ValueError(err_invalid)

            self._format_preview_label.setText(f"圖：{self._img_prefix_edit.text()}{out_img}.png\n文：{self._txt_prefix_edit.text()}{out_txt}.txt")
            _ok = "color: {{accent}};"
            self._format_preview_label.setStyleSheet(self._config_mgr.apply_theme_to_text(_ok) if self._config_mgr else _ok)
            self._set_save_enabled(True)

        except Exception as e:
            err_tpl = self.config_mgr.get_text("ui_dialog_settings_err_format", "⚠️ 格式錯誤: {}") if self.config_mgr else "⚠️ 格式錯誤: {}"
            self._format_preview_label.setText(err_tpl.format(str(e)))
            _err = "color: {{danger}};"
            self._format_preview_label.setStyleSheet(self._config_mgr.apply_theme_to_text(_err) if self._config_mgr else _err)
            self._set_save_enabled(False)

    def _set_save_enabled(self, enabled):
        btn_save_text = self.config_mgr.get_text("ui_dialog_settings_btn_save", "完成並儲存") if self.config_mgr else "完成並儲存"
        for btn in self.findChildren(QPushButton):
            if btn.text() == btn_save_text:
                btn.setEnabled(enabled)
                break

    # ── Accept / Reject ────────────────────────────────────────────────────────

    def accept(self) -> None:
        self._config_mgr.apply_theme_preset(self._theme_combo.currentText())

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
