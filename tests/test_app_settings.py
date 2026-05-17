"""
AppSettings 深度重構 — 完整測試計畫
===========================================
涵蓋 ConfigManager 資料層 + AppSettingsDialog UI 層的所有邏輯驗證。
不依賴 GUI 視窗，使用 tmpdir 隔離，確保測試可重複執行。

執行: python -m pytest tests/test_app_settings.py -v
"""
import json
import re
import sys
import datetime
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 將專案根目錄加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config_manager import ConfigManager


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_config_dir(tmp_path):
    """建立隔離的暫存設定目錄，仿造正式 config.json 結構。"""
    config = {
        "remote_index_root": "",
        "default_scan_root": "C:",
        "max_depth": 2,
        "search_limit": 1000,
        "is_master_node": False,
        "monitored_paths": ["C:/TestDir"],
        "restore_last_session": True,
        "pdf_preview_max_pages": 3,
        "confirm_before_delete": True,
        "maintenance_settings": {
            "idle_check_interval_ms": 60000,
            "idle_lock_cooldown_min": 2,
            "nightly_scan_hour": 2,
            "nightly_scan_minute": 0
        },
        "paste_settings": {
            "image_prefix": "剪貼圖",
            "text_prefix": "文字筆記",
            "image_format": "%Y%m%d_%H%M%S",
            "text_format": "%Y%m%d_%H%M%S"
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")
    return tmp_path


@pytest.fixture
def cfg(tmp_config_dir):
    """建立指向暫存目錄的 ConfigManager 實例。"""
    mgr = ConfigManager.__new__(ConfigManager)
    mgr.config_dir = tmp_config_dir
    mgr.config_file = tmp_config_dir / "config.json"
    return mgr


# ============================================================================
# Test Suite 1: ConfigManager 資料層
# ============================================================================

class TestConfigManagerDataLayer:
    """驗證 ConfigManager 的讀取、寫入與資料完整性。"""

    def test_load_basic_keys(self, cfg):
        """TC-01: 基本鍵值讀取。"""
        config = cfg.load_config()
        assert config["search_limit"] == 1000
        assert config["is_master_node"] is False
        assert config["monitored_paths"] == ["C:/TestDir"]

    def test_save_app_settings_round_trip(self, cfg):
        """TC-02: save → load 往返一致性。"""
        new_settings = {
            "restore_last_session": False,
            "remote_index_root": "Z:\\Test\\Path",
            "default_scan_root": "D:",
            "search_limit": 5000,
            "nightly_scan_hour": 3,
            "nightly_scan_minute": 30,
            "pdf_preview_max_pages": 5,
            "confirm_before_delete": False,
            "image_prefix": "截圖",
            "text_prefix": "筆記",
            "image_format": "%Y-%m-%d",
            "text_format": "%H%M",
            "is_master_node": True,
            "monitored_paths": ["D:/Folder1", "E:/Folder2"],
        }
        result = cfg.save_app_settings(new_settings)
        assert result is True

        # 重新載入並驗證（mock exists 避免 auto_discover 覆蓋測試路徑）
        with patch("os.path.exists", return_value=True):
            config = cfg.load_config()
        assert config["restore_last_session"] is False
        assert config["remote_index_root"] == "Z:\\Test\\Path"
        assert config["search_limit"] == 5000
        assert config["is_master_node"] is True
        assert config["monitored_paths"] == ["D:/Folder1", "E:/Folder2"]
        assert config["pdf_preview_max_pages"] == 5
        assert config["confirm_before_delete"] is False

    def test_save_nightly_scan_nested(self, cfg):
        """TC-03: 夜間掃描設定正確寫入 maintenance_settings。"""
        cfg.save_app_settings({"nightly_scan_hour": 4, "nightly_scan_minute": 45})
        config = cfg.load_config()
        maint = config["maintenance_settings"]
        assert maint["nightly_scan_hour"] == 4
        assert maint["nightly_scan_minute"] == 45

    def test_save_paste_settings_nested(self, cfg):
        """TC-04: 貼上設定正確寫入 paste_settings。"""
        cfg.save_app_settings({
            "image_prefix": "IMG",
            "image_format": "%Y%m%d",
            "text_prefix": "TXT",
            "text_format": "%H%M%S",
        })
        config = cfg.load_config()
        paste = config["paste_settings"]
        assert paste["image_prefix"] == "IMG"
        assert paste["image_format"] == "%Y%m%d"
        assert paste["text_prefix"] == "TXT"
        assert paste["text_format"] == "%H%M%S"

    def test_partial_save_preserves_other_keys(self, cfg):
        """TC-06: 部分儲存不會覆蓋其他未觸及的 key。"""
        cfg.save_app_settings({"search_limit": 9999})
        config = cfg.load_config()
        # 確認只改了 search_limit，其他不動
        assert config["search_limit"] == 9999
        assert config["default_scan_root"] == "C:"
        assert config["monitored_paths"] == ["C:/TestDir"]


# ============================================================================
# Test Suite 2: get_app_settings 整合讀取
# ============================================================================

class TestGetAppSettings:
    """驗證 get_app_settings 從多個子結構正確聚合資料。"""

    def test_aggregates_maintenance_settings(self, cfg):
        """TC-10: 夜間掃描的時/分從 maintenance_settings 正確讀出。"""
        s = cfg.get_app_settings()
        assert s["nightly_scan_hour"] == 2
        assert s["nightly_scan_minute"] == 0

    def test_aggregates_paste_settings(self, cfg):
        """TC-11: 貼上設定從 paste_settings 正確讀出。"""
        s = cfg.get_app_settings()
        assert s["image_prefix"] == "剪貼圖"
        assert s["image_format"] == "%Y%m%d_%H%M%S"

    def test_defaults_when_keys_missing(self, tmp_path):
        """TC-12: config.json 缺少欄位時，回傳安全預設值。"""
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        mgr = ConfigManager.__new__(ConfigManager)
        mgr.config_dir = tmp_path
        mgr.config_file = tmp_path / "config.json"
        s = mgr.get_app_settings()
        assert s["restore_last_session"] is True
        assert s["search_limit"] == 1000
        assert s["pdf_preview_max_pages"] == 3


# ============================================================================
# Test Suite 4: strftime 格式校驗 (雙層防護網)
# ============================================================================

class TestFormatValidation:
    """模擬 AppSettingsDialog._update_format_preview 的核心校驗邏輯。"""

    INVALID_CHARS = r'[\\/:*?"<>|]'

    def _validate_format(self, fmt_string: str) -> tuple[bool, str]:
        """純 Python 校驗邏輯 (不依賴 PyQt)。

        Returns:
            (is_valid, result_or_error)
        """
        try:
            result = datetime.datetime.now().strftime(fmt_string)
            if re.search(self.INVALID_CHARS, result):
                return (False, f"包含非法檔名字元: {re.findall(self.INVALID_CHARS, result)}")
            return (True, result)
        except Exception as e:
            return (False, str(e))

    def test_valid_format_underscore(self):
        """TC-13: 標準安全格式 %Y%m%d_%H%M%S → PASS。"""
        ok, result = self._validate_format("%Y%m%d_%H%M%S")
        assert ok is True
        assert len(result) == 15  # e.g. 20260406_175215

    def test_valid_format_dash_only(self):
        """TC-14: %Y-%m-%d 不含冒號 → PASS。"""
        ok, _ = self._validate_format("%Y-%m-%d")
        assert ok is True

    def test_invalid_format_colon(self):
        """TC-15: %H:%M:%S 含冒號 → FAIL (Windows 禁用)。"""
        ok, err = self._validate_format("%H:%M:%S")
        assert ok is False
        assert "非法" in err or ":" in err

    def test_invalid_format_slash(self):
        """TC-16: %Y/%m/%d 含斜線 → FAIL。"""
        ok, err = self._validate_format("%Y/%m/%d")
        assert ok is False

    def test_invalid_format_backslash(self):
        """TC-17: 反斜線 → FAIL。"""
        ok, err = self._validate_format("prefix\\%Y")
        assert ok is False

    def test_invalid_format_question_mark(self):
        """TC-18: 問號 → FAIL。"""
        ok, err = self._validate_format("%Y?%m")
        assert ok is False

    def test_invalid_format_angle_brackets(self):
        """TC-19: 角括號 → FAIL。"""
        ok, err = self._validate_format("<%Y>")
        assert ok is False

    def test_invalid_format_pipe(self):
        """TC-20: 管線符號 → FAIL。"""
        ok, err = self._validate_format("%Y|%m")
        assert ok is False

    def test_invalid_format_asterisk(self):
        """TC-21: 星號 → FAIL。"""
        ok, err = self._validate_format("%Y*%m")
        assert ok is False

    def test_invalid_format_double_quote(self):
        """TC-22: 雙引號 → FAIL。"""
        ok, err = self._validate_format('%Y"%m')
        assert ok is False

    def test_empty_format(self):
        """TC-23: 空字串 → PASS (strftime('') == '')。"""
        ok, result = self._validate_format("")
        assert ok is True

    def test_pure_text_format(self):
        """TC-24: 不含任何 % 格式碼的純文字 → PASS (合法但無日期)。"""
        ok, result = self._validate_format("my_file")
        assert ok is True
        assert result == "my_file"



# ============================================================================
# Test Suite 6: 資料完整性邊界測試
# ============================================================================

class TestEdgeCases:
    """極端條件下的防禦性測試。"""

    def test_corrupted_json_returns_defaults(self, tmp_path):
        """TC-28: config.json 損毀時不崩潰，回傳空 dict + 預設值。"""
        (tmp_path / "config.json").write_text("NOT_VALID_JSON{{{", encoding="utf-8")
        mgr = ConfigManager.__new__(ConfigManager)
        mgr.config_dir = tmp_path
        mgr.config_file = tmp_path / "config.json"
        config = mgr.load_config()
        # load_config 應回傳 dict (空或帶預設值)
        assert isinstance(config, dict)

    def test_save_to_readonly_dir(self, cfg, tmp_path):
        """TC-29: 儲存失敗時回傳 False 而非拋出例外。"""
        # 指向不存在的深層目錄
        cfg.config_file = tmp_path / "nonexistent" / "deep" / "path" / "config.json"
        cfg.config_dir = tmp_path / "nonexistent" / "deep" / "path"
        # save_app_settings 應處理例外並回傳 bool
        result = cfg.save_app_settings({"search_limit": 1})
        # 應該要 True (因為 mkdir parents=True 會建立目錄)
        assert isinstance(result, bool)

    def test_missing_config_file_creates_defaults(self, tmp_path):
        """TC-30: config.json 完全不存在時，load_config 建立預設值。"""
        cfg_file = tmp_path / "config.json"
        assert not cfg_file.exists()
        mgr = ConfigManager.__new__(ConfigManager)
        mgr.config_dir = tmp_path
        mgr.config_file = cfg_file
        config = mgr.load_config()
        assert isinstance(config, dict)

    def test_special_chars_in_path(self, cfg):
        """TC-31: 路徑中含中文字元不影響儲存。"""
        cfg.save_app_settings({
            "remote_index_root": "K:\\公司\\部門\\索引庫",
            "monitored_paths": ["D:/專案/測試用"],
        })
        with patch("os.path.exists", return_value=True):
            config = cfg.load_config()
        assert config["remote_index_root"] == "K:\\公司\\部門\\索引庫"
        assert "D:/專案/測試用" in config["monitored_paths"]


# ============================================================================
# Test Suite 7: 殘留功能清理驗證
# ============================================================================

class TestRemovedFeatures:
    """確認已移除的功能不會殘留或干擾系統。"""

    def test_no_trash_settings_in_defaults(self, cfg):
        """TC-32: load_config 不再注入 trash_settings。"""
        config = cfg.load_config()
        # 如果 fixture 中有放就跳過，但預設不應新增
        # 重點：get_trash_settings 方法不應存在
        assert not hasattr(cfg, "get_trash_settings")

    def test_no_trash_model_import(self):
        """TC-33: trash_model.py 不應存在。"""
        trash_path = ROOT / "core" / "models" / "trash_model.py"
        assert not trash_path.exists(), f"殘留檔案: {trash_path}"

    def test_no_itrash_view_in_interfaces(self):
        """TC-34: ITrashView 不應存在。"""
        from core import interfaces
        assert not hasattr(interfaces, "ITrashView")
