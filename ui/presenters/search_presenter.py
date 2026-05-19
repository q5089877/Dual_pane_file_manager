import os
from PyQt6.QtCore import QDate, QThread, pyqtSignal
from ui.workers.threads import SearchThread
from network_search.engine import IndexManager
from core.interfaces import ISearchView
from core.config_manager import ConfigManager

class _SQLiteSearchWorker(QThread):
    result_ready = pyqtSignal(str, float, float, str)  # path, mtime, size, context
    progress = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, index_mgr, conditions, config=None):
        super().__init__()
        self.index_mgr = index_mgr
        self.conditions = conditions
        self.limit = 1000
        self.config = config or {}

    def run(self):
        self.progress.emit("正在檢索資料庫...")
        keyword = self.conditions.get('pattern', '')
        min_size = self.conditions.get('min_size', 0)
        min_mtime = self.conditions.get('min_mtime', 0)

        use_local = self.conditions.get('use_local', self.conditions.get('use_global', True))
        use_network = self.conditions.get('use_network', self.conditions.get('use_k', True))

        path_prefix = (self.conditions.get('path')
                       if not self.conditions.get('use_global') and not self.conditions.get('use_k')
                       else None)

        is_master = self.config.get("is_master_node", False)

        results = self.index_mgr.search(
            keyword,
            limit=self.limit,
            min_size=min_size,
            path_prefix=path_prefix,
            min_mtime=min_mtime,
            use_local=(is_master and use_network),
            use_network=(not is_master and use_network),
            use_personal=use_local,
            local_path_filter=None,
            network_path_filter=None
        )

        import datetime, fnmatch as _fnmatch
        date_from = self.conditions.get('date_from')
        date_to = self.conditions.get('date_to')
        max_size = self.conditions.get('max_size', 0) * 1024 * 1024

        orig_pattern = self.conditions.get('pattern', '')
        use_fnmatch = ('*' in orig_pattern or '?' in orig_pattern) and orig_pattern not in ('*', '*.*')

        count = 0
        for _, mtime, size, path in results:
            if use_fnmatch:
                if not _fnmatch.fnmatch(os.path.basename(path).lower(), orig_pattern.lower()):
                    continue

            if mtime:
                dt = datetime.datetime.fromtimestamp(mtime)
                qd = QDate(dt.year, dt.month, dt.day)
                if date_from and qd < date_from: continue
                if date_to and qd > date_to: continue

            if max_size > 0 and size > max_size: continue

            self.result_ready.emit(path, float(mtime or 0), float(size or 0), "")
            count += 1

        self.finished.emit(count)

    def stop(self):
        pass

class SearchPresenter:
    """MVP Presenter for Advanced Search. Manages index connections and async searches."""
    def __init__(self, view: ISearchView, config_mgr: ConfigManager = None):
        self.view = view
        self.config_mgr = config_mgr or ConfigManager()
        self.db_dir = None
        self.index_mgr = None
        self.active_worker = None
        self.reload_config()

    def reload_config(self):
        """Re-initializes the DB connection based on new configuration."""
        self.db_dir = self.config_mgr.get_index_path()
        config = self.config_mgr.load_config()
        is_master = config.get("is_master_node", False)
        nas_path = config.get("remote_index_root")
        self.index_mgr = IndexManager(self.db_dir, nas_folder_path=nas_path, read_only=not is_master)

    def check_personal_db_exists(self) -> bool:
        p = self.db_dir / "personal.db"
        if not p.exists() or p.stat().st_size < 1024:
            return False
        return True

    def start_search(self, conditions: dict):
        self.stop_search()

        has_content_search = bool(conditions.get('content'))
        use_global = conditions.get('use_global', False)
        use_k = conditions.get('use_k', False)

        config = self.config_mgr.load_config()

        if not has_content_search and (use_global or use_k):
            self.active_worker = _SQLiteSearchWorker(self.index_mgr, conditions, config=config)
            self.active_worker.result_ready.connect(self.view.add_result)
            self.active_worker.progress.connect(self.view.show_progress)
            self.active_worker.finished.connect(self.view.search_finished)
            self.active_worker.start()
        else:
            if use_global:
                search_root = "C:\\"
            elif use_k:
                monitored = config.get('monitored_paths') or []
                search_root = monitored[0] if monitored else conditions['path']
            else:
                search_root = conditions['path']
            self.active_worker = SearchThread(
                search_root,
                conditions['pattern'],
                conditions.get('content', ''),
                conditions.get('date_from', QDate(1900, 1, 1)),
                conditions.get('date_to', QDate.currentDate()),
                conditions.get('min_size', 0),
                conditions.get('max_size', 0)
            )
            self.active_worker.match_found.connect(
                lambda path, mtime, size, ctx: self.view.add_result(path, mtime, size, ctx)
            )
            self.active_worker.progress.connect(self.view.show_progress)
            self.active_worker.finished_signal.connect(self.view.search_finished)
            self.active_worker.start()

    def stop_search(self):
        if self.active_worker:
            self.active_worker.stop()
            self.active_worker.wait()
            self.active_worker = None
