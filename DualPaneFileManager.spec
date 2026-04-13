# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('styles.qss', '.'), ('app_icon.png', '.'), ('theme.json', '.'), ('ui', 'ui'), ('langs', 'langs'), ('network_search', 'network_search')],
    hiddenimports=['fitz', 'pymupdf', 'send2trash', 'winshell', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'scipy', 'matplotlib', 'pandas', 'IPython', 'black', 'jedi', 'PySide6'],
    noarchive=False,
    optimize=0,
)

# Filter out heavy unneeded resource/binary files (saves 150MB+)
a.binaries = [b for b in a.binaries if not any(ign in b[0].lower() for ign in ['opengl32sw.dll', 'libscipy_openblas', 'tbb.dll'])]
a.datas = [d for d in a.datas if not d[0].endswith('.debug.pak')]
a.datas = [d for d in a.datas if not ('qtwebengine_locales' in d[0].replace('\\', '/') and not any(loc in d[0] for loc in ('en-US.pak', 'zh-TW.pak', 'zh-CN.pak')))]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DualPaneFileManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DualPaneFileManager',
)
