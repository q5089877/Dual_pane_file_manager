import sys
print(f"Python version: {sys.version}")
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
    print("SUCCESS: PyQt6-WebEngine imported successfully.")
except ImportError as e:
    print(f"FAILURE: PyQt6-WebEngine import failed: {e}")
except Exception as e:
    print(f"ERROR: An error occurred: {e}")
