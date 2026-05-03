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
    finished = pyqtSignal(str)

    def __init__(self, config_mgr):
        super().__init__()
        self.config_mgr = config_mgr

    def run(self):
        path = self.config_mgr.auto_discover_remote_root()
        self.finished.emit(path or "")


class AppSettingsDialog(QDialog):
    """集中式設定對話框：外觀 / 索引 / 行為"""

    theme_changed = pyqtSignal()

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._config_mgr = config_mgr
        s = config_mgr.get_app_settings()
        self._backup_theme = s["theme_name"]
        self._backup_lang = s.get("language", "zh_TW")
        self._block_theme_signal = False

        title = self.config_mgr.get_text("ui_dialog_settings_title", "設定") if self.config_mgr else "設定"
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self._build_ui(s)

    def _build_ui(self, s: dict) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 12)

        tabs = QTabWidget()
        root.addWidget(tabs)

        tabs.addTab(self._tab_appearance(s), "🎨 外觀")
        tabs.addTab(self._tab_index(s),      "🔍 索引")
        tabs.addTab(self._tab_behavior(s),   "⚙️ 行為")

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

    def _muted_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        qss = "color: {{textMuted}}; font-size: 11px;"
        if self._config_mgr:
            qss = self._config_mgr.apply_theme_to_text(qss)
        lbl.setStyleSheet(qss)
        lbl.setWordWrap(True)
        return lbl

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        return sep

    # ── Tab 1: 外觀 ────────────────────────────────────────────────────────────

    def _tab_appearance(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(self.config_mgr.get_theme_names())
        self._theme_combo.setCurrentText(s["theme_name"])
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_theme", "主題："), self._theme_combo)

        self._lang_combo = QComboBox()
        l_zh = self.config_mgr.get_text("ui_lang_zh_TW", "繁體中文")
        l_en = self.config_mgr.get_text("ui_lang_en_US", "English")
        self._lang_options = [(l_zh, "zh_TW"), (l_en, "en_US")]
        self._lang_combo.addItems([name for name, _ in self._lang_options])
        cur_lang = s.get("language", "zh_TW")
        for i, (_, code) in enumerate(self._lang_options):
            if code == cur_lang:
                self._lang_combo.setCurrentIndex(i)
                break
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_lang", "語言："), self._lang_combo)

        self._restore_session_chk = QCheckBox(
            self.config_mgr.get_text("ui_dialog_settings_restore_session", "啟動時還原上一次的分頁"))
        self._restore_session_chk.setChecked(s.get("restore_last_session", True))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_startup", "啟動行為："),
                 self._restore_session_chk)

        return w

    def _on_theme_changed(self, theme_name: str) -> None:
        if self._block_theme_signal:
            return
        self._config_mgr.apply_theme_preset(theme_name)
        self.theme_changed.emit()

    # ── Tab 2: 索引 ────────────────────────────────────────────────────────────

    def _tab_index(self, s: dict) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 共用欄位（Master + Consumer 都需要）──────────────────────────────
        w_common, f_common = self._form_widget()

        # 角色
        self._is_master_chk = QCheckBox(
            self.config_mgr.get_text("ui_dialog_settings_master_mode", "啟用生產者模式 (Master Node)"))
        self._is_master_chk.setChecked(s.get("is_master_node", False))
        self._is_master_chk.setToolTip(
            self.config_mgr.get_text("ui_dialog_settings_master_mode_tip",
                                     "僅公司主機需要開啟。開啟後負責執行背景掃描並發布索引。"))
        self._is_master_chk.toggled.connect(self._on_master_toggled)
        f_common.addRow(self.config_mgr.get_text("ui_dialog_settings_label_role", "運行角色："),
                        self._is_master_chk)

        # 團隊索引存放路徑
        self._remote_root_edit = QLineEdit(s.get("remote_index_root", ""))
        self._remote_root_edit.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_settings_remote_root_placeholder", "K:\\... 資料庫存放路徑"))
        self._discover_btn = QToolButton()
        self._discover_btn.setText("🪄")
        self._discover_btn.setToolTip(
            self.config_mgr.get_text("ui_dialog_settings_remote_root_tooltip", "智慧偵測網路索引位置"))
        self._discover_btn.clicked.connect(self._on_discover_clicked)
        browse_remote = QPushButton("📂")
        browse_remote.setFixedWidth(32)
        browse_remote.clicked.connect(lambda: self._browse_dir(self._remote_root_edit))
        row_remote = QHBoxLayout()
        row_remote.addWidget(self._remote_root_edit)
        row_remote.addWidget(self._discover_btn)
        row_remote.addWidget(browse_remote)
        f_common.addRow(self.config_mgr.get_text("ui_dialog_settings_label_remote_root", "團隊索引存放路徑："),
                        row_remote)

        # 搜尋結果上限
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(100, 50000)
        self._limit_spin.setSingleStep(100)
        self._limit_spin.setValue(s.get("search_limit", 1000))
        f_common.addRow(self.config_mgr.get_text("ui_dialog_settings_label_limit", "搜尋結果上限："),
                        self._limit_spin)

        layout.addWidget(w_common)

        # ── Master-only 區塊（可 show/hide）──────────────────────────────────
        self._master_section = QWidget()
        layout.addWidget(self._master_section)
        ms_layout = QVBoxLayout(self._master_section)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_layout.setSpacing(0)

        w_master, f_master = self._form_widget()

        f_master.addRow(self._separator())
        f_master.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_monitored_note",
                                     "Master Node 掃描的來源資料夾（如 C:\\, K:\\Project）")))

        # 監控路徑清單
        self._path_list = QListWidget()
        self._path_list.setMaximumHeight(120)
        for p in s.get("monitored_paths", []):
            self._path_list.addItem(p)
        f_master.addRow(self._path_list)

        btn_add_text = self.config_mgr.get_text("ui_dialog_settings_btn_add_path", "新增路徑")
        btn_rm_text  = self.config_mgr.get_text("ui_dialog_settings_btn_remove_path", "移除所選")
        add_btn = QPushButton(btn_add_text)
        add_btn.clicked.connect(self._on_add_monitored_path)
        rm_btn = QPushButton(btn_rm_text)
        rm_btn.clicked.connect(self._on_remove_monitored_path)
        path_btns = QHBoxLayout()
        path_btns.addWidget(add_btn)
        path_btns.addWidget(rm_btn)
        path_btns.addStretch()
        f_master.addRow(path_btns)

        f_master.addRow(self._separator())
        f_master.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_nightly_note",
                                     "夜間自動掃描索引的執行時間（24小時制）")))

        # 預設搜尋根目錄
        self._scan_root_edit = QLineEdit(s.get("default_scan_root", ""))
        self._scan_root_edit.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_settings_scan_root_placeholder", "K: 或其他磁碟根目錄"))
        browse_scan = QPushButton("📂")
        browse_scan.setFixedWidth(32)
        browse_scan.clicked.connect(lambda: self._browse_dir(self._scan_root_edit))
        row_scan = QHBoxLayout()
        row_scan.addWidget(self._scan_root_edit)
        row_scan.addWidget(browse_scan)
        f_master.addRow(self.config_mgr.get_text("ui_dialog_settings_label_scan_root", "預設搜尋根目錄："),
                        row_scan)

        # 夜間排程
        self._hour_spin = QSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setValue(s.get("nightly_scan_hour", 2))
        self._hour_spin.setSuffix(self.config_mgr.get_text("ui_dialog_settings_hour_suffix", " 時"))
        f_master.addRow(self.config_mgr.get_text("ui_dialog_settings_label_nightly_hour", "夜間掃描時間："),
                        self._hour_spin)

        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 59)
        self._min_spin.setValue(s.get("nightly_scan_minute", 0))
        self._min_spin.setSuffix(self.config_mgr.get_text("ui_dialog_settings_min_suffix", " 分"))
        f_master.addRow(self.config_mgr.get_text("ui_dialog_settings_label_nightly_minute", "分鐘："),
                        self._min_spin)

        ms_layout.addWidget(w_master)
        ms_layout.addStretch()

        layout.addStretch()

        # 初始可見性
        self._master_section.setVisible(s.get("is_master_node", False))

        return outer

    def _on_master_toggled(self, checked: bool) -> None:
        if checked:
            title = self.config_mgr.get_text("ui_dialog_settings_auth_title", "權限驗證")
            msg   = self.config_mgr.get_text("ui_dialog_settings_auth_msg", "開啟生產者模式請輸入密碼:")
            txt, ok = QInputDialog.getText(self, title, msg, QLineEdit.EchoMode.Password)
            if not ok or txt != self.config_mgr.get_master_password():
                if ok:
                    QMessageBox.warning(
                        self,
                        self.config_mgr.get_text("ui_dialog_common_error", "錯誤"),
                        self.config_mgr.get_text("ui_dialog_settings_auth_err", "密碼不正確"))
                self._is_master_chk.setChecked(False)
                return
        self._master_section.setVisible(checked)

    def _on_add_monitored_path(self):
        title = self.config_mgr.get_text("ui_dialog_settings_dlg_select_dir", "選擇要監測的資料夾")
        path = QFileDialog.getExistingDirectory(self, title)
        if path:
            for i in range(self._path_list.count()):
                if self._path_list.item(i).text() == path:
                    return
            self._path_list.addItem(path)

    def _on_remove_monitored_path(self):
        for item in self._path_list.selectedItems():
            self._path_list.takeItem(self._path_list.row(item))

    def _on_discover_clicked(self):
        self._discover_btn.setEnabled(False)
        self._remote_root_edit.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_settings_detecting", "正在智慧偵測中..."))
        self._discovery_worker = PathDiscoveryWorker(self._config_mgr)
        self._discovery_worker.finished.connect(self._on_discovery_finished)
        self._discovery_worker.start()

    def _on_discovery_finished(self, path: str) -> None:
        self._discover_btn.setEnabled(True)
        if path:
            self._remote_root_edit.setText(path)
            ok_qss = "background-color: {{success}}; color: {{text}};"
            self._remote_root_edit.setStyleSheet(
                self._config_mgr.apply_theme_to_text(ok_qss) if self._config_mgr else ok_qss)
            QTimer.singleShot(1000, lambda: self._remote_root_edit.setStyleSheet(""))
            QMessageBox.information(
                self,
                self.config_mgr.get_text("ui_dialog_settings_detect_success_title", "偵測成功"),
                self.config_mgr.get_text("ui_dialog_settings_detect_success_msg",
                                         "已尋獲索引存放區：\n{}").format(path))
        else:
            self._remote_root_edit.setPlaceholderText(
                self.config_mgr.get_text("ui_dialog_settings_detect_fail", "偵測失敗，請手動指定"))
            QMessageBox.warning(
                self,
                self.config_mgr.get_text("ui_dialog_settings_detect_fail_title", "偵測失敗"),
                self.config_mgr.get_text("ui_dialog_settings_detect_fail_msg",
                                         "無法自動定位網路索引，請手動選擇資料夾。"))

    def _browse_dir(self, edit: QLineEdit) -> None:
        title = self.config_mgr.get_text("ui_dialog_settings_dlg_select_dir_general", "選擇資料夾")
        path = QFileDialog.getExistingDirectory(self, title, edit.text() or "")
        if path:
            edit.setText(path)

    # ── Tab 3: 行為 ────────────────────────────────────────────────────────────

    def _tab_behavior(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        # 預覽字體
        self._preview_font_spin = QSpinBox()
        self._preview_font_spin.setRange(9, 24)
        self._preview_font_spin.setValue(s.get("preview_font_size", 13))
        self._preview_font_spin.setSuffix(" px")
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_preview_font", "預覽字體大小："),
                 self._preview_font_spin)

        # 刪除防呆
        self._confirm_delete_chk = QCheckBox(
            self.config_mgr.get_text("ui_dialog_settings_confirm_delete", "刪除檔案前顯示確認視窗"))
        self._confirm_delete_chk.setChecked(s.get("confirm_before_delete", True))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_delete", "刪除防呆："),
                 self._confirm_delete_chk)

        # AI 匯出排除目錄
        ai_s = self._config_mgr.get_ai_exporter_settings()
        self._ai_exclude_edit = QLineEdit(", ".join(ai_s.get("blacklist_dirs", [])))
        self._ai_exclude_edit.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_settings_ai_exclude_placeholder", "例如: node_modules, .git"))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_ai_exclude", "AI 匯出排除目錄："),
                 self._ai_exclude_edit)

        f.addRow(self._separator())
        f.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_paste_note",
                                     "「貼上為檔案」功能的命名規則（支援 strftime 格式）")))

        # 圖片貼上
        default_img = self.config_mgr.get_text("paste_prefix_image", "剪貼圖")
        self._img_prefix_edit = QLineEdit(s.get("image_prefix", default_img))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_img_prefix", "圖片前綴："),
                 self._img_prefix_edit)

        self._img_format_edit = QLineEdit(s.get("image_format", "%Y%m%d_%H%M%S"))
        self._img_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._img_format_edit.textChanged.connect(self._update_format_preview)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_img_format", "圖片日期格式："),
                 self._img_format_edit)

        # 文字貼上
        default_txt = self.config_mgr.get_text("paste_prefix_text", "文字筆記")
        self._txt_prefix_edit = QLineEdit(s.get("text_prefix", default_txt))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_txt_prefix", "文字前綴："),
                 self._txt_prefix_edit)

        self._txt_format_edit = QLineEdit(s.get("text_format", "%Y%m%d_%H%M%S"))
        self._txt_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._txt_format_edit.textChanged.connect(self._update_format_preview)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_txt_format", "文字日期格式："),
                 self._txt_format_edit)

        # 格式預覽
        self._format_preview_label = QLabel()
        preview_qss = "color: {{accent}}; font-size: 11px; font-weight: bold;"
        if self._config_mgr:
            preview_qss = self._config_mgr.apply_theme_to_text(preview_qss)
        self._format_preview_label.setStyleSheet(preview_qss)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_preview", "💡 預覽："),
                 self._format_preview_label)

        self._update_format_preview()
        return w

    def _update_format_preview(self):
        fmt_img = self._img_format_edit.text().strip()
        fmt_txt = self._txt_format_edit.text().strip()
        try:
            ts = datetime.datetime.now()
            out_img = ts.strftime(fmt_img)
            out_txt = ts.strftime(fmt_txt)
            if re.search(r'[\\/:*?"<>|]', out_img) or re.search(r'[\\/:*?"<>|]', out_txt):
                raise ValueError(
                    self.config_mgr.get_text("ui_dialog_settings_err_format_invalid",
                                             r"包含非法檔名字元 (如 : / \ * 等)"))
            self._format_preview_label.setText(
                f"圖：{self._img_prefix_edit.text()}{out_img}.png\n"
                f"文：{self._txt_prefix_edit.text()}{out_txt}.txt")
            ok_qss = "color: {{accent}};"
            self._format_preview_label.setStyleSheet(
                self._config_mgr.apply_theme_to_text(ok_qss) if self._config_mgr else ok_qss)
            self._set_save_enabled(True)
        except Exception as e:
            self._format_preview_label.setText(
                self.config_mgr.get_text("ui_dialog_settings_err_format", "⚠️ 格式錯誤: {}").format(str(e)))
            err_qss = "color: {{danger}};"
            self._format_preview_label.setStyleSheet(
                self._config_mgr.apply_theme_to_text(err_qss) if self._config_mgr else err_qss)
            self._set_save_enabled(False)

    def _set_save_enabled(self, enabled: bool) -> None:
        btn_text = self.config_mgr.get_text("ui_dialog_settings_btn_save", "完成並儲存")
        for btn in self.findChildren(QPushButton):
            if btn.text() == btn_text:
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
            QMessageBox.information(
                self,
                self.config_mgr.get_text("ui_dialog_settings_lang_changed_title", "語言已變更"),
                self.config_mgr.get_text("ui_dialog_settings_lang_changed_msg",
                                         "語言設定已儲存，重新啟動應用程式後生效。"))
        super().accept()

    def reject(self) -> None:
        self._block_theme_signal = True
        self._config_mgr.apply_theme_preset(self._backup_theme)
        self._block_theme_signal = False
        self.theme_changed.emit()
        super().reject()
