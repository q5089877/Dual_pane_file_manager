import os, datetime, re, logging

logger = logging.getLogger(__name__)

def _natural_key(s: str) -> list:
    """Split string into text/number chunks for human-friendly sorting."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s or "")]
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox,
    QHeaderView,
    QMenu, QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem,
    QWidget, QSplitter,
)
from PyQt6.QtCore import Qt, QTimer, QThread, QSortFilterProxyModel
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor


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

        # Numeric comparison for Date (2) and Size (3)
        if col in (2, 3):
            if left_data is not None and right_data is not None:
                try:
                    return float(left_data) < float(right_data)
                except (TypeError, ValueError):
                    pass

            # Handle None or invalid data by treating them as minimal values
            if left_data is None: return True
            if right_data is None: return False

        # Natural sort for Name (1) — "part_2" before "part_10"
        if col == 1:
            l = self.sourceModel().data(left, Qt.ItemDataRole.DisplayRole) or ""
            r = self.sourceModel().data(right, Qt.ItemDataRole.DisplayRole) or ""
            return _natural_key(l) < _natural_key(r)

        return super().lessThan(left, right)


class DuplicateAnalysisDialog(QDialog):
    """Master-detail duplicate file viewer.
    Left panel: folder-pair list (sorted by wasted space).
    Right panel: files organised by folder for the selected pair.
    """

    # ── inner worker ──────────────────────────────────────────────────────────
    class _Worker(QThread):
        from PyQt6.QtCore import pyqtSignal
        progress = pyqtSignal(str)
        done     = pyqtSignal(list)

        def __init__(self, index_mgr, parent=None):
            super().__init__(parent)
            self._index_mgr = index_mgr

        def run(self):
            self.progress.emit("查詢資料庫...")
            rows = self._index_mgr.find_duplicates()
            by_key: dict[tuple[str, int], list[str]] = {}
            for name, size, full_path, _mtime in rows:
                by_key.setdefault((name, int(size)), []).append(full_path)
            groups: list[tuple[str, int, list[str]]] = [
                (name, size, paths)
                for (name, size), paths in sorted(by_key.items(), key=lambda x: x[0][1], reverse=True)
                if len(paths) >= 2
            ]
            logger.info("[DupAnalysis] %d rows → %d groups", len(rows), len(groups))
            self.done.emit(groups)

    # ── init ──────────────────────────────────────────────────────────────────

    def __init__(self, index_mgr, config_mgr=None, on_navigate=None, parent=None):
        super().__init__(parent)
        self._index_mgr  = index_mgr
        self._config_mgr = config_mgr
        self._on_navigate = on_navigate
        self._worker = None
        title = config_mgr.get_text("ui_dup_analysis_title", "重複檔案分析") if config_mgr else "重複檔案分析"
        self.setWindowTitle(title)
        self.resize(1100, 650)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self._build_ui()
        QTimer.singleShot(50, self._start_worker)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(6)

        self._status_label = QLabel("分析中...")
        root.addWidget(self._status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: flat folder-pair list
        self._left = QTreeWidget()
        self._left.setHeaderLabels(["資料夾", "浪費空間"])
        self._left.setColumnWidth(0, 200)
        self._left.setColumnWidth(1, 110)
        self._left.setRootIsDecorated(False)
        self._left.setAlternatingRowColors(True)
        self._left.currentItemChanged.connect(self._on_pair_selected)
        splitter.addWidget(self._left)

        # Right: file detail per folder
        right_w = QWidget()
        rl = QVBoxLayout(right_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self._detail_label = QLabel()
        self._detail_label.setStyleSheet("font-size: 11px; color: #6c7086; padding: 2px 6px;")
        self._detail_label.setWordWrap(True)
        rl.addWidget(self._detail_label)
        self._right = QTreeWidget()
        self._right.setHeaderLabels(["檔案名稱", "大小"])
        self._right.setColumnWidth(0, 480)
        self._right.setColumnWidth(1, 90)
        self._right.setRootIsDecorated(True)
        self._right.setAlternatingRowColors(True)
        self._right.currentItemChanged.connect(self._on_file_selected)
        self._right.itemDoubleClicked.connect(self._on_double_click)
        self._right.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._right.customContextMenuRequested.connect(self._on_context_menu)
        rl.addWidget(self._right, stretch=1)
        splitter.addWidget(right_w)
        splitter.setSizes([340, 760])
        root.addWidget(splitter, stretch=1)

        btn_row = QHBoxLayout()
        self._del_btn = QPushButton("🗑 移至資源回收筒")
        self._del_btn.setEnabled(False)
        self._del_btn.setToolTip("將選取的檔案移至資源回收筒（可復原）")
        self._del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        nav_text = self._config_mgr.get_text("ui_dup_analysis_navigate", "導航至所選路徑") if self._config_mgr else "導航至所選路徑"
        self._nav_btn = QPushButton(nav_text)
        self._nav_btn.setEnabled(False)
        self._nav_btn.clicked.connect(self._navigate_selected)
        btn_row.addWidget(self._nav_btn)
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _fmt_size(self, size: int) -> str:
        s = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if s < 1024.0:
                return f"{s:.1f} {unit}"
            s /= 1024.0
        return f"{s:.1f} TB"

    @staticmethod
    def _last_name(folder: str) -> str:
        return os.path.basename(folder.rstrip("/\\")) or folder

    # ── worker ────────────────────────────────────────────────────────────────

    def _start_worker(self):
        self._worker = self._Worker(self._index_mgr, parent=self)
        self._worker.progress.connect(self._status_label.setText)
        self._worker.done.connect(self._populate_left)
        self._worker.start()

    # ── left panel ────────────────────────────────────────────────────────────

    def _populate_left(self, groups: list):
        self._left.clear()
        self._right.clear()
        self._detail_label.setText("")
        if not groups:
            self._status_label.setText(
                self._config_mgr.get_text("ui_dup_analysis_empty", "未找到重複檔案") if self._config_mgr else "未找到重複檔案")
            return

        pair_map: dict[frozenset, list] = {}
        for name, size, paths in groups:
            key = frozenset(os.path.dirname(p) for p in paths)
            pair_map.setdefault(key, []).append((name, size, paths))

        def _waste(fg: list) -> int:
            return sum((len(p) - 1) * s for _, s, p in fg)

        sorted_pairs = sorted(pair_map.items(), key=lambda x: _waste(x[1]), reverse=True)
        total_waste  = sum(_waste(fg) for _, fg in sorted_pairs)
        self._status_label.setText(
            f"找到 {len(sorted_pairs)} 個資料夾對，{len(groups)} 組重複，浪費 {self._fmt_size(total_waste)}")

        for folders, file_groups in sorted_pairs:
            folder_list = sorted(folders)
            names = list(dict.fromkeys(self._last_name(f) for f in folder_list))
            if len(names) == 1:
                display = names[0]
            elif len(names) == 2:
                display = f"{names[0]}  /  {names[1]}"
            else:
                display = f"{names[0]}  /  {names[1]}  (+{len(names) - 2})"
            waste_str = self._fmt_size(_waste(file_groups))
            item = QTreeWidgetItem([f"📁  {display}", f"{len(file_groups)} 組 · {waste_str}"])
            item.setToolTip(0, "\n".join(folder_list))
            item.setData(0, Qt.ItemDataRole.UserRole, {"folders": folder_list, "file_groups": file_groups})
            self._left.addTopLevelItem(item)

    def _on_pair_selected(self, current: QTreeWidgetItem, _prev):
        self._right.clear()
        self._detail_label.setText("")
        if not current:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self._populate_right(data)

    # ── right panel ───────────────────────────────────────────────────────────

    @staticmethod
    def _drive_tag(folder: str) -> str:
        drive, _ = os.path.splitdrive(folder)
        if not drive:
            return ""
        if drive.startswith("\\\\"):
            server = drive.lstrip("\\").split("\\")[0]
            return f"\\\\{server}"
        return drive  # e.g. "C:"

    def _populate_right(self, data: dict):
        folders     = data["folders"]
        file_groups = data["file_groups"]
        self._detail_label.setText("   →   ".join(folders))

        folder_items: dict[str, QTreeWidgetItem] = {}
        for folder in folders:
            tag  = self._drive_tag(folder)
            name = self._last_name(folder)
            label = f"📁  [{tag}]  {name}" if tag else f"📁  {name}"
            fi = QTreeWidgetItem([label, ""])
            fi.setToolTip(0, folder)
            fi.setExpanded(True)
            self._right.addTopLevelItem(fi)
            folder_items[folder] = fi

        item_size: dict[int, int] = {}
        for name, size, paths in sorted(file_groups, key=lambda x: x[1], reverse=True):
            size_str = self._fmt_size(size)
            for path in paths:
                folder = os.path.dirname(path)
                parent = folder_items.get(folder) or next(
                    (folder_items[f] for f in folders if path.lower().startswith(f.lower())), None)
                if parent is not None:
                    child = QTreeWidgetItem([name, size_str])
                    child.setData(0, Qt.ItemDataRole.UserRole, path)
                    child.setToolTip(0, path)
                    parent.addChild(child)
                    item_size[id(parent)] = item_size.get(id(parent), 0) + size

        for fi in folder_items.values():
            total = item_size.get(id(fi), 0)
            if total:
                fi.setText(1, self._fmt_size(total))

    # ── selection & navigation ────────────────────────────────────────────────

    def _on_file_selected(self, current: QTreeWidgetItem, _prev):
        is_file = current is not None and current.data(0, Qt.ItemDataRole.UserRole) is not None
        self._del_btn.setEnabled(is_file)
        self._nav_btn.setEnabled(is_file)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and self._on_navigate:
            self._do_navigate(path)

    def _navigate_selected(self):
        item = self._right.currentItem()
        if item:
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and self._on_navigate:
                self._do_navigate(path)

    def _do_navigate(self, path: str):
        if self.parent():
            self.parent().close()
        self._on_navigate(path)

    # ── context menu ─────────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        item = self._right.itemAt(pos)
        if not item:
            return
        is_file = item.data(0, Qt.ItemDataRole.UserRole) is not None
        menu = QMenu(self)
        if is_file:
            trash_act = menu.addAction("🗑 移至資源回收筒")
            nav_act   = menu.addAction("📂 導航至此路徑")
            chosen = menu.exec(self._right.viewport().mapToGlobal(pos))
            if chosen == trash_act:
                self._do_delete(item)
            elif chosen == nav_act:
                path = item.data(0, Qt.ItemDataRole.UserRole)
                if path and self._on_navigate:
                    self._do_navigate(path)
        else:
            n = item.childCount()
            del_act = menu.addAction(f"🗑 刪除此資料夾下全部 {n} 個副本")
            if menu.exec(self._right.viewport().mapToGlobal(pos)) == del_act:
                self._do_delete_folder(item)

    # ── deletion ──────────────────────────────────────────────────────────────

    def _delete_selected(self):
        item = self._right.currentItem()
        if item and item.data(0, Qt.ItemDataRole.UserRole) is not None:
            self._do_delete(item)

    def _do_delete(self, item: QTreeWidgetItem):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        if os.path.exists(path):
            try:
                import send2trash
                send2trash.send2trash(path)
            except Exception as e:
                QMessageBox.warning(self, "刪除失敗", f"{os.path.basename(path)}\n\n{e}")
                return
        folder_item = item.parent()
        if folder_item:
            folder_item.removeChild(item)
            if folder_item.childCount() == 0:
                self._right.takeTopLevelItem(self._right.indexOfTopLevelItem(folder_item))
        self._prune_left_if_empty()

    def _do_delete_folder(self, folder_item: QTreeWidgetItem):
        n = folder_item.childCount()
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要將「{folder_item.toolTip(0)}」\n下的 {n} 個重複檔案移至資源回收筒？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        import send2trash
        failed = []
        for i in range(n - 1, -1, -1):
            path = folder_item.child(i).data(0, Qt.ItemDataRole.UserRole)
            if path and os.path.exists(path):
                try:
                    send2trash.send2trash(path)
                except Exception as e:
                    failed.append(f"{os.path.basename(path)}: {e}")
        if failed:
            QMessageBox.warning(self, "部分刪除失敗", "\n".join(failed))
        self._right.takeTopLevelItem(self._right.indexOfTopLevelItem(folder_item))
        self._prune_left_if_empty()

    def _prune_left_if_empty(self):
        if self._right.topLevelItemCount() == 0:
            item = self._left.currentItem()
            if item:
                self._left.takeTopLevelItem(self._left.indexOfTopLevelItem(item))
        pairs = self._left.topLevelItemCount()
        if pairs == 0:
            self._status_label.setText(
                self._config_mgr.get_text("ui_dup_analysis_empty", "未找到重複檔案") if self._config_mgr else "未找到重複檔案")
        else:
            self._status_label.setText(f"剩餘 {pairs} 個資料夾對")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)


class BatchRenameDialog(QDialog):
    """批次重新命名對話框。確認後透過 get_op_pairs() 取得 (src, dst) 清單。"""

    _INVALID_RE = re.compile(r'[\\/:*?"<>|]')

    def __init__(self, src_paths: list[str], config_mgr=None, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr or (getattr(parent, 'config_mgr', None) if parent else None)
        self._src_paths = src_paths
        self._confirmed_pairs: list[tuple[str, str]] = []
        self._today = datetime.datetime.now().strftime("%Y%m%d")
        self.setWindowTitle(f"批次重新命名 ({len(src_paths)} 個項目)")
        self.resize(700, 450)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._init_ui()
        self._update_preview()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 樣板列
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("樣板:"))
        self._tpl = QLineEdit()
        self._tpl.setPlaceholderText("例如: {date}_{name}  或  report_{n:03d}")
        self._tpl.textChanged.connect(self._update_preview)
        tpl_row.addWidget(self._tpl, 1)

        quick_btn = QToolButton()
        quick_btn.setText("快速樣板 ▼")
        quick_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        qm = QMenu(self)
        for tpl, label in [
            ("{date}_{name}",  "{date}_{name}  (日期_原名)"),
            ("{n:03d}_{name}", "{n:03d}_{name}  (序號_原名)"),
            ("{name}_{date}",  "{name}_{date}  (原名_日期)"),
            ("{n}_{name}",     "{n}_{name}      (序號_原名)"),
        ]:
            qm.addAction(label).triggered.connect(
                lambda checked, t=tpl: self._tpl.setText(t))
        quick_btn.setMenu(qm)
        tpl_row.addWidget(quick_btn)
        layout.addLayout(tpl_row)

        hint = QLabel("佔位符：{name} 原檔名  {ext} 副檔名  {date} 今日日期  {n} 序號  {n:03d} 補零序號")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        # 預覽表格
        self._model = QStandardItemModel(0, 4)
        self._model.setHorizontalHeaderLabels(["#", "原始名稱", "新名稱（預覽）", "狀態"])
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setRootIsDecorated(False)
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree.setSelectionMode(QTreeView.SelectionMode.NoSelection)
        self._tree.setAlternatingRowColors(True)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(0, 36)
        self._tree.setColumnWidth(1, 200)
        self._tree.setColumnWidth(3, 80)
        layout.addWidget(self._tree)

        # 底部按鈕
        btn_row = QHBoxLayout()
        btn_row.addWidget(QPushButton("取消", clicked=self.reject))
        btn_row.addStretch()
        self._apply_btn = QPushButton(f"套用重新命名 ({len(self._src_paths)} 個)")
        self._apply_btn.setDefault(True)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)
        layout.addLayout(btn_row)

    def _apply_template(self, template: str, src_path: str, index: int) -> str:
        name, ext = os.path.splitext(os.path.basename(src_path))
        result = template
        result = result.replace("{name}", name)
        result = result.replace("{ext}",  ext)
        result = result.replace("{date}", self._today)
        result = re.sub(r'\{n:([^}]+)\}', lambda m: format(index + 1, m.group(1)), result)
        result = result.replace("{n}", str(index + 1))
        if "{ext}" not in template.lower() and ext:
            result += ext
        return result

    def _update_preview(self):
        from collections import Counter
        template = self._tpl.text()
        self._model.removeRows(0, self._model.rowCount())
        if not template.strip():
            self._apply_btn.setText("套用重新命名 (0 個)")
            self._apply_btn.setEnabled(False)
            return

        previews = [(s, self._apply_template(template, s, i), os.path.dirname(s))
                    for i, s in enumerate(self._src_paths)]
        dup_counter = Counter((p, n) for (_, n, p) in previews)

        valid = 0
        for i, (src, new_name, parent) in enumerate(previews):
            orig = os.path.basename(src)
            new_path = os.path.join(parent, new_name)
            same = os.path.normcase(new_name) == os.path.normcase(orig)

            if same:
                st, color, ok = "—", QColor("gray"), False
            elif self._INVALID_RE.search(new_name):
                st, color, ok = "✗ 無效", QColor("#e74c3c"), False
            elif dup_counter[(parent, new_name)] > 1:
                st, color, ok = "⚠ 重複", QColor("#e67e22"), False
            elif os.path.normcase(new_path) != os.path.normcase(src) and os.path.exists(new_path):
                st, color, ok = "⚠ 重複", QColor("#e67e22"), False
            else:
                st, color, ok = "✓", QColor("#2ecc71"), True

            if ok:
                valid += 1

            row = [QStandardItem(str(i + 1)), QStandardItem(orig),
                   QStandardItem(new_name),   QStandardItem(st)]
            row[0].setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            row[3].setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            row[3].setForeground(color)
            self._model.appendRow(row)

        self._apply_btn.setText(f"套用重新命名 ({valid} 個)")
        self._apply_btn.setEnabled(valid > 0)

    def _on_apply(self):
        from collections import Counter
        template = self._tpl.text().strip()
        if not template:
            return
        pairs = []
        for i, src in enumerate(self._src_paths):
            new_name = self._apply_template(template, src, i)
            parent   = os.path.dirname(src)
            new_path = os.path.join(parent, new_name)
            if os.path.normcase(os.path.basename(src)) == os.path.normcase(new_name):
                continue
            if self._INVALID_RE.search(new_name):
                continue
            if os.path.normcase(new_path) != os.path.normcase(src) and os.path.exists(new_path):
                continue
            pairs.append((src, new_path))
        dest_count = Counter(os.path.normcase(d) for _, d in pairs)
        pairs = [(s, d) for s, d in pairs if dest_count[os.path.normcase(d)] == 1]
        if not pairs:
            return
        self._confirmed_pairs = pairs
        self.accept()

    def get_op_pairs(self) -> list[tuple[str, str]]:
        return self._confirmed_pairs
