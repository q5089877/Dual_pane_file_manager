from __future__ import annotations
import os
import datetime

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QToolButton,
    QListWidget, QSpinBox, QProgressBar,
    QMessageBox, QFileDialog, QGroupBox,
)
from PyQt6.QtCore import Qt, QTimer


# ── Scan-status display widget ─────────────────────────────────────────────────

class _ScanStatusWidget(QWidget):
    """Read-only widget showing last completed scan time and progress."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.status_label = QLabel("⏳ 尚未查詢...")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(14)
        lay.addWidget(self.progress_bar)

    def refresh_status(self, monitored_paths: list[str]) -> None:
        if not monitored_paths:
            self.status_label.setText("⚠️ 尚未設定監控路徑")
            return
        try:
            from network_search.engine import IndexManager
            db_dir = self.config_mgr.get_index_path()
            idx_mgr = IndexManager(db_dir, read_only=False)
            lines: list[str] = []
            for p in monitored_paths[:3]:
                row = idx_mgr.get_scan_status(p)
                if row:
                    _, last_finished, total = row
                    if last_finished:
                        dt = datetime.datetime.fromtimestamp(last_finished)
                        lines.append(f"✅ {os.path.basename(p)}: {dt.strftime('%Y-%m-%d %H:%M')} ({total} 個檔案)")
                    else:
                        lines.append(f"⚠️ {os.path.basename(p)}: 尚未完成掃描")
                else:
                    lines.append(f"⚪ {os.path.basename(p)}: 尚無索引記錄")
            self.status_label.setText("\n".join(lines) if lines else "⚪ 無資料")
        except Exception as exc:
            self.status_label.setText(f"⚠️ 無法讀取狀態: {exc}")

    def set_scanning(self, active: bool) -> None:
        self.progress_bar.setVisible(active)
        if active:
            self.status_label.setText("🔄 掃描中...")


# ── Config form widget ─────────────────────────────────────────────────────────

class _AdminConfigForm(QWidget):
    """Editable form: NAS path, monitored paths, max depth."""

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # NAS index path
        nas_group = QGroupBox("NAS 索引存放路徑")
        nas_lay = QHBoxLayout(nas_group)
        self.nas_path_edit = QLineEdit()
        self.nas_path_edit.setPlaceholderText(r"例: K:\SHL TECH\...\資料庫存放區")
        nas_lay.addWidget(self.nas_path_edit, 1)
        browse_btn = QToolButton()
        browse_btn.setText("…")
        browse_btn.setToolTip("瀏覽資料夾")
        browse_btn.clicked.connect(self._on_browse_nas)
        nas_lay.addWidget(browse_btn)
        lay.addWidget(nas_group)

        # Monitored paths
        paths_group = QGroupBox("掃描監控路徑 (網路/NAS)")
        paths_lay = QVBoxLayout(paths_group)
        self.path_list = QListWidget()
        self.path_list.setMaximumHeight(110)
        paths_lay.addWidget(self.path_list)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("＋ 新增路徑")
        add_btn.clicked.connect(self._on_add_path)
        remove_btn = QPushButton("－ 移除選取")
        remove_btn.clicked.connect(self._on_remove_path)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        paths_lay.addLayout(btn_row)
        lay.addWidget(paths_group)

        # Scan depth
        depth_group = QGroupBox("最大掃描深度")
        depth_lay = QHBoxLayout(depth_group)
        depth_lay.addWidget(QLabel("深度:"))
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 20)
        self.depth_spin.setValue(7)
        depth_lay.addWidget(self.depth_spin)
        depth_lay.addStretch()
        lay.addWidget(depth_group)

        self._load_values()

    def _load_values(self) -> None:
        config = self.config_mgr.load_config()
        default_nas = config.get(
            "remote_index_root",
            r"K:\SHL TECH\_STEC_Staff\Neil\效率提升軟體\K槽檔案尋找資料庫存放區"
        )
        self.nas_path_edit.setText(default_nas)
        for p in config.get("monitored_paths", []):
            self.path_list.addItem(p)
        self.depth_spin.setValue(config.get("max_depth", 7))

    def _on_browse_nas(self) -> None:
        start = self.nas_path_edit.text() or "K:\\"
        path = QFileDialog.getExistingDirectory(self, "選擇 NAS 索引存放資料夾", start)
        if path:
            self.nas_path_edit.setText(os.path.normpath(path))

    def _on_add_path(self) -> None:
        existing = [self.path_list.item(i).text()
                    for i in range(self.path_list.count())]
        path = QFileDialog.getExistingDirectory(self, "新增監控路徑", "K:\\")
        if path:
            norm = os.path.normpath(path)
            if norm not in existing:
                self.path_list.addItem(norm)

    def _on_remove_path(self) -> None:
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))

    def get_values(self) -> dict:
        monitored = [
            self.path_list.item(i).text()
            for i in range(self.path_list.count())
        ]
        return {
            "remote_index_root": self.nas_path_edit.text().strip(),
            "monitored_paths": monitored,
            "max_depth": self.depth_spin.value(),
            "network_scan_depth": self.depth_spin.value(),
        }


# ── Admin dialog ───────────────────────────────────────────────────────────────

class AdminConfigDialog(QDialog):
    """Hidden admin panel: NAS config + manual scan trigger.
    Accessed only via secret keyboard shortcut + password.
    """

    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self._scan_worker = None
        self.setWindowTitle("管理者設定")
        self.setMinimumWidth(520)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()
        QTimer.singleShot(50, self._refresh_status)

    def _build_ui(self) -> None:
        main_lay = QVBoxLayout(self)
        main_lay.setSpacing(10)

        self._form = _AdminConfigForm(self.config_mgr, self)
        main_lay.addWidget(self._form)

        # Scan section
        scan_group = QGroupBox("索引掃描")
        scan_lay = QVBoxLayout(scan_group)
        self._status_widget = _ScanStatusWidget(self.config_mgr, self)
        scan_lay.addWidget(self._status_widget)
        self._scan_btn = QPushButton("▶ 開始掃描並發布至 NAS")
        self._scan_btn.clicked.connect(self._start_scan)
        scan_lay.addWidget(self._scan_btn)
        main_lay.addWidget(scan_group)

        # Button row
        btn_row = QHBoxLayout()
        consumer_btn = QPushButton("切換至消費者模式")
        consumer_btn.setToolTip("儲存設定並切換為消費者角色（隱藏管理選項）")
        consumer_btn.clicked.connect(self._on_switch_to_consumer)
        btn_row.addWidget(consumer_btn)
        btn_row.addStretch()
        save_btn = QPushButton("儲存並關閉")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        main_lay.addLayout(btn_row)

    def _refresh_status(self) -> None:
        values = self._form.get_values()
        self._status_widget.refresh_status(values["monitored_paths"])

    def _check_nas_reachable(self, path: str) -> bool:
        if not path:
            QMessageBox.warning(self, "路徑錯誤", "NAS 路徑不能為空。")
            return False
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "NAS 無法存取",
                f"路徑無法存取，請確認網路磁碟已掛載：\n{path}"
            )
            return False
        return True

    def _start_scan(self) -> None:
        values = self._form.get_values()
        nas_path = values["remote_index_root"]
        monitored = values["monitored_paths"]
        max_depth = values["max_depth"]

        if not self._check_nas_reachable(nas_path):
            return
        if not monitored:
            QMessageBox.warning(self, "無監控路徑", "請先新增至少一個掃描監控路徑。")
            return

        configs_k = [
            (os.path.normpath(p), max_depth)
            for p in monitored if os.path.exists(p)
        ]
        if not configs_k:
            QMessageBox.warning(
                self, "路徑不存在", "所有監控路徑目前均無法存取，請確認網路連線。"
            )
            return

        try:
            from network_search.engine import ScannerWorker, IndexManager
            db_dir = self.config_mgr.get_index_path()
            idx_mgr = IndexManager(db_dir, read_only=False)
            self._scan_worker = ScannerWorker(
                configs_k, idx_mgr,
                remote_db_dir=nas_path,
                target_db="local",
            )
            self._scan_worker.progress.connect(
                lambda msg: self._status_widget.status_label.setText(f"🔄 {msg}"))
            self._scan_worker.files_indexed.connect(
                lambda n: self._status_widget.status_label.setText(f"🔄 已索引 {n} 個檔案..."))
            self._scan_worker.finished.connect(self._on_scan_finished)
            self._scan_worker.cancelled.connect(self._on_scan_cancelled)
            self._scan_btn.setEnabled(False)
            self._status_widget.set_scanning(True)
            self._scan_worker.start()
        except Exception as exc:
            QMessageBox.critical(self, "掃描錯誤", f"無法啟動掃描：{exc}")

    def _on_scan_finished(self, total: int) -> None:
        self._status_widget.set_scanning(False)
        self._scan_btn.setEnabled(True)
        self._scan_worker = None
        values = self._form.get_values()
        self._status_widget.status_label.setText(
            f"✅ 掃描完成，共 {total} 個檔案已發布至 NAS"
        )
        QTimer.singleShot(500, lambda: self._status_widget.refresh_status(
            values["monitored_paths"]))

    def _on_scan_cancelled(self, total: int) -> None:
        self._status_widget.set_scanning(False)
        self._status_widget.status_label.setText(f"⏹ 掃描已取消（已索引 {total} 個）")
        self._scan_btn.setEnabled(True)
        self._scan_worker = None

    def _on_accept(self) -> None:
        values = self._form.get_values()
        nas_path = values["remote_index_root"]
        drive, relative = os.path.splitdrive(nas_path)
        self.config_mgr.save_config(
            is_master_node=True,
            remote_index_root=nas_path,
            nas_relative_path=relative.lstrip(os.sep),
            monitored_paths=values["monitored_paths"],
            max_depth=values["max_depth"],
            network_scan_depth=values["network_scan_depth"],
        )
        self.accept()

    def _on_switch_to_consumer(self) -> None:
        self.config_mgr.save_config(is_master_node=False)
        self.accept()

    def closeEvent(self, event) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            if hasattr(self._scan_worker, "stop"):
                self._scan_worker.stop()
        super().closeEvent(event)
