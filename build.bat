@echo off
setlocal
rem Construit Beheread : tests, puis exe en mode dossier (PyInstaller), puis
rem installateur (Inno Setup) -> dist\Beheread-Setup-<version>.exe
rem Prerequis : pip install -r requirements-dev.txt, et Inno Setup 6
rem (winget install JRSoftware.InnoSetup).

cd /d "%~dp0"
for /f "delims=" %%v in ('python -c "from beheread.version import __version__; print(__version__)"') do set "VERSION=%%v"
if not defined VERSION (
    echo Impossible de lire la version de Beheread.
    exit /b 1
)

echo === Beheread %VERSION% : tests ===
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
echo Installateur pret : dist\Beheread-Setup-%VERSION%.exe
