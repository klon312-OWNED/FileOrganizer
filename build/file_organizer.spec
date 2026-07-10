# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: FileOrganizer.exe + FileOrganizerAgent.exe в одной папке."""

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent
icon_file = str(root / "assets" / "icon.ico")

hidden = [
    "PIL._tkinter_finder",
    "pillow_heif",
    "cv2",
    "send2trash",
    "pystray._win32",
    "watchdog.observers",
    "watchdog.observers.polling",
    "watchdog.observers.read_directory_changes",
    "watchdog.observers.winapi",
    "organizer",
    "organizer.classify",
    "organizer.config",
    "organizer.database",
    "organizer.layouts",
    "organizer.theme",
    "organizer.preview",
    "organizer.preview_panel",
    "organizer.compression",
    "organizer.scanner",
    "organizer.sorter",
    "organizer.thumbs",
    "organizer.tray",
    "organizer.watcher",
    "organizer.notify",
    "organizer.icon",
    "organizer.cleanup_summary",
    "organizer.win_drop",
    "organizer.ai_assistant",
    "organizer.ai_ui",
    "organizer.video_player",
    "windnd",
    "fitz",
]

a_mgr = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "transformers", "tensorflow",
        "pandas", "scipy", "matplotlib", "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a_agent = Analysis(
    [str(root / "run_background.pyw")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch", "torchvision", "transformers", "tensorflow",
        "pandas", "scipy", "matplotlib", "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

MERGE((a_mgr, "mgr", "mgr"), (a_agent, "agent", "agent"))

pyz_mgr = PYZ(a_mgr.pure, a_mgr.zipped_data, cipher=block_cipher)
pyz_agent = PYZ(a_agent.pure, a_agent.zipped_data, cipher=block_cipher)

exe_mgr = EXE(
    pyz_mgr,
    a_mgr.scripts,
    [],
    exclude_binaries=True,
    name="FileOrganizer",
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
    icon=icon_file if Path(icon_file).exists() else None,
)

exe_agent = EXE(
    pyz_agent,
    a_agent.scripts,
    [],
    exclude_binaries=True,
    name="FileOrganizerAgent",
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
    icon=icon_file if Path(icon_file).exists() else None,
)

coll = COLLECT(
    exe_mgr,
    a_mgr.binaries,
    a_mgr.zipfiles,
    a_mgr.datas,
    exe_agent,
    a_agent.binaries,
    a_agent.zipfiles,
    a_agent.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FileOrganizer",
)
