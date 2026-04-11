import os
import string
import ctypes
from typing import Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QFileIconProvider
)
from PyQt6.QtCore import Qt, QStandardPaths, QFileInfo, pyqtSignal


class NavPanel(QWidget):
    clicked = pyqtSignal()  # 任何點擊 → 通知外部切換焦點

    """
    導覽窗格側邊欄，提供兩個區段：
    - 磁碟機：僅列本機固定碟與卸除式磁碟（排除網路磁碟/光碟）
    - 常用資料夾：桌面、下載、文件、圖片、音樂、影片
    點擊項目後呼叫 on_navigate(path)。
    """

    def __init__(self, on_navigate: Callable[[str], None], parent=None, config_mgr=None):
        super().__init__(parent)
        self._cm = config_mgr
        self.on_navigate = on_navigate
        self.setObjectName("navPanel")
        self.setFixedWidth(200)
        self._icon_provider = QFileIconProvider()
        self._init_ui()
        self._populate()

    def set_config_mgr(self, cm) -> None:
        self._cm = cm

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(12)
        self.tree.setAnimated(True)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.pressed.connect(lambda _: self.clicked.emit())
        layout.addWidget(self.tree)

    def _make_section(self, title: str) -> QTreeWidgetItem:
        """建立粗體的區段標題，不可選取。"""
        item = QTreeWidgetItem(self.tree, [title])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _make_entry(self, parent: QTreeWidgetItem, label: str, path: str) -> None:
        """建立可點擊的葉節點，附系統圖示。"""
        item = QTreeWidgetItem(parent, [label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        if path and os.path.exists(path):
            icon = self._icon_provider.icon(QFileInfo(path))
            item.setIcon(0, icon)

    def _populate(self) -> None:
        """建立所有區段的項目。"""
        self.tree.clear()

        # ── 快速存取 ──────────────────────────────────────
        quick_section = self._make_section("快速存取")
        self._populate_quick_access(quick_section)
        quick_section.setExpanded(True)

        # ── 磁碟機 ───────────────────────────────────────
        drives_section = self._make_section("磁碟機")
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drive_type = self._get_drive_type(root)
                if drive_type in ("local", "removable", "remote"):
                    label = self._get_drive_label(root) or f"({letter}:)"
                    self._make_entry(drives_section, label, root)
        drives_section.setExpanded(True)

        # ── 常用資料夾 ───────────────────────────────────
        folders_section = self._make_section("常用資料夾")
        common = [
            ("桌面", QStandardPaths.StandardLocation.DesktopLocation),
            ("下載", QStandardPaths.StandardLocation.DownloadLocation),
            ("文件", QStandardPaths.StandardLocation.DocumentsLocation),
            ("圖片", QStandardPaths.StandardLocation.PicturesLocation),
            ("音樂", QStandardPaths.StandardLocation.MusicLocation),
            ("影片", QStandardPaths.StandardLocation.MoviesLocation),
        ]
        for name, loc in common:
            path = QStandardPaths.writableLocation(loc)
            if path and os.path.exists(path):
                self._make_entry(folders_section, name, path)

        # OneDrive（從環境變數取得本機同步路徑）
        onedrive_path = os.environ.get("OneDrive") or os.environ.get("ONEDRIVE")
        if onedrive_path and os.path.exists(onedrive_path):
            self._make_entry(folders_section, "OneDrive", onedrive_path)

        folders_section.setExpanded(True)

    def _populate_quick_access(self, section: QTreeWidgetItem) -> None:
        """讀取 Windows 快速存取（釘選資料夾 + 常用資料夾）。"""
        try:
            import win32com.client  # pywin32
            shell_app = win32com.client.Dispatch("Shell.Application")
            ns = shell_app.Namespace("shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}")
            if ns is None:
                return
            items = ns.Items()
            for i in range(items.Count):
                item = items.Item(i)
                if not item.ExtendedProperty("System.Home.IsPinned"):
                    continue
                path = item.Path
                name = item.Name
                if path and os.path.exists(path):
                    self._make_entry(section, name, path)
        except Exception:
            pass

    def _get_drive_type(self, root: str) -> str:
        """
        回傳 'local'、'removable' 或 'other'。
        GetDriveTypeW: 3=FIXED, 2=REMOVABLE, 4=REMOTE, 5=CDROM, 6=RAMDISK
        """
        try:
            dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
            return {3: "local", 2: "removable", 4: "remote"}.get(dtype, "other")
        except Exception:
            return "local"

    def _get_drive_label(self, root: str) -> str:
        """取得磁碟標籤，格式：'Windows (C:)'。"""
        try:
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.kernel32.GetVolumeInformationW(
                root, buf, 256, None, None, None, None, 0)
            letter = root[0].upper()
            label = buf.value.strip()
            return f"{label} ({letter}:)" if label else f"({letter}:)"
        except Exception:
            return ""

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        path: str | None = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            self.on_navigate(path)

    def mousePressEvent(self, event) -> None:
        """點擊空白處也觸發 clicked（用於切換 pane 焦點）。"""
        self.clicked.emit()
        super().mousePressEvent(event)

    def refresh_drives(self) -> None:
        """重新掃描磁碟機（例如 USB 插入後使用）。"""
        self._populate()
