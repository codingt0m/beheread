# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour Beheread, en mode DOSSIER (onedir) :
    pyinstaller beheread.spec --noconfirm
produit dist\\Beheread\\Beheread.exe et ses bibliotheques (_internal\\).

Pourquoi « onedir » plutot qu'un exe unique : demarrage immediat (rien a
extraire dans un dossier temporaire a chaque lancement) et beaucoup moins de
faux positifs antivirus. Le dossier est ensuite emballe par l'installateur
Inno Setup (installer\\beheread.iss) et en archive zip (voir build.bat)."""

# Composants que les hooks PySide6 embarquent d'office et que Beheread (Qt
# Widgets, QtPdf, QtNetwork) ne charge jamais - environ 45 Mo :
# * opengl32sw.dll : OpenGL logiciel, utile aux seules applications OpenGL/QML ;
# * le clavier virtuel et, tires par lui seul, Qt Quick, QML et Qt OpenGL.
# S'y ajoutent les traductions de Qt (aucun QTranslator n'est installe).
_UNUSED_QT = ('opengl32sw.dll', 'qt6quick', 'qt6qml', 'qt6opengl.dll',
              'qt6virtualkeyboard', 'qtvirtualkeyboardplugin')


def _unused(dest):
    dest = dest.replace('\\', '/').lower()
    return dest.rsplit('/', 1)[-1].startswith(_UNUSED_QT) or '/translations/' in dest


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
a.binaries = [b for b in a.binaries if not _unused(b[0])]
a.datas = [d for d in a.datas if not _unused(d[0])]
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
