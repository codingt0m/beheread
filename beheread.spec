# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour Beheread, en mode DOSSIER (onedir) :
    pyinstaller beheread.spec --noconfirm
produit dist\\Beheread\\Beheread.exe et ses bibliotheques (_internal\\).

Pourquoi « onedir » plutot qu'un exe unique : demarrage immediat (rien a
extraire dans un dossier temporaire a chaque lancement) et beaucoup moins de
faux positifs antivirus. Le dossier est ensuite emballe par l'installateur
Inno Setup (installer\\beheread.iss, voir build.bat)."""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # icone et autres ressources, retrouvees par beheread.config.resource_path
    datas=[('beheread/resources', 'beheread/resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pytest', 'pytestqt'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Beheread',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX desactive : la compression declenche frequemment des faux positifs
    # antivirus sur les .exe PyInstaller, pour un gain de taille marginal.
    upx=False,
    console=False,          # app graphique : pas de fenetre console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='beheread/resources/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Beheread',
)
