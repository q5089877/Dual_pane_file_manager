from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox, QGridLayout,
    QLineEdit, QTableWidget, QTableWidgetItem, QPushButton, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from core.config_manager import ConfigManager
from ui.presenters.compare_presenter import ComparePresenter


class CompareDialog(QDialog):
    def __init__(self, left_path: str, right_path: str, parent=None):
        super().__init__(parent)
        self.config_mgr = ConfigManager()
        self.setWindowTitle(self.config_mgr.get_text("ui_dialog_compare_title", "資料夾比較與同步"))
        self.resize(1000, 700)
        self.left_path = left_path
        self.right_path = right_path
        self.differences = []
        theme = self.config_mgr.get_theme_colors()
        self._color_success = QColor(theme.get("success", "#2ecc71"))
        self._color_danger  = QColor(theme.get("danger",  "#EF5350"))
        self._color_accent  = QColor(theme.get("accent",  "#58A6FF"))
        self.presenter = ComparePresenter(self, left_path, right_path)
        self._init_ui()

    def closeEvent(self, event) -> None:
        self.presenter.cleanup()
        super().closeEvent(event)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        path_box = QGroupBox(self.config_mgr.get_text("ui_dialog_compare_range", "比較範圍"))
        path_layout = QGridLayout(path_box)
        path_layout.addWidget(QLabel(self.config_mgr.get_text("ui_dialog_compare_left_path", "左側路徑:")), 0, 0)
        path_layout.addWidget(QLineEdit(self.left_path, readOnly=True), 0, 1)
        path_layout.addWidget(QLabel(self.config_mgr.get_text("ui_dialog_compare_right_path", "右側路徑:")), 1, 0)
        path_layout.addWidget(QLineEdit(self.right_path, readOnly=True), 1, 1)
        layout.addWidget(path_box)

        self.status_label = QLabel(self.config_mgr.get_text("ui_dialog_compare_status_ready", "準備就緒"))
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            self.config_mgr.get_text("ui_dialog_compare_col_sync", "同步"),
            self.config_mgr.get_text("ui_dialog_compare_col_rel_path", "相對路徑"),
            self.config_mgr.get_text("ui_dialog_compare_col_type", "類型"),
            self.config_mgr.get_text("ui_dialog_compare_col_status", "狀態"),
            self.config_mgr.get_text("ui_dialog_compare_col_advice", "建議操作"),
        ])
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 60)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.clicked.connect(self.on_table_clicked)
        layout.addWidget(self.table)

        self.empty_state_label = QLabel(self.config_mgr.get_text("ui_dialog_compare_empty", "✅\n🎉 兩個資料夾已完全同步，無需任何操作"))
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _empty_qss = "font-size: 16px; color: {{success}}; font-weight: bold; margin: 60px; line-height: 1.5;"
        self.empty_state_label.setStyleSheet(self.config_mgr.apply_theme_to_text(_empty_qss))
        self.empty_state_label.setVisible(False)
        layout.addWidget(self.empty_state_label)

        btn_layout = QHBoxLayout()
        self.scan_btn = QPushButton(self.config_mgr.get_text("ui_dialog_compare_btn_scan", "開始完整掃描"))
        self.scan_btn.clicked.connect(self.start_scan)
        self.mirror_btn = QPushButton(self.config_mgr.get_text("ui_dialog_compare_btn_mirror", "完全鏡像 (左側為準)"))
        self.mirror_btn.setObjectName("syncMirrorBtn")
        self.mirror_btn.setToolTip(
            "以左側為基準，完全同步到右側。\n"
            "• 左有右無 → 複製到右\n"
            "• 右有左無 → 移入 .sync_trash（危險）\n"
            "• 兩側不同 → 用左覆蓋右"
        )
        self.mirror_btn.clicked.connect(lambda: self.run_sync("L2R_MIRROR"))

        self.upd_r2l = QPushButton(self.config_mgr.get_text("ui_dialog_compare_btn_update_r2l", "反向更新 (左 ← 右)"))
        self.upd_r2l.setToolTip(
            "將右側有、左側無的內容補到左側。\n"
            "• 右有左無 → 複製到左\n"
            "• 兩側不同 → 用右覆蓋左\n"
            "• 左有右無 → 忽略（不刪除）"
        )
        self.upd_r2l.clicked.connect(lambda: self.run_sync("R2L_UPDATE"))

        self.upd_l2r = QPushButton(self.config_mgr.get_text("ui_dialog_compare_btn_update_l2r", "單向更新 (左 → 右)"))
        self.upd_l2r.setObjectName("syncL2RBtn")
        self.upd_l2r.setToolTip(
            "將左側有、右側無的內容補到右側。\n"
            "• 左有右無 → 複製到右\n"
            "• 兩側不同 → 用左覆蓋右\n"
            "• 右有左無 → 忽略（不刪除）"
        )
        self.upd_l2r.clicked.connect(lambda: self.run_sync("L2R_UPDATE"))

        self.mirror_r2l_btn = QPushButton("完全鏡像 (右側為準)")
        self.mirror_r2l_btn.setObjectName("syncMirrorBtn")
        self.mirror_r2l_btn.setToolTip(
            "以右側為基準，完全同步到左側。\n"
            "• 右有左無 → 複製到左\n"
            "• 左有右無 → 移入 .sync_trash（危險）\n"
            "• 兩側不同 → 用右覆蓋左"
        )
        self.mirror_r2l_btn.clicked.connect(lambda: self.run_sync("R2L_MIRROR"))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(2)

        self.set_sync_buttons_enabled(False)
        btn_layout.addWidget(self.scan_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.mirror_btn)
        btn_layout.addWidget(self.upd_r2l)
        btn_layout.addWidget(self.upd_l2r)
        btn_layout.addWidget(self.mirror_r2l_btn)
        btn_layout.addWidget(sep)
        layout.addLayout(btn_layout)

    def set_sync_buttons_enabled(self, enabled: bool) -> None:
        for btn in [self.mirror_r2l_btn, self.upd_r2l, self.upd_l2r, self.mirror_btn]:
            btn.setEnabled(enabled)

    def start_scan(self) -> None:
        self.table.setRowCount(0)
        self.differences = []
        self.set_sync_buttons_enabled(False)
        self.scan_btn.setEnabled(False)
        self.empty_state_label.setVisible(False)
        self.presenter.start_compare()

    # ICompareView implementations
    def show_progress(self, message: str) -> None:
        self.status_label.setText(message)

    def show_differences(self, differences: list, total_count: int) -> None:
        self.scan_btn.setEnabled(True)
        self.differences = differences
        self.table.setRowCount(0)

        has_diff = len(self.differences) > 0
        self.table.setVisible(has_diff)
        self.empty_state_label.setVisible(not has_diff)
        self.set_sync_buttons_enabled(has_diff)

        if not has_diff:
            self.status_label.setText(self.config_mgr.get_text("ui_dialog_compare_status_finished", "掃描完畢。比對了 {} 個項目，發現 {} 個差異。").format(total_count, 0))
            return

        self.status_label.setText(self.config_mgr.get_text("ui_dialog_compare_status_finished", "掃描完畢。比對了 {} 個項目，發現 {} 個差異。").format(total_count, len(self.differences)))
        for d in self.differences:
            row = self.table.rowCount()
            self.table.insertRow(row)

            chk_item = QTableWidgetItem()
            chk_item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, chk_item)

            path_item = QTableWidgetItem(d['rel_path'])
            path_item.setToolTip(d['rel_path'])
            self.table.setItem(row, 1, path_item)

            self.table.setItem(row, 2, QTableWidgetItem("📁" if d['is_dir'] else "📄"))

            status, advice, color = self._get_status_view_data(d)

            status_item = QTableWidgetItem(status)
            status_item.setForeground(color)
            self.table.setItem(row, 3, status_item)

            advice_item = QTableWidgetItem(advice)
            advice_item.setForeground(color)
            self.table.setItem(row, 4, advice_item)

        self.set_sync_buttons_enabled(True)

    def on_header_clicked(self, index: int) -> None:
        if index == 0 and self.table.rowCount() > 0:
            first_state = self.table.item(0, 0).checkState()
            new_state = Qt.CheckState.Unchecked if first_state == Qt.CheckState.Checked else Qt.CheckState.Checked
            for i in range(self.table.rowCount()):
                self.table.item(i, 0).setCheckState(new_state)

    def on_table_clicked(self, index) -> None:
        if index.column() != 0:
            item = self.table.item(index.row(), 0)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def _get_status_view_data(self, d: dict) -> tuple[str, str, QColor]:
        if d['status'] == 'L_ONLY':
            return (
                self.config_mgr.get_text("ui_dialog_compare_status_l_only", "僅左側有"),
                self.config_mgr.get_text("ui_dialog_compare_status_l_only_advice", "[+] 複製到右側"),
                self._color_success,
            )
        if d['status'] == 'R_ONLY':
            return (
                self.config_mgr.get_text("ui_dialog_compare_status_r_only", "右側多出"),
                self.config_mgr.get_text("ui_dialog_compare_status_r_only_advice", "[✖] 移至安全暫存區"),
                self._color_danger,
            )
        if d['status'] == 'DIFF':
            suffix = self.config_mgr.get_text("ui_dialog_compare_status_diff_l_newer", " (左偏新)") if d['l_newer'] else self.config_mgr.get_text("ui_dialog_compare_status_diff_r_newer", " (右偏新)")
            status = self.config_mgr.get_text("ui_dialog_compare_status_diff", "內容不同") + suffix
            return status, self.config_mgr.get_text("ui_dialog_compare_status_diff_advice", "[➔] 更新至最新版本"), self._color_accent
        return "", "", QColor()

    def run_sync(self, mode: str) -> None:
        if not self.differences: return
        selected_diffs = []
        for i, d in enumerate(self.differences):
            if self.table.item(i, 0).checkState() == Qt.CheckState.Checked:
                selected_diffs.append(d)
        self.presenter.run_sync(mode, selected_diffs)

    def show_sync_result(self, success: int, errors: int) -> None:
        QMessageBox.information(
            self,
            self.config_mgr.get_text("ui_dialog_compare_finished_title", "完成"),
            self.config_mgr.get_text("ui_dialog_compare_finished_msg", "成功: {}, 失敗: {}").format(success, errors),
        )
        self.start_scan()
        if self.parent():
            if hasattr(self.parent(), 'refresh_all_panes'): self.parent().refresh_all_panes()
            if hasattr(self.parent(), 'statusBar'): self.parent().statusBar().showMessage(self.config_mgr.get_text("ui_dialog_compare_sync_done", "同步完成"), 8000)

    def ask_confirmation(self, title: str, message: str) -> bool:
        return QMessageBox.question(self, title, message) == QMessageBox.StandardButton.Yes
