import ctypes
from ctypes import wintypes
import os
import threading

# Known virtual/phone/cloud path segments that should never be accessed at startup
_VIRTUAL_PATH_SEGMENTS = (
    os.sep + "CrossDevice" + os.sep,
    os.sep + "CrossDevice",
)

def is_virtual_path(path: str) -> bool:
    """True if path is a known phone/cloud virtual folder — skip without I/O."""
    p = os.path.normpath(path).lower()
    return any(seg.lower() in p for seg in _VIRTUAL_PATH_SEGMENTS)


def path_exists_fast(path: str, timeout: float = 1.5) -> bool:
    """os.path.exists with timeout — skips virtual paths and slow drives immediately."""
    if is_virtual_path(path):
        return False
    result = [False]
    ev = threading.Event()
    def _check():
        try:
            result[0] = os.path.exists(path)
        except Exception:
            pass
        ev.set()
    threading.Thread(target=_check, daemon=True).start()
    return ev.wait(timeout) and result[0]

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

def get_user_idle_time_ms() -> int:
    """Returns milliseconds elapsed since the last keyboard or mouse input."""
    try:
        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick_now = ctypes.windll.kernel32.GetTickCount()
            return int((tick_now - lii.dwTime) % (2 ** 32))
        return 0
    except Exception:
        return 0


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


def discover_nas_root(relative_path: str) -> str | None:
    """Scan REMOTE drive letters for {drive}\\relative_path\\current_version.txt.

    Uses GetDriveTypeW to skip non-network drives without touching them (防卡死).
    Returns the full path on success, None if not found.
    """
    if not relative_path:
        return None
    import string as _string
    DRIVE_REMOTE = 4
    try:
        get_type = ctypes.windll.kernel32.GetDriveTypeW
    except Exception:
        return None
    for letter in _string.ascii_uppercase:
        drive = f"{letter}:\\"
        try:
            if get_type(drive) != DRIVE_REMOTE:
                continue
        except Exception:
            continue
        candidate = os.path.join(drive, relative_path)
        version_file = os.path.join(candidate, "current_version.txt")
        if path_exists_fast(version_file, timeout=2.0):
            return candidate
    return None
