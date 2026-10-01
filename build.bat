@echo off
setlocal
rem Construit Beheread : verification du code et tests, puis exe en mode
rem dossier (PyInstaller), puis les fichiers a publier, dans dist\ :
rem   Beheread-Setup-<version>.exe         installateur (Inno Setup)
rem   Beheread-<version>-windows-x64.zip   le meme dossier, sans installation
rem   SHA256SUMS.txt                       sommes de controle des deux
rem Prerequis : pip install -r requirements-dev.txt, et Inno Setup 6
rem (winget install JRSoftware.InnoSetup).
rem Meme script en local et pour la publication (.github\workflows\release.yml).

cd /d "%~dp0"
for /f "delims=" %%v in ('python -c "from beheread.version import __version__; print(__version__)"') do set "VERSION=%%v"
if not defined VERSION (
    echo Impossible de lire la version de Beheread.
    exit /b 1
)

echo === Beheread %VERSION% : verification du code et tests ===
python -m ruff check .
if errorlevel 1 (
    echo Verification du code en echec : build annule.
    exit /b 1
)
python -m pytest -q
if errorlevel 1 (
    echo Tests en echec : build annule.
    exit /b 1
)

echo === Exe (dossier dist\Beheread) ===
pyinstaller beheread.spec --noconfirm
if errorlevel 1 (
    echo Le build PyInstaller a echoue.
    exit /b 1
)

set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo Inno Setup 6 introuvable : winget install JRSoftware.InnoSetup
    exit /b 1
)

echo === Installateur ===
"%ISCC%" /Q /DAppVersion=%VERSION% installer\beheread.iss
if errorlevel 1 (
    echo La compilation de l'installateur a echoue.
    exit /b 1
)

echo === Archive sans installation ===
python -c "import shutil, sys; shutil.make_archive('dist/Beheread-' + sys.argv[1] + '-windows-x64', 'zip', 'dist', 'Beheread')" %VERSION%
if errorlevel 1 (
    echo La creation de l'archive a echoue.
    exit /b 1
)

echo === Sommes de controle ===
python -c "import hashlib, pathlib, sys; d = pathlib.Path('dist'); names = ['Beheread-Setup-' + sys.argv[1] + '.exe', 'Beheread-' + sys.argv[1] + '-windows-x64.zip']; (d / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256((d / n).read_bytes()).hexdigest() + '  ' + n + '\n' for n in names), newline='\n')" %VERSION%
if errorlevel 1 (
    echo Le calcul des sommes de controle a echoue.
    exit /b 1
)

echo Fichiers a publier, dans dist\ :
echo   Beheread-Setup-%VERSION%.exe
echo   Beheread-%VERSION%-windows-x64.zip
echo   SHA256SUMS.txt
exit /b 0
