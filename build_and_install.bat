@echo off
setlocal
rem Construit Beheread (build.bat) puis l'installe pour l'utilisateur courant,
rem sans droits administrateur : %LOCALAPPDATA%\Programs\Beheread, avec les
rem associations .cbz / .cbr / .epub (et Beheread dans « Ouvrir avec » des PDF).
rem Si Beheread est ouvert, l'installateur le ferme d'abord.

cd /d "%~dp0"
call build.bat
if errorlevel 1 (
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python -c "from beheread.version import __version__; print(__version__)"') do set "VERSION=%%v"

echo === Installation de Beheread %VERSION% ===
"dist\Beheread-Setup-%VERSION%.exe" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /TASKS="assoc"
if errorlevel 1 (
    echo L'installation a echoue.
    pause
    exit /b 1
)
echo Installe dans "%LOCALAPPDATA%\Programs\Beheread".

echo === Lancement de Beheread ===
start "" "%LOCALAPPDATA%\Programs\Beheread\Beheread.exe"
