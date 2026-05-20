import datetime
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox, QListWidget, QInputDialog, QCheckBox,
    QTabWidget, QWidget, QFormLayout, QSpinBox, QFileDialog, QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal


class AppSettingsDialog(QDialog):
    """集中式設定對話框：外觀 / 索引 / 行為"""

    theme_changed = pyqtSignal()

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._config_mgr = config_mgr
        s = config_mgr.get_app_settings()

        title = self.config_mgr.get_text(
            "ui_dialog_settings_title", "設定") if self.config_mgr else "設定"
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        self._build_ui(s)

    def _build_ui(self, s: dict) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 12)

        tabs = QTabWidget()
        root.addWidget(tabs)

        is_admin = self.config_mgr.is_admin_mode() if self.config_mgr else False
        tab_defs = [
            (self._tab_behavior, "⚙️ 行為"),
        ]
        if is_admin:
            tab_defs.insert(1, (self._tab_index, "🔍 索引"))
        for builder, label in tab_defs:
            tabs.addTab(builder(s), label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 0)
        btn_row.addStretch()

        btn_save_text = self.config_mgr.get_text(
            "ui_dialog_settings_btn_save", "完成並儲存") if self.config_mgr else "完成並儲存"
        save_btn = QPushButton(btn_save_text)
        save_btn.setStyleSheet("font-weight: bold; padding: 6px 20px;")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)

        btn_cancel_text = self.config_mgr.get_text(
            "ui_dialog_settings_btn_cancel", "取消") if self.config_mgr else "取消"
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

    # ── Tab: 索引 ─────────────────────────────────────────────────────────────

    def _tab_index(self, s: dict) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_common_index_section(s))
        self._master_section = self._build_master_node_section(s)
        layout.addWidget(self._master_section)
        layout.addStretch()
        self._master_section.setVisible(s.get("is_master_node", False))
        return outer

    def _build_common_index_section(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        self._is_master_chk = QCheckBox(
            self.config_mgr.get_text("ui_dialog_settings_master_mode", "啟用生產者模式 (Master Node)"))
        self._is_master_chk.setChecked(s.get("is_master_node", False))
        self._is_master_chk.setToolTip(
            self.config_mgr.get_text("ui_dialog_settings_master_mode_tip",
                                     "僅公司主機需要開啟。開啟後負責執行背景掃描並發布索引。"))
        self._is_master_chk.toggled.connect(self._on_master_toggled)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_role", "運行角色："),
                 self._is_master_chk)

        self._remote_root_edit = QLineEdit(s.get("remote_index_root", ""))
        self._remote_root_edit.setPlaceholderText(
            self.config_mgr.get_text("ui_dialog_settings_remote_root_placeholder", "K:\\... 資料庫存放路徑"))
        browse_remote = QPushButton("📂")
        browse_remote.setFixedWidth(32)
        browse_remote.clicked.connect(lambda: self._browse_dir(self._remote_root_edit))
        row_remote = QHBoxLayout()
        row_remote.addWidget(self._remote_root_edit)
        row_remote.addWidget(browse_remote)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_remote_root", "團隊索引存放路徑："),
                 row_remote)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(100, 50000)
        self._limit_spin.setSingleStep(100)
        self._limit_spin.setValue(s.get("search_limit", 1000))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_limit", "搜尋結果上限："),
                 self._limit_spin)

        return w

    def _build_master_node_section(self, s: dict) -> QWidget:
        container = QWidget()
        ms_layout = QVBoxLayout(container)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_layout.setSpacing(0)

        w, f = self._form_widget()

        f.addRow(self._separator())
        f.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_monitored_note",
                                     "Master Node 掃描的來源資料夾（如 C:\\, K:\\Project）")))

        self._path_list = QListWidget()
        self._path_list.setMaximumHeight(120)
        for p in s.get("monitored_paths", []):
            self._path_list.addItem(p)
        f.addRow(self._path_list)

        add_btn = QPushButton(self.config_mgr.get_text("ui_dialog_settings_btn_add_path", "新增路徑"))
        add_btn.clicked.connect(self._on_add_monitored_path)
        rm_btn = QPushButton(self.config_mgr.get_text("ui_dialog_settings_btn_remove_path", "移除所選"))
        rm_btn.clicked.connect(self._on_remove_monitored_path)
        path_btns = QHBoxLayout()
        path_btns.addWidget(add_btn)
        path_btns.addWidget(rm_btn)
        path_btns.addStretch()
        f.addRow(path_btns)

        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(1, 20)
        self._depth_spin.setValue(s.get("network_scan_depth", 7))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_depth", "資料夾搜尋深度 (1-20 層)："),
                 self._depth_spin)

        _default_exts = [".tmp", ".bak", ".log", ".cache", ".thumbs", ".db-wal", ".db-shm", ".lock"]
        self._excl_exts_edit = QLineEdit(", ".join(s.get("exclude_exts") or _default_exts))
        self._excl_exts_edit.setPlaceholderText(".tmp, .bak, .log")
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_excl_exts", "排除副檔名（逗號分隔）："),
                 self._excl_exts_edit)

        _default_dirs = ["Archive", "Old", "Temp", "_archive", "Backup", "$RECYCLE.BIN"]
        self._excl_dirs_edit = QLineEdit(", ".join(s.get("exclude_dirs") or _default_dirs))
        self._excl_dirs_edit.setPlaceholderText("Archive, Old, Temp")
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_excl_dirs", "排除資料夾關鍵字（逗號分隔）："),
                 self._excl_dirs_edit)

        f.addRow(self._separator())
        f.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_nightly_note",
                                     "夜間自動掃描索引的執行時間（24小時制）")))

        self._hour_spin = QSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setValue(s.get("nightly_scan_hour", 2))
        self._hour_spin.setSuffix(self.config_mgr.get_text("ui_dialog_settings_hour_suffix", " 時"))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_nightly_hour", "夜間掃描時間："),
                 self._hour_spin)

        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 59)
        self._min_spin.setValue(s.get("nightly_scan_minute", 0))
        self._min_spin.setSuffix(self.config_mgr.get_text("ui_dialog_settings_min_suffix", " 分"))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_nightly_minute", "分鐘："),
                 self._min_spin)

        ms_layout.addWidget(w)
        ms_layout.addStretch()
        return container

    def _on_master_toggled(self, checked: bool) -> None:
        if checked:
            title = self.config_mgr.get_text(
                "ui_dialog_settings_auth_title", "權限驗證")
            msg = self.config_mgr.get_text(
                "ui_dialog_settings_auth_msg", "開啟生產者模式請輸入密碼:")
            txt, ok = QInputDialog.getText(
                self, title, msg, QLineEdit.EchoMode.Password)
            if not ok or txt != self.config_mgr.get_master_password():
                if ok:
                    QMessageBox.warning(
                        self,
                        self.config_mgr.get_text(
                            "ui_dialog_common_error", "錯誤"),
                        self.config_mgr.get_text("ui_dialog_settings_auth_err", "密碼不正確"))
                self._is_master_chk.setChecked(False)
                return
        self._master_section.setVisible(checked)

    def _on_add_monitored_path(self):
        title = self.config_mgr.get_text(
            "ui_dialog_settings_dlg_select_dir", "選擇要監測的資料夾")
        path = QFileDialog.getExistingDirectory(self, title)
        if path:
            for i in range(self._path_list.count()):
                if self._path_list.item(i).text() == path:
                    return
            self._path_list.addItem(path)

    def _on_remove_monitored_path(self):
        for item in self._path_list.selectedItems():
            self._path_list.takeItem(self._path_list.row(item))

    def _browse_dir(self, edit: QLineEdit) -> None:
        title = self.config_mgr.get_text(
            "ui_dialog_settings_dlg_select_dir_general", "選擇資料夾")
        path = QFileDialog.getExistingDirectory(self, title, edit.text() or "")
        if path:
            edit.setText(path)

    # ── Tab 3: 行為 ────────────────────────────────────────────────────────────

    def _tab_behavior(self, s: dict) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_view_section(s))
        layout.addWidget(self._build_paste_section(s))
        layout.addStretch()
        return outer

    def _build_view_section(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        self._preview_font_spin = QSpinBox()
        self._preview_font_spin.setRange(9, 24)
        self._preview_font_spin.setValue(s.get("preview_font_size", 14))
        self._preview_font_spin.setSuffix(" px")
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_preview_font", "預覽字體大小："),
                 self._preview_font_spin)

        self._pdf_pages_spin = QSpinBox()
        self._pdf_pages_spin.setRange(1, 20)
        self._pdf_pages_spin.setValue(s.get("pdf_preview_max_pages", 3))
        self._pdf_pages_spin.setSuffix(self.config_mgr.get_text(
            "ui_dialog_settings_pdf_pages_suffix", " 頁"))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_pdf_pages", "PDF 預覽頁數："),
                 self._pdf_pages_spin)

        self._confirm_delete_chk = QCheckBox(
            self.config_mgr.get_text("ui_dialog_settings_confirm_delete", "刪除檔案前顯示確認視窗"))
        self._confirm_delete_chk.setChecked(s.get("confirm_before_delete", False))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_delete", "刪除防呆："),
                 self._confirm_delete_chk)

        return w

    def _build_paste_section(self, s: dict) -> QWidget:
        w, f = self._form_widget()

        f.addRow(self._separator())
        f.addRow(self._muted_label(
            self.config_mgr.get_text("ui_dialog_settings_paste_note",
                                     "「貼上為檔案」功能的命名規則（支援 strftime 格式）")))

        default_img = self.config_mgr.get_text("paste_prefix_image", "剪貼圖")
        self._img_prefix_edit = QLineEdit(s.get("image_prefix", default_img))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_img_prefix", "圖片前綴："),
                 self._img_prefix_edit)

        self._img_format_edit = QLineEdit(s.get("image_format", "%Y%m%d_%H%M%S"))
        self._img_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._img_format_edit.textChanged.connect(self._update_format_preview)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_img_format", "圖片日期格式："),
                 self._img_format_edit)

        default_txt = self.config_mgr.get_text("paste_prefix_text", "文字筆記")
        self._txt_prefix_edit = QLineEdit(s.get("text_prefix", default_txt))
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_txt_prefix", "文字前綴："),
                 self._txt_prefix_edit)

        self._txt_format_edit = QLineEdit(s.get("text_format", "%Y%m%d_%H%M%S"))
        self._txt_format_edit.setPlaceholderText("例: %Y%m%d_%H%M%S")
        self._txt_format_edit.textChanged.connect(self._update_format_preview)
        f.addRow(self.config_mgr.get_text("ui_dialog_settings_label_txt_format", "文字日期格式："),
                 self._txt_format_edit)

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
        btn_text = self.config_mgr.get_text(
            "ui_dialog_settings_btn_save", "完成並儲存")
        for btn in self.findChildren(QPushButton):
            if btn.text() == btn_text:
                btn.setEnabled(enabled)
                break

    # ── Accept / Reject ────────────────────────────────────────────────────────

    def accept(self) -> None:
        m_paths = [self._path_list.item(i).text()
                   for i in range(self._path_list.count())]

        self._config_mgr.save_app_settings({
            "remote_index_root":     self._remote_root_edit.text().strip(),
            "search_limit":          self._limit_spin.value(),
            "nightly_scan_hour":     self._hour_spin.value(),
            "nightly_scan_minute":   self._min_spin.value(),
            "preview_font_size":     self._preview_font_spin.value(),
            "pdf_preview_max_pages": self._pdf_pages_spin.value(),
            "confirm_before_delete": self._confirm_delete_chk.isChecked(),
            "image_prefix":          self._img_prefix_edit.text().strip(),
            "text_prefix":           self._txt_prefix_edit.text().strip(),
            "image_format":          self._img_format_edit.text().strip(),
            "text_format":           self._txt_format_edit.text().strip(),
            "is_master_node":        self._is_master_chk.isChecked(),
            "monitored_paths":       m_paths,
            "network_scan_depth":    self._depth_spin.value(),
            "exclude_exts":          [e.strip() for e in self._excl_exts_edit.text().split(",") if e.strip()],
            "exclude_dirs":          [d.strip() for d in self._excl_dirs_edit.text().split(",") if d.strip()],
        })
        self.theme_changed.emit()
        super().accept()

    def reject(self) -> None:
        super().reject()
