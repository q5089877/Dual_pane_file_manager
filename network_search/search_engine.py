import os
import sqlite3
import stat  # 判斷 Windows 檔案屬性
import logging
from PyQt6.QtCore import QThread, pyqtSignal


class IndexManager:
    """Handles SQLite FTS5 indexing and fingerprinting."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # Table for directory modification timestamps (fingerprints)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS folder_fingerprints (
                    path TEXT PRIMARY KEY,
                    mtime REAL
                )
            """)

            # Main file index
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files_index (
                    path TEXT PRIMARY KEY,
                    name TEXT,
                    parent TEXT,
                    size INTEGER,
                    mtime REAL
                )
            """)

            # Simple migration for 'size' column
            cursor = conn.execute("PRAGMA table_info(files_index)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'size' not in columns:
                conn.execute("ALTER TABLE files_index ADD COLUMN size INTEGER")

            # FTS5 Virtual Table for fast filename searching
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                        name,
                        path UNINDEXED,
                        content='files_index',
                        content_rowid='rowid'
                    )
                """)
            except sqlite3.OperationalError:
                # If FTS5 is not available or schema mismatch, try to recreate or ignore
                pass

    def get_folder_metadata(self, folder_path):
        folder_path = os.path.normpath(folder_path)
        with self._get_conn() as conn:
            res = conn.execute(
                "SELECT mtime FROM folder_fingerprints WHERE path = ?", (folder_path,)).fetchone()
            if not res:
                return None, False

            # 檢查該資料夾下是否有檔案缺失 size (舊資料)
            has_null_size = conn.execute(
                "SELECT 1 FROM files_index WHERE parent = ? AND size IS NULL LIMIT 1", (folder_path,)).fetchone()
            return res[0], not has_null_size

    def update_folder(self, folder_path, mtime, files):
        """
        updates files in a folder. 'files' is a list of (full_path, name, size, mtime)
        """
        folder_path = os.path.normpath(folder_path)
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO folder_fingerprints (path, mtime) VALUES (?, ?)", (folder_path, mtime))
            conn.execute(
                "DELETE FROM files_index WHERE parent = ?", (folder_path,))
            conn.executemany("INSERT INTO files_index (path, name, parent, size, mtime) VALUES (?, ?, ?, ?, ?)",
                             [(os.path.normpath(f[0]), f[1], folder_path, f[2], f[3]) for f in files])

    def search(self, keyword, limit=100, min_size=0):
        with self._get_conn() as conn:
            # 判斷是否包含萬用字元 (* 或 ?)
            is_wildcard = '*' in keyword or '?' in keyword

            size_filter = f"AND i.size >= {min_size}" if min_size > 0 else ""

            if is_wildcard:
                # 萬用字元模式：轉換 * 為 %，? 為 _
                lk_pattern = keyword.replace('*', '%').replace('?', '_')
                query = f"""
                    SELECT name, mtime, size, path
                    FROM files_index
                    WHERE name LIKE ? {size_filter.replace('i.', '')}
                    LIMIT ?
                """
                return conn.execute(query, (lk_pattern, limit)).fetchall()
            else:
                # 快搜模式 (FTS5)
                query = f"""
                    SELECT i.name, i.mtime, i.size, i.path
                    FROM fts_files f
                    JOIN files_index i ON f.rowid = i.rowid
                    WHERE f.name MATCH ? {size_filter} LIMIT ?
                """
                # Note: 'fts_files' is a placeholder, usually we use files_fts
                # Fix: Use files_fts
                query = query.replace("fts_files", "files_fts")
                try:
                    return conn.execute(query, (f'"{keyword}"*', limit)).fetchall()
                except sqlite3.OperationalError:
                    # Fallback
                    lk_query = f"SELECT name, mtime, size, path FROM files_index WHERE name LIKE ? {size_filter.replace('i.', '')} LIMIT ?"
                    return conn.execute(lk_query, (f"%{keyword}%", limit)).fetchall()


class ScannerWorker(QThread):
    """Background scanner for network/local paths."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, root_paths, index_mgr):
        super().__init__()
        self.root_paths = [os.path.normpath(p) for p in root_paths]
        self.index_mgr = index_mgr
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        total_files = 0
        for root in self.root_paths:
            if not self._is_running:
                break
            total_files += self._scan_recursive(root)
        self.finished.emit(total_files)

    def _scan_recursive(self, path):
        path = os.path.normpath(path)
        if not self._is_running:
            return 0

        folder_name = os.path.basename(path)
        # 1. 檔名過濾: 排除隱藏與開發暫存目錄
        if folder_name.startswith('.') and path not in self.root_paths:
            return 0
        if folder_name.lower() in ['node_modules', '__pycache__', 'venv', 'bin', 'obj']:
            return 0

        try:
            stat_res = os.stat(path)
            # 2. 屬性過濾: Windows 系統隱藏/系統檔 (排除指定根目錄)
            if os.name == 'nt' and path not in self.root_paths:
                if stat_res.st_file_attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                    return 0

            current_mtime = stat_res.st_mtime
            cached_mtime, has_size_data = self.index_mgr.get_folder_metadata(
                path)

            if cached_mtime == current_mtime and has_size_data:
                return 0

            self.progress.emit(f"掃描中: {path}")
            files_to_index = []
            subfolders = []

            with os.scandir(path) as it:
                for entry in it:
                    if not self._is_running:
                        return 0
                    full_path = os.path.normpath(entry.path)
                    if entry.is_file():
                        try:
                            s = entry.stat()
                            files_to_index.append(
                                (full_path, entry.name, s.st_size, s.st_mtime))
                        except:
                            continue
                    elif entry.is_dir():
                        subfolders.append(full_path)

            self.index_mgr.update_folder(path, current_mtime, files_to_index)
            count = len(files_to_index)
            for sub in subfolders:
                count += self._scan_recursive(sub)
            return count
        except Exception as e:
            logging.error(f"Error scanning {path}: {e}")
            return 0
