# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour Beheread, en mode DOSSIER (onedir) :
    pyinstaller beheread.spec --noconfirm

* Windows : produit dist\\Beheread\\Beheread.exe et ses bibliotheques
  (_internal\\), emballe ensuite par l'installateur Inno Setup
  (installer\\beheread.iss) et en archive zip (voir build.bat).
* macOS : produit en plus dist/Beheread.app, l'application a glisser dans
  Applications, emballee en .dmg par packaging/macos/build.sh. Ne se
  construit que sur un Mac (pas de compilation croisee).

Pourquoi « onedir » plutot qu'un exe unique : demarrage immediat (rien a
extraire dans un dossier temporaire a chaque lancement) et beaucoup moins de
faux positifs antivirus."""

import sys

sys.path.insert(0, SPECPATH)
from beheread.version import __version__  # noqa: E402

MACOS = sys.platform == 'darwin'

# Composants que les hooks PySide6 embarquent d'office et que Beheread (Qt
# Widgets, QtPdf, QtNetwork) ne charge jamais - environ 45 Mo :
# * opengl32sw.dll : OpenGL logiciel, utile aux seules applications OpenGL/QML ;
# * le clavier virtuel et, tires par lui seul, Qt Quick, QML et Qt OpenGL.
# S'y ajoutent les traductions de Qt (aucun QTranslator n'est installe).
_UNUSED_QT = ('opengl32sw.dll', 'qt6quick', 'qt6qml', 'qt6opengl.dll',
              'qt6virtualkeyboard', 'qtvirtualkeyboardplugin')
# Les memes sous macOS, ou Qt est livre en frameworks (QtQuick.framework...).
_UNUSED_QT_MAC = ('qtquick', 'qtqml', 'qtopengl', 'qtvirtualkeyboard',
                  'libqtvirtualkeyboardplugin')


def _unused(dest):
    dest = dest.replace('\\', '/').lower()
    if '/translations/' in dest:
        return True
    if MACOS:
        return any(part.startswith(_UNUSED_QT_MAC) for part in dest.split('/'))
    return dest.rsplit('/', 1)[-1].startswith(_UNUSED_QT)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # icone et autres ressources, retrouvees par beheread.config.resource_path
    datas=[('beheread/resources', 'beheread/resources')],
    # moteur du Trousseau, importe a l'usage (voir platforms/macos.py)
    hiddenimports=['keyring.backends.macOS'] if MACOS else [],
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
    # les fichiers du Finder arrivent par QFileOpenEvent (voir app.py) :
    # pas d'emulation d'argv, qui entrerait en conflit avec Qt
    argv_emulation=False,
    # Mac Apple Silicon seulement (les Mac Intel ne recoivent plus les
    # nouvelles versions de macOS)
    target_arch='arm64' if MACOS else None,
    codesign_identity=None,   # macOS : signature « ad hoc » (pas de compte Apple)
    entitlements_file=None,
    icon='packaging/macos/icon.icns' if MACOS else 'beheread/resources/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Beheread',
)

if MACOS:
    def _document(name, utis, rank):
        return {'CFBundleTypeName': name, 'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': rank, 'LSItemContentTypes': utis}

    def _imported(uti, description, extension, mime, conforms):
        return {'UTTypeIdentifier': uti, 'UTTypeDescription': description,
                'UTTypeConformsTo': conforms,
                'UTTypeTagSpecification': {'public.filename-extension': [extension],
                                           'public.mime-type': [mime]}}

    _CBZ = 'io.github.codingt0m.beheread.cbz'
    _CBR = 'io.github.codingt0m.beheread.cbr'
    app = BUNDLE(
        coll,
        name='Beheread.app',
        icon='packaging/macos/icon.icns',
        bundle_identifier='io.github.codingt0m.beheread',
        version=__version__,
        info_plist={
            'CFBundleName': 'Beheread',
            'CFBundleDisplayName': 'Beheread',
            'CFBundleShortVersionString': __version__,
            'CFBundleVersion': __version__,
            'CFBundleDevelopmentRegion': 'fr',
            'LSApplicationCategoryType': 'public.app-category.entertainment',
            'LSMinimumSystemVersion': '13.0',
            'NSHighResolutionCapable': True,
            'NSHumanReadableCopyright': 'Beheread - licence PolyForm Noncommercial',
            # CBZ et CBR n'ont pas de type declare par macOS : Beheread les
            # declare (importes : un autre lecteur peut aussi le faire)
            'UTImportedTypeDeclarations': [
                _imported(_CBZ, 'Livre CBZ', 'cbz', 'application/vnd.comicbook+zip',
                          ['public.zip-archive', 'public.data']),
                _imported(_CBR, 'Livre CBR', 'cbr', 'application/vnd.comicbook-rar',
                          ['public.archive', 'public.data']),
            ],
            # « Ouvrir avec » propose Beheread pour les quatre formats ; il peut
            # devenir l'application par defaut des CBZ, CBR et EPUB, jamais
            # des PDF (comme sous Windows)
            'CFBundleDocumentTypes': [
                _document('Livre CBZ', [_CBZ], 'Default'),
                _document('Livre CBR', [_CBR], 'Default'),
                _document('Livre EPUB', ['org.idpf.epub-container'], 'Default'),
                _document('Document PDF', ['com.adobe.pdf'], 'Alternate'),
            ],
        },
    )
