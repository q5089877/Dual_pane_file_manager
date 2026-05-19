import sys
import os
import logging
import logging.handlers
import fitz # Force PyInstaller to detect PyMuPDF
import send2trash # Force PyInstaller to detect send2trash

# Log file: %LOCALAPPDATA%\SHL\<app>\app.log
_log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "SHL", "DualPaneFileManager")
os.makedirs(_log_dir, exist_ok=True)
_log_path = os.path.join(_log_dir, "app.log")

_fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
_file_handler = logging.handlers.RotatingFileHandler(
    _log_path, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
_file_handler.setFormatter(_fmt)
_file_handler.setLevel(logging.INFO)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_fmt)
_console_handler.setLevel(logging.WARNING)   # console 仍只顯示 WARNING+

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])
logger = logging.getLogger(__name__)

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--log-level=3")

try:
    import PyQt6.QtWebEngineWidgets  # noqa: F401 — must be imported before QApplication
except ImportError:
    pass
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon, QFont
from ui.windows.main_window import MainWindow
from core.config_manager import ConfigManager

def main():
    # Make taskbar icon match application icon on Windows
    if sys.platform == "win32":
        try:
            import ctypes
            my_app_id = u"DualPaneFileManager.1.0"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(my_app_id)
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setOrganizationName("DualPaneFileManager")
    app.setApplicationName("DualPaneFileManager")

    # Set Window Icon
    icon_path = ConfigManager.get_resource_path("app_icon.png")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)
        logger.debug(f"Icon loaded from {icon_path}")
    else:
        logger.debug(f"Icon NOT FOUND at {icon_path}")
            
    # 預防 QFont::setPointSize: Point size <= 0 (-1)
    app_font = QFont("Segoe UI", 10)
    if app_font.pointSize() <= 0:
        app_font.setPointSize(10)
    app_font.setFamilies(["Segoe UI", "Microsoft JhengHei", "Arial", "Consolas"])
    app.setFont(app_font)
    
    # Load and process styling
    cfg = ConfigManager()
    logger.debug(f"Root Main Config File = {cfg.config_file.absolute()}")
    logger.debug(f"Root Main Index Dir = {cfg.get_index_path().absolute()}")
    
    stylesheet = cfg.load_stylesheet("styles.qss", "theme.json")
    if stylesheet:
        app.setStyleSheet(stylesheet)

    window = MainWindow()
    if not app.windowIcon().isNull():
        window.setWindowIcon(app.windowIcon())
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
