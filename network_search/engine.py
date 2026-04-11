import os
import sqlite3
import logging
import time

logger = logging.getLogger(__name__)

import queue
import threading
import datetime
import shutil
import urllib.parse
from collections import deque
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from abc import ABC, abstractmethod
from PyQt6.QtCore import QThread, pyqtSignal
from core.system_utils import is_reparse_point, set_current_thread_priority_low


def unc_to_sqlite_uri(db_path: str) -> str:
    """
    Converts a Windows UNC or local path to a SQLite-safe read-only URI.
    Note: Do NOT use Path.as_uri() as it URL-encodes spaces/Chinese,
    breaking SQLite's ability to resolve Windows paths.
    """
    normalized_path = db_path.replace('\\', '/')

    if normalized_path.startswith('//'):
        # UNC: file:////server/share/file.db (Total 4 slashes before server)
        return f"file:{normalized_path}?mode=ro"
    else:
        # Drive letter: file:///K:/path/file.db (Total 3 slashes)
        return f"file:///{normalized_path}?mode=ro"


class IndexManager:
    """Handles SQLite FTS5 indexing with local and remote databases."""

    def __init__(self, local_db_dir, nas_folder_path=None, read_only=False):
        self.local_db_dir = Path(local_db_dir)
        self.nas_folder_path = nas_folder_path
        self.read_only = read_only

        self.master_db_path = self.local_db_dir / "master.db"
        self.current_shared_slot = None
        self.force_rescan = False

        # Connect to databases
        self.local_db_dir.mkdir(parents=True, exist_ok=True)
        self.personal_db_path = self.local_db_dir / "personal.db"
        
        logger.debug(f"IndexManager master_db_path = {self.master_db_path.absolute()}")
        logger.debug(f"IndexManager personal_db_path = {self.personal_db_path.absolute()}")
        
        # Schema check MUST happen BEFORE persistent _init_db
        self._check_schema_upgrade(self.master_db_path)
        self._check_schema_upgrade(self.personal_db_path)
        
        self.conn = self._get_conn(self.master_db_path)
        self.personal_conn = self._get_conn(self.personal_db_path)
        self._init_db(self.conn)
        self._init_db(self.personal_conn)

    def _check_schema_upgrade(self, db_path):
        """Checks if database needs a reset due to schema change (V3)."""
        if not db_path or not db_path.exists():
            return

        needs_reset = False
        try:
            conn = sqlite3.connect(str(db_path), timeout=5, uri=True)
            cursor = conn.cursor()
            cols = [c[1] for c in cursor.execute("PRAGMA table_info(files_index)").fetchall()]
            if cols and "folder_id" not in cols:
                needs_reset = True
            conn.close()
        except Exception as e:
            logging.warning(f"Schema check failed for {db_path}: {e}")
            needs_reset = True

        if needs_reset:
            logging.warning(f"Schema upgrade detected or DB corrupted for {db_path}. Resetting DB.")
            self.reset_db(db_path, init_after=False)

    def _get_conn(self, db_path):
        """Creates a WAL mode connection with FTS support and reasonable timeout."""
        if not db_path: return None
        db_path = Path(db_path)
        from core.config_manager import ConfigManager
        settings = ConfigManager().get_db_settings()
        try:
            conn = sqlite3.connect(str(db_path), timeout=settings.get("sqlite_timeout", 30), check_same_thread=False, uri=True)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            cache_size = settings.get("wal_cache_size", -10000)
            conn.execute(f"PRAGMA cache_size={cache_size};")
            busy_ms = settings.get("busy_timeout_ms", 5000)
            conn.execute(f"PRAGMA busy_timeout={busy_ms};")
            # Ensure schema exists (folders, files_index, fts_index)
            # _ensure_schema is called by _init_db, which is called in __init__
            # self._ensure_schema(conn)
            return conn
        except Exception as e:
            logging.error(f"Failed to connect to {db_path}: {e}")
            return None

    def _ensure_schema(self, conn):
        """Ensures the basic schema exists in the given connection."""
        conn.execute("CREATE TABLE IF NOT EXISTS folders (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_folders_path ON folders(path);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS files_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_id INTEGER,
                name TEXT,
                mtime REAL,
                size INTEGER,
                FOREIGN KEY(folder_id) REFERENCES folders(id)
            )
        """)
        
        # 安全升級舊架構：如果舊資料表沒有 folder_id，則就地追加，這可以解決無法刪除檔案時的崩潰問題
        try:
            conn.execute("ALTER TABLE files_index ADD COLUMN folder_id INTEGER")
        except sqlite3.OperationalError:
            pass # 欄位已存在
            
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_folder ON files_index(folder_id);")
        conn.execute("CREATE TABLE IF NOT EXISTS folder_fingerprints (folder_id INTEGER PRIMARY KEY, mtime REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS scan_metadata (root_path TEXT PRIMARY KEY, status TEXT, last_finished REAL, total_files INTEGER)")

        # FTS5 Virtual Table
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(name, content=files_index, content_rowid=id);")

        # FTS5 Triggers
        conn.execute("CREATE TRIGGER IF NOT EXISTS fts_after_insert AFTER INSERT ON files_index BEGIN INSERT INTO fts_index(rowid, name) VALUES (new.id, new.name); END;")
        conn.execute("CREATE TRIGGER IF NOT EXISTS fts_after_delete AFTER DELETE ON files_index BEGIN INSERT INTO fts_index(fts_index, rowid, name) VALUES('delete', old.id, old.name); END;")
        conn.execute("CREATE TRIGGER IF NOT EXISTS fts_after_update AFTER UPDATE ON files_index BEGIN INSERT INTO fts_index(fts_index, rowid, name) VALUES('delete', old.id, old.name); INSERT INTO fts_index(rowid, name) VALUES (new.id, new.name); END;")
        conn.commit()

    def _ensure_latest_shared_db(self):
        """Checks current_version.txt and hot-swaps the shared_db if needed."""
        if not self.nas_folder_path or not self.conn: return

        version_file = os.path.join(self.nas_folder_path, "current_version.txt")
        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                latest_slot = f.read().strip().upper()
        except:
            return # NAS not ready or version file missing

        if latest_slot == self.current_shared_slot:
            return

        cursor = self.conn.cursor()
        # Detach old if exists
        if self.current_shared_slot:
            try: cursor.execute("DETACH DATABASE shared_db;")
            except: pass

        # Attach new slot
        new_db_path = os.path.join(self.nas_folder_path, f"index_{latest_slot}.db")
        if os.path.exists(new_db_path):
            uri = unc_to_sqlite_uri(new_db_path)
            try:
                cursor.execute(f"ATTACH DATABASE '{uri}' AS shared_db;")
                self.current_shared_slot = latest_slot
                logging.info(f"Hot-swapped to NAS Slot {latest_slot}")
            except Exception as e:
                logging.error(f"Failed to attach shared_db: {e}")

    def reset_db(self, db_path, init_after=True):
        """Safely resets the database."""
        db_path_str = str(db_path)
        logging.warning(f"🔧 Resetting database: {db_path_str}")
        
        # Ensure we close connections if we hold them
        if getattr(self, 'conn', None) and db_path == self.master_db_path:
            try: self.conn.close()
            except: pass
            self.conn = None
        if getattr(self, 'personal_conn', None) and db_path == self.personal_db_path:
            try: self.personal_conn.close()
            except: pass
            self.personal_conn = None

        import glob
        for f in glob.glob(db_path_str + "*"):
            try:
                if os.path.exists(f): os.remove(f)
            except: pass
            
        if init_after:
            if db_path == self.master_db_path:
                self.conn = self._get_conn(self.master_db_path)
                self._init_db(self.conn)
            elif db_path == getattr(self, 'personal_db_path', None):
                self.personal_conn = self._get_conn(self.personal_db_path)
                self._init_db(self.personal_conn)
        return True

    def _init_db(self, conn):
        """Initializes the database schema for a given connection."""
        if not conn: return
        self._ensure_schema(conn)

    def get_folder_id(self, conn, folder_path):
        """Resolves folder_id, creating it if necessary."""
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO folders (path) VALUES (?)", (folder_path,))
        c.execute("SELECT id FROM folders WHERE path = ?", (folder_path,))
        res = c.fetchone()
        return res[0] if res else None

    def search(self, keyword, limit=1000, min_size=0, path_prefix=None, min_mtime=0,
               use_local=True, use_network=False, local_path_filter=None, network_path_filter=None,
               use_personal=True):
        """Unified search across local, personal, and attached network indices."""
        if not self.conn: return []
        if use_network: self._ensure_latest_shared_db()

        queries = []
        params = []

        # Clean and check for global search
        keyword = (keyword or "").strip()
        # Robust detection of global patterns that shouldn't trigger FTS MATCH
        clean_check = keyword.replace("*", "").strip()
        is_global_search = keyword in ("*.*", "*", "") or clean_check in ("", ".")

        # Build parts of the query
        if is_global_search:
            join_fts = ""
            match_sql = "1"
        else:
            # FTS5 matches tokens. We wrap in double quotes to handle special chars (dots, spaces)
            # and append * for prefix matching.
            clean_kw = keyword.replace('"', '').replace("*", "").strip()
            if clean_kw and len(clean_kw) > 0:
                keyword = f'"{clean_kw}"*'
                join_fts = f"JOIN {{db}}.fts_index fts ON f.id = fts.rowid"
                match_sql = "fts.name MATCH ?"
            else:
                join_fts = ""
                match_sql = "1"

        # Build filter SQL
        filter_sql = ""
        path_prefix_param = None
        if path_prefix:
            filter_sql = " AND d.path LIKE ? ESCAPE '!'"
            # 1. 先正規化路徑
            clean_prefix = os.path.normpath(path_prefix)
            # 2. 先對路徑本身的 _ 和 % 進行跳脫
            clean_prefix = clean_prefix.replace("!", "!!").replace("_", "!_").replace("%", "!%")
            # 3. 最後才把代表 SQL 萬用字元的 % 加在尾巴
            path_prefix_param = f"{clean_prefix}%"

        # Search Template combining files_index and folders
        search_template = f"""
            SELECT f.name, f.mtime, CAST(f.size AS REAL), (d.path || '\\' || f.name) as full_path
            FROM {{db}}.files_index f
            JOIN {{db}}.folders d ON f.folder_id = d.id
            {join_fts}
            WHERE {match_sql}
              AND f.size >= ?
              AND f.mtime >= ?
              {filter_sql}
              AND d.path LIKE ? ESCAPE '!'
        """

        if use_local:
            # 搜尋 local.db (如果是 Master 剛好有索引到一些 K:)
            queries.append(search_template.format(db="main"))
            
            if not is_global_search: params.append(keyword)
            params.extend([min_size, min_mtime])
            if path_prefix_param: params.append(path_prefix_param)
            
            # 修正 Local Filter：預設值改為空字串，不要用 "%" 去被替換
            l_filter = (local_path_filter or "").replace("!", "!!").replace("_", "!_").replace("%", "!%")
            params.append(f"{l_filter}%")

        if use_personal and self.personal_conn:
            # 優先搜尋 personal.db (個人私有 C:)
            queries.append(search_template.format(db="personal_db"))
            
            # Attach personal_db if not already attached (e.g., if only personal search is enabled)
            try:
                self.conn.execute("ATTACH DATABASE ? AS personal_db", (str(self.personal_db_path),))
            except: pass

            if not is_global_search: params.append(keyword)
            params.extend([min_size, min_mtime])
            if path_prefix_param: params.append(path_prefix_param)
            # Personal filter is usually C:\
            params.append(f"C:\\%")

        if use_network and self.current_shared_slot:
            queries.append(search_template.format(db="shared_db"))
            if not is_global_search: params.append(keyword)
            params.extend([min_size, min_mtime])
            if path_prefix_param: params.append(path_prefix_param)
            
            # 修正 Network Filter：預設值改為空字串
            n_filter = (network_path_filter or "").replace("!", "!!").replace("_", "!_").replace("%", "!%")
            params.append(f"{n_filter}%")


        if not queries: return []

        master_query = " UNION ALL ".join(queries) + " ORDER BY mtime DESC LIMIT ?"
        params.append(limit)

        try:
            cursor = self.conn.cursor()
            cursor.execute(master_query, params)
            return cursor.fetchall()
        except Exception as e:
            logging.error(f"Search error: {e}")
            return []

    def update_folder(self, folder_path, mtime, files, conn=None):
        """Updates files for a single folder with normalized schema."""
        folder_path = os.path.normpath(folder_path)

        def do_update(c):
            folder_id = self.get_folder_id(c, folder_path)
            if not folder_id: return

            # 1. Clear existing files for this folder
            c.execute("DELETE FROM files_index WHERE folder_id = ?", (folder_id,))

            # 2. Insert new files
            if files:
                c.executemany(
                    "INSERT INTO files_index (folder_id, name, size, mtime) VALUES (?, ?, ?, ?)",
                    [(folder_id, f[1], f[2], f[3]) for f in files]
                )

            # 3. Update fingerprint
            c.execute("INSERT OR REPLACE INTO folder_fingerprints (folder_id, mtime) VALUES (?, ?)", (folder_id, mtime))

        if conn:
            do_update(conn)
        else:
            with self._get_conn(self.master_db_path) as new_conn:
                do_update(new_conn)
                new_conn.commit()

    def publish_to_nas(self, nas_folder_path):
        """Atomic A/B Slot publication to NAS."""
        if not nas_folder_path or not os.path.exists(nas_folder_path): return False

        version_file = os.path.join(nas_folder_path, "current_version.txt")
        current_v = "A"
        if os.path.exists(version_file):
            try:
                with open(version_file, "r") as f: current_v = f.read().strip().upper()
            except: pass

        inactive_slot = "B" if current_v == "A" else "A"
        dest = os.path.join(nas_folder_path, f"index_{inactive_slot}.db")

        logging.info(f"Publishing to NAS Slot {inactive_slot}...")
        try:
            # 1. 使用線上備份 API 產生一個乾淨的副本
            from pathlib import Path
            import shutil
            import sqlite3 # 確保可用
            temp_db = self.local_db_dir / "temp_publish.db"
            if temp_db.exists(): temp_db.unlink()
            
            local_size = self.master_db_path.stat().st_size if self.master_db_path.exists() else 0
            logger.debug(f"Master DB size before backup: {local_size} bytes")

            # 👑 關鍵修正：開啟一個獨立的新連接進行備份，確保讀取到最新磁碟狀態 (含 WAL)
            source_uri = unc_to_sqlite_uri(str(self.master_db_path))
            with sqlite3.connect(source_uri, uri=True) as source_conn:
                backup_conn = sqlite3.connect(str(temp_db), isolation_level=None)
                try:
                    source_conn.backup(backup_conn)
                    # 在副本上進行優化，不影響正使用的 local.db
                    backup_conn.execute("PRAGMA journal_mode=DELETE;") # 轉為單一檔案模式
                    backup_conn.execute("VACUUM;")
                    backup_conn.execute("ANALYZE;")
                except Exception as e:
                    logger.error(f"BACKUP INTERNAL ERROR: {e}")
                    raise
                finally:
                    backup_conn.close()

            # 2. Copy to inactive slot
            shutil.copy2(str(temp_db), dest)

            # 3. Atomic version flip
            temp_v = os.path.join(nas_folder_path, "temp_version.txt")
            with open(temp_v, "w") as f: f.write(inactive_slot)
            os.replace(temp_v, version_file)

            logging.info(f"Successfully published to Slot {inactive_slot}")
            if temp_db.exists(): temp_db.unlink()
            return True
        except Exception as e:
            logging.error(f"Publish failed: {e}")
            logger.error(f"PUBLISH ERROR: {e}")
            return False

    def set_scan_status(self, root_path, status, total_files=0, conn=None):
        root_path = os.path.normpath(root_path)
        mtime = datetime.datetime.now().timestamp() if status == 'FINISHED' else None

        def do_set(c):
            c.execute("INSERT OR REPLACE INTO scan_metadata (root_path, status, last_finished, total_files) VALUES (?, ?, COALESCE(?, (SELECT last_finished FROM scan_metadata WHERE root_path=?)), ?)",
                         (root_path, status, mtime, root_path, total_files))

        if conn:
            do_set(conn)
        else:
            with self._get_conn(self.master_db_path) as new_conn:
                do_set(new_conn)
                new_conn.commit()

    def get_scan_status(self, root_path):
        root_path = os.path.normpath(root_path)
        with self._get_conn(self.master_db_path) as conn:
            try: return conn.execute("SELECT status, last_finished, total_files FROM scan_metadata WHERE root_path = ?", (root_path,)).fetchone()
            except: return None

# ==========================================
# MVP: Contract (介面隔離)
# ==========================================
class IScanView(ABC):
    """View 抽象合約：僅負責顯示狀態與進度"""
    @abstractmethod
    def show_progress(self, message: str) -> None: pass
    @abstractmethod
    def update_count(self, count: int) -> None: pass
    @abstractmethod
    def finish_scan(self, total: int) -> None: pass
    @abstractmethod
    def cancel_scan(self, total: int) -> None: pass
    @property
    @abstractmethod
    def is_cancelled_flag(self) -> bool: pass

# ==========================================
# MVP: Model (純資料與底層邏輯)
# ==========================================
class FileScannerModel:
    """單純處理檔案系統 I/O (Producer)，無狀態、無 UI 耦合"""
    def __init__(self, exclude_dirs=None, exclude_exts=None):
        self.global_exclude = {
            "node_modules", ".git", ".vs", ".idea", "__pycache__", "bin", "obj", "dist", "build",
            # Windows 系統目錄（無需索引，且含大量深層巢狀檔案）
            "windows", "program files", "program files (x86)", "programdata",
            "softwaredistribution", "windowsapps", "winsxs",
            "$recycle.bin", "system volume information",
            # Java / 建置工具快取（Maven、Gradle）
            ".m2", ".gradle", "gradle",
            # 瀏覽器 / Electron App 快取
            "cache", "caches", "gpucache", "code cache", "crashreports",
            "local storage", "leveldb", "indexeddb", "shader cache",
            "service worker", "cache2", "offline pages",
            # AppData 整個排除（全是 app 快取/沙盒，不是使用者檔案）
            "appdata",
            # 其他開發工具快取
            ".nuget", ".cargo", ".rustup", "target",
            "venv", ".venv", "site-packages",
        }
        if exclude_dirs:
            dirs = exclude_dirs.split(",") if isinstance(exclude_dirs, str) else list(exclude_dirs)
            for d in dirs:
                if isinstance(d, str):
                    d = d.strip().lower()
                    if d: self.global_exclude.add(d)

        default_exts = {'.tmp', '.bak', '.log', '.cache', '.thumbs', '.db-wal', '.db-shm', '.lock',
                        '.ldb', '.sst', '.manifest'}  # LevelDB / RocksDB 系統檔
        if exclude_exts:
            custom_exts = {e.strip().lower() if e.strip().startswith('.') else f".{e.strip().lower()}" for e in exclude_exts.split(",") if e.strip()}
            self.ext_blacklist = default_exts | custom_exts
        else:
            self.ext_blacklist = default_exts

        self.prefix_blacklist = ('~$', '.~', '$')

    def scan_folder(self, folder_path, depth, max_depth, mtime, mtime_cache, force_rescan):
        """讀取單一資料夾並返回指紋與檔案清單 (純資料 I/O)"""
        files_to_index = []
        subfolders = []
        actual_max_mtime = mtime
        
        normalized_path = os.path.normpath(folder_path)
        cached_mtime = mtime_cache.get(normalized_path.lower())

        try:
            with os.scandir(folder_path) as it:
                for entry in it:
                    name_low = entry.name.lower()
                    if name_low in self.global_exclude or any(name_low.startswith(p) for p in self.prefix_blacklist):
                        continue

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            # 跳過所有隱藏資料夾（以 . 開頭），如 .cache .claude .config .m2 等
                            if name_low.startswith('.'):
                                continue
                            s = entry.stat()
                            subfolders.append((entry.path, depth + 1, s.st_mtime))
                            files_to_index.append((entry.path, entry.name, 0, s.st_mtime))
                        elif entry.is_file(follow_symlinks=False):
                            ext = os.path.splitext(name_low)[1]
                            if ext in self.ext_blacklist: continue
                            
                            s = entry.stat()
                            files_to_index.append((entry.path, entry.name, s.st_size, s.st_mtime))
                            if s.st_mtime > actual_max_mtime:
                                actual_max_mtime = s.st_mtime
                    except (PermissionError, OSError):
                        continue

            should_update = (
                force_rescan or 
                cached_mtime is None or 
                abs(cached_mtime - actual_max_mtime) > 0.1
            )

            return {
                'type': 'folder_data',
                'folder_path': folder_path,
                'mtime': actual_max_mtime,
                'files': files_to_index,
                'subfolders': subfolders,
                'should_update': should_update
            }
        except Exception:
            return None

# ==========================================
# MVP: Presenter (商務邏輯中介者)
# ==========================================
class ScanPresenter:
    """中介者：透過 DI 注入 View 與 Model，處理執行緒與掃描流程調度"""
    def __init__(self, view: IScanView, index_model, file_model: FileScannerModel, root_configs, remote_db_dir, force_rescan, target_db):
        self.view = view
        self.index_model = index_model
        self.file_model = file_model
        self.root_configs = root_configs
        self.remote_db_dir = remote_db_dir
        self.force_rescan = force_rescan
        self.target_db = target_db
        
        self.total_scanned = 0
        self.result_queue = queue.Queue(maxsize=10000)
        self.active_tasks = 0
        self.task_lock = threading.Lock()

    def execute(self):
        db_conn = None
        try:
            target_path = self.index_model.master_db_path if self.target_db == "local" else self.index_model.personal_db_path
            db_conn = self.index_model._get_conn(target_path)

            cursor = db_conn.execute("SELECT d.path, f.mtime FROM folder_fingerprints f JOIN folders d ON f.folder_id = d.id")
            mtime_cache = {os.path.normpath(p).lower(): m for p, m in cursor.fetchall()}

            for root_path_raw, max_depth in self.root_configs:
                if self.view.is_cancelled_flag: break
                root_path = os.path.normpath(root_path_raw)
                if not os.path.exists(root_path): continue

                self.view.show_progress(f"🚀 掃描中 (並行): {root_path}")
                self._run_parallel_scan(root_path, max_depth, mtime_cache, db_conn)
                self.index_model.set_scan_status(root_path, 'FINISHED', self.total_scanned, conn=db_conn)

            db_conn.close()
            db_conn = None

            if self.remote_db_dir and not self.view.is_cancelled_flag:
                self.view.show_progress("📤 發布索引至 NAS 中...")
                success = self.index_model.publish_to_nas(self.remote_db_dir)
                if success:
                    self.view.show_progress("✅ 索引已成功發布至 NAS")
                else:
                    self.view.show_progress("❌ 索引發布失敗 (請檢查網路權限或路徑)")

            if self.view.is_cancelled_flag:
                self.view.cancel_scan(self.total_scanned)
            else:
                self.view.finish_scan(self.total_scanned)

        except Exception as e:
            logging.error(f"ScanPresenter execution failed: {e}")
            if db_conn:
                try: db_conn.close()
                except: pass
            self.view.cancel_scan(self.total_scanned)

    def _run_parallel_scan(self, root_path, max_depth, mtime_cache, db_conn):
        drive = os.path.splitdrive(root_path)[0].lower()
        is_network = drive == 'k:' or root_path.startswith('\\\\')
        workers = 8 if is_network else 4

        batch_counter = 0
        last_progress_time = 0

        with ThreadPoolExecutor(max_workers=workers) as executor:
            try:
                st = os.stat(root_path)
                with self.task_lock:
                    self.active_tasks += 1
                executor.submit(self._worker_proxy, root_path, 0, max_depth, st.st_mtime, mtime_cache)
            except Exception as e:
                logging.error(f"Failed to start scan for {root_path}: {e}")
                return
            db_conn.execute("BEGIN TRANSACTION")

            while not self.view.is_cancelled_flag and self.active_tasks > 0:
                try:
                    from core.config_manager import ConfigManager
                    qt = ConfigManager().get_db_settings().get("queue_get_timeout", 0.2)
                    result = self.result_queue.get(timeout=qt)
                    if result['type'] == 'task_done':
                        with self.task_lock:
                            self.active_tasks -= 1
                        self.result_queue.task_done()
                    elif result['type'] == 'folder_data':
                        import time
                        current_time = time.time()
                        if current_time - last_progress_time > 0.1:
                            # 節流閥：每 0.1 秒向 UI 發送一次更新，避免 Qt Event Loop 塞爆
                            self.view.show_progress(f"正在掃描: {os.path.basename(result['folder_path']) or result['folder_path']}")
                            last_progress_time = current_time

                        try:
                            if result['should_update']:
                                self._apply_to_db(result, db_conn)

                            for sub_path, depth, sub_mtime in result['subfolders']:
                                if depth <= max_depth:
                                    with self.task_lock:
                                        self.active_tasks += 1
                                    executor.submit(self._worker_proxy, sub_path, depth, max_depth, sub_mtime, mtime_cache)

                            if result['should_update']:
                                batch_counter += 1
                                from core.config_manager import ConfigManager
                                bs = ConfigManager().get_db_settings().get("transaction_batch_size", 5)
                                if batch_counter >= bs:
                                    db_conn.commit()
                                    db_conn.execute("BEGIN TRANSACTION")
                                    batch_counter = 0

                        except Exception as e:
                            err_msg = str(e).lower()
                            if "shutdown" in err_msg or isinstance(e, RuntimeError) or self.view.is_cancelled_flag:
                                # 偵測到直譯器關閉中或已取消，直接跳出迴圈以避免無效的 rollback/commit
                                break
                            logging.error(f"Transaction error, rolling back batch: {e}")
                            try:
                                db_conn.rollback()
                                db_conn.execute("BEGIN TRANSACTION")
                            except: pass
                            batch_counter = 0

                        self.result_queue.task_done()
                except queue.Empty:
                    continue

            if self.view.is_cancelled_flag:
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)
                
            try:
                db_conn.commit()
            except:
                pass

    def _worker_proxy(self, folder_path, depth, max_depth, mtime, mtime_cache):
        from core.config_manager import ConfigManager
        qt = ConfigManager().get_db_settings().get("queue_put_timeout", 0.2)
        if self.view.is_cancelled_flag:
            try: self.result_queue.put({'type': 'task_done'}, timeout=qt)
            except: pass
            return

        result = self.file_model.scan_folder(folder_path, depth, max_depth, mtime, mtime_cache, self.force_rescan)
        if result:
            try: self.result_queue.put(result, timeout=qt)
            except: pass
        try: self.result_queue.put({'type': 'task_done'}, timeout=qt)
        except: pass

    def _apply_to_db(self, result, db_conn):
        f_path = result['folder_path']
        try:
            folder_id = self.index_model.get_folder_id(db_conn, f_path)
            if not folder_id: return

            db_conn.execute("DELETE FROM files_index WHERE folder_id = ?", (folder_id,))
            if result['files']:
                db_conn.executemany(
                    "INSERT INTO files_index (folder_id, name, size, mtime) VALUES (?, ?, ?, ?)",
                    [(folder_id, f[1], f[2], f[3]) for f in result['files']]
                )
            db_conn.execute("INSERT OR REPLACE INTO folder_fingerprints (folder_id, mtime) VALUES (?, ?)", (folder_id, result['mtime']))

            self.total_scanned += len(result['files'])
            self.view.update_count(self.total_scanned)
        except Exception as e:
            logging.error(f"DB Write error for {f_path}: {e}")
            raise

# ==========================================
# MVP: View Adapter (PyQt 實作與向下相容)
# ==========================================
class ScannerWorker(QThread):
    """View 層：繼承 QThread 維持舊有介面不變，內部利用 Adapter 實作 IScanView 以避免 Metaclass 衝突"""
    progress = pyqtSignal(str)
    files_indexed = pyqtSignal(int)
    finished = pyqtSignal(int)
    cancelled = pyqtSignal(int)

    def __init__(self, root_configs, index_mgr, remote_db_dir=None, force_rescan=False,
                 exclude_exts=None, exclude_dirs=None, is_background=False, target_db="local"):
        super().__init__()
        self.root_configs = [(os.path.normpath(p), d) for p, d in root_configs]
        self.index_mgr = index_mgr
        self.remote_db_dir = remote_db_dir
        self.force_rescan = force_rescan
        self.is_background = is_background
        self.target_db = target_db
        self.exclude_exts = exclude_exts
        self.exclude_dirs = exclude_dirs
        
        self._is_cancelled = False

    def stop(self):
        self._is_cancelled = True

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self.is_background: 
            set_current_thread_priority_low()

        # 透過 Composition (內部類別) 實作 View 合約，避開 QThread (SIP) 與 ABC 的 Metaclass 衝突
        class _ScanViewAdapter(IScanView):
            def __init__(self, worker):
                self.worker = worker
            def show_progress(self, msg: str): self.worker.progress.emit(msg)
            def update_count(self, c: int): self.worker.files_indexed.emit(c)
            def finish_scan(self, total: int): self.worker.finished.emit(total)
            def cancel_scan(self, total: int): self.worker.cancelled.emit(total)
            @property
            def is_cancelled_flag(self) -> bool: return self.worker._is_cancelled
            
        file_model = FileScannerModel(self.exclude_dirs, self.exclude_exts)
        presenter = ScanPresenter(
            view=_ScanViewAdapter(self),
            index_model=self.index_mgr,
            file_model=file_model,
            root_configs=self.root_configs,
            remote_db_dir=self.remote_db_dir,
            force_rescan=self.force_rescan,
            target_db=self.target_db
        )
        presenter.execute()
