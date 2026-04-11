import ctypes
from ctypes import wintypes
import os

# Windows API Constants
WTS_CURRENT_SERVER_HANDLE = 0
WTS_CURRENT_SESSION_ID = -1
WTS_SESSION_INFO_EX = 25
WTS_CONNECTED_SESSION = 0x1
WTS_SESSIONSTATE_LOCK = 0x0
WTS_SESSIONSTATE_UNLOCK = 0x1

# Thread Priority Constants
THREAD_PRIORITY_LOWEST = -2
THREAD_MODE_BACKGROUND_BEGIN = 0x00010000
THREAD_MODE_BACKGROUND_END = 0x00020000

def is_computer_locked():
    """
    Checks if the current Windows session is locked.
    Uses WTSQuerySessionInformation to get session state.
    """
    try:
        # A simpler way that often works well for GUI apps:
        # If the desktop "Default" is not switchable, it's likely locked.
        h_desktop = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x0100) # DESKTOP_SWITCHDESKTOP
        if h_desktop:
            # SwitchDesktop returns 0 if it fails to switch (e.g., when locked)
            result = ctypes.windll.user32.SwitchDesktop(h_desktop)
            ctypes.windll.user32.CloseDesktop(h_desktop)
            return not result
        return True
    except Exception:
        return False

def set_current_thread_priority_low():
    """
    Lowers the priority of the current thread to background level.
    """
    try:
        handle = ctypes.windll.kernel32.GetCurrentThread()
        # THREAD_MODE_BACKGROUND_BEGIN is very effective on modern Windows
        ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_MODE_BACKGROUND_BEGIN)
    except Exception:
        # Fallback to THREAD_PRIORITY_LOWEST
        try:
            ctypes.windll.kernel32.SetThreadPriority(handle, THREAD_PRIORITY_LOWEST)
        except Exception:
            pass

def is_reparse_point(path):
    """
    Checks if a path is a Windows Reparse Point (Junction or Symlink).
    Useful for avoiding "Access Denied" errors on system junctions like 'Application Data'.
    """
    try:
        FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    except Exception:
        return False
