# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['discord_priority_manager_FIXED.py'],  # Используем исправленную версию БЕЗ перезапуска
    pathex=[],
    binaries=[],
    datas=[
        ('lang_ru.json', '.'),
        ('lang_uk.json', '.'),
        ('lang_en.json', '.'),
        ('icon.ico', '.'),
        ('tray_icon_green.png', '.'),
        ('tray_icon_red.png', '.'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
        'pystray._win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        'setuptools',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='DiscordPriorityManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Без консоли для GUI приложения
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
    manifest='app.manifest',
    version='version_info.txt',
    uac_admin=True,  # Запрос прав администратора
)
