import os
import shutil
import ctypes
from ctypes import wintypes


try:
    import send2trash
except ImportError:
    send2trash = None


class FileOps:
    """Core file system operations and shell integrations."""

    @staticmethod
    def is_offline_cloud_file(path: str) -> bool:
        """
        Detects if a file is a cloud placeholder (OneDrive, etc.) that is NOT locally present.
        Checking attributes avoids triggering a download (hydration).
        """
        try:
            # 0x1000: FILE_ATTRIBUTE_OFFLINE
            # 0x00400000: FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS (modern OneDrive)
            # 0x00040000: FILE_ATTRIBUTE_RECALL_ON_OPEN
            # 0x00100000: FILE_ATTRIBUTE_UNPINNED (OneDrive "Free up space")
            # 0x0200: FILE_ATTRIBUTE_SPARSE_FILE
            # 0x0400: FILE_ATTRIBUTE_REPARSE_POINT
            attrs = ctypes.windll.kernel32.GetFileAttributesW(
                os.path.normpath(path))
            if attrs == -1:
                return False

            is_offline = bool(attrs & 0x1000)
            is_recall = bool(attrs & 0x00400000)
            is_recall_open = bool(attrs & 0x00040000)
            is_unpinned = bool(attrs & 0x00100000)
            is_sparse = bool(attrs & 0x0200)
            is_reparse = bool(attrs & 0x0400)

            # If it's a sparse reparse point OR marked with any cloud dehydrated flags
            return is_offline or is_recall or is_recall_open or is_unpinned or (is_sparse and is_reparse)
        except Exception:
            return False

    @staticmethod
    def get_timestamp_suffix_name(src_path: str) -> str:
        """Generates a name by appending _YYYYMMDD to the filename for in-place rename."""
        import datetime
        dir_name = os.path.dirname(src_path)
        base_name = os.path.basename(src_path)
        ts_str = datetime.datetime.now().strftime("%Y%m%d")

        if os.path.isfile(src_path):
            name_part, ext_part = os.path.splitext(base_name)
            new_base = f"{name_part}_{ts_str}{ext_part}"
        else:
            new_base = f"{base_name}_{ts_str}"

        new_path = os.path.join(dir_name, new_base)
        # Handle rare collision
        if os.path.exists(new_path):
            counter = 1
            if os.path.isfile(src_path):
                name_part, ext_part = os.path.splitext(base_name)
                while os.path.exists(new_path):
                    new_path = os.path.join(
                        dir_name, f"{name_part}_{ts_str}_{counter}{ext_part}")
                    counter += 1
            else:
                while os.path.exists(new_path):
                    new_path = os.path.join(
                        dir_name, f"{base_name}_{ts_str}_{counter}")
                    counter += 1
        return os.path.normpath(new_path)

    @staticmethod
    def get_versioned_name(src_path):
        """Generates a name with today's date suffix, e.g., 'file_2026-03-22.txt'."""
        import datetime
        dir_name = os.path.dirname(src_path)
        base_name = os.path.basename(src_path)
        date_str = datetime.datetime.now().strftime("%Y%m%d")

        if os.path.isfile(src_path):
            name_part, ext_part = os.path.splitext(base_name)
            new_base = f"{name_part}_{date_str}{ext_part}"
            new_path = os.path.join(dir_name, new_base)
            counter = 1
            while os.path.exists(new_path):
                new_base = f"{name_part}_{date_str}_v{counter}{ext_part}"
                new_path = os.path.join(dir_name, new_base)
                counter += 1
        else:
            new_base = f"{base_name}_{date_str}"
            new_path = os.path.join(dir_name, new_base)
            counter = 1
            while os.path.exists(new_path):
                new_path = os.path.join(
                    dir_name, f"{base_name}_{date_str}_v{counter}")
                counter += 1
        return os.path.normpath(new_path)

    @staticmethod
    def get_unique_copy_name(src_path):
        """Generates a unique name like 'file - 複製.txt' for same-folder copies."""
        dir_name = os.path.dirname(src_path)
        base_name = os.path.basename(src_path)

        if os.path.isfile(src_path):
            name_part, ext_part = os.path.splitext(base_name)
            new_base = f"{name_part} - 複製{ext_part}"
            new_path = os.path.join(dir_name, new_base)
            counter = 2
            while os.path.exists(new_path):
                new_base = f"{name_part} - 複製 ({counter}){ext_part}"
                new_path = os.path.join(dir_name, new_base)
                counter += 1
        else:
            new_base = f"{base_name} - 複製"
            new_path = os.path.join(dir_name, new_base)
            counter = 2
            while os.path.exists(new_path):
                new_path = os.path.join(
                    dir_name, f"{base_name} - 複製 ({counter})")
                counter += 1
        return os.path.normpath(new_path)

    @staticmethod
    def delete_paths(paths, permanent=False):
        """Deletes files/folders, either permanently or to recycle bin."""
        results = []
        for path in paths:
            try:
                if permanent or send2trash is None:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                else:
                    send2trash.send2trash(os.path.normpath(path))
                results.append((path, True, ""))
            except Exception as e:
                results.append((path, False, str(e)))
        return results

    @staticmethod
    def show_properties(path):
        """Shows Windows file properties dialog."""
        SW_SHOW = 5
        SEE_MASK_INVOKEIDLIST = 0x0000000C

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", ctypes.c_ulong),
                ("hwnd", wintypes.HWND),
                ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p),
                ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        lp_info = SHELLEXECUTEINFO()
        lp_info.cbSize = ctypes.sizeof(lp_info)
        lp_info.fMask = SEE_MASK_INVOKEIDLIST
        lp_info.lpVerb = "properties"
        lp_info.lpFile = os.path.normpath(path)
        lp_info.nShow = SW_SHOW

        return ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(lp_info))

    @staticmethod
    def open_with(path):
        """Triggers Windows 'Open With' dialog."""
        path = os.path.normpath(path)
        try:
            os.startfile(path, operation="openas")
            return True
        except Exception:
            try:
                import subprocess
                subprocess.Popen(
                    ['rundll32.exe', 'shell32.dll,OpenAs_RunDLL', path])
                return True
            except Exception:
                return False

    @staticmethod
    def edit_with_notepad(path):
        """Opens file in Notepad."""
        import subprocess
        try:
            subprocess.Popen(['notepad.exe', os.path.normpath(path)])
            return True
        except Exception:
            return False

    @staticmethod
    def move_paths(op_pairs):
        """Moves files/folders."""
        results = []
        for src, dest in op_pairs:
            try:
                if os.path.exists(dest):
                    if os.path.isdir(dest):
                        shutil.rmtree(dest)
                    else:
                        os.remove(dest)
                shutil.move(src, dest)
                results.append((src, True, ""))
            except Exception as e:
                results.append((src, False, str(e)))
        return results

    # ------------------------------------------------------------------
    # Archive helpers
    # ------------------------------------------------------------------

    _ARCHIVE_EXTS = frozenset({'.zip', '.tar', '.gz', '.bz2', '.xz', '.tgz'})

    @staticmethod
    def is_archive(path: str) -> bool:
        """True if path is a supported archive format (.zip / .tar*)."""
        lower = path.lower()
        for compound in ('.tar.gz', '.tar.bz2', '.tar.xz'):
            if lower.endswith(compound):
                return True
        _, ext = os.path.splitext(lower)
        return ext in FileOps._ARCHIVE_EXTS

    @staticmethod
    def archive_dest_folder(path: str) -> str:
        """Return the extraction destination folder (same dir, name without extension)."""
        parent = os.path.dirname(path)
        base = os.path.basename(path)
        lower = base.lower()
        for compound in ('.tar.gz', '.tar.bz2', '.tar.xz'):
            if lower.endswith(compound):
                return os.path.join(parent, base[: -len(compound)])
        name, _ = os.path.splitext(base)
        return os.path.join(parent, name)

    @staticmethod
    def zip_dest_path(folder_path: str) -> str:
        """Return a dated zip output path for folder_path, avoiding conflicts."""
        import datetime
        base = os.path.basename(folder_path.rstrip("/\\"))
        parent = os.path.dirname(folder_path.rstrip("/\\"))
        today = datetime.datetime.now().strftime("%Y%m%d")
        candidate = os.path.join(parent, f"{base}_{today}.zip")
        if not os.path.exists(candidate):
            return candidate
        i = 1
        while True:
            candidate = os.path.join(parent, f"{base}_{today}_v{i}.zip")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    @staticmethod
    def get_win_quick_access_paths() -> list[str]:
        """讀取 Windows 檔案總管中使用者手動釘選的 Quick Access 資料夾路徑。"""
        try:
            import win32com.client
            shell_app = win32com.client.Dispatch("Shell.Application")
            ns = shell_app.Namespace(
                "shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}")
            if ns is None:
                return []
            items = ns.Items()
            paths = []
            for i in range(items.Count):
                item = items.Item(i)
                if not item.ExtendedProperty("System.Home.IsPinned"):
                    continue
                path = item.Path
                if path and os.path.isdir(path):
                    paths.append(path)
            return paths
        except Exception:
            return []
