import sys
import os
import logging
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

try:
    from .engine import IndexManager
    from .ui import NetworkSearchWindow
except ImportError:
    from engine import IndexManager
    from ui import NetworkSearchWindow

def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DualPaneFileManager")
    app.setApplicationName("DualPaneFileManager")
    
    from core.config_manager import ConfigManager
    config_mgr = ConfigManager()
    logger.debug(f"Config File = {config_mgr.config_file}")
    logger.debug(f"Index Dir = {config_mgr.get_index_path()}")
    
    config = config_mgr.load_config()
    is_master = config.get("is_master_node", False)
    logger.debug(f"ROLE = {'MASTER' if is_master else 'CONSUMER'}")
    nas_path = config.get("remote_index_root")
    
    engine = IndexManager(config_mgr.get_index_path(), nas_folder_path=nas_path)
    window = NetworkSearchWindow(engine, config_mgr)
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    # Ensure project root is in sys.path for importing core module
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    main()
