import os
import sys
from core.config_manager import ConfigManager

def test_paths():
    cm = ConfigManager()
    
    # Test get_resource_path
    qss_path = cm.get_resource_path("styles.qss")
    print(f"Styles path: {qss_path}")
    print(f"Styles exists: {os.path.exists(qss_path)}")
    
    # Test get_ui_resource_path
    icon_path = cm.get_ui_resource_path("search")
    print(f"Icon path: {icon_path}")
    print(f"Icon exists: {os.path.exists(icon_path)}")
    
    # Test load_stylesheet rewriting
    ss = cm.load_stylesheet("styles.qss", "theme.json")
    if "url(" in ss:
        # Simplified check for absolute path in URL
        import re
        match = re.search(r'url\((["\']?)(.*?)/ui/', ss)
        if match:
            print(f"QSS rewrite check: SUCCESS (found absolute path: {match.group(2)})")
        else:
            print("QSS rewrite check: FAILED or NO UI URL FOUND")

if __name__ == "__main__":
    test_paths()
