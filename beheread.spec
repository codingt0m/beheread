# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour Beheread. Construire avec :
    pyinstaller beheread.spec
L'executable (et son dossier dist/) sont regeneres a chaque build ;
supprimer build/ et dist/ pour repartir de zero si besoin."""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Beheread',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX desactive : la compression declenche frequemment des faux positifs
    # antivirus sur les .exe PyInstaller, pour un gain de taille marginal.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # app graphique : pas de fenetre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
