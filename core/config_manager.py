import json
import os
import string
import re
from pathlib import Path


class ConfigManager:
    """Handles application configuration and theme loading."""
    APP_VERSION = "1.3.0"
    GITHUB_REPO  = "q5089877/Dual_pane_file_manager"
    _DEFAULT_UPDATE_SUFFIX = ""
    _DEFAULT_REMOTE_INDEX_SUFFIX = ""

    def __init__(self, app_name="DualPaneFileManager"):
        # Portable Mode Check
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = Path(os.path.dirname(sys.executable))
        else:
            base_dir = Path(os.path.dirname(os.path.abspath(
                sys.argv[0] if sys.argv else __file__)))

        portable_config = base_dir / "config.json"
        self.config = {}  # MUST initialize early for attribute safety

        if portable_config.exists():
            self.config_dir = base_dir
            self.config_file = portable_config
            self.is_portable = True
        else:
            if sys.platform == "win32":
                local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
                self.config_dir = Path(local_appdata) / "SHL" / app_name
            else:
                self.config_dir = Path(os.path.expanduser("~/.config")) / app_name
            
            self.config_file = self.config_dir / "config.json"
            self.is_portable = False

        self.app_name = app_name
        self.lang_data = {}

    @staticmethod
    def detect_os_language() -> str:
        """Returns 'zh_TW' if the Windows UI language is Chinese, else 'en_US'."""
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Primary language ID 0x04 = Chinese
            if (lcid & 0xFF) == 0x04:
                return "zh_TW"
        except Exception:
            pass
        try:
            import locale
            lang = (locale.getdefaultlocale()[0] or "")
            if lang.lower().startswith("zh"):
                return "zh_TW"
        except Exception:
            pass
        return "en_US"

    def get_text(self, key: str, default: str = None) -> str:
        """Returns translated text for the given key."""
        return self.lang_data.get(key, default or key)

    def load_language(self, lang_code: str = None):
        """Loads language JSON file into memory."""
        if not lang_code:
            lang_code = self.detect_os_language()
        
        lang_path = self.get_resource_path(f"langs/{lang_code}.json")
        if os.path.exists(lang_path):
            try:
                with open(lang_path, "r", encoding="utf-8") as f:
                    self.lang_data = json.load(f)
            except Exception:
                self.lang_data = {}
        else:
            self.lang_data = {}

    def load_config(self):
        """Loads configuration from JSON file."""
        config = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if isinstance(config, list):
                        config = {"custom_paths": config}
            except (json.JSONDecodeError, Exception):
                pass

        self.config = config
        self.load_language(config.get("language"))

        if self._apply_config_defaults(config):
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
            except Exception:
                pass

        return config

    def _apply_config_defaults(self, config: dict) -> bool:
        """Fill in missing config sections. Returns True if any defaults were applied."""
        changed = False

        if "github_repo" not in config:
            config["github_repo"] = self.GITHUB_REPO
            changed = True

        if "db_settings" not in config:
            config["db_settings"] = {
                "sqlite_timeout": 30,
                "busy_timeout_ms": 5000,
                "wal_cache_size": -10000,
                "transaction_batch_size": 200,
                "queue_get_timeout": 0.2,
                "queue_put_timeout": 0.2,
            }
            changed = True

        if "search_filters" not in config:
            config["search_filters"] = {
                "size_labels": ["全部", "> 1 MB", "> 10 MB", "> 100 MB", "> 1 GB"],
                "size_thresholds": {"0": 0, "1": 1048576, "2": 10485760, "3": 104857600, "4": 1073741824},
                "time_labels": ["全部", "🕒 今日", "📅 本週", "本月"],
            }
            changed = True

        if "maintenance_settings" not in config:
            config["maintenance_settings"] = {
                "idle_check_interval_ms": 60000,
                "idle_lock_cooldown_min": 2,
                "nightly_scan_hour": 2,
                "nightly_scan_minute": 0,
            }
            changed = True

        if "paste_settings" not in config:
            config["paste_settings"] = {
                "image_prefix": "剪貼圖",
                "text_prefix": "文字筆記",
                "image_format": "%Y%m%d_%H%M%S",
                "text_format": "%Y%m%d_%H%M%S",
            }
            changed = True

        if "nas_relative_path" not in config:
            config["nas_relative_path"] = (
                r"SHL TECH\_STEC_Staff\Neil\效率提升軟體\K槽檔案尋找資料庫存放區"
            )
            changed = True

        return changed

    def get_update_source_path(self):
        """尋找更新來源目錄路徑。"""
        config = getattr(self, "config", {})
        update_suffix = config.get("update_source_suffix", self._DEFAULT_UPDATE_SUFFIX)
        search_drives = ['K', 'H', 'G', 'S', 'Z', 'Y', 'P', 'Q'] + list(string.ascii_uppercase)
        for drive in search_drives:
            potential = os.path.join(f"{drive}:\\", update_suffix)
            if os.path.exists(potential):
                return potential
        return None

    @staticmethod
    def get_file_mtime(path: str) -> float:
        try:
            if os.path.exists(path):
                return os.path.getmtime(path)
        except Exception:
            pass
        return 0.0

    def save_config(self, custom_paths=None, left_tabs=None, right_tabs=None, splitter_sizes=None, **kwargs):
        config = self.load_config()
        if custom_paths is not None:
            config["custom_paths"] = custom_paths
        if left_tabs is not None:
            config["left_tabs"] = left_tabs
        if right_tabs is not None:
            config["right_tabs"] = right_tabs
        if splitter_sizes is not None:
            config["splitter_sizes"] = splitter_sizes
        for k, v in kwargs.items():
            if v is not None:
                config[k] = v
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False

    @staticmethod
    def get_resource_path(relative_path):
        import sys
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)

    def get_ui_resource_path(self, name: str) -> str:
        """回傳 ui/{name}.svg 的絕對路徑，供 PyInstaller 打包後也能正確取得。"""
        return self.get_resource_path(os.path.join("ui", f"{name}.svg"))

    def get_theme_colors(self, theme_rel_path: str = "theme.json") -> dict:
        theme_path = self.get_resource_path(theme_rel_path)
        try:
            with open(theme_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ── 內建主題 Preset ────────────────────────────────────────────────────────
    _THEME_PRESETS: dict[str, dict] = {
        "調光護眼 (預設)": {
            "themeName": "調光護眼 (預設)",
            "bg": "#1e2128", "panelBg": "#23272e", "headerBg": "#282c34",
            "activeTab": "#2d5a8e", "activeBorder": "#D97706", "inactiveTab": "#21262D",
            "text": "#C9D1D9", "textMuted": "#8B949E", "folder": "#B58900",
            "accent": "#58A6FF", "border": "#3e4451",
            "success": "#57B77F", "danger": "#C9605A",
            "glassBg": "rgba(30, 34, 45, 0.92)", "glassBorder": "rgba(255, 255, 255, 0.15)",
            "actionBarBg": "rgba(30, 34, 45, 0.5)", "surfaceSubtle": "rgba(255, 255, 255, 0.04)",
            "accentSubtle": "rgba(88, 166, 255, 0.12)", "accentBorder": "rgba(88, 166, 255, 0.4)",
            "errorSubtle": "rgba(244, 63, 94, 0.08)", "shadow": "rgba(0, 0, 0, 0.6)",
            "quickLookBg": "rgba(30, 30, 30, 0.95)", "quickLookBorder": "rgba(255, 255, 255, 0.2)",
        },
    }

    def get_theme_names(self) -> list[str]:
        return list(self._THEME_PRESETS.keys())

    def get_master_password(self) -> str:
        return self.load_config().get("master_node_password", "1235")

    def is_admin_mode(self) -> bool:
        """此節點是否為管理者/生產者模式。"""
        return bool(self.load_config().get("is_master_node", False))

    def apply_theme_preset(self, theme_name: str) -> bool:
        """將指定的內建主題寫入 theme.json。找不到對應 preset 時靜默忽略。"""
        preset = self._THEME_PRESETS.get(theme_name)
        if not preset:
            return False
        theme_path = self.get_resource_path("theme.json")
        try:
            with open(theme_path, "w", encoding="utf-8") as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def apply_theme_to_text(self, text: str, theme_rel_path: str = "theme.json") -> str:
        theme_data = self.get_theme_colors(theme_rel_path)
        if not theme_data:
            return text
        for key, value in theme_data.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text

    def load_stylesheet(self, style_rel_path, theme_rel_path):
        style_path = self.get_resource_path(style_rel_path)
        theme_path = self.get_resource_path(theme_rel_path)
        stylesheet = ""
        if os.path.exists(style_path):
            with open(style_path, "r", encoding="utf-8") as f:
                stylesheet = f.read()
            if os.path.exists(theme_path):
                try:
                    with open(theme_path, "r", encoding="utf-8") as f:
                        theme_data = json.load(f)
                    for key, value in theme_data.items():
                        stylesheet = stylesheet.replace(f"{{{{{key}}}}}", value)
                except Exception:
                    pass
            ui_base_dir = self.get_resource_path("ui").replace("\\", "/")
            stylesheet = re.sub(r'url\((["\']?)ui/', f'url(\\1{ui_base_dir}/', stylesheet)
        return stylesheet

    def get_active_slot(self):
        config = self.load_config()
        root = config.get("remote_index_root", "")
        if not root or not os.path.exists(root):
            return "A"
        version_file = os.path.join(root, "current_version.txt")
        if os.path.exists(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    v = f.read().strip().upper()
                    if v in ["A", "B"]: return v
            except Exception: pass
        return "A"

    def get_index_path(self) -> Path:
        """Always returns AppData indexes path regardless of portable/installed mode."""
        import sys
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))
            return Path(local_appdata) / "SHL" / self.app_name / "indexes"
        return Path(os.path.expanduser("~/.config")) / self.app_name / "indexes"

    def get_db_settings(self):
        return self.load_config().get("db_settings", {})

    def get_search_filters(self):
        return self.load_config().get("search_filters", {})

    def get_maintenance_settings(self):
        return self.load_config().get("maintenance_settings", {
            "idle_check_interval_ms": 60000,
            "idle_lock_cooldown_min": 2,
            "nightly_scan_hour": 2,
            "nightly_scan_minute": 0
        })

    def get_paste_settings(self):
        return self.load_config().get("paste_settings", {
            "image_prefix": "剪貼圖",
            "text_prefix": "文字筆記",
            "image_format": "%Y%m%d_%H%M%S",
            "text_format": "%Y%m%d_%H%M%S"
        })



    def get_app_settings(self) -> dict:
        config = self.load_config()
        theme = self.get_theme_colors()
        maint = config.get("maintenance_settings", {})
        paste = config.get("paste_settings", {})
        _default_exts = [".tmp", ".bak", ".log", ".cache", ".thumbs", ".db-wal", ".db-shm", ".lock"]
        _default_dirs = ["Archive", "Old", "Temp", "_archive", "Backup", "$RECYCLE.BIN"]
        return {
            "theme_name":            theme.get("themeName", "調光護眼 (預設)"),
            "restore_last_session":  config.get("restore_last_session", True),
            "remote_index_root":     config.get(
                "remote_index_root",
                r"K:\SHL TECH\_STEC_Staff\Neil\效率提升軟體\K槽檔案尋找資料庫存放區"
            ),
            "is_master_node":        config.get("is_master_node", False),
            "monitored_paths":       config.get("monitored_paths", []),
            "network_scan_depth":    config.get("network_scan_depth", 7),
            "exclude_exts":          config.get("exclude_exts") or _default_exts,
            "exclude_dirs":          config.get("exclude_dirs") or _default_dirs,
            "max_depth":             config.get("max_depth", 2),
            "search_limit":          config.get("search_limit", 1000),
            "nightly_scan_hour":     maint.get("nightly_scan_hour", 2),
            "nightly_scan_minute":   maint.get("nightly_scan_minute", 0),
            "pdf_preview_max_pages": config.get("pdf_preview_max_pages", 3),
            "confirm_before_delete": config.get("confirm_before_delete", True),
            "preview_font_size":     config.get("preview_font_size", 14),
            "image_prefix":          paste.get("image_prefix", "剪貼圖"),
            "text_prefix":           paste.get("text_prefix", "文字筆記"),
            "image_format":          paste.get("image_format", "%Y%m%d_%H%M%S"),
            "text_format":           paste.get("text_format", "%Y%m%d_%H%M%S"),
            "language":              self.detect_os_language(),
        }

    # ── Favorites ─────────────────────────────────────────────────────────────

    def get_favorites(self) -> list[dict]:
        return self.load_config().get("favorites", [])

    def save_favorites(self, favorites: list[dict]) -> None:
        config = self.load_config()
        config["favorites"] = favorites
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    # ── Pin management ────────────────────────────────────────────────────────

    def _save_pins(self, config: dict, pins: list) -> bool:
        config["pinned_items"] = pins
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False

    def get_pins(self) -> list:
        return self.load_config().get("pinned_items", [])

    def is_pinned(self, path: str) -> bool:
        return any(p["path"] == path for p in self.get_pins())

    def add_pin(self, path: str, is_dir: bool, note: str = "") -> bool:
        import datetime
        config = self.load_config()
        pins: list = config.get("pinned_items", [])
        if any(p["path"] == path for p in pins):
            return False
        pins.insert(0, {
            "path": path,
            "is_dir": is_dir,
            "pinned_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "note": note.strip(),
            "important": False,
        })
        config["pinned_items"] = pins
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception:
            return False

    def remove_pin(self, path: str) -> bool:
        config = self.load_config()
        pins: list = config.get("pinned_items", [])
        new_pins = [p for p in pins if p["path"] != path]
        if len(new_pins) == len(pins):
            return False
        return self._save_pins(config, new_pins)

    def set_pin_important(self, path: str, important: bool) -> bool:
        config = self.load_config()
        pins: list = config.get("pinned_items", [])
        for p in pins:
            if p["path"] == path:
                p["important"] = important
                return self._save_pins(config, pins)
        return False

    def update_pin_note(self, path: str, note: str) -> bool:
        config = self.load_config()
        pins: list = config.get("pinned_items", [])
        for p in pins:
            if p["path"] == path:
                p["note"] = note.strip()
                return self._save_pins(config, pins)
        return False


    @staticmethod
    def get_fixed_drives() -> list[str]:
        import string
        drives = []
        for letter in string.ascii_uppercase:
            d = f"{letter}:\\"
            if os.path.exists(d):
                drives.append(d)
        return drives

    def save_app_settings(self, settings: dict) -> bool:
        config = self.load_config()
        top_level_keys = ["restore_last_session", "remote_index_root", "max_depth", "search_limit", "pdf_preview_max_pages", "confirm_before_delete", "preview_font_size", "is_master_node", "monitored_paths", "network_scan_depth", "exclude_exts", "exclude_dirs"]
        for key in top_level_keys:
            if key in settings: config[key] = settings[key]
        if "nightly_scan_hour" in settings or "nightly_scan_minute" in settings:
            maint = config.setdefault("maintenance_settings", {})
            if "nightly_scan_hour" in settings: maint["nightly_scan_hour"] = settings["nightly_scan_hour"]
            if "nightly_scan_minute" in settings: maint["nightly_scan_minute"] = settings["nightly_scan_minute"]

        paste_keys = ["image_prefix", "text_prefix", "image_format", "text_format"]
        if any(k in settings for k in paste_keys):
            paste = config.setdefault("paste_settings", {})
            for k in paste_keys:
                if k in settings: paste[k] = settings[k]
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception: return False
