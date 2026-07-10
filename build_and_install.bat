@echo off
setlocal

rem Regenere l'exe Beheread avec PyInstaller puis le copie dans
rem "C:\Program Files\Beheread". La copie necessite les droits admin :
rem relance ce script en administrateur si besoin.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Ce script doit etre execute en tant qu'administrateur.
    echo Relance en cours...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

rem Ferme une eventuelle instance de Beheread deja ouverte, sinon la copie de
rem l'exe vers "Program Files" echoue (fichier verrouille).
tasklist /fi "IMAGENAME eq Beheread.exe" 2>nul | find /i "Beheread.exe" >nul
if %errorlevel% equ 0 (
    echo === Fermeture de Beheread en cours d'execution ===
    taskkill /im "Beheread.exe" /f >nul 2>&1
    rem laisse le temps a Windows de liberer le verrou sur le fichier
    timeout /t 2 /nobreak >nul
)

echo === Build de Beheread.exe avec PyInstaller ===
pyinstaller beheread.spec
if %errorlevel% neq 0 (
    echo Le build a echoue.
    pause
    exit /b 1
)

if not exist "dist\Beheread.exe" (
    echo dist\Beheread.exe introuvable apres le build.
    pause
    exit /b 1
)

set "INSTALL_DIR=C:\Program Files\Beheread"

echo === Copie vers "%INSTALL_DIR%" ===
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
copy /y "dist\Beheread.exe" "%INSTALL_DIR%\Beheread.exe" >nul
if %errorlevel% neq 0 (
    echo La copie a echoue.
    pause
    exit /b 1
)

echo Termine : "%INSTALL_DIR%\Beheread.exe" mis a jour.

echo === Association des fichiers .cbz / .cbr / .epub a Beheread ===
rem Declare les ProgId "Beheread.cbz" / "Beheread.cbr" / "Beheread.epub" et associe les extensions.
rem Windows peut encore demander de confirmer l'appli par defaut au premier
rem double-clic (protection UserChoice) : accepter Beheread dans "Ouvrir avec".
reg add "HKLM\Software\Classes\Beheread.cbz" /ve /d "Livre CBZ (Beheread)" /f >nul
reg add "HKLM\Software\Classes\Beheread.cbz\DefaultIcon" /ve /d "\"%INSTALL_DIR%\Beheread.exe\",0" /f >nul
reg add "HKLM\Software\Classes\Beheread.cbz\shell\open\command" /ve /d "\"%INSTALL_DIR%\Beheread.exe\" \"%%1\"" /f >nul
reg add "HKLM\Software\Classes\.cbz" /ve /d "Beheread.cbz" /f >nul
reg add "HKLM\Software\Classes\.cbz\OpenWithProgids" /v "Beheread.cbz" /d "" /f >nul
reg add "HKLM\Software\Classes\Beheread.cbr" /ve /d "Livre CBR (Beheread)" /f >nul
reg add "HKLM\Software\Classes\Beheread.cbr\DefaultIcon" /ve /d "\"%INSTALL_DIR%\Beheread.exe\",0" /f >nul
reg add "HKLM\Software\Classes\Beheread.cbr\shell\open\command" /ve /d "\"%INSTALL_DIR%\Beheread.exe\" \"%%1\"" /f >nul
reg add "HKLM\Software\Classes\.cbr" /ve /d "Beheread.cbr" /f >nul
reg add "HKLM\Software\Classes\.cbr\OpenWithProgids" /v "Beheread.cbr" /d "" /f >nul
reg add "HKLM\Software\Classes\Beheread.epub" /ve /d "Livre EPUB (Beheread)" /f >nul
reg add "HKLM\Software\Classes\Beheread.epub\DefaultIcon" /ve /d "\"%INSTALL_DIR%\Beheread.exe\",0" /f >nul
reg add "HKLM\Software\Classes\Beheread.epub\shell\open\command" /ve /d "\"%INSTALL_DIR%\Beheread.exe\" \"%%1\"" /f >nul
reg add "HKLM\Software\Classes\.epub" /ve /d "Beheread.epub" /f >nul
reg add "HKLM\Software\Classes\.epub\OpenWithProgids" /v "Beheread.epub" /d "" /f >nul
rem Rafraichit les icones/associations dans l'explorateur.
powershell -NoProfile -Command "Add-Type -Namespace Win32 -Name Shell -MemberDefinition '[DllImport(\"shell32.dll\")] public static extern void SHChangeNotify(int e, int f, IntPtr a, IntPtr b);'; [Win32.Shell]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)" >nul 2>&1
echo Associations .cbz / .cbr / .epub enregistrees.

echo === Lancement de Beheread ===
rem Ce script tourne en administrateur ; lancer Beheread directement le ferait
rem tourner eleve, ce qui CASSE le glisser-deposer (bloque par l'UIPI de
rem Windows : DoDragDrop se termine aussitot). On le lance donc via explorer.exe
rem pour retomber au niveau d'integrite normal de l'utilisateur.
start "" explorer.exe "%INSTALL_DIR%\Beheread.exe"

pause
